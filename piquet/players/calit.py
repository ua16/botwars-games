# BotWars 2026 Finals — Team Calit — Piquet bot
#
# Architecture (mirrors our German Whist qualifier approach):
#   - Module-level tracker rebuilt each hand (reset on the exchange call).
#   - Exchange: candidate discard subsets evaluated by Monte Carlo over draws.
#   - Declare: claim whenever the category holding is valid (engine picks best).
#   - Tricks: PIMC — sample opponent hands from the unseen pool under
#     constraints, greedy rollouts, maximize expected trick-point margin.
#
# Safety: every decision is wrapped in try/except with a guaranteed-legal
# fallback; search loops are time-budgeted far below the 2s harness limit.

import random
import time

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(7, 15))              # 7..14, 14 = Ace
FULL_DECK = [(s, r) for s in SUITS for r in RANKS]

PRESETS = {
    "balanced": {
        "N_SIMS": 28,           # opponent-hand samples per tricks decision
        "DRAW_SAMPLES": 26,     # MC draws per exchange candidate
        "W_TRICK": 1.0,
        "W_DECL": 1.0,
        "LONG_SUIT_BONUS": 0.55,
        "MAJORITY_SHAPE": 4.0,
        "USE_LOSS_CONSTRAINTS": True,
        "TIME_BUDGET": 0.6,
    },
    "declmax": {
        "N_SIMS": 28,
        "DRAW_SAMPLES": 26,
        "W_TRICK": 0.8,
        "W_DECL": 1.5,
        "LONG_SUIT_BONUS": 0.55,
        "MAJORITY_SHAPE": 4.0,
        "USE_LOSS_CONSTRAINTS": True,
        "TIME_BUDGET": 0.6,
    },
    "trickmax": {
        "N_SIMS": 40,
        "DRAW_SAMPLES": 26,
        "W_TRICK": 1.3,
        "W_DECL": 0.7,
        "LONG_SUIT_BONUS": 0.7,
        "MAJORITY_SHAPE": 5.0,
        "USE_LOSS_CONSTRAINTS": True,
        "TIME_BUDGET": 0.6,
    },
}

_ACTIVE = "balanced"
CONFIG = PRESETS[_ACTIVE]

_RNG = random.Random(20260808)


# ---------------------------------------------------------------------------
# Tracker (per hand)
# ---------------------------------------------------------------------------
def _fresh_tracker():
    return {
        "active": False,
        "my_discards": [],
        "my_plays": [],
        "opp_lead_plays": [],       # opponent cards we actually saw (they led)
        "led_results": [],          # (my_lead_card, i_won) — opp follow unseen
        "opp_drew": None,
        "prev_played": None,
        "prev_we_led": False,
        "prev_tricks_me": 0,
        "prev_phase": None,
        "seen_follow_this_trick": False,
    }


TRACKER = _fresh_tracker()


def _reset_tracker():
    TRACKER.clear()
    TRACKER.update(_fresh_tracker())


def _reconcile_tricks(gs):
    """Resolve the outcome of our previous lead (opp's follow is never shown)."""
    t = TRACKER
    if t["prev_phase"] == "tricks" and t["prev_we_led"] and t["prev_played"] is not None:
        me = gs.your_name
        i_won = gs.tricks_won.get(me, 0) > t["prev_tricks_me"]
        t["led_results"].append((t["prev_played"], i_won))
        t["prev_played"] = None


def _observe(gs):
    if gs.current_trick:
        name, card = gs.current_trick[0]
        if name == gs.opponent_name:
            TRACKER["opp_lead_plays"].append(card)


def _snapshot(gs, played):
    t = TRACKER
    t["my_plays"].append(played)
    t["prev_played"] = played
    t["prev_we_led"] = (len(gs.current_trick) == 0)
    t["prev_tricks_me"] = gs.tricks_won.get(gs.your_name, 0)
    t["prev_phase"] = "tricks"
    t["active"] = True


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _legal_cards(hand, lead_card):
    if lead_card is None:
        return list(hand)
    same = [c for c in hand if c[0] == lead_card[0]]
    return same if same else list(hand)


def _has_sequence(hand):
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], set()).add(c[1])
    for ranks in by_suit.values():
        rs = sorted(ranks)
        run = 1
        for i in range(1, len(rs)):
            if rs[i] == rs[i - 1] + 1:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 1
    return False


