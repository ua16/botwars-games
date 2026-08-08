# legendary_fixed.py
# Competition-grade two-player Spades bot.
#
# Design goals:
#   * hard move budget below 1.5 s
#   * keep a very fast TEST_MODE
#   * never generate an illegal move from current_trick
#   * use exact alpha-beta search when the opponent hand is fully inferable
#   * otherwise use bid-aware determinizations with common random numbers
#   * use stronger contract-aware rollout play and conservative Nil bidding

import random
import time


# ===========================================================================
# LOCAL TESTING TOGGLE
# ===========================================================================
# True  -> very fast local tests
# False -> competition search, hard-capped below 1.5 seconds
TEST_MODE = False

TEST_TIME_LIMIT = 0.055
COMP_TIME_LIMIT = 1.38       # leaves ~0.12 s safety under a 1.5 s limit
BID_TEST_TIME_LIMIT = 0.025
BID_COMP_TIME_LIMIT = 0.22

# Search tuning. Root moves are NEVER pruned; only interior search nodes are.
MAX_INTERIOR_MOVES = 7
TIME_CHECK_MASK = 63         # check clock every 64 search nodes
# ===========================================================================

SUITS = ("H", "D", "C", "S")
SPADE = "S"
RANKS = tuple(range(2, 15))

# The original competition bot used a 50-card deck with 2C and 2D removed.
DECK = tuple(
    (s, r)
    for s in SUITS
    for r in RANKS
    if not (s in ("C", "D") and r == 2)
)


class _SearchTimeout(Exception):
    pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def nextMove(gameState):
    """Competition entry point."""
    start_time = time.perf_counter()
    if gameState.phase == "bid":
        return get_best_bid(gameState, start_time)
    return get_best_play(gameState, start_time)


# ---------------------------------------------------------------------------
# Bidding
# ---------------------------------------------------------------------------

def get_best_bid(gameState, start_time=None):
    """
    Contract-aware bid estimator.

    It starts from a fast structural hand estimate, then (when time allows)
    stress-tests nearby bids against plausible opponent hands. Nil is allowed,
    but only for genuinely low-risk hands.
    """
    if start_time is None:
        start_time = time.perf_counter()

    hand = list(gameState.your_hand)
    bags = getattr(gameState, "your_bags", 0)
    structural = quick_bid_estimate(hand)
    base = int(round(structural))

    # The original code supported Nil in scoring but accidentally clamped every
    # bid to at least 1. Keep Nil, but make it deliberately conservative.
    nil_ok = is_safe_nil_hand(hand)

    max_bid = min(13, len(hand))
    candidates = set()
    for b in range(base - 2, base + 3):
        candidates.add(max(1, min(max_bid, b)))
    if nil_ok:
        candidates.add(0)

    # Bags near the penalty line make a slightly higher contract attractive.
    if bags >= 8:
        candidates.add(max(1, min(max_bid, base + 1)))

    # If the game object is minimal, the structural estimate is still safe.
    unseen = get_unseen_cards(gameState)
    opp_size = len(hand)
    opp_voids = get_opponent_voids(gameState)

    time_budget = BID_TEST_TIME_LIMIT if TEST_MODE else BID_COMP_TIME_LIMIT
    deadline = start_time + time_budget

    # Deterministic per-state RNG: reproducible tests, no global RNG pollution.
    rng = random.Random(_state_seed(gameState, salt=0xB1D))

    totals = {b: 0.0 for b in candidates}
    counts = {b: 0 for b in candidates}

    # Estimate opponent contract from sampled hand strength. At bidding time the
    # official opponent bid may not exist yet, so this avoids assuming it does.
    while time.perf_counter() < deadline:
        opp = deal_hand(unseen, opp_size, opp_voids, rng=rng)
        if len(opp) != opp_size:
            break
        opp_bid = max(1, min(max_bid, int(round(quick_bid_estimate(opp)))))

        for bid in candidates:
            if time.perf_counter() >= deadline:
                break
            mt, ot = rollout_trick_counts(
                hand, opp,
                getattr(gameState, "lead", getattr(gameState, "your_name", "me")),
                getattr(gameState, "your_name", "me"),
                bid, opp_bid,
            )
            score = calculate_score(bid, mt, bags)
            # Opponent bags are unavailable in some bid states; default to zero.
            opp_score = calculate_score(
                opp_bid, ot, getattr(gameState, "opponent_bags", 0)
            )
            totals[bid] += score - opp_score
            counts[bid] += 1

    if any(counts.values()):
        def bid_value(b):
            mean = totals[b] / max(1, counts[b])
            # Tiny conservatism on ambitious contracts; missing a bid is costly.
            return mean - 0.20 * max(0, b - structural)

        return max(candidates, key=lambda b: (bid_value(b), -abs(b - structural), -b))

    # Structural fallback.
    if nil_ok and structural < 0.55:
        return 0
    bid = max(1, min(max_bid, base))
    if bags >= 8:
        bid = min(max_bid, bid + 1)
    return bid


