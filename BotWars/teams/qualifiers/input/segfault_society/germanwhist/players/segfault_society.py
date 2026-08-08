# Team: segfault_society — BotWars 2026 qualifiers (German Whist)
#
# Particle-filter card tracker + EV exchange logic + determinized endgame
# minimax.
#
# The opponent's hand is modeled as a cloud of "particles" (concrete hand
# hypotheses) maintained from trick 1. Contradicted particles are REPAIRED by
# swapping in the minimal consistent card (conditioning), never mass-killed —
# rejection filtering would collapse the population after a few observations.
# All probability estimates (voids, beaters, trumps) are particle statistics,
# and the endgame solver runs exact minimax over particle determinizations.
#
# Phase 1 treats each trick as a card exchange: fight for the face-up card only
# when its value beats the expected hidden card by more than the cost of the
# card burned. Phase 2 cashes counted masters, exits cheaply, and hands the
# last ~7 tricks to the solver.

import random
import time

SUITS = ("H", "D", "C", "S")
DECK = frozenset((s, r) for s in SUITS for r in range(2, 15))

NONTRUMP_V = {2: 0.5, 3: 1.0, 4: 2.0, 5: 3.0, 6: 4.0, 7: 5.0, 8: 7.0, 9: 9.0,
              10: 13.0, 11: 19.0, 12: 30.0, 13: 47.0, 14: 72.0}
TRUMP_V = {2: 40.0, 3: 42.0, 4: 44.0, 5: 46.0, 6: 49.0, 7: 52.0, 8: 56.0,
           9: 61.0, 10: 67.0, 11: 74.0, 12: 84.0, 13: 95.0, 14: 106.0}

# Shape shaping (void/ruff plan) — see _delta and _discard_value
TR_PREMIUM = 8.0      # extra worth of a trump face-up (ruff ammunition)
VOID_REFILL = 9.0     # penalty on face-ups that would refill our void
NEAR_VOID_PEN = 4.0   # penalty on low face-ups joining a singleton suit
LEN_BONUS = 3.0       # bonus for face-ups extending a 4+ suit
DUMP_LEN_W = 2.5      # dump preference weight for short suits
GUARD_K = 14.0        # keep the guard next to a king
GUARD_Q = 4.0         # mild guard for queens
TRUMP_CLING = 60.0    # reluctance to discard trumps
MASTER_KEEP = 50.0    # reluctance to discard likely masters
EXIT_VOID_W = 6.0     # avoid exiting into a ruff-ready void
RISK_MAX = 0.20       # max ruff risk to cash a side master in phase 2
PT_DEAD = 0.10        # opponent considered trumpless below this probability
P1_LEAD_MARGIN = 1.0
P1_FOLLOW_MARGIN = 0.5

N_PARTICLES = 250
MIN_PARTICLES = 60
BEHAVE_EPS = 0.25         # chance the behavior model picks a random consistent card
EG_HAND = 7
EG_SAMPLES = 16
EG_TIME = 0.025

_S = {}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _v(card, trump):
    return TRUMP_V[card[1]] if card[0] == trump else NONTRUMP_V[card[1]]


def _beats(lead_card, follow_card, trump):
    ls, lr = lead_card
    fs, fr = follow_card
    if fs == ls:
        return fr > lr
    return fs == trump


def _trick_id(view):
    if view.phase == 1:
        return (25 - view.stock_remaining) // 2 + 1
    return 14 + sum(view.tricks_won.values())


def _opp_size(view):
    if view.phase == 1:
        return 13 if not view.current_trick else 12
    n = len(view.your_hand)
    return n if not view.current_trick else n - 1


def _unseen():
    return DECK - _S["ever_mine"] - _S["faceups"] - _S["opp_led"]


# ---------------------------------------------------------------------------
# Particle filter over the opponent's hand
# ---------------------------------------------------------------------------
def _reset(view):
    _S.clear()
    _S["me"] = view.your_name
    _S["ever_mine"] = set(view.your_hand)
    _S["faceups"] = set()
    _S["opp_led"] = set()
    _S["taken_bag"] = set()   # coarse fallback memory of face-ups they won
    _S["pending"] = None
    if view.face_up_card is not None:
        _S["faceups"].add(view.face_up_card)

    pool = list(DECK - _S["ever_mine"] - _S["faceups"])
    parts = []
    if view.current_trick:
        # we are following trick 1: their lead is known, they hold 12 more
        lead = view.current_trick[0][1]
        rest = [c for c in pool if c != lead]
        for _ in range(N_PARTICLES):
            parts.append(set(random.sample(rest, 12)))
        _S["opp_led"].add(lead)
    else:
        for _ in range(N_PARTICLES):
            parts.append(set(random.sample(pool, 13)))
    _S["particles"] = parts


