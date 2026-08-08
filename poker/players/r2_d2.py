#R2_D2 Poker Player

import itertools
import random
from collections import Counter

SUITS = ("H", "D", "C", "S")
RANKS = list(range(2, 15))
_DECK = [(s, r) for s in SUITS for r in RANKS]


# ---------------------------------------------------------------------------
# Hand evaluation (mirrors engine._evaluate_five for self-containment)
# ---------------------------------------------------------------------------
def _straight_high(ranks_set):
    unique = sorted(ranks_set, reverse=True)
    if 14 in unique:
        unique.append(1)
    unique = sorted(set(unique), reverse=True)
    for i in range(len(unique) - 4):
        window = unique[i : i + 5]
        if window[0] - window[4] == 4:
            return window[0]
    return None


def _evaluate_five(cards):
    ranks = sorted((c[1] for c in cards), reverse=True)
    suits = [c[0] for c in cards]
    counts = Counter(ranks)
    by_freq = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(set(ranks))

    if is_flush and straight_high:
        return (8, straight_high)
    if by_freq[0][1] == 4:
        return (6, by_freq[0][0], by_freq[1][0])
    if by_freq[0][1] == 3 and by_freq[1][1] == 2:
        return (5, by_freq[0][0], by_freq[1][0])
    if is_flush:
        return (4,) + tuple(ranks)
    if straight_high:
        return (3, straight_high)
    if by_freq[0][1] == 3:
        trips = by_freq[0][0]
        kickers = tuple(r for r in ranks if r != trips)
        return (2, trips) + kickers
    if by_freq[0][1] == 2 and by_freq[1][1] == 2:
        hi = max(by_freq[0][0], by_freq[1][0])
        lo = min(by_freq[0][0], by_freq[1][0])
        kicker = next(r for r in ranks if r not in (hi, lo))
        return (1, hi, lo, kicker)
    if by_freq[0][1] == 2:
        pair = by_freq[0][0]
        kickers = tuple(r for r in ranks if r != pair)
        return (0, pair) + kickers
    return (-1,) + tuple(ranks)


def _best_of(cards):
    best = None
    for combo in itertools.combinations(cards, 5):
        score = _evaluate_five(combo)
        if best is None or score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# Monte Carlo equity
# ---------------------------------------------------------------------------
def _mc_equity(hole, board, n_opp, n_sims):
    known = set(hole) | set(board)
    unknown = [c for c in _DECK if c not in known]
    board_needed = 5 - len(board)
    wins = 0.0

    for _ in range(n_sims):
        random.shuffle(unknown)
        idx = 0
        opps = []
        for _ in range(n_opp):
            opps.append(unknown[idx : idx + 2])
            idx += 2
        completed_board = list(board) + unknown[idx : idx + board_needed]

        my_score = _best_of(list(hole) + completed_board)
        opp_scores = [_best_of(o + completed_board) for o in opps]
        if not opp_scores:
            wins += 1
            continue

        max_opp = max(opp_scores)
        if my_score > max_opp:
            wins += 1
        elif my_score == max_opp:
            n_tied = 1 + sum(1 for s in opp_scores if s == max_opp)
            wins += 1.0 / n_tied

    return wins / n_sims


# ---------------------------------------------------------------------------
# PlayerView helpers
# ---------------------------------------------------------------------------
def _active_opponent_count(gs):
    count = 0
    for name, status in gs.player_status.items():
        if name == gs.your_name:
            continue
        if status != "folded":
            count += 1
    return max(1, count)


def _reconstruct_street_wager(gs):
    """Rebuild our street commitment (needed to compute all-in raise targets)."""
    level = 0
    my_wager = 0
    for name, action in gs.action_history:
        kind = action[0]
        if kind in ("bet", "raise") and len(action) >= 2:
            level = action[1]
            if name == gs.your_name:
                my_wager = level
        elif kind == "call" and name == gs.your_name:
            my_wager = level
    return my_wager, level


# ---------------------------------------------------------------------------
# Bet sizing helpers
# ---------------------------------------------------------------------------
def _clamp_bet(amount, stack):
    if stack <= 0:
        return 0
    return max(1, min(amount, stack))