def quick_bid_estimate(hand):
    """Fast hand-strength estimate used for bidding and opponent modelling."""
    suits = {s: [] for s in SUITS}
    for s, r in hand:
        suits[s].append(r)
    for ranks in suits.values():
        ranks.sort(reverse=True)

    value = 0.0

    # Side suits: honors gain value when protected; unsupported honors are cut.
    for s in ("H", "D", "C"):
        ranks = suits[s]
        n = len(ranks)
        if not ranks:
            continue
        if 14 in ranks:
            value += 0.95
        if 13 in ranks:
            value += 0.72 if 14 in ranks or n <= 3 else 0.48
        if 12 in ranks:
            value += 0.42 if (14 in ranks or 13 in ranks) else (0.24 if n <= 3 else 0.12)
        if 11 in ranks and (14 in ranks or 13 in ranks):
            value += 0.16

    spades = suits[SPADE]
    nsp = len(spades)
    # High trumps.
    for r, w in ((14, 1.00), (13, 0.92), (12, 0.75), (11, 0.55), (10, 0.34)):
        if r in spades:
            value += w

    # Trump length turns middling spades into eventual winners.
    if nsp > 3:
        value += 0.62 * (nsp - 3)
    if nsp > 6:
        value += 0.16 * (nsp - 6)

    # Ruffing potential from short side suits, but only with enough trumps.
    if nsp >= 3:
        for s in ("H", "D", "C"):
            n = len(suits[s])
            if n == 0:
                value += 0.58
            elif n == 1:
                value += 0.32
            elif n == 2:
                value += 0.12

    return max(0.0, value)


def is_safe_nil_hand(hand):
    """Conservative Nil gate. False positives are much more expensive than misses."""
    if not hand:
        return False
    suits = {s: [] for s in SUITS}
    for s, r in hand:
        suits[s].append(r)

    spades = suits[SPADE]
    if len(spades) >= 5:
        return False
    if any(r >= 12 for r in spades):
        return False

    danger = 0.0
    for s in ("H", "D", "C"):
        ranks = suits[s]
        n = len(ranks)
        for r in ranks:
            if r == 14:
                danger += 2.4
            elif r == 13:
                danger += 1.45 if n <= 4 else 1.0
            elif r == 12:
                danger += 0.75 if n <= 3 else 0.42
            elif r == 11:
                danger += 0.28 if n <= 2 else 0.12
    for r in spades:
        if r >= 10:
            danger += 0.5

    return danger <= 0.9 and quick_bid_estimate(hand) < 0.7


# ---------------------------------------------------------------------------
# Play engine
# ---------------------------------------------------------------------------

def get_best_play(gameState, start_time):
    """Choose the strongest legal card while respecting a hard time deadline."""
    my_hand = list(gameState.your_hand)
    trick = list(getattr(gameState, "current_trick", []) or [])
    lead_card = extract_lead_card(trick)
    spades_broken = bool(getattr(gameState, "spades_broken", False))

    # CRITICAL: legal-card filtering must receive the lead CARD, not current_trick.
    legal_moves = get_legal_cards(my_hand, lead_card, spades_broken)
    if len(legal_moves) == 1:
        return legal_moves[0]

    limit = TEST_TIME_LIMIT if TEST_MODE else COMP_TIME_LIMIT
    deadline = start_time + limit

    unseen = get_unseen_cards(gameState)
    opp_voids = get_opponent_voids(gameState)
    opp_hand_size = opponent_cards_remaining(gameState, len(my_hand), trick)

    my_name = getattr(gameState, "your_name", "me")
    opp_name = getattr(gameState, "opponent_name", "opp")
    my_tricks = getattr(gameState, "tricks_won", {}).get(my_name, 0)
    opp_tricks = getattr(gameState, "tricks_won", {}).get(opp_name, 0)
    my_bid = getattr(gameState, "your_bid", 1)
    opp_bid = getattr(gameState, "opponent_bid", 1)
    my_bags = getattr(gameState, "your_bags", 0)
    opp_bags = getattr(gameState, "opponent_bags", 0)

    possible = [c for c in unseen if c[0] not in opp_voids]

    # If every unseen feasible card must be in the opponent's hand, information
    # is exact. Repeating Monte Carlo samples would be pure wasted CPU.
    exact_hand = None
    if len(unseen) == opp_hand_size:
        exact_hand = list(unseen)
    elif len(possible) == opp_hand_size:
        exact_hand = list(possible)

    if exact_hand is not None:
        return perfect_information_move(
            legal_moves, my_hand, exact_hand, trick, lead_card, spades_broken,
            my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags,
            deadline,
        )

    return determinized_move(
        gameState, legal_moves, my_hand, unseen, opp_hand_size, opp_voids,
        trick, lead_card, spades_broken,
        my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags,
        deadline,
    )