def _swap_out(p, protect=None):
    """Remove one card from particle p, preferring non-certain cards."""
    taken = _S["taken_bag"]
    cands = [c for c in p if c not in taken]
    if not cands:
        cands = list(p)
    if protect is not None:
        keep = [c for c in cands if c != protect]
        if keep:
            cands = keep
    p.discard(random.choice(cands))


def _fresh_card(p, prefer=None):
    """A replacement card for p drawn from the unseen pool."""
    pool = [c for c in (prefer if prefer else _unseen()) if c not in p]
    if not pool:
        pool = [c for c in _unseen() if c not in p]
    if not pool:
        return None
    return random.choice(pool)


def _cull(card):
    """A card proved NOT to be in the opponent's hand: swap it out."""
    for p in _S["particles"]:
        if card in p:
            p.discard(card)
            c = _fresh_card(p)
            if c is not None:
                p.add(c)


def _opp_lead_event(card, view=None):
    """They led `card`: condition every particle on holding it."""
    _S["opp_led"].add(card)
    _S["taken_bag"].discard(card)
    for p in _S["particles"]:
        if card in p:
            p.discard(card)
        else:
            _swap_out(p)
    # Behavioral prior: leading low non-trump junk in phase 2 usually means
    # "no sure winners in hand" (cash-or-exit bots). Softly strip particles
    # of cards that are obvious cashes.
    if view is not None and view.phase == 2 and card[0] != view.trump_suit \
            and card[1] <= 10:
        trump = view.trump_suit
        mine = set(view.your_hand)
        unseen = _unseen()
        for p in _S["particles"]:
            if random.random() >= 0.6:
                continue
            others = mine | unseen | p
            cashes = []
            for c in p:
                if c[1] >= 12 and not any(
                        o[0] == c[0] and o[1] > c[1] and o != c for o in others):
                    cashes.append(c)
            for c in cashes[:2]:
                repl = _fresh_card(p)
                if repl is not None:
                    p.discard(c)
                    p.add(repl)


def _consistent_plays(p, our_lead, they_won, trump):
    ls, lr = our_lead
    same = [c for c in p if c[0] == ls]
    legal = same if same else list(p)
    out = []
    for c in legal:
        wins = _beats(our_lead, c, trump)
        if wins == they_won:
            out.append(c)
    return out


def _rebuild_particle(size, forbid_suit=None):
    """Fresh consistent hypothesis when repair is impossible."""
    pool = list(_unseen() | set(_S["taken_bag"]))
    if forbid_suit is not None:
        pool = [c for c in pool if c[0] != forbid_suit]
    if len(pool) < size:
        pool = list(_unseen() | set(_S["taken_bag"]))
    if len(pool) < size:
        return set(pool)
    return set(random.sample(pool, size))


def _opp_follow_event(our_lead, they_won, trump):
    """They played an unseen card to our lead; outcome is known.

    Particles with a consistent play evolve via the behavior model; the rest
    are REPAIRED: the played card is hypothesised to be an unseen card that
    the particle missed, so one card leaves the particle instead.
    """
    ls, lr = our_lead
    unseen = _unseen()
    u_beater = any(c[0] == ls and c[1] > lr for c in unseen)
    u_lower = any(c[0] == ls and c[1] < lr for c in unseen)
    u_trump = any(c[0] == trump for c in unseen)

    out = []
    for p in _S["particles"]:
        cons = _consistent_plays(p, our_lead, they_won, trump)
        if cons:
            if len(cons) == 1 or random.random() < BEHAVE_EPS:
                played = random.choice(cons)
            else:
                played = min(cons, key=lambda c: _v(c, trump))
            p.discard(played)
            out.append(p)
            continue
        # repair
        size_after = len(p) - 1
        same = [c for c in p if c[0] == ls]
        if same:
            if they_won and u_beater:
                p.discard(random.choice(same))       # played unseen beater
            elif (not they_won) and u_lower:
                p.discard(random.choice(same))       # played unseen low card
            else:
                # their holding of this suit was wrong altogether: they were
                # void (ruffed to win / discarded to lose)
                p = _rebuild_particle(size_after, forbid_suit=ls)
            out.append(p)
        else:
            # particle says void; a win needed a trump, a loss a non-trump
            if they_won and (ls == trump or not u_trump) and not u_beater:
                p = _rebuild_particle(size_after)
            else:
                _swap_out(p)                          # played an unseen card
            out.append(p)
    _S["particles"] = out

    # Behavioral prior: in phase 2 almost every bot WINS cheaply when it can.
    # If they lost to our lead, particles that still hold beaters are suspect.
    if not they_won and _S.get("phase2_rational"):
        for p in _S["particles"]:
            if random.random() >= 0.8:
                continue
            same_p = [c for c in p if c[0] == ls]
            if same_p:
                suspects = [c for c in same_p if c[1] > lr]
            else:
                suspects = [c for c in p if c[0] == trump] if ls != trump else []
            for c in suspects[:2]:
                repl = _fresh_card(p)
                if repl is not None:
                    p.discard(c)
                    p.add(repl)


