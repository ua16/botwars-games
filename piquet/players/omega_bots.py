"""
apex_piquet.py — BotWars 2026, Stage 1, Piquet entry.

Single-file, standard-library-only Piquet player. Self-contained: does not
import engine.py so it stays safe to submit standalone. All helper logic
below (best_point / best_sequence / best_set / scoring) is a faithful,
independently-written re-implementation of the same rules the actual
engine.py enforces, used only for the bot's own reasoning (never to bypass
validation - the engine remains authoritative for legality/scoring).

Key engine-specific findings this bot is built around (see notes at bottom
of file for the full rationale):

 1. Declaring is (almost) strictly dominant over passing. There is no
    penalty for claiming and losing a category comparison - you only ever
    forfeit if you claim a category you have nothing valid for (sequence
    with no 3+ run, or a set - the engine pre-checks set validity but not
    sequence validity before letting you commit). So: always claim point
    (always valid), and claim sequence/set whenever you actually hold a
    qualifying combo. Passing is only ever used to *avoid an illegal
    claim*, never as a strategic concession.

 2. Mid-hand trick information is much sparser than "traditional" card
    counting assumes: PlayerView only exposes the *current* trick, never a
    running log of this hand's completed tricks. You only ever directly see
    an opponent's played card when they lead a trick you are following. You
    never see the card they played when following *your* lead within the
    same hand - that only becomes visible retroactively in `hand_history`
    on the *next* hand. Real-time trick reasoning therefore leans on (a)
    tricks_won deltas + resolve_trick's mechanics to infer bounds on what
    the opponent must hold, and (b) declaration reveals.

 3. Because pique requires the opponent's trick-phase point *gain* to be
    exactly zero, and every completed trick gives the winner >=1 point,
    pique in this engine can only trigger together with capot (winning all
    12 tricks). It is not a separate, easier-to-reach threshold like in
    traditional rules - so there is no special "pique-hunting" line
    distinct from "try to sweep the hand" once a capot looks plausible.
"""

import random
from itertools import combinations

SUITS = ("H", "D", "C", "S")
RANKS = tuple(range(7, 15))  # 7..14, 14 = Ace
FULL_DECK = tuple((s, r) for s in SUITS for r in RANKS)
TARGET_SCORE = 100

_RNG = random.Random()

# ---------------------------------------------------------------------------
# persistent, in-process memory (legal: lives only inside this player)
# ---------------------------------------------------------------------------
# keyed by opponent_name -> aggregate tendencies observed across hands/games
_OPP_PROFILE = {}
# keyed by (your_name, opponent_name) -> per-hand scoped belief state
_HAND_STATE = {}


def _profile(name):
    p = _OPP_PROFILE.get(name)
    if p is None:
        p = {
            "exchange_counts": [],       # observed opponent discard counts
            "declare_claims": 0,
            "declare_passes": 0,
            "hands_seen": 0,
        }
        _OPP_PROFILE[name] = p
    return p


def _hand_key(view):
    return (view.your_name, view.opponent_name)


def _fresh_hand_state():
    return {
        "reset_for": None,
        "my_played": set(),
        "my_discarded": set(),
        "opp_led_seen": set(),          # cards we directly saw opponent lead
        "opp_certain": set(),           # cards we are sure opponent still holds
        "opp_suit_ceiling": {},         # suit -> rank we know opp has nothing above
        "declared_suits": {},           # our declared point suit info this hand
    }


def _get_hand_state(view):
    key = _hand_key(view)
    st = _HAND_STATE.get(key)
    if st is None:
        st = _fresh_hand_state()
        _HAND_STATE[key] = st

    hand_idx = len(view.hand_history)
    if view.phase == "exchange" and st["reset_for"] != hand_idx:
        st = _fresh_hand_state()
        st["reset_for"] = hand_idx
        _HAND_STATE[key] = st
    return st


# ---------------------------------------------------------------------------
# card / rule helpers (independent re-implementation, engine stays authoritative)
# ---------------------------------------------------------------------------
def point_pip(card):
    r = card[1]
    if r == 14:
        return 11
    if r >= 10:
        return 10
    return r