def opponent_cards_remaining(gameState, my_hand_size, trick):
    """Infer how many cards are still in the opponent's hand."""
    size = my_hand_size
    if trick:
        # If opponent already played into the current trick, their hand has one
        # fewer card than ours at the moment nextMove() is called.
        first_player = trick[0][0] if _is_play_record(trick[0]) else None
        if first_player == getattr(gameState, "opponent_name", None):
            size -= 1
    return max(0, size)


def perfect_information_move(
    legal_moves, my_hand, opp_hand, trick, lead_card, spades_broken,
    my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags, deadline,
):
    """Iterative-deepening alpha-beta search for a fully known opponent hand."""
    # Safe fallback is available before search starts.
    fallback = root_policy_choice(
        legal_moves, my_hand, opp_hand, lead_card, spades_broken,
        my_tricks, my_bid,
    )
    best_move = fallback
    ordered_root = order_root_moves(
        legal_moves, my_hand, opp_hand, lead_card, spades_broken,
        my_tricks, my_bid,
    )

    max_depth = min(len(my_hand), 18)
    depth = 1
    while depth <= max_depth and time.perf_counter() < deadline:
        ctx = {
            "deadline": deadline,
            "nodes": 0,
            "tt": {},
            "my_bid": my_bid,
            "opp_bid": opp_bid,
            "my_bags": my_bags,
            "opp_bags": opp_bags,
        }
        try:
            move, _ = root_alpha_beta(
                ordered_root, my_hand, opp_hand, trick, lead_card,
                spades_broken, my_tricks, opp_tricks, depth, ctx,
            )
            best_move = move
            # Principal-variation ordering: previous winner first next iteration.
            ordered_root = [best_move] + [m for m in ordered_root if m != best_move]
            depth += 1
        except _SearchTimeout:
            break

    return best_move


def root_alpha_beta(
    legal_moves, my_hand, opp_hand, trick, lead_card, spades_broken,
    my_tricks, opp_tricks, depth, ctx,
):
    best_move = legal_moves[0]
    best_value = float("-inf")
    alpha = float("-inf")
    beta = float("inf")

    for move in legal_moves:
        _check_time(ctx)
        value, next_my, next_opp, next_leader, next_broken, mt, ot = apply_root_move(
            move, my_hand, opp_hand, trick, lead_card, spades_broken,
            my_tricks, opp_tricks, ctx,
            search_depth=max(0, depth - 1),
            alpha=alpha, beta=beta,
        )
        if value is None:
            value = alpha_beta_state(
                next_my, next_opp, next_leader, next_broken,
                mt, ot, max(0, depth - 1), alpha, beta, ctx,
            )

        if value > best_value:
            best_value = value
            best_move = move
        alpha = max(alpha, best_value)

    return best_move, best_value


def apply_root_move(
    move, my_hand, opp_hand, trick, lead_card, spades_broken,
    my_tricks, opp_tricks, ctx, search_depth, alpha, beta,
):
    """
    Apply our root move. If we are leading, opponent chooses the worst response
    for us (minimizing). If we are following, the trick resolves immediately.
    """
    my_after = list(my_hand)
    my_after.remove(move)

    if lead_card is not None:
        won = card_beats(move, lead_card, lead_card[0])
        if won:
            my_tricks += 1
            leader = "me"
        else:
            opp_tricks += 1
            leader = "opp"
        broken = spades_broken or move[0] == SPADE or lead_card[0] == SPADE
        return None, tuple(sorted(my_after)), tuple(sorted(opp_hand)), leader, broken, my_tricks, opp_tricks

    # We lead: opponent gets to choose a legal response.
    responses = get_legal_cards(opp_hand, move, spades_broken)
    responses = order_interior_moves(
        responses, opp_hand, my_after, move, spades_broken,
        opp_tricks, ctx["opp_bid"], maximizing=False,
    )

    worst = float("inf")
    worst_state = None
    for response in responses:
        _check_time(ctx)
        opp_after = list(opp_hand)
        opp_after.remove(response)
        broken = spades_broken or move[0] == SPADE or response[0] == SPADE
        if card_beats(move, response, move[0]):
            mt, ot, leader = my_tricks + 1, opp_tricks, "me"
        else:
            mt, ot, leader = my_tricks, opp_tricks + 1, "opp"

        val = alpha_beta_state(
            tuple(sorted(my_after)), tuple(sorted(opp_after)), leader, broken,
            mt, ot, search_depth, alpha, beta, ctx,
        )
        if val < worst:
            worst = val
            worst_state = (tuple(sorted(my_after)), tuple(sorted(opp_after)), leader, broken, mt, ot)
        beta = min(beta, worst)
        if beta <= alpha:
            break

    if worst_state is None:
        # Defensive fallback; should never happen with a legal opponent hand.
        return terminal_utility(my_tricks, opp_tricks, ctx), tuple(sorted(my_after)), tuple(sorted(opp_hand)), "me", spades_broken, my_tricks, opp_tricks

    return worst, *worst_state