def _opp_gain_faceup(card):
    for p in _S["particles"]:
        p.add(card)
    _S["taken_bag"].add(card)


def _opp_gain_hidden():
    pool = list(_unseen())
    if not pool:
        return
    for p in _S["particles"]:
        for _ in range(6):
            c = random.choice(pool)
            if c not in p:
                p.add(c)
                break
        else:
            extra = [c for c in pool if c not in p]
            if extra:
                p.add(random.choice(extra))


def _repopulate(size):
    parts = _S["particles"]
    if len(parts) >= MIN_PARTICLES:
        return
    unseen = list(_unseen())
    if parts:
        # clone + mutate survivors
        while len(parts) < N_PARTICLES:
            base = set(random.choice(parts))
            swap_out = [c for c in base]
            swap_in = [c for c in unseen if c not in base]
            if swap_out and swap_in:
                base.discard(random.choice(swap_out))
                base.add(random.choice(swap_in))
            parts.append(base)
        return
    # full rebuild (tracking contradiction): coarse pool
    pool = list((set(unseen) | set(_S["taken_bag"])))
    for _ in range(N_PARTICLES):
        if len(pool) >= size:
            parts.append(set(random.sample(pool, size)))
    if not parts:
        parts.append(set(random.sample(unseen, min(size, len(unseen)))))
    _S["particles"] = parts


def _enforce_size(size):
    _S["particles"] = [p for p in _S["particles"] if len(p) == size]


# ---------------------------------------------------------------------------
# Per-call update
# ---------------------------------------------------------------------------
def _update(view):
    if view.phase == 1 and view.stock_remaining == 25 and len(view.your_hand) == 13:
        _reset(view)
        return _trick_id(view)
    if not _S or "particles" not in _S:
        _reset(view)

    # cards newly proven ours / newly revealed face-ups can't be theirs
    # (update ever_mine BEFORE culling so replacements are drawn correctly)
    new_mine = set(view.your_hand) - _S["ever_mine"]
    _S["ever_mine"].update(new_mine)
    for c in new_mine:
        _cull(c)
        _S["taken_bag"].discard(c)
    fu = view.face_up_card
    if fu is not None and fu not in _S["faceups"]:
        _S["faceups"].add(fu)
        _cull(fu)
        _S["taken_bag"].discard(fu)

    tid = _trick_id(view)

    # resolve our previous lead (their follow was unobserved)
    pend = _S["pending"]
    if pend is not None and pend[0] < tid:
        ptid, pcard, pfu, pphase = pend
        we_won = (view.lead == view.your_name)
        _S["phase2_rational"] = (pphase == 2)
        _opp_follow_event(pcard, not we_won, view.trump_suit)
        if pphase == 1:
            if we_won:
                _opp_gain_hidden()
            elif pfu is not None:
                _opp_gain_faceup(pfu)
        _S["pending"] = None

    # their lead this trick is observed
    if view.current_trick:
        _opp_lead_event(view.current_trick[0][1], view)

    size = _opp_size(view)
    _enforce_size(size)
    _repopulate(size)
    return tid


def _after_move(view, card, tid):
    if view.current_trick:
        lead_card = view.current_trick[0][1]
        we_win = _beats(lead_card, card, view.trump_suit)
        if view.phase == 1:
            if we_win:
                _opp_gain_hidden()
            elif view.face_up_card is not None:
                _opp_gain_faceup(view.face_up_card)
        _S["pending"] = None
    else:
        _S["pending"] = (tid, card, view.face_up_card, view.phase)