def best_point(hand):
    by_suit = {s: [] for s in SUITS}
    for c in hand:
        by_suit[c[0]].append(c)
    best_len, best_pips, best_suit = 0, 0, None
    for s, cards in by_suit.items():
        if not cards:
            continue
        length = len(cards)
        pips = sum(point_pip(c) for c in cards)
        if length > best_len or (length == best_len and pips > best_pips):
            best_len, best_pips, best_suit = length, pips, s
    return best_len, best_pips, best_suit


def all_sequences(hand):
    out = []
    by_suit = {s: sorted({c[1] for c in hand if c[0] == s}) for s in SUITS}
    for suit, ranks in by_suit.items():
        if len(ranks) < 3:
            continue
        i = 0
        while i < len(ranks):
            start = i
            while i + 1 < len(ranks) and ranks[i + 1] == ranks[i] + 1:
                i += 1
            run_len = i - start + 1
            if run_len >= 3:
                top = ranks[i]
                run_ranks = ranks[start:i + 1]
                out.append((run_len, top, suit, [(suit, r) for r in run_ranks]))
            i += 1
    return out


def best_sequence(hand):
    seqs = all_sequences(hand)
    return max(seqs, key=lambda s: (s[0], s[1])) if seqs else None


def all_sets(hand):
    by_rank = {}
    for c in hand:
        if c[1] >= 10:
            by_rank.setdefault(c[1], []).append(c)
    return [(len(cards), rank, cards[:4]) for rank, cards in by_rank.items() if len(cards) >= 3]


def best_set(hand):
    sets = all_sets(hand)
    return max(sets, key=lambda s: (s[1], s[0])) if sets else None


def score_point_len(length):
    return length


def score_sequence_len(length):
    if length == 3:
        return 3
    if length == 4:
        return 4
    return 10 + (length - 5)


def score_set_count(count):
    return 14 if count >= 4 else 3


def legal_cards(hand, lead_card):
    if lead_card is None:
        return list(hand)
    same = [c for c in hand if c[0] == lead_card[0]]
    return same if same else list(hand)


def resolve_trick(lead_card, follow_card):
    if follow_card[0] == lead_card[0]:
        return lead_card[1] >= follow_card[1]
    return True


# ---------------------------------------------------------------------------
# hand evaluation
# ---------------------------------------------------------------------------
def evaluate_hand(hand):
    """Scalar quality estimate combining declaration potential + trick strength."""
    plen, ppips, _ = best_point(hand)
    declare_score = plen * 1.4 + ppips * 0.03

    seq = best_sequence(hand)
    if seq:
        declare_score += score_sequence_len(seq[0]) * 0.9

    st = best_set(hand)
    if st:
        declare_score += score_set_count(st[0]) * 0.9

    trick_score = 0.0
    by_suit = {s: sorted([c[1] for c in hand if c[0] == s], reverse=True) for s in SUITS}
    for s, ranks in by_suit.items():
        n = len(ranks)
        for idx, r in enumerate(ranks):
            if r == 14:
                trick_score += 4.6
            elif r == 13:
                trick_score += 3.1
            elif r == 12:
                trick_score += 1.9
            elif r == 11:
                trick_score += 1.0
            else:
                # low cards in long suits gain latent value once high cards fall
                trick_score += 0.15 + 0.08 * max(0, n - 3)
        if n == 0:
            # Being void in a suit means we can *never* contest a trick the
            # opponent leads in it - with no trump to punish them for
            # leading it, a suit we cannot fight for at all is a real
            # liability (empirically confirmed: voiding a suit during
            # exchange let an opponent repeatedly cash cheap winners there
            # late in the hand with zero resistance).
            trick_score -= 1.4
        elif n == 1:
            trick_score -= 0.3  # a singleton is only slightly better - one shot to contest it

    return declare_score + trick_score