def alpha_beta_state(my_hand, opp_hand, leader, spades_broken,
                     my_tricks, opp_tricks, depth, alpha, beta, ctx):
    """Search from the start of a trick."""
    _check_time(ctx)

    if not my_hand or not opp_hand:
        return terminal_utility(my_tricks, opp_tricks, ctx)

    if depth <= 0:
        return rollout_value(
            list(my_hand), list(opp_hand), leader, spades_broken,
            my_tricks, opp_tricks,
            ctx["my_bid"], ctx["opp_bid"], ctx["my_bags"], ctx["opp_bags"],
        )

    key = (my_hand, opp_hand, leader, spades_broken, my_tricks, opp_tricks, depth)
    cached = ctx["tt"].get(key)
    if cached is not None:
        return cached

    completed = True

    if leader == "me":
        leads = get_legal_cards(my_hand, None, spades_broken)
        leads = order_interior_moves(
            leads, my_hand, opp_hand, None, spades_broken,
            my_tricks, ctx["my_bid"], maximizing=True,
        )
        best = float("-inf")
        for m in leads:
            _check_time(ctx)
            my_after = list(my_hand)
            my_after.remove(m)
            responses = get_legal_cards(opp_hand, m, spades_broken)
            responses = order_interior_moves(
                responses, opp_hand, my_after, m, spades_broken,
                opp_tricks, ctx["opp_bid"], maximizing=False,
            )
            worst_response = float("inf")
            local_beta = beta
            for o in responses:
                opp_after = list(opp_hand)
                opp_after.remove(o)
                broken = spades_broken or m[0] == SPADE or o[0] == SPADE
                if card_beats(m, o, m[0]):
                    mt, ot, next_leader = my_tricks + 1, opp_tricks, "me"
                else:
                    mt, ot, next_leader = my_tricks, opp_tricks + 1, "opp"
                val = alpha_beta_state(
                    tuple(sorted(my_after)), tuple(sorted(opp_after)), next_leader,
                    broken, mt, ot, depth - 1, alpha, local_beta, ctx,
                )
                worst_response = min(worst_response, val)
                local_beta = min(local_beta, worst_response)
                if local_beta <= alpha:
                    completed = False
                    break
            best = max(best, worst_response)
            alpha = max(alpha, best)
            if alpha >= beta:
                completed = False
                break
    else:
        leads = get_legal_cards(opp_hand, None, spades_broken)
        leads = order_interior_moves(
            leads, opp_hand, my_hand, None, spades_broken,
            opp_tricks, ctx["opp_bid"], maximizing=False,
        )
        best = float("inf")
        for o in leads:
            _check_time(ctx)
            opp_after = list(opp_hand)
            opp_after.remove(o)
            responses = get_legal_cards(my_hand, o, spades_broken)
            responses = order_interior_moves(
                responses, my_hand, opp_after, o, spades_broken,
                my_tricks, ctx["my_bid"], maximizing=True,
            )
            best_response = float("-inf")
            local_alpha = alpha
            for m in responses:
                my_after = list(my_hand)
                my_after.remove(m)
                broken = spades_broken or m[0] == SPADE or o[0] == SPADE
                if card_beats(o, m, o[0]):
                    mt, ot, next_leader = my_tricks, opp_tricks + 1, "opp"
                else:
                    mt, ot, next_leader = my_tricks + 1, opp_tricks, "me"
                val = alpha_beta_state(
                    tuple(sorted(my_after)), tuple(sorted(opp_after)), next_leader,
                    broken, mt, ot, depth - 1, local_alpha, beta, ctx,
                )
                best_response = max(best_response, val)
                local_alpha = max(local_alpha, best_response)
                if local_alpha >= beta:
                    completed = False
                    break
            best = min(best, best_response)
            beta = min(beta, best)
            if alpha >= beta:
                completed = False
                break

    if completed:
        ctx["tt"][key] = best
    return best