def _has_set(hand):
    counts = {}
    for c in hand:
        if c[1] >= 10:
            counts[c[1]] = counts.get(c[1], 0) + 1
    return max(counts.values(), default=0) >= 3


def _suit_lengths(hand):
    d = {s: 0 for s in SUITS}
    for c in hand:
        d[c[0]] += 1
    return d


def _best_runs(hand):
    """Best run length per the whole hand: (length, top_rank) or None."""
    best = None
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], set()).add(c[1])
    for ranks in by_suit.values():
        rs = sorted(ranks)
        i = 0
        while i < len(rs):
            start = i
            while i + 1 < len(rs) and rs[i + 1] == rs[i] + 1:
                i += 1
            length = i - start + 1
            if length >= 3:
                cand = (length, rs[i])
                if best is None or cand > best:
                    best = cand
            i += 1
    return best


def _best_set(hand):
    """(count, rank) of best set (rank-first, matching engine) or None."""
    counts = {}
    for c in hand:
        if c[1] >= 10:
            counts[c[1]] = counts.get(c[1], 0) + 1
    best = None
    for rank, cnt in counts.items():
        if cnt >= 3:
            cand = (rank, cnt)
            if best is None or cand > best:
                best = cand
    if best is None:
        return None
    return (best[1], best[0])   # (count, rank)


# ---------------------------------------------------------------------------
# Static hand evaluation (used by the exchange search)
# ---------------------------------------------------------------------------
_POINT_WIN_P = {0: 0.0, 1: 0.0, 2: 0.03, 3: 0.12, 4: 0.45, 5: 0.78,
                6: 0.93, 7: 0.98, 8: 1.0, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.0}
_SEQ_WIN_P = {3: 0.35, 4: 0.65, 5: 0.88, 6: 0.95, 7: 0.98, 8: 1.0}
_SET_WIN_P = {10: 0.25, 11: 0.40, 12: 0.55, 13: 0.75, 14: 0.95}
_CARD_WIN_P = {14: 1.0, 13: 0.72, 12: 0.45, 11: 0.25, 10: 0.12,
               9: 0.06, 8: 0.03, 7: 0.02}


def _seq_score(length):
    if length == 3:
        return 3
    if length == 4:
        return 4
    return 10 + (length - 5)


def _hand_value(hand, cfg):
    lens = _suit_lengths(hand)
    longest = max(lens.values())

    decl = longest * _POINT_WIN_P.get(longest, 1.0)
    run = _best_runs(hand)
    if run is not None:
        decl += _seq_score(run[0]) * _SEQ_WIN_P.get(run[0], 1.0)
    st = _best_set(hand)
    if st is not None:
        count, rank = st
        base = 14 if count >= 4 else 3
        p = min(1.0, _SET_WIN_P.get(rank, 0.3) + (0.05 if count >= 4 else 0.0))
        decl += base * p

    exp_tricks = sum(_CARD_WIN_P.get(c[1], 0.02) for c in hand)
    for n in lens.values():
        if n > 4:
            exp_tricks += (n - 4) * cfg["LONG_SUIT_BONUS"]
    trick_ev = 2.0 * exp_tricks
    if exp_tricks > 6.0:
        trick_ev += (exp_tricks - 6.0) * cfg["MAJORITY_SHAPE"]

    return cfg["W_DECL"] * decl + cfg["W_TRICK"] * trick_ev


# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------
def _keep_value(card, hand, lens, point_suit, run_suits, set_ranks):
    v = _CARD_WIN_P.get(card[1], 0.02) * 3.0 + card[1] / 14.0
    if card[0] == point_suit:
        v += 2.2
    if card[0] in run_suits:
        v += 2.0
    if card[1] in set_ranks:
        v += 2.0
    v += lens[card[0]] * 0.25
    return v