# ---------------------------------------------------------------------------
# 1. EXCHANGE
# ---------------------------------------------------------------------------
def _match_phase_weights(view):
    """Return (risk_bias) : >0 favors variance when far behind late, <0 favors
    safety when far ahead late."""
    diff = view.your_score - view.opponent_score
    progress = max(view.your_score, view.opponent_score) / TARGET_SCORE
    risk = 0.0
    if diff < -15:
        risk += 0.6 * progress
    elif diff > 15:
        risk -= 0.4 * progress
    return risk


def choose_exchange(view):
    hand = list(view.your_hand)
    is_elder = view.your_name == view.elder
    if is_elder:
        max_disc = min(5, len(hand))
    else:
        max_disc = min(view.talon_remaining, len(hand))

    if max_disc == 0:
        return []

    # unseen pool for simulating possible draws: everything not currently in our hand
    unseen = [c for c in FULL_DECK if c not in hand]

    # per-card "keep value" heuristic to shrink the discard candidate pool
    seq = best_sequence(hand)
    seq_cards = set(seq[3]) if seq else set()
    st = best_set(hand)
    set_cards = set(st[2]) if st else set()
    _, _, point_suit = best_point(hand)

    def keep_value(card):
        s, r = card
        v = 0.0
        if card in seq_cards:
            v += 6.0
        if card in set_cards:
            v += 6.0
        if s == point_suit:
            v += 0.9
        v += {14: 4.0, 13: 2.6, 12: 1.6, 11: 0.9}.get(r, 0.2)
        return v

    ranked = sorted(hand, key=keep_value)
    candidate_pool_size = min(len(hand), max_disc + 4)
    candidates = ranked[:candidate_pool_size]
    protected = [c for c in hand if c not in candidates]

    # enumerate discard subsets of the weak candidate pool only
    subset_pool = []
    for k in range(0, max_disc + 1):
        if k > len(candidates):
            break
        subset_pool.extend(combinations(candidates, k))
    if not subset_pool:
        subset_pool = [()]

    num_combos = len(subset_pool)
    samples_per_combo = max(4, min(24, 2400 // max(1, num_combos)))
    risk = _match_phase_weights(view)

    best_combo = ()
    best_score = float("-inf")
    for combo in subset_pool:
        k = len(combo)
        remaining = [c for c in hand if c not in combo]
        if k == 0:
            avg = evaluate_hand(remaining)
            best_val = avg
            score = avg
        else:
            pool = unseen
            if len(pool) < k:
                continue
            vals = []
            for _ in range(samples_per_combo):
                drawn = _RNG.sample(pool, k)
                new_hand = remaining + drawn
                vals.append(evaluate_hand(new_hand))
            avg = sum(vals) / len(vals)
            if risk != 0.0 and len(vals) > 1:
                mean = avg
                var = sum((v - mean) ** 2 for v in vals) / len(vals)
                std = var ** 0.5
                score = avg + risk * std
            else:
                score = avg
        if score > best_score:
            best_score = score
            best_combo = combo

    return list(best_combo)


# ---------------------------------------------------------------------------
# 2. DECLARATION
# ---------------------------------------------------------------------------
def choose_declaration(view):
    cat = view.declare_category
    hand = view.your_hand
    prof = _profile(view.opponent_name)

    if cat == "point":
        # always valid; claiming is never worse than passing (see module docstring)
        return "claim"
    if cat == "sequence":
        return "claim" if best_sequence(hand) is not None else "pass"
    if cat == "set":
        return "claim" if best_set(hand) is not None else "pass"
    return "pass"


# ---------------------------------------------------------------------------
# 3. TRICK PLAY
# ---------------------------------------------------------------------------
def _update_hand_state_pretrick(view, st):
    # remember our own cards played this hand (from tricks_won-driven diffing is
    # unreliable for *which* card, so we log directly whenever WE choose one -
    # done in choose_trick after deciding). Here we absorb what we can see now:
    if view.current_trick:
        for name, card in view.current_trick:
            if name == view.opponent_name:
                st["opp_led_seen"].add(card)
                st["opp_certain"].discard(card)

    # absorb declaration reveals once (idempotent - safe to redo each call)
    for decl in view.declarations:
        claim = decl.get("claim")
        if not claim or decl.get("winner") != view.opponent_name:
            continue
        if claim[0] == "sequence":
            _, length, top, suit = claim
            cards = [(suit, r) for r in range(top - length + 1, top + 1)]
            for c in cards:
                if c not in st["opp_led_seen"] and c not in view.your_hand:
                    st["opp_certain"].add(c)
        elif claim[0] == "set" and claim[1] == 4:
            rank = claim[2]
            for s in SUITS:
                c = (s, rank)
                if c not in st["opp_led_seen"] and c not in view.your_hand:
                    st["opp_certain"].add(c)


def _unseen_pool(view, st):
    known = set(view.your_hand) | st["my_played"] | st["my_discarded"] | st["opp_led_seen"]
    return [c for c in FULL_DECK if c not in known]


def _opponent_hand_size(view):
    played = sum(view.tricks_won.values())
    return max(0, 12 - played)


def _sample_opponent_hand(view, st):
    size = _opponent_hand_size(view)
    certain = [c for c in st["opp_certain"] if c not in st["my_played"]]
    certain = certain[:size]
    remaining_needed = size - len(certain)
    pool = [c for c in _unseen_pool(view, st) if c not in certain]
    if remaining_needed <= 0:
        return list(certain)
    if len(pool) < remaining_needed:
        remaining_needed = len(pool)
    sampled = _RNG.sample(pool, remaining_needed) if remaining_needed > 0 else []
    return certain + sampled


def _greedy_play(hand, lead_card):
    """Simple, fast policy used inside rollouts to stand in for 'a reasonable
    opponent' and to project our own future plays cheaply."""
    legal = legal_cards(hand, lead_card)
    if lead_card is None:
        # cash the highest card available - in a no-trump 2-player race for
        # tricks, sure/likely winners are rarely worth holding back
        return max(legal, key=lambda c: c[1])
    same = [c for c in legal if c[0] == lead_card[0]]
    if same:
        beats = [c for c in same if c[1] > lead_card[1]]
        if beats:
            return min(beats, key=lambda c: c[1])
        return min(same, key=lambda c: c[1])
    return min(legal, key=lambda c: c[1])


def _hand_value(my_tricks, opp_tricks):
    """Approximate remaining trick-phase point value (bonuses only meaningfully
    resolved at 12 tricks total, so this is an estimate mid-hand)."""
    val = my_tricks - opp_tricks
    total = my_tricks + opp_tricks
    if total >= 12:
        if my_tricks == 12:
            val += 4.0
        elif my_tricks >= 7:
            val += 1.0
        elif opp_tricks == 12:
            val -= 4.0
        elif opp_tricks >= 7:
            val -= 1.0
    return val


def choose_trick(view):
    key = _hand_key(view)
    st = _get_hand_state(view)
    _update_hand_state_pretrick(view, st)

    hand = view.your_hand
    lead_card = view.current_trick[0][1] if view.current_trick else None
    legal = legal_cards(hand, lead_card)

    if len(legal) == 1:
        chosen = legal[0]
        st["my_played"].add(chosen)
        return chosen

    remaining_tricks = 12 - sum(view.tricks_won.values())
    my_tricks_so_far = view.tricks_won.get(view.your_name, 0)
    opp_tricks_so_far = view.tricks_won.get(view.opponent_name, 0)

    # deep(er) search once few cards remain - fully determinized samples
    if remaining_tricks <= 7:
        num_samples = 24 if remaining_tricks <= 4 else 14
        best_card, best_score = None, float("-inf")
        for card in legal:
            total = 0.0
            for _ in range(num_samples):
                opp_hand = _sample_opponent_hand(view, st)
                my_rest = [c for c in hand if c != card]
                if lead_card is None:
                    # we lead this trick with `card`
                    if opp_hand:
                        fc = _greedy_play(opp_hand, card)
                        opp_rest = [c for c in opp_hand if c != fc]
                        i_win = resolve_trick(card, fc)
                    else:
                        opp_rest = []
                        i_win = True
                    mt = my_tricks_so_far + (1 if i_win else 0)
                    ot = opp_tricks_so_far + (0 if i_win else 1)
                    final_mt, final_ot = _rollout_value_wrapper(
                        my_rest, opp_rest, None, i_win, mt, ot
                    )
                else:
                    # we are following; opp already led lead_card
                    i_win = resolve_trick(lead_card, card)
                    mt = my_tricks_so_far + (1 if i_win else 0)
                    ot = opp_tricks_so_far + (0 if i_win else 1)
                    final_mt, final_ot = _rollout_value_wrapper(
                        my_rest, [c for c in opp_hand], None, i_win, mt, ot
                    )
                total += _hand_value(final_mt, final_ot)
            avg = total / num_samples
            if avg > best_score:
                best_score = avg
                best_card = card
        chosen = best_card if best_card is not None else legal[0]
        st["my_played"].add(chosen)
        return chosen

    # mid/early game: heuristic scoring (fast, no rollout)
    best_card, best_score = None, float("-inf")
    opp_ceiling = st["opp_suit_ceiling"]
    for card in legal:
        s, r = card
        score = 0.0
        if lead_card is None:
            ceiling = opp_ceiling.get(s)
            if ceiling is not None and r > ceiling:
                score += 3.0  # likely a safe winner if we already know opp tops out lower here
            # aces always win outright (no trump); kings/queens are usually
            # strong too - cash sure/likely winners and keep the tempo of
            # leading rather than sitting on them.
            score += r * 0.18
            if r == 14:
                score += 1.6
            elif r == 13:
                score += 0.7
            suit_len = sum(1 for c in hand if c[0] == s)
            if suit_len >= 4 and r <= 10:
                score += 0.35  # mild probe value with a low card from a long suit
        else:
            same_suit = card[0] == lead_card[0]
            if same_suit and r > lead_card[1]:
                margin = r - lead_card[1]
                score += 2.0 - 0.05 * margin  # win as cheaply as possible
            elif same_suit:
                score -= r * 0.05  # must follow but can't win - shed the lowest of that suit
            else:
                score -= r * 0.05  # can't follow suit - shed our least valuable off-suit card
        if best_card is None or score > best_score:
            best_score = score
            best_card = card

    chosen = best_card if best_card is not None else legal[0]
    st["my_played"].add(chosen)
    return chosen


def _rollout_value_wrapper(my_rest, opp_rest, lead, i_won_current, mt, ot):
    turn_is_me = i_won_current
    return _rollout_play(my_rest, opp_rest, turn_is_me, mt, ot)


def _rollout_play(my_hand, opp_hand, turn_is_me, my_tricks, opp_tricks):
    my_hand = list(my_hand)
    opp_hand = list(opp_hand)
    while my_hand or opp_hand:
        if turn_is_me:
            if not my_hand:
                break
            lead = _greedy_play(my_hand, None)
            my_hand.remove(lead)
            if opp_hand:
                fc = _greedy_play(opp_hand, lead)
                opp_hand.remove(fc)
                i_win = resolve_trick(lead, fc)
            else:
                i_win = True
        else:
            if not opp_hand:
                break
            lead = _greedy_play(opp_hand, None)
            opp_hand.remove(lead)
            if my_hand:
                fc = _greedy_play(my_hand, lead)
                my_hand.remove(fc)
                i_win = not resolve_trick(lead, fc)
            else:
                i_win = False
        if i_win:
            my_tricks += 1
            turn_is_me = True
        else:
            opp_tricks += 1
            turn_is_me = False
    return my_tricks, opp_tricks


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def nextMove(gameState):
    view = gameState
    if view.phase == "exchange":
        return choose_exchange(view)
    if view.phase == "declare":
        return choose_declaration(view)
    if view.phase == "tricks":
        return choose_trick(view)
    raise ValueError(f"unknown phase: {view.phase!r}")