def determinized_move(
    gameState, legal_moves, my_hand, unseen, opp_hand_size, opp_voids,
    trick, lead_card, spades_broken,
    my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags, deadline,
):
    """Information-set search when unknown cards remain outside opponent hand."""
    rng = random.Random(_state_seed(gameState, salt=0xC0FFEE))

    totals = {m: 0.0 for m in legal_moves}
    totals_sq = {m: 0.0 for m in legal_moves}
    counts = {m: 0 for m in legal_moves}

    # Strong deterministic fallback if the time limit is exceptionally tight.
    fallback = root_policy_choice(
        legal_moves, my_hand, None, lead_card, spades_broken, my_tricks, my_bid
    )

    while time.perf_counter() < deadline:
        opp_hand = deal_hand(
            unseen, opp_hand_size, opp_voids,
            rng=rng, target_bid=opp_bid,
        )
        if len(opp_hand) != opp_hand_size:
            break

        # Common random numbers: every root move sees the same sampled hand.
        ordered = order_root_moves(
            legal_moves, my_hand, opp_hand, lead_card, spades_broken,
            my_tricks, my_bid,
        )
        for move in ordered:
            if time.perf_counter() >= deadline:
                break
            score = simulate_root_rollout(
                move, my_hand, opp_hand, trick, lead_card, spades_broken,
                my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags,
            )
            totals[move] += score
            totals_sq[move] += score * score
            counts[move] += 1

    sampled = [m for m in legal_moves if counts[m] > 0]
    if not sampled:
        return fallback

    # Risk-aware expected score: tiny uncertainty penalty prevents a move with one
    # lucky sample from beating a well-tested, nearly equal alternative.
    def value(m):
        n = counts[m]
        mean = totals[m] / n
        if n <= 1:
            return mean - 0.8
        var = max(0.0, totals_sq[m] / n - mean * mean)
        uncertainty = (var / n) ** 0.5
        return mean - 0.08 * uncertainty

    return max(sampled, key=lambda m: (value(m), counts[m], root_tiebreak(m, lead_card, my_tricks, my_bid)))


# ---------------------------------------------------------------------------
# Rollouts and move policy
# ---------------------------------------------------------------------------

def simulate_root_rollout(
    first_move, my_hand, opp_hand, trick, lead_card, spades_broken,
    my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags,
):
    """Resolve one candidate root move and greedily play the round to completion."""
    my_hand = list(my_hand)
    opp_hand = list(opp_hand)
    my_hand.remove(first_move)

    if lead_card is None:
        o_move = select_policy_card(
            opp_hand, first_move, spades_broken,
            opp_tricks, opp_bid, my_hand,
        )
        opp_hand.remove(o_move)
        spades_broken = spades_broken or first_move[0] == SPADE or o_move[0] == SPADE
        if card_beats(first_move, o_move, first_move[0]):
            my_tricks += 1
            leader = "me"
        else:
            opp_tricks += 1
            leader = "opp"
    else:
        spades_broken = spades_broken or first_move[0] == SPADE or lead_card[0] == SPADE
        if card_beats(first_move, lead_card, lead_card[0]):
            my_tricks += 1
            leader = "me"
        else:
            opp_tricks += 1
            leader = "opp"

    return rollout_value(
        my_hand, opp_hand, leader, spades_broken,
        my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags,
    )


def rollout_value(my_hand, opp_hand, leader, spades_broken,
                  my_tricks, opp_tricks, my_bid, opp_bid, my_bags, opp_bags):
    """Fast perfect-information rollout from the start of a trick."""
    my_hand = list(my_hand)
    opp_hand = list(opp_hand)

    while my_hand and opp_hand:
        if leader == "me":
            m = select_policy_card(
                my_hand, None, spades_broken, my_tricks, my_bid, opp_hand
            )
            my_hand.remove(m)
            o = select_policy_card(
                opp_hand, m, spades_broken, opp_tricks, opp_bid, my_hand
            )
            opp_hand.remove(o)
            spades_broken = spades_broken or m[0] == SPADE or o[0] == SPADE
            if card_beats(m, o, m[0]):
                my_tricks += 1
            else:
                opp_tricks += 1
                leader = "opp"
        else:
            o = select_policy_card(
                opp_hand, None, spades_broken, opp_tricks, opp_bid, my_hand
            )
            opp_hand.remove(o)
            m = select_policy_card(
                my_hand, o, spades_broken, my_tricks, my_bid, opp_hand
            )
            my_hand.remove(m)
            spades_broken = spades_broken or m[0] == SPADE or o[0] == SPADE
            if card_beats(o, m, o[0]):
                opp_tricks += 1
            else:
                my_tricks += 1
                leader = "me"

    return score_utility(my_bid, my_tricks, my_bags, opp_bid, opp_tricks, opp_bags)