def _exchange_move(gs, cfg):
    hand = list(gs.your_hand)
    if gs.your_name == gs.elder:
        max_k = min(5, len(hand))
    else:
        max_k = min(gs.talon_remaining or 0, len(hand))
    if max_k <= 0:
        return []

    lens = _suit_lengths(hand)
    point_suit = max(SUITS, key=lambda s: (lens[s], sum(c[1] for c in hand if c[0] == s)))

    # Suits containing a run of >=2 consecutive (protect budding sequences)
    run_suits = set()
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], set()).add(c[1])
    for suit, ranks in by_suit.items():
        rs = sorted(ranks)
        for i in range(1, len(rs)):
            if rs[i] == rs[i - 1] + 1:
                run_suits.add(suit)
                break

    # Ranks >=10 held at least twice (potential sets)
    rank_counts = {}
    for c in hand:
        if c[1] >= 10:
            rank_counts[c[1]] = rank_counts.get(c[1], 0) + 1
    set_ranks = {r for r, n in rank_counts.items() if n >= 2}

    ordered = sorted(hand, key=lambda c: _keep_value(c, hand, lens, point_suit,
                                                    run_suits, set_ranks))
    unseen = [c for c in FULL_DECK if c not in hand]

    ks = {0, max_k}
    if max_k >= 2:
        ks.add(max_k - 1)
    if max_k >= 3:
        ks.add(max_k - 2)

    best_disc = []
    best_val = None
    for k in sorted(ks):
        disc = ordered[:k]
        kept = hand[:]
        for c in disc:
            kept.remove(c)
        if k == 0:
            val = _hand_value(kept, cfg)
        else:
            total = 0.0
            for _ in range(cfg["DRAW_SAMPLES"]):
                draw = _RNG.sample(unseen, k)
                total += _hand_value(kept + draw, cfg)
            val = total / cfg["DRAW_SAMPLES"]
        if best_val is None or val > best_val:
            best_val = val
            best_disc = disc
    return best_disc


# ---------------------------------------------------------------------------
# Declare
# ---------------------------------------------------------------------------
def _declare_move(gs):
    cat = gs.declare_category
    hand = gs.your_hand
    if cat == "sequence" and not _has_sequence(hand):
        return "pass"
    if cat == "set" and not _has_set(hand):
        return "pass"
    if not hand:
        return "pass"
    return ("claim",)


# ---------------------------------------------------------------------------
# Tricks: PIMC with greedy rollouts
# ---------------------------------------------------------------------------
def _g_follow(hand, lead):
    """Greedy follow with full knowledge inside a rollout."""
    same = [c for c in hand if c[0] == lead[0]]
    if same:
        winners = [c for c in same if c[1] > lead[1]]
        if winners:
            return min(winners, key=lambda c: c[1])
        return min(same, key=lambda c: c[1])
    return min(hand, key=lambda c: c[1])


def _g_lead(hand, other):
    """Greedy lead with full knowledge inside a rollout (no trump)."""
    other_max = {}
    for c in other:
        if c[1] > other_max.get(c[0], 0):
            other_max[c[0]] = c[1]
    # Free tricks: suits where opponent is void
    for s in SUITS:
        if s not in other_max:
            mine = [c for c in hand if c[0] == s]
            if mine:
                return min(mine, key=lambda c: c[1])
    # Winning leads: my top card beats their top card
    best = None
    for s in SUITS:
        mine = [c for c in hand if c[0] == s]
        if not mine:
            continue
        my_top = max(c[1] for c in mine)
        if my_top > other_max.get(s, 0):
            if best is None or my_top > best[1]:
                best = (s, my_top)
    if best is not None:
        return best
    return min(hand, key=lambda c: c[1])


def _trick_points(t_me, t_opp, last_me):
    pts = t_me + (1 if last_me else 0)
    opp_pts = t_opp + (0 if last_me else 1)
    if t_me == 12:
        pts += 40 + 30       # capot + pique (opponent scored 0 in tricks)
    elif t_me >= 7:
        pts += 10
    if t_opp == 12:
        opp_pts += 40 + 30
    elif t_opp >= 7:
        opp_pts += 10
    return pts - opp_pts


def _rollout(my_hand, opp_hand, my_lead, t_me, t_opp, last_me):
    my_hand = list(my_hand)
    opp_hand = list(opp_hand)
    while my_hand:
        if my_lead:
            lead = _g_lead(my_hand, opp_hand)
            my_hand.remove(lead)
            fol = _g_follow(opp_hand, lead)
            opp_hand.remove(fol)
            i_win = not (fol[0] == lead[0] and fol[1] > lead[1])
        else:
            lead = _g_lead(opp_hand, my_hand)
            opp_hand.remove(lead)
            fol = _g_follow(my_hand, lead)
            my_hand.remove(fol)
            i_win = fol[0] == lead[0] and fol[1] > lead[1]
        if i_win:
            t_me += 1
        else:
            t_opp += 1
        last_me = i_win
        my_lead = i_win
    return _trick_points(t_me, t_opp, last_me)