# ---------------------------------------------------------------------------
# Particle statistics
# ---------------------------------------------------------------------------
def _suit_summaries():
    """Per particle: {suit: (count, max, min)} plus has_trump flag."""
    out = []
    for p in _S["particles"]:
        d = {}
        for s, r in p:
            if s in d:
                cnt, mx, mn = d[s]
                d[s] = (cnt + 1, max(mx, r), min(mn, r))
            else:
                d[s] = (1, r, r)
        out.append(d)
    return out


def _p_can_beat_lead(card, summaries, trump):
    """P(opp CAN beat this card if we lead it)."""
    s, r = card
    n = len(summaries)
    if n == 0:
        return 0.5
    cnt = 0
    for d in summaries:
        suit = d.get(s)
        if suit is not None:
            if suit[1] > r:
                cnt += 1
        elif s != trump and trump in d:
            cnt += 1
    return cnt / float(n)


def _p_stat(fn):
    parts = _S["particles"]
    if not parts:
        return 0.5
    return sum(1 for p in parts if fn(p)) / float(len(parts))


# ---------------------------------------------------------------------------
# Discard shaping
# ---------------------------------------------------------------------------
def _discard_value(card, hand, trump, opp_max=None):
    """Lower = better to throw. Prefers short weak side suits (digs voids),
    guards honors, clings to trumps and likely masters."""
    s, r = card
    val = _v(card, trump)
    if s == trump:
        return val + TRUMP_CLING
    ranks = [x[1] for x in hand if x[0] == s]
    hi = max(ranks)
    sc = val + DUMP_LEN_W * min(len(ranks), 5)
    if hi == 13 and len(ranks) == 2 and r < hi:
        sc += GUARD_K
    if hi == 12 and len(ranks) <= 3 and r < hi:
        sc += GUARD_Q
    if opp_max is not None and r > opp_max.get(s, 0):
        sc += MASTER_KEEP
    return sc


def _best_discard(cards, hand, trump, opp_max=None):
    return min(cards, key=lambda c: _discard_value(c, hand, trump, opp_max))


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------
def _delta(view):
    """Shape-adjusted worth of the face-up card minus the mean hidden card."""
    fu = view.face_up_card
    if fu is None:
        return 0.0
    trump = view.trump_suit
    unseen = _unseen()
    if unseen:
        mean_u = sum(_v(c, trump) for c in unseen) / float(len(unseen))
    else:
        mean_u = 25.0
    s, r = fu
    val = _v(fu, trump)
    if s == trump:
        val += TR_PREMIUM
    else:
        ln = sum(1 for c in view.your_hand if c[0] == s)
        if ln == 0 and r <= 12:
            val -= VOID_REFILL
        elif ln == 1 and r <= 10:
            val -= NEAR_VOID_PEN
        elif ln >= 4:
            val += LEN_BONUS
    return val - mean_u


def _phase1_follow(view):
    hand = view.your_hand
    trump = view.trump_suit
    lead_card = view.current_trick[0][1]
    ls, lr = lead_card
    delta = _delta(view)

    same = [c for c in hand if c[0] == ls]
    if same:
        duck = min(same, key=lambda c: c[1])
        winners = [c for c in same if c[1] > lr]
        if winners:
            w = min(winners, key=lambda c: c[1])
            if 2.0 * delta > _v(w, trump) - _v(duck, trump) + P1_FOLLOW_MARGIN:
                return w
        return duck

    dump = _best_discard(list(hand), hand, trump)
    if ls != trump:
        trumps = [c for c in hand if c[0] == trump]
        if trumps:
            w = min(trumps, key=lambda c: c[1])
            if 2.0 * delta > _v(w, trump) - _v(dump, trump) + P1_FOLLOW_MARGIN:
                return w              # ruff to steal a face-up worth having
    return dump


def _phase1_lead(view):
    hand = view.your_hand
    trump = view.trump_suit
    delta = _delta(view)
    dump = _best_discard(list(hand), hand, trump)

    if delta > 0.5:
        summaries = _suit_summaries()
        n = max(1, len(summaries))
        dv = _v(dump, trump)
        best, best_ev = None, P1_LEAD_MARGIN
        for c in hand:
            s, r = c
            beat = 0
            for d in summaries:
                suit = d.get(s)
                if suit is not None:
                    if suit[1] > r:
                        beat += 1
                elif s != trump and trump in d:
                    beat += 1          # void: they ruff to take the face-up
            p_win = 1.0 - beat / float(n)
            ev = 2.0 * p_win * delta - (_v(c, trump) - dv)
            if ev > best_ev:
                best, best_ev = c, ev
        if best is not None:
            return best
    # Junk (or unfightable) face-up: force-feed with our shape dump.
    return dump