def rollout_trick_counts(my_hand, opp_hand, lead_name, my_name, my_bid, opp_bid):
    """Bid-phase rollout returning trick counts instead of score."""
    mine = list(my_hand)
    theirs = list(opp_hand)
    mt = ot = 0
    broken = False
    leader = "me" if lead_name == my_name else "opp"

    while mine and theirs:
        if leader == "me":
            m = select_policy_card(mine, None, broken, mt, my_bid, theirs)
            mine.remove(m)
            o = select_policy_card(theirs, m, broken, ot, opp_bid, mine)
            theirs.remove(o)
            broken = broken or m[0] == SPADE or o[0] == SPADE
            if card_beats(m, o, m[0]):
                mt += 1
            else:
                ot += 1
                leader = "opp"
        else:
            o = select_policy_card(theirs, None, broken, ot, opp_bid, mine)
            theirs.remove(o)
            m = select_policy_card(mine, o, broken, mt, my_bid, theirs)
            mine.remove(m)
            broken = broken or m[0] == SPADE or o[0] == SPADE
            if card_beats(o, m, o[0]):
                ot += 1
            else:
                mt += 1
                leader = "me"
    return mt, ot


def select_policy_card(hand, lead_card, spades_broken, tricks_won, bid, other_hand=None):
    """Contract-aware deterministic rollout policy."""
    legal = get_legal_cards(hand, lead_card, spades_broken)
    legal = sorted(legal, key=card_sort_key)
    need = bid > 0 and tricks_won < bid

    if lead_card is not None:
        lead_suit = lead_card[0]
        following = legal and legal[0][0] == lead_suit

        if following:
            winners = [c for c in legal if card_beats(c, lead_card, lead_suit)]
            losers = [c for c in legal if not card_beats(c, lead_card, lead_suit)]
            if need:
                return min(winners, key=card_sort_key) if winners else min(legal, key=card_sort_key)
            # Already safe: shed the highest card that can still lose. If forced
            # to win, spend the cheapest winner, not the highest winner.
            if losers:
                return max(losers, key=card_sort_key)
            return min(winners, key=card_sort_key)

        # Void in lead suit.
        spades = sorted((c for c in legal if c[0] == SPADE), key=card_sort_key)
        off = sorted((c for c in legal if c[0] != SPADE), key=card_sort_key)
        if need:
            if spades and lead_suit != SPADE:
                return spades[0]
            return off[0] if off else legal[0]
        # Avoiding tricks: dump a dangerous high off-suit card when possible.
        if off:
            return off[-1]
        return spades[-1] if spades else legal[-1]

    # Leading. If we know the other hand, evaluate how each legal lead fares
    # against every legal response rather than blindly playing the highest card.
    if other_hand:
        scored = []
        for card in legal:
            responses = get_legal_cards(other_hand, card, spades_broken)
            if responses:
                wins = sum(1 for r in responses if card_beats(card, r, card[0]))
                pwin = wins / len(responses)
            else:
                pwin = 1.0

            # Prefer preserving spades unless a trump lead is useful/required.
            trump_cost = 0.10 if card[0] == SPADE else 0.0
            rank_cost = card[1] / 100.0
            if need:
                # Win probability dominates; among similar winners spend less.
                score = 3.0 * pwin - rank_cost - trump_cost
            else:
                # Lose probability dominates; among safe losers dump high danger.
                score = -3.0 * pwin + rank_cost + (0.04 if card[0] != SPADE else 0.0)
            scored.append((score, card))
        return max(scored, key=lambda x: x[0])[1]

    non_spades = [c for c in legal if c[0] != SPADE]
    if need:
        return max(non_spades or legal, key=card_sort_key)
    return min(non_spades or legal, key=card_sort_key)


# ---------------------------------------------------------------------------
# Search ordering / pruning helpers
# ---------------------------------------------------------------------------

def order_root_moves(legal, hand, opp_hand, lead_card, spades_broken, tricks_won, bid):
    preferred = root_policy_choice(legal, hand, opp_hand, lead_card, spades_broken, tricks_won, bid)
    rest = [c for c in legal if c != preferred]
    need = bid > 0 and tricks_won < bid
    rest.sort(key=card_sort_key, reverse=need)
    return [preferred] + rest