def _sample_pool(gs):
    """Unseen pool + opponent hand size."""
    t = TRACKER
    known = set(gs.your_hand)
    known.update(t["my_discards"])
    known.update(t["my_plays"])
    known.update(t["opp_lead_plays"])
    pool = [c for c in FULL_DECK if c not in known]
    completed = sum(gs.tricks_won.values())
    opp_plays = completed + (1 if gs.current_trick else 0)
    opp_size = 12 - opp_plays
    return pool, opp_size


def _sample_opp_hand(pool, opp_size, cfg):
    """One determinized opponent hand honoring lead-loss constraints."""
    p = list(pool)
    if cfg["USE_LOSS_CONSTRAINTS"]:
        for (card, i_won) in TRACKER["led_results"]:
            s, r = card
            if not i_won:
                elig = [c for c in p if c[0] == s and c[1] > r]
            else:
                elig = [c for c in p if not (c[0] == s and c[1] > r)]
            if elig:
                p.remove(_RNG.choice(elig))
    if len(p) < opp_size:
        p = list(pool)
    return _RNG.sample(p, opp_size)


def _tricks_move(gs, cfg):
    start = time.monotonic()
    lead_card = gs.current_trick[0][1] if gs.current_trick else None
    legal = _legal_cards(gs.your_hand, lead_card)
    if len(legal) == 1:
        return legal[0]

    pool, opp_size = _sample_pool(gs)
    me = gs.your_name
    t_me = gs.tricks_won.get(me, 0)
    t_opp = gs.tricks_won.get(gs.opponent_name, 0)

    if opp_size <= 0 or len(pool) < opp_size:
        return _fallback_trick(gs)

    samples = []
    for _ in range(cfg["N_SIMS"]):
        samples.append(_sample_opp_hand(pool, opp_size, cfg))
        if time.monotonic() - start > cfg["TIME_BUDGET"] * 0.3:
            break

    best_move = legal[0]
    best_score = None
    for m in legal:
        my_after = list(gs.your_hand)
        my_after.remove(m)
        total = 0.0
        used = 0
        for opp in samples:
            opp_after = list(opp)
            if lead_card is not None:
                i_win = m[0] == lead_card[0] and m[1] > lead_card[1]
                total += _rollout(my_after, opp_after, i_win,
                                  t_me + (1 if i_win else 0),
                                  t_opp + (0 if i_win else 1), i_win)
            else:
                fol = _g_follow(opp_after, m)
                opp_after.remove(fol)
                i_win = not (fol[0] == m[0] and fol[1] > m[1])
                total += _rollout(my_after, opp_after, i_win,
                                  t_me + (1 if i_win else 0),
                                  t_opp + (0 if i_win else 1), i_win)
            used += 1
            if time.monotonic() - start > cfg["TIME_BUDGET"]:
                break
        avg = total / max(used, 1)
        if best_score is None or avg > best_score:
            best_score = avg
            best_move = m
        if time.monotonic() - start > cfg["TIME_BUDGET"]:
            break
    return best_move


# ---------------------------------------------------------------------------
# Fallbacks (guaranteed legal)
# ---------------------------------------------------------------------------
def _fallback_trick(gs):
    lead_card = gs.current_trick[0][1] if gs.current_trick else None
    legal = _legal_cards(gs.your_hand, lead_card)
    return min(legal, key=lambda c: c[1])


def _fallback(gs):
    phase = gs.phase
    if phase == "exchange":
        return []
    if phase == "declare":
        try:
            return _declare_move(gs)
        except Exception:
            return "pass"
    return _fallback_trick(gs)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def nextMove(gameState):
    try:
        phase = gameState.phase
        if phase == "exchange":
            _reset_tracker()
            move = _exchange_move(gameState, CONFIG)
            TRACKER["my_discards"] = list(move)
            TRACKER["opp_drew"] = gameState.opponent_discarded
            return move
        if phase == "declare":
            return _declare_move(gameState)
        # tricks
        _reconcile_tricks(gameState)
        _observe(gameState)
        move = _tricks_move(gameState, CONFIG)
        # Validate before committing (cheap insurance against logic bugs)
        lead_card = gameState.current_trick[0][1] if gameState.current_trick else None
        if move not in _legal_cards(gameState.your_hand, lead_card):
            move = _fallback_trick(gameState)
        _snapshot(gameState, move)
        return move
    except Exception:
        try:
            return _fallback(gameState)
        except Exception:
            if gameState.phase == "exchange":
                return []
            if gameState.phase == "declare":
                return "pass"
            return list(gameState.your_hand)[0]