# ---------------------------------------------------------------------------
# Phase 2 heuristics
# ---------------------------------------------------------------------------
def _particle_env(view):
    """Aggregate particle statistics used by phase-2 decisions."""
    summaries = _suit_summaries()
    n = max(1, len(summaries))
    trump = view.trump_suit
    pt = sum(1 for d in summaries if trump in d) / float(n)
    exp_tr = sum(d[trump][0] for d in summaries if trump in d) / float(n)
    omax = {s: 0 for s in SUITS}
    for d in summaries:
        for s, (cnt, mx, mn) in d.items():
            if mx > omax[s]:
                omax[s] = mx

    def p_void(s):
        return sum(1 for d in summaries if s not in d) / float(n)

    return summaries, pt, exp_tr, omax, p_void


def _phase2_lead(view):
    hand = view.your_hand
    trump = view.trump_suit
    summaries, pt, exp_tr, omax, p_void = _particle_env(view)
    pb = {c: _p_can_beat_lead(c, summaries, trump) for c in hand}
    my_tr = [c for c in hand if c[0] == trump]

    # 1. Cash side masters whose combined beat/ruff risk is low.
    side_safe = [c for c in hand if c[0] != trump and pb[c] <= RISK_MAX]
    if side_safe:
        return min(side_safe, key=lambda c: (pb[c], c[1]))

    # 2. Opponent (near-)trumpless: every trump master we lead is a sure trick.
    if my_tr and pt <= PT_DEAD:
        return min(my_tr, key=lambda c: c[1])

    # 3. Strip their trumps only when our trump masters cover them all and we
    #    keep something to cash afterwards.
    trump_m = [c for c in my_tr if pb[c] <= 0.15]
    n = max(1, len(summaries))
    side_m = [c for c in hand if c[0] != trump and
              sum(1 for d in summaries
                  if c[0] in d and d[c[0]][1] > c[1]) / float(n) <= 0.15]
    if trump_m and exp_tr > 0.4 and len(trump_m) >= exp_tr and \
            (side_m or len(my_tr) >= exp_tr + 2.0):
        return min(trump_m, key=lambda c: c[1])

    # 4. Exit low from a short suit, avoiding their ruff-ready voids.
    exits = [c for c in hand if c[0] != trump] or list(hand)

    def exit_score(c):
        return _discard_value(c, hand, trump, omax) + \
            EXIT_VOID_W * p_void(c[0]) * pt
    return min(exits, key=exit_score)


def _phase2_follow(view):
    hand = view.your_hand
    trump = view.trump_suit
    lead_card = view.current_trick[0][1]
    ls, lr = lead_card

    same = [c for c in hand if c[0] == ls]
    if same:
        winners = [c for c in same if c[1] > lr]
        if winners:
            return min(winners, key=lambda c: c[1])
        return min(same, key=lambda c: c[1])
    if ls != trump:
        trumps = [c for c in hand if c[0] == trump]
        if trumps:
            return min(trumps, key=lambda c: c[1])
    _summ, _pt, _etr, omax, _pv = _particle_env(view)
    return _best_discard(list(hand), hand, trump, omax)


# ---------------------------------------------------------------------------
# Endgame: determinized minimax over particle samples
# ---------------------------------------------------------------------------
def _filter_equiv(cards, other_hand, lead_card=None):
    out = []
    by_suit = {}
    for c in sorted(cards, key=lambda c: (c[0], c[1])):
        by_suit.setdefault(c[0], []).append(c)
    for s, lst in by_suit.items():
        marks = sorted(r for (os_, r) in other_hand if os_ == s)
        if lead_card is not None and lead_card[0] == s:
            marks.append(lead_card[1])
        prev = None
        for c in lst:
            if prev is not None and not any(prev[1] < mr < c[1] for mr in marks):
                continue
            out.append(c)
            prev = c
    return out