def root_policy_choice(legal, hand, opp_hand, lead_card, spades_broken, tricks_won, bid):
    chosen = select_policy_card(hand, lead_card, spades_broken, tricks_won, bid, opp_hand)
    return chosen if chosen in legal else legal[0]


def order_interior_moves(legal, hand, other_hand, lead_card, spades_broken,
                         tricks_won, bid, maximizing):
    """Order and lightly compress interior branches; root moves remain complete."""
    if len(legal) <= MAX_INTERIOR_MOVES:
        moves = list(legal)
    else:
        moves = strategic_subset(legal, lead_card)

    preferred = select_policy_card(
        hand, lead_card, spades_broken, tricks_won, bid, other_hand
    )
    ordered = []
    if preferred in moves:
        ordered.append(preferred)
    ordered.extend(c for c in moves if c != preferred)

    need = bid > 0 and tricks_won < bid
    ordered[1:] = sorted(ordered[1:], key=card_sort_key, reverse=need)
    return ordered


def strategic_subset(cards, lead_card):
    """Keep tactically distinct cards while reducing deep-search branching."""
    cards = sorted(set(cards), key=card_sort_key)
    if len(cards) <= MAX_INTERIOR_MOVES:
        return cards

    keep = {cards[0], cards[-1]}

    if lead_card is not None:
        winners = [c for c in cards if card_beats(c, lead_card, lead_card[0])]
        losers = [c for c in cards if not card_beats(c, lead_card, lead_card[0])]
        if winners:
            keep.add(winners[0])
            keep.add(winners[-1])
        if losers:
            keep.add(losers[0])
            keep.add(losers[-1])
    else:
        by_suit = {s: [] for s in SUITS}
        for c in cards:
            by_suit[c[0]].append(c)
        for arr in by_suit.values():
            if arr:
                keep.add(arr[0])
                keep.add(arr[-1])

    ordered = sorted(keep, key=card_sort_key)
    if len(ordered) > MAX_INTERIOR_MOVES:
        # Preserve extremes and evenly spread the middle choices.
        idxs = [round(i * (len(ordered) - 1) / (MAX_INTERIOR_MOVES - 1))
                for i in range(MAX_INTERIOR_MOVES)]
        ordered = [ordered[i] for i in sorted(set(idxs))]
    return ordered


def root_tiebreak(card, lead_card, tricks_won, bid):
    need = bid > 0 and tricks_won < bid
    if lead_card is not None:
        wins = card_beats(card, lead_card, lead_card[0])
        if need:
            return (1 if wins else 0, -card[1])
        return (1 if not wins else 0, card[1])
    return card[1] if need else -card[1]


# ---------------------------------------------------------------------------
# Rules / scoring / information helpers
# ---------------------------------------------------------------------------

def calculate_score(bid, tricks, bags_before):
    """Round score using the rules assumed by the original bot."""
    if bid == 0:
        return 100 if tricks == 0 else -100

    if tricks >= bid:
        overtricks = tricks - bid
        score = bid * 10 + overtricks
        if bags_before + overtricks >= 10:
            score -= 100
        return score
    return -(bid * 10)


def score_utility(my_bid, my_tricks, my_bags, opp_bid, opp_tricks, opp_bags):
    """Primary objective is score difference, with tiny stable tie breakers."""
    my_score = calculate_score(my_bid, my_tricks, my_bags)
    opp_score = calculate_score(opp_bid, opp_tricks, opp_bags)

    # Exact score dominates. The fractional term only separates equal-score
    # continuations in a strategically sensible way.
    utility = float(my_score - opp_score)
    if my_bid > 0:
        utility += 0.03 * min(my_tricks, my_bid)
        utility -= 0.02 * max(0, my_tricks - my_bid)
    elif my_tricks == 0:
        utility += 0.05

    if opp_bid > 0:
        utility -= 0.03 * min(opp_tricks, opp_bid)
        utility += 0.02 * max(0, opp_tricks - opp_bid)
    elif opp_tricks == 0:
        utility -= 0.05
    return utility


def wins_trick(lead_card, follow_card):
    """Compatibility helper: True iff lead_card beats follow_card."""
    return card_beats(lead_card, follow_card, lead_card[0])


def card_beats(card_a, card_b, lead_suit):
    """True iff card_a beats card_b in a two-card Spades trick."""
    sa, ra = card_a
    sb, rb = card_b

    if sa == sb:
        return ra > rb
    if sa == SPADE and sb != SPADE:
        return True
    if sb == SPADE and sa != SPADE:
        return False
    # Neither is trump and suits differ: only a card in the led suit can win.
    if sa == lead_suit and sb != lead_suit:
        return True
    return False