def _pot_fraction_bet(gs, fraction, floor):
    pot = max(0, gs.pot)
    stack = gs.your_stack
    target = int(pot * fraction) if pot > 0 else floor
    target = max(target, floor)
    return _clamp_bet(target, stack)


def _raise_target(gs, fraction):
    """Return a legal raise-to target that adds ~fraction*pot on top of the call."""
    if gs.min_raise_to is None:
        return None
    my_wager, _level = _reconstruct_street_wager(gs)
    max_to = my_wager + gs.your_stack
    min_to = gs.min_raise_to
    if min_to > max_to:
        return None
    pot_after_call = gs.pot + gs.amount_to_call
    extra = int(pot_after_call * fraction) if pot_after_call > 0 else 0
    target = min_to + max(0, extra)
    if target > max_to:
        target = max_to
    if target < min_to:
        target = min_to
    return target


# ---------------------------------------------------------------------------
# Equity estimation router
# ---------------------------------------------------------------------------
def _estimate_equity(gs, n_opp):
    hole = gs.your_hole_cards
    board = gs.community_cards
    street = gs.street

    if street == "preflop":
        sims = 220
    elif street == "flop":
        sims = 320
    elif street == "turn":
        sims = 420
    else:
        sims = 500

    if n_opp > 2:
        sims = max(120, sims // (n_opp - 1))

    return _mc_equity(hole, board, n_opp, sims)


# ---------------------------------------------------------------------------
# Decision core
# ---------------------------------------------------------------------------
def nextMove(gameState):
    try:
        return _decide(gameState)
    except Exception:
        if gameState.amount_to_call == 0:
            return ("check",)
        return ("fold",)


def _decide(gs):
    stack = gs.your_stack
    to_call = gs.amount_to_call
    pot = gs.pot
    street = gs.street

    if stack <= 0:
        return ("check",) if to_call == 0 else ("call",)

    n_opp = _active_opponent_count(gs)
    equity = _estimate_equity(gs, n_opp)

    if to_call == 0:
        return _decide_unbet(gs, equity, pot, stack, street)
    return _decide_facing_bet(gs, equity, pot, stack, to_call, street)


def _decide_unbet(gs, equity, pot, stack, street):
    if street == "preflop":
        if equity >= 0.85:
            return ("bet", _clamp_bet(4500, stack))
        if equity >= 0.70:
            return ("bet", _clamp_bet(2500, stack))
        if equity >= 0.58:
            return ("bet", _clamp_bet(1200, stack))
        return ("check",)

    if equity >= 0.90:
        target = _pot_fraction_bet(gs, 1.2, 3000)
        return ("bet", target)
    if equity >= 0.75:
        target = _pot_fraction_bet(gs, 0.75, 2000)
        return ("bet", target)
    if equity >= 0.60:
        target = _pot_fraction_bet(gs, 0.5, 1500)
        return ("bet", target)
    if equity >= 0.50 and pot >= 4000:
        target = _pot_fraction_bet(gs, 0.35, 800)
        return ("bet", target)
    return ("check",)


def _decide_facing_bet(gs, equity, pot, stack, to_call, street):
    if pot + to_call <= 0:
        pot_odds = 1.0
    else:
        pot_odds = to_call / (pot + to_call)

    margin = 0.03 if street != "preflop" else 0.02

    if equity >= 0.90:
        target = _raise_target(gs, 1.0)
        if target is not None:
            return ("raise", target)
        return ("call",)

    if equity >= 0.78:
        target = _raise_target(gs, 0.5)
        if target is not None:
            return ("raise", target)
        return ("call",)

    if equity >= 0.65 and to_call <= stack // 3:
        target = _raise_target(gs, 0.0)
        if target is not None and street != "river":
            return ("raise", target)
        return ("call",)

    if to_call >= stack:
        if equity >= pot_odds + margin:
            return ("call",)
        return ("fold",)

    if equity + margin >= pot_odds:
        return ("call",)

    return ("fold",)