def _solve(my, opp, i_lead, trump, memo):
    if not my:
        return 0
    key = (my, opp, i_lead)
    if key in memo:
        return memo[key]
    if i_lead:
        best = -1
        for c in _filter_equiv(my, opp):
            rest_my = tuple(x for x in my if x != c)
            same = [o for o in opp if o[0] == c[0]]
            replies = same if same else list(opp)
            worst = None
            for o in _filter_equiv(replies, rest_my, c):
                rest_opp = tuple(x for x in opp if x != o)
                i_win = not _beats(c, o, trump)
                val = (1 if i_win else 0) + _solve(rest_my, rest_opp, i_win, trump, memo)
                if worst is None or val < worst:
                    worst = val
                if worst <= best:
                    break
            if worst > best:
                best = worst
    else:
        best = None
        for o in _filter_equiv(opp, my):
            rest_opp = tuple(x for x in opp if x != o)
            same = [c for c in my if c[0] == o[0]]
            replies = same if same else list(my)
            sub_best = -1
            for c in _filter_equiv(replies, rest_opp, o):
                rest_my = tuple(x for x in my if x != c)
                i_win = _beats(o, c, trump)
                val = (1 if i_win else 0) + _solve(rest_my, rest_opp, i_win, trump, memo)
                if val > sub_best:
                    sub_best = val
            if best is None or sub_best < best:
                best = sub_best
    memo[key] = best
    return best


def _endgame_move(view):
    hand = view.your_hand
    trump = view.trump_suit
    t0 = time.time()

    if view.current_trick:
        lead_card = view.current_trick[0][1]
        same = [c for c in hand if c[0] == lead_card[0]]
        legal = same if same else list(hand)
    else:
        lead_card = None
        legal = list(hand)
    if len(legal) == 1:
        return legal[0]

    size = _opp_size(view)
    parts = [p for p in _S["particles"] if len(p) == size]
    if not parts:
        return None
    samples = []
    seen = set()
    random.shuffle(parts)
    for p in parts:
        key = tuple(sorted(p))
        if key not in seen:
            seen.add(key)
            samples.append(key)
        if len(samples) >= EG_SAMPLES:
            break

    vals = {c: [] for c in legal}
    for opp in samples:
        memo = {}
        for c in legal:
            rest_my = tuple(sorted(x for x in hand if x != c))
            if lead_card is None:
                same_o = [o for o in opp if o[0] == c[0]]
                replies = same_o if same_o else list(opp)
                worst = None
                for o in replies:
                    rest_opp = tuple(x for x in opp if x != o)
                    i_win = not _beats(c, o, trump)
                    val = (1 if i_win else 0) + _solve(rest_my, rest_opp, i_win, trump, memo)
                    if worst is None or val < worst:
                        worst = val
                vals[c].append(worst)
            else:
                i_win = _beats(lead_card, c, trump)
                val = (1 if i_win else 0) + _solve(rest_my, tuple(sorted(opp)), i_win, trump, memo)
                vals[c].append(val)
        if time.time() - t0 > EG_TIME and len(vals[legal[0]]) >= 4:
            break
    if not vals[legal[0]]:
        return None

    # Objective: maximise P(win the GAME), i.e. P(tricks >= needed), with
    # expected tricks as tiebreak. Falls back to pure expectation when the
    # game is already decided either way.
    needed = 7 - view.tricks_won.get(view.your_name, 0)

    def score(c):
        v = vals[c]
        mean = sum(v) / float(len(v))
        if 1 <= needed <= len(hand):
            hit = sum(1 for x in v if x >= needed) / float(len(v))
            return (hit, mean)
        return (0.0, mean)
    return max(legal, key=score)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _safe_move(view):
    try:
        hand = view.your_hand
        if view.current_trick:
            ls = view.current_trick[0][1][0]
            same = [c for c in hand if c[0] == ls]
            if same:
                return min(same, key=lambda c: c[1])
        return min(hand, key=lambda c: c[1])
    except Exception:
        return view.your_hand[0]


def _legal_ok(view, card):
    if card is None or card not in view.your_hand:
        return False
    if view.current_trick:
        ls = view.current_trick[0][1][0]
        if card[0] != ls and any(c[0] == ls for c in view.your_hand):
            return False
    return True


def _move(view):
    tid = _update(view)

    if view.phase == 1:
        card = _phase1_follow(view) if view.current_trick else _phase1_lead(view)
    else:
        card = None
        if len(view.your_hand) <= EG_HAND:
            card = _endgame_move(view)
        if card is None or not _legal_ok(view, card):
            card = _phase2_follow(view) if view.current_trick else _phase2_lead(view)

    if not _legal_ok(view, card):
        card = _safe_move(view)
    _after_move(view, card, tid)
    return card


def nextMove(gameState):
    try:
        return _move(gameState)
    except Exception:
        return _safe_move(gameState)