def get_legal_cards(hand, lead_card, spades_broken):
    """Return only cards legal under standard follow-suit / break-spades rules."""
    if lead_card is not None:
        lead_suit = lead_card[0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        return same_suit if same_suit else list(hand)

    if spades_broken or all(c[0] == SPADE for c in hand):
        return list(hand)
    non_spades = [c for c in hand if c[0] != SPADE]
    return non_spades if non_spades else list(hand)


def extract_lead_card(current_trick):
    """Normalize current_trick to its actual lead card."""
    if not current_trick:
        return None
    first = current_trick[0]
    if _is_play_record(first):
        return first[1]
    # Defensive support if an engine supplies a bare card instead of (player,card).
    if _is_card(first):
        return first
    return None


def _is_card(value):
    return (
        isinstance(value, (tuple, list)) and len(value) == 2
        and value[0] in SUITS and isinstance(value[1], int)
    )


def _is_play_record(value):
    return (
        isinstance(value, (tuple, list)) and len(value) == 2
        and _is_card(value[1])
    )


def get_unseen_cards(gameState):
    """Cards not in our hand and not already exposed in played tricks."""
    known = set(tuple(c) for c in gameState.your_hand)

    for trick in getattr(gameState, "trick_history", []) or []:
        plays = trick.get("plays", []) if isinstance(trick, dict) else trick
        for play in plays:
            if _is_play_record(play):
                known.add(tuple(play[1]))

    for play in getattr(gameState, "current_trick", []) or []:
        if _is_play_record(play):
            known.add(tuple(play[1]))
        elif _is_card(play):
            known.add(tuple(play))

    return [c for c in DECK if c not in known]


def get_opponent_voids(gameState):
    """Infer suits the opponent has proven void in from completed tricks."""
    voids = set()
    opp_name = getattr(gameState, "opponent_name", None)

    for trick in getattr(gameState, "trick_history", []) or []:
        plays = trick.get("plays", []) if isinstance(trick, dict) else trick
        if not plays or not _is_play_record(plays[0]):
            continue
        lead_suit = plays[0][1][0]
        for play in plays:
            if not _is_play_record(play):
                continue
            player, card = play
            if player == opp_name and card[0] != lead_suit:
                voids.add(lead_suit)
    return voids


def deal_hand(unseen_cards, hand_size, voids, rng=None, target_bid=None):
    """
    Sample an opponent hand consistent with known voids.

    If an opponent bid is known, choose among a few random candidate hands whose
    structural strength is closest to that bid. This makes determinizations much
    less naive without expensive Bayesian machinery.
    """
    rng = rng or random
    possible = [c for c in unseen_cards if c[0] not in voids]
    if len(possible) < hand_size:
        possible = list(unseen_cards)
    if len(possible) < hand_size:
        return []
    if len(possible) == hand_size:
        return list(possible)

    if target_bid is None:
        return rng.sample(possible, hand_size)

    attempts = 3 if not TEST_MODE else 1
    best = None
    best_gap = float("inf")
    for _ in range(attempts):
        sample = rng.sample(possible, hand_size)
        gap = abs(quick_bid_estimate(sample) - target_bid)
        if gap < best_gap:
            best_gap = gap
            best = sample
    return best


def card_sort_key(card):
    # Rank dominates. Suit order is only a deterministic tie-break.
    return (card[1], SUITS.index(card[0]))


def terminal_utility(my_tricks, opp_tricks, ctx):
    return score_utility(
        ctx["my_bid"], my_tricks, ctx["my_bags"],
        ctx["opp_bid"], opp_tricks, ctx["opp_bags"],
    )


def _check_time(ctx):
    ctx["nodes"] += 1
    if (ctx["nodes"] & TIME_CHECK_MASK) == 0 and time.perf_counter() >= ctx["deadline"]:
        raise _SearchTimeout


def _state_seed(gameState, salt=0):
    """Stable-ish local seed derived only from visible state."""
    items = [salt]
    items.extend(sorted(tuple(c) for c in getattr(gameState, "your_hand", []) or []))
    items.append(getattr(gameState, "your_bid", None))
    items.append(getattr(gameState, "opponent_bid", None))
    items.append(getattr(gameState, "your_bags", 0))
    items.append(getattr(gameState, "opponent_bags", 0))
    items.append(bool(getattr(gameState, "spades_broken", False)))
    # repr is sufficient here; seed reproducibility is useful, cryptography is not.
    return hash(repr(items))
