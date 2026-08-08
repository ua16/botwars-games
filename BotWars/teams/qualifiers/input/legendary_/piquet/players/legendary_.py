# legendary_piquet.py
# Competition-oriented Piquet bot
#
# Design goals:
#   * preserve TEST_MODE for fast local testing
#   * hard search budget comfortably below a 2.0 second move limit
#   * stronger exchange decisions using expected post-draw hand quality
#   * correct Piquet declaration detection
#   * no-trump follow-suit trick logic
#   * opponent void inference from previous tricks
#   * constrained hidden-hand sampling + adversarial alpha-beta look-ahead
#
# Assumed card representation:
#   ("H", 7) ... ("H", 14), where Ace == 14
#
# Assumed phases:
#   "exchange", "declare", and trick-play otherwise
#
# Assumed current_trick representation:
#   [(player_name, (suit, rank)), ...]
#
# Only the public game-state fields used by the user's original bot are required.
# Extra history fields are consumed defensively when they exist.

import itertools
import random
import time


# ===========================================================================
# LOCAL TESTING TOGGLE
# ===========================================================================
# True  -> very fast decisions for local testing
# False -> competition mode
TEST_MODE = False

# User's prompt states a 2.0 s move limit. 1.35 s leaves a large safety margin
# for framework overhead, Python scheduling, and return/serialization time.
TEST_TIME_LIMIT = 0.055
COMP_TIME_LIMIT = 1.35

# Exchange does not need the entire trick-search budget.
EXCHANGE_TEST_TIME_LIMIT = 0.025
EXCHANGE_COMP_TIME_LIMIT = 0.30

# Search tuning
TIME_CHECK_MASK = 63
EXACT_ENDGAME_CARDS = 6
MAX_DEPTH_TEST = 2
MAX_DEPTH_COMP = 5
MAX_ROOT_SAMPLES_TEST = 4
MAX_ROOT_SAMPLES_COMP = 80
MAX_INTERIOR_MOVES = 7
# ===========================================================================


SUITS = ("H", "D", "C", "S")
RANKS = tuple(range(7, 15))
DECK = tuple((s, r) for s in SUITS for r in RANKS)

INF = 10**12


class _SearchTimeout(Exception):
    pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def nextMove(gameState):
    """
    Main dispatcher.

    Every branch is deadline-aware. Competition mode intentionally stops well
    before 2.0 seconds instead of trying to use the final few milliseconds.
    """
    start = time.perf_counter()
    phase = getattr(gameState, "phase", None)

    if phase == "exchange":
        return _exchange_phase(gameState, start)
    if phase == "declare":
        return _declare_phase(gameState)

    return _trick_phase(gameState, start)


# ---------------------------------------------------------------------------
# Exchange phase
# ---------------------------------------------------------------------------

def _exchange_phase(gameState, start_time=None):
    """
    Choose the discard set by estimating the strength of the resulting hand.

    Unlike a fixed "throw the N weakest cards" rule, this can keep a seemingly
    mediocre card when it completes a point, sequence, or set, and it can choose
    fewer than the maximum discards when the current hand is already strong.
    """
    if start_time is None:
        start_time = time.perf_counter()

    hand = list(getattr(gameState, "your_hand", []) or [])
    if not hand:
        return []

    is_elder = getattr(gameState, "your_name", None) == getattr(gameState, "elder", None)

    if is_elder:
        max_discard = min(5, len(hand))
    else:
        remaining = getattr(gameState, "talon_remaining", 0)
        try:
            remaining = int(remaining or 0)
        except (TypeError, ValueError):
            remaining = 0
        max_discard = min(max(0, remaining), len(hand))

    if max_discard <= 0:
        return []

    budget = EXCHANGE_TEST_TIME_LIMIT if TEST_MODE else EXCHANGE_COMP_TIME_LIMIT
    deadline = start_time + budget

    # The unknown pool contains the opponent's cards and the talon. A card from
    # our original hand cannot be drawn back immediately after discarding it.
    unknown_pool = [c for c in DECK if c not in set(hand)]

    # Rank cards by how painful they are to throw away.
    keep_scores = {c: _card_keep_value(hand, c) for c in hand}
    weakest = sorted(hand, key=lambda c: (keep_scores[c], c[1]))

    # Search combinations mainly among the weak half of the hand. This gives
    # much better structural decisions than a pure prefix while staying tiny.
    candidate_pool_size = min(len(hand), max(7, max_discard + 3))
    candidate_pool = weakest[:candidate_pool_size]

    candidates = {()}
    for k in range(1, max_discard + 1):
        # Always include the simple "k weakest" baseline.
        candidates.add(tuple(sorted(weakest[:k])))
        for combo in itertools.combinations(candidate_pool, k):
            candidates.add(tuple(sorted(combo)))

    # Deterministic proxy first; keep only the most plausible candidates for MC.
    proxy_ranked = []
    for discard in candidates:
        remaining_hand = [c for c in hand if c not in discard]
        # Partial-hand value plus expected-rank refill prior.
        proxy = _hand_strength(remaining_hand)
        proxy += len(discard) * 2.0
        proxy_ranked.append((proxy, discard))

    proxy_ranked.sort(reverse=True, key=lambda x: x[0])
    finalists = [d for _, d in proxy_ranked[:48]]

    # Always retain no-exchange and each prefix baseline.
    must_keep = [()]
    for k in range(1, max_discard + 1):
        must_keep.append(tuple(sorted(weakest[:k])))
    for d in must_keep:
        if d not in finalists:
            finalists.append(d)

    rng = random.Random(_state_seed(gameState, salt=0xE11E))

    totals = {d: 0.0 for d in finalists}
    counts = {d: 0 for d in finalists}

    # Give every finalist at least one deterministic/cheap evaluation.
    for discard in finalists:
        if time.perf_counter() >= deadline:
            break
        k = len(discard)
        remaining_hand = [c for c in hand if c not in discard]
        if k == 0:
            totals[discard] += _hand_strength(remaining_hand)
            counts[discard] += 1
            continue
        if len(unknown_pool) >= k:
            draw = rng.sample(unknown_pool, k)
            totals[discard] += _hand_strength(remaining_hand + draw)
            counts[discard] += 1

    # Round-robin common-budget Monte Carlo. More samples go to all candidates
    # rather than accidentally spending the whole clock on the first one.
    rounds = 0
    while time.perf_counter() < deadline:
        rounds += 1
        for discard in finalists:
            if time.perf_counter() >= deadline:
                break

            k = len(discard)
            remaining_hand = [c for c in hand if c not in discard]

            if k == 0:
                value = _hand_strength(remaining_hand)
            elif len(unknown_pool) >= k:
                draw = rng.sample(unknown_pool, k)
                value = _hand_strength(remaining_hand + draw)
            else:
                continue

            totals[discard] += value
            counts[discard] += 1

        # In TEST_MODE, avoid spending time on needless extra rounds.
        if TEST_MODE and rounds >= 5:
            break

    current_strength = _hand_strength(hand)

    def candidate_value(discard):
        n = counts.get(discard, 0)
        if n <= 0:
            return -INF
        mean = totals[discard] / n

        # Small transaction cost: don't disturb a strong hand for a marginal gain.
        mean -= 0.10 * len(discard)

        # Strong made declarations deserve extra protection.
        if _best_sequence_length(hand) >= 4:
            broken = _sequence_damage(hand, discard)
            mean -= 2.5 * broken
        if _best_set_size(hand) >= 3:
            broken_sets = _set_damage(hand, discard)
            mean -= 4.0 * broken_sets

        return mean

    best_discard = max(
        finalists,
        key=lambda d: (candidate_value(d), -len(d))
    )

    # If exchange modelling found no actual improvement, keeping the hand can be
    # preferable when zero-card exchange is legal in the competition engine.
    best_value = candidate_value(best_discard)
    no_value = candidate_value(()) if () in totals else current_strength

    if () in finalists and no_value >= best_value - 0.20:
        best_discard = ()

    return list(best_discard)


def _card_keep_value(hand, card):
    """Structural value of one card inside the current hand."""
    suit, rank = card
    suit_cards = sorted(c[1] for c in hand if c[0] == suit)
    same_rank = sum(1 for c in hand if c[1] == rank)

    value = 0.0

    # Trick-taking / raw rank value.
    value += (rank - 6) * 1.15
    if rank == 14:
        value += 4.5
    elif rank == 13:
        value += 2.2
    elif rank == 12:
        value += 1.0

    # Point declaration: long suits matter.
    value += len(suit_cards) * 1.9

    # Sequence connectivity.
    if rank - 1 in suit_cards:
        value += 4.0
    if rank + 1 in suit_cards:
        value += 4.0
    if rank - 2 in suit_cards:
        value += 1.5
    if rank + 2 in suit_cards:
        value += 1.5

    # Sets of tens and above.
    if rank >= 10 and same_rank >= 2:
        value += 6.0 * (same_rank - 1)

    # Exact contribution test: how much does removing this card hurt the hand?
    without = list(hand)
    without.remove(card)
    value += max(0.0, _hand_strength(hand) - _hand_strength(without)) * 0.28

    return value


def _hand_strength(hand):
    """
    Fast Piquet hand evaluator used during exchange and static search.

    It deliberately values:
      point potential,
      sequences,
      sets,
      high-card trick control,
      long-suit pressure.
    """
    if not hand:
        return 0.0

    by_suit = {s: [] for s in SUITS}
    by_rank = {}
    for s, r in hand:
        by_suit[s].append(r)
        by_rank[r] = by_rank.get(r, 0) + 1

    for ranks in by_suit.values():
        ranks.sort()

    value = 0.0

    # Point: length first, then rank sum as the normal tie-break strength.
    best_suit = max(
        SUITS,
        key=lambda s: (len(by_suit[s]), sum(by_suit[s]))
    )
    point_len = len(by_suit[best_suit])
    point_sum = sum(by_suit[best_suit])
    value += point_len * 5.2 + point_sum * 0.10

    # Sequences: reward every made run, with a large premium for 5+.
    for ranks in by_suit.values():
        for run_len, top_rank in _runs(ranks):
            if run_len >= 3:
                value += _sequence_score(run_len) * 2.3
                value += top_rank * 0.04

    # Sets: three/four of a kind among 10-A.
    for rank, n in by_rank.items():
        if rank >= 10:
            if n == 3:
                value += 8.0
            elif n >= 4:
                value += 23.0

    # Trick control.
    for s in SUITS:
        ranks = by_suit[s]
        n = len(ranks)
        if not ranks:
            continue

        if 14 in ranks:
            value += 6.2
        if 13 in ranks:
            value += 3.0 + (1.0 if 14 in ranks else 0.0)
        if 12 in ranks:
            value += 1.5 + (0.6 if 13 in ranks or 14 in ranks else 0.0)
        if 11 in ranks:
            value += 0.6

        # Long suits create repeat-entry pressure in a no-trump trick game.
        if n >= 4:
            value += (n - 3) * 1.8

    return value


def _runs(ranks):
    """Return (length, top_rank) for every maximal consecutive run."""
    if not ranks:
        return []

    unique = sorted(set(ranks))
    out = []
    start = unique[0]
    prev = unique[0]

    for r in unique[1:]:
        if r == prev + 1:
            prev = r
        else:
            out.append((prev - start + 1, prev))
            start = prev = r

    out.append((prev - start + 1, prev))
    return out


def _sequence_score(length):
    """Traditional Piquet-style sequence weight."""
    if length <= 2:
        return 0
    if length == 3:
        return 3
    if length == 4:
        return 4
    return 10 + length  # 5->15, 6->16, 7->17, 8->18


def _best_sequence_length(hand):
    best = 0
    by_suit = {}
    for s, r in hand:
        by_suit.setdefault(s, []).append(r)
    for ranks in by_suit.values():
        for run_len, _ in _runs(ranks):
            best = max(best, run_len)
    return best


def _best_set_size(hand):
    counts = {}
    for _, r in hand:
        if r >= 10:
            counts[r] = counts.get(r, 0) + 1
    return max(counts.values(), default=0)


def _sequence_damage(hand, discard):
    before = _best_sequence_length(hand)
    after_hand = list(hand)
    for c in discard:
        if c in after_hand:
            after_hand.remove(c)
    after = _best_sequence_length(after_hand)
    return max(0, before - after)


def _set_damage(hand, discard):
    def made_sets(cards):
        counts = {}
        for _, r in cards:
            if r >= 10:
                counts[r] = counts.get(r, 0) + 1
        return sum(1 for n in counts.values() if n >= 3)

    before = made_sets(hand)
    after_hand = list(hand)
    for c in discard:
        if c in after_hand:
            after_hand.remove(c)
    return max(0, before - made_sets(after_hand))


# ---------------------------------------------------------------------------
# Declaration phase
# ---------------------------------------------------------------------------

def _declare_phase(gameState):
    """
    Make only declarations that actually exist in the hand.

    The competition framework is assumed to perform opponent comparison and
    scoring after a legal claim, exactly as in the user's original interface.
    """
    hand = list(getattr(gameState, "your_hand", []) or [])
    cat = str(getattr(gameState, "declare_category", "") or "").lower()

    if cat == "point":
        return ("claim",) if hand else "pass"

    if cat == "sequence":
        return ("claim",) if _has_sequence(hand) else "pass"

    if cat == "set":
        return ("claim",) if _has_set(hand) else "pass"

    # Defensive support if the engine exposes carte blanche as a declaration.
    if cat in ("carte_blanche", "carte blanche"):
        return ("claim",) if _has_carte_blanche(hand) else "pass"

    return "pass"


def _has_set(hand):
    counts = {}
    for _, rank in hand:
        if rank >= 10:
            counts[rank] = counts.get(rank, 0) + 1
    return max(counts.values(), default=0) >= 3


def _has_sequence(hand):
    by_suit = {}
    for suit, rank in hand:
        by_suit.setdefault(suit, set()).add(rank)

    for ranks in by_suit.values():
        ordered = sorted(ranks)
        run = 1
        for i in range(1, len(ordered)):
            if ordered[i] == ordered[i - 1] + 1:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 1

    return False


def _has_carte_blanche(hand):
    # Court cards in Piquet are J/Q/K. Ace is not a court card.
    return all(rank not in (11, 12, 13) for _, rank in hand)


# ---------------------------------------------------------------------------
# Trick phase
# ---------------------------------------------------------------------------

def _trick_phase(gameState, start_time=None):
    """
    Hidden-information Piquet trick engine.

    1. Enforces follow-suit legality.
    2. Infers opponent void suits from history.
    3. Samples only plausible opponent hands.
    4. Searches each sampled hand adversarially.
    5. Aggregates mean + downside robustness instead of trusting one deal.
    """
    if start_time is None:
        start_time = time.perf_counter()

    hand = list(getattr(gameState, "your_hand", []) or [])
    if not hand:
        return None

    current_trick = list(getattr(gameState, "current_trick", []) or [])
    lead_card = _extract_lead_card(current_trick)
    legal_moves = _legal_cards(hand, lead_card)

    if len(legal_moves) == 1:
        return legal_moves[0]

    fallback = _heuristic_trick_move(hand, lead_card, gameState)

    limit = TEST_TIME_LIMIT if TEST_MODE else COMP_TIME_LIMIT
    deadline = start_time + limit

    unseen = _unseen_cards(gameState)
    opp_voids = _opponent_voids(gameState)
    opp_size = _opponent_cards_remaining(hand, current_trick)

    # If state extraction fails, never risk an exception at competition time.
    if opp_size <= 0 or len(unseen) < opp_size:
        return fallback

    rng = random.Random(_state_seed(gameState, salt=0x71C))

    totals = {m: 0.0 for m in legal_moves}
    counts = {m: 0 for m in legal_moves}
    worst = {m: INF for m in legal_moves}

    my_name = getattr(gameState, "your_name", "me")
    opp_name = getattr(gameState, "opponent_name", "opp")
    my_won, opp_won = _tricks_already_won(gameState, my_name, opp_name)

    max_samples = MAX_ROOT_SAMPLES_TEST if TEST_MODE else MAX_ROOT_SAMPLES_COMP
    max_depth = MAX_DEPTH_TEST if TEST_MODE else MAX_DEPTH_COMP

    # Endgames with small hands are often cheap enough for exact search.
    if len(hand) <= EXACT_ENDGAME_CARDS:
        max_depth = len(hand)

    sample_no = 0
    while sample_no < max_samples and time.perf_counter() < deadline:
        opp_hand = _sample_opponent_hand(unseen, opp_size, opp_voids, rng)
        if len(opp_hand) != opp_size:
            break

        sample_no += 1

        # Iterative deepening lets every move receive a shallow score first.
        for depth in range(1, max_depth + 1):
            if time.perf_counter() >= deadline:
                break

            completed_this_depth = []
            for move in _order_root_moves(legal_moves, hand, lead_card):
                if time.perf_counter() >= deadline:
                    break

                try:
                    score = _evaluate_root_move(
                        move=move,
                        my_hand=hand,
                        opp_hand=opp_hand,
                        lead_card=lead_card,
                        my_tricks=my_won,
                        opp_tricks=opp_won,
                        depth=depth,
                        deadline=deadline,
                    )
                except _SearchTimeout:
                    break

                completed_this_depth.append((move, score))

            # Only count a depth if all root moves were evaluated. This prevents
            # a late-clock partial pass from biasing the first moves in ordering.
            if len(completed_this_depth) == len(legal_moves):
                depth_weight = 1.0 + depth * 0.18
                for move, score in completed_this_depth:
                    totals[move] += score * depth_weight
                    counts[move] += 1
                    worst[move] = min(worst[move], score)

        # Even one sample is useful; continue while clock permits.

    evaluated = [m for m in legal_moves if counts[m] > 0]
    if not evaluated:
        return fallback

    def robust_value(move):
        mean = totals[move] / counts[move]
        downside = worst[move] if worst[move] < INF else mean

        # Mostly expected value, with a smaller worst-case component. This makes
        # the bot less fragile against one nasty hidden-card distribution.
        return 0.82 * mean + 0.18 * downside

    return max(
        evaluated,
        key=lambda m: (
            robust_value(m),
            _root_tiebreak(m, hand, lead_card),
        )
    )


def _evaluate_root_move(
    move,
    my_hand,
    opp_hand,
    lead_card,
    my_tricks,
    opp_tricks,
    depth,
    deadline,
):
    """Evaluate one legal root card against one sampled opponent hand."""
    if time.perf_counter() >= deadline:
        raise _SearchTimeout

    my_rest = list(my_hand)
    my_rest.remove(move)
    opp_rest = list(opp_hand)

    tt = {}
    nodes = [0]

    if lead_card is not None:
        # Opponent already led the current trick.
        i_win = _card_beats(move, lead_card)
        if i_win:
            my_tricks += 1
            leader = 0
        else:
            opp_tricks += 1
            leader = 1

        return _alphabeta(
            tuple(sorted(my_rest)),
            tuple(sorted(opp_rest)),
            leader,
            my_tricks,
            opp_tricks,
            max(0, depth - 1),
            -INF,
            INF,
            deadline,
            tt,
            nodes,
        )

    # We are leading. Opponent chooses the response that is worst for us.
    replies = _legal_cards(opp_rest, move)
    replies = _order_follow_moves(replies, move, maximizing=False)

    worst_value = INF
    alpha = -INF
    beta = INF

    for reply in replies:
        if time.perf_counter() >= deadline:
            raise _SearchTimeout

        o_rest = list(opp_rest)
        o_rest.remove(reply)

        if _card_beats(reply, move):
            next_my = my_tricks
            next_opp = opp_tricks + 1
            leader = 1
        else:
            next_my = my_tricks + 1
            next_opp = opp_tricks
            leader = 0

        value = _alphabeta(
            tuple(sorted(my_rest)),
            tuple(sorted(o_rest)),
            leader,
            next_my,
            next_opp,
            max(0, depth - 1),
            alpha,
            beta,
            deadline,
            tt,
            nodes,
        )

        worst_value = min(worst_value, value)
        beta = min(beta, worst_value)

    return worst_value


def _alphabeta(
    my_hand,
    opp_hand,
    leader,
    my_tricks,
    opp_tricks,
    depth,
    alpha,
    beta,
    deadline,
    tt,
    nodes,
):
    """
    Trick-level minimax.

    leader == 0 -> we lead and maximize
    leader == 1 -> opponent leads and minimizes

    Alpha/beta bounds are kept local to each nested response node. Transposition
    values are cached only when the node was searched completely, so a cutoff
    bound is never mistaken for an exact score.
    """
    nodes[0] += 1
    if (nodes[0] & TIME_CHECK_MASK) == 0 and time.perf_counter() >= deadline:
        raise _SearchTimeout

    if not my_hand or not opp_hand:
        return _terminal_trick_value(my_tricks, opp_tricks)

    if depth <= 0:
        return _static_trick_value(my_hand, opp_hand, my_tricks, opp_tricks)

    key = (my_hand, opp_hand, leader, my_tricks, opp_tricks, depth)
    cached = tt.get(key)
    if cached is not None:
        return cached

    if leader == 0:
        # MAX node: we choose a lead, then the opponent chooses a reply.
        leads = _order_leads(my_hand, maximizing=True)[:MAX_INTERIOR_MOVES]
        best = -INF
        node_complete = True

        for lead in leads:
            my_rest = list(my_hand)
            my_rest.remove(lead)

            replies = _legal_cards(list(opp_hand), lead)
            replies = _order_follow_moves(replies, lead, maximizing=False)

            worst_reply = INF
            reply_beta = beta

            for reply in replies:
                opp_rest = list(opp_hand)
                opp_rest.remove(reply)

                if _card_beats(reply, lead):
                    value = _alphabeta(
                        tuple(sorted(my_rest)),
                        tuple(sorted(opp_rest)),
                        1,
                        my_tricks,
                        opp_tricks + 1,
                        depth - 1,
                        alpha,
                        reply_beta,
                        deadline,
                        tt,
                        nodes,
                    )
                else:
                    value = _alphabeta(
                        tuple(sorted(my_rest)),
                        tuple(sorted(opp_rest)),
                        0,
                        my_tricks + 1,
                        opp_tricks,
                        depth - 1,
                        alpha,
                        reply_beta,
                        deadline,
                        tt,
                        nodes,
                    )

                worst_reply = min(worst_reply, value)
                reply_beta = min(reply_beta, worst_reply)

                # MIN child cannot improve enough to beat our current MAX alpha.
                if reply_beta <= alpha:
                    node_complete = False
                    break

            best = max(best, worst_reply)
            alpha = max(alpha, best)

            if alpha >= beta:
                node_complete = False
                break

        if node_complete:
            tt[key] = best
        return best

    # MIN node: opponent chooses a lead, then we choose our best reply.
    leads = _order_leads(opp_hand, maximizing=False)[:MAX_INTERIOR_MOVES]
    best_for_opp = INF
    node_complete = True

    for lead in leads:
        opp_rest = list(opp_hand)
        opp_rest.remove(lead)

        replies = _legal_cards(list(my_hand), lead)
        replies = _order_follow_moves(replies, lead, maximizing=True)

        best_reply = -INF
        reply_alpha = alpha

        for reply in replies:
            my_rest = list(my_hand)
            my_rest.remove(reply)

            if _card_beats(reply, lead):
                value = _alphabeta(
                    tuple(sorted(my_rest)),
                    tuple(sorted(opp_rest)),
                    0,
                    my_tricks + 1,
                    opp_tricks,
                    depth - 1,
                    reply_alpha,
                    beta,
                    deadline,
                    tt,
                    nodes,
                )
            else:
                value = _alphabeta(
                    tuple(sorted(my_rest)),
                    tuple(sorted(opp_rest)),
                    1,
                    my_tricks,
                    opp_tricks + 1,
                    depth - 1,
                    reply_alpha,
                    beta,
                    deadline,
                    tt,
                    nodes,
                )

            best_reply = max(best_reply, value)
            reply_alpha = max(reply_alpha, best_reply)

            # MAX child cannot become low enough to improve the MIN parent.
            if reply_alpha >= beta:
                node_complete = False
                break

        best_for_opp = min(best_for_opp, best_reply)
        beta = min(beta, best_for_opp)

        if beta <= alpha:
            node_complete = False
            break

    if node_complete:
        tt[key] = best_for_opp
    return best_for_opp


def _terminal_trick_value(my_tricks, opp_tricks):
    """
    Utility for completed trick play.

    Trick differential is primary; majority and sweep/capot-like outcomes receive
    extra weight so the search does not treat the seventh and twelfth tricks as
    strategically identical to an irrelevant middle trick.
    """
    diff = my_tricks - opp_tricks
    value = diff * 12.0

    if my_tricks > opp_tricks:
        value += 14.0
    elif opp_tricks > my_tricks:
        value -= 14.0

    total = my_tricks + opp_tricks
    if total >= 12:
        if opp_tricks == 0:
            value += 45.0
        elif my_tricks == 0:
            value -= 45.0

    return value


def _static_trick_value(my_hand, opp_hand, my_tricks, opp_tricks):
    """Depth-limit evaluator."""
    value = (my_tricks - opp_tricks) * 12.0

    # Compare immediate suit controls.
    for suit in SUITS:
        mine = sorted((r for s, r in my_hand if s == suit), reverse=True)
        theirs = sorted((r for s, r in opp_hand if s == suit), reverse=True)

        if mine:
            value += len(mine) * 0.22
            if mine[0] == 14:
                value += 2.7
            elif not theirs or mine[0] > theirs[0]:
                value += 1.3

        if theirs:
            value -= len(theirs) * 0.22
            if theirs[0] == 14:
                value -= 2.7
            elif not mine or theirs[0] > mine[0]:
                value -= 1.3

    # Long-suit pressure.
    my_lengths = sorted(
        (sum(1 for s, _ in my_hand if s == suit) for suit in SUITS),
        reverse=True,
    )
    opp_lengths = sorted(
        (sum(1 for s, _ in opp_hand if s == suit) for suit in SUITS),
        reverse=True,
    )
    if my_lengths:
        value += my_lengths[0] * 0.45
    if opp_lengths:
        value -= opp_lengths[0] * 0.45

    return value


# ---------------------------------------------------------------------------
# Trick heuristics / ordering
# ---------------------------------------------------------------------------

def _heuristic_trick_move(hand, lead_card, gameState):
    """Fast legal fallback used before and during time-limited search."""
    legal = _legal_cards(hand, lead_card)

    if lead_card is not None:
        lead_suit, lead_rank = lead_card
        same_suit = [c for c in legal if c[0] == lead_suit]

        if same_suit:
            winners = sorted((c for c in same_suit if c[1] > lead_rank), key=lambda c: c[1])
            losers = sorted((c for c in same_suit if c[1] < lead_rank), key=lambda c: c[1])

            if winners:
                # Cheapest winner preserves higher controls.
                return winners[0]
            if losers:
                # Cannot win: unload the smallest card.
                return losers[0]
            return min(same_suit, key=lambda c: c[1])

        # Void in led suit: no trump exists in Piquet. Discard the card that hurts
        # our remaining structure least, not merely the globally lowest rank.
        return min(hand, key=lambda c: (_card_keep_value(hand, c), c[1]))

    # Leading: prefer a proven/high control from a useful long suit.
    by_suit = {s: [] for s in SUITS}
    for c in hand:
        by_suit[c[0]].append(c)
    for cards in by_suit.values():
        cards.sort(key=lambda c: c[1])

    voids = _opponent_voids(gameState)

    def lead_score(card):
        s, r = card
        n = len(by_suit[s])
        score = r * 1.0 + n * 2.2

        if r == 14:
            score += 8.0
        elif r == 13:
            score += 3.2
        elif r == 12:
            score += 1.0

        # If opponent is known void, this suit cannot be won by them when we lead.
        if s in voids:
            score += 3.0

        # Prefer leading from connected runs.
        ranks = [x[1] for x in by_suit[s]]
        if r - 1 in ranks or r + 1 in ranks:
            score += 1.2

        return score

    return max(legal, key=lead_score)


def _order_root_moves(moves, hand, lead_card):
    if lead_card is not None:
        return sorted(
            moves,
            key=lambda c: (
                _card_beats(c, lead_card),
                -abs(c[1] - lead_card[1]) if _card_beats(c, lead_card) else -c[1],
            ),
            reverse=True,
        )

    return sorted(
        moves,
        key=lambda c: (
            c[1] == 14,
            sum(1 for x in hand if x[0] == c[0]),
            c[1],
        ),
        reverse=True,
    )


def _root_tiebreak(move, hand, lead_card):
    if lead_card is not None:
        if _card_beats(move, lead_card):
            # Between equivalent winning moves, spend the cheaper card.
            return -move[1]
        return -_card_keep_value(hand, move)

    suit_len = sum(1 for c in hand if c[0] == move[0])
    return suit_len * 3 + move[1]


def _order_leads(hand, maximizing):
    cards = list(hand)

    def score(c):
        s, r = c
        n = sum(1 for x in cards if x[0] == s)
        control = (8 if r == 14 else 3 if r == 13 else 1 if r == 12 else 0)
        return r + n * 2 + control

    return sorted(cards, key=score, reverse=maximizing)


def _order_follow_moves(cards, lead, maximizing):
    def score(c):
        wins = _card_beats(c, lead)
        # Winning cheaply is normally strong; when minimizing, the opponent gets
        # the mirrored preference through reversed ordering.
        if wins:
            return 100 - c[1]
        return c[1]

    return sorted(cards, key=score, reverse=maximizing)


# ---------------------------------------------------------------------------
# Hidden information
# ---------------------------------------------------------------------------

def _unseen_cards(gameState):
    """Cards not publicly known to be ours or already played."""
    known = set(getattr(gameState, "your_hand", []) or [])

    for trick in _iter_history_tricks(gameState):
        for _, card in trick:
            if _valid_card(card):
                known.add(tuple(card))

    for _, card in list(getattr(gameState, "current_trick", []) or []):
        if _valid_card(card):
            known.add(tuple(card))

    # If the framework explicitly exposes our own discarded cards, they are also
    # known not to be in the opponent's current hand.
    for attr in ("your_discards", "discarded_cards", "known_discards"):
        cards = getattr(gameState, attr, None)
        if cards:
            try:
                for card in cards:
                    if _valid_card(card):
                        known.add(tuple(card))
            except TypeError:
                pass

    return [c for c in DECK if c not in known]


def _sample_opponent_hand(unseen, hand_size, voids, rng):
    """
    Sample a plausible opponent hand while respecting suits they are known void in.

    Unknown talon/discard cards remain in the pool, which is correct for imperfect
    information: we choose a hand-sized subset from all still-hidden cards.
    """
    allowed = [c for c in unseen if c[0] not in voids]

    if len(allowed) >= hand_size:
        # Mild high-card/structure bias would risk inventing hidden information,
        # so sampling remains unbiased among states consistent with observations.
        return rng.sample(allowed, hand_size)

    # Defensive fallback if history information is inconsistent.
    if len(unseen) >= hand_size:
        return rng.sample(list(unseen), hand_size)

    return []


def _opponent_voids(gameState):
    """Infer suits the opponent failed to follow in completed tricks."""
    opp_name = getattr(gameState, "opponent_name", None)
    voids = set()

    for trick in _iter_history_tricks(gameState):
        if not trick:
            continue

        lead_card = trick[0][1]
        if not _valid_card(lead_card):
            continue

        lead_suit = lead_card[0]

        for player, card in trick[1:]:
            if player == opp_name and _valid_card(card) and card[0] != lead_suit:
                voids.add(lead_suit)

    return voids


def _opponent_cards_remaining(my_hand, current_trick):
    # Before a trick begins both players hold equal counts.
    # If opponent has already led, they now hold one fewer card than we do.
    if current_trick:
        return max(0, len(my_hand) - 1)
    return len(my_hand)


# ---------------------------------------------------------------------------
# Rules / state helpers
# ---------------------------------------------------------------------------

def _legal_cards(hand, lead_card):
    """Piquet has no trump: follow the led suit if possible."""
    if lead_card is None:
        return list(hand)

    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def _card_beats(follow_card, lead_card):
    """
    Whether the follower beats the leader in no-trump Piquet.

    An off-suit card cannot win the trick.
    """
    if follow_card[0] != lead_card[0]:
        return False
    return follow_card[1] > lead_card[1]


def _extract_lead_card(current_trick):
    if not current_trick:
        return None

    first = current_trick[0]

    # Expected form: (player, card)
    if isinstance(first, (tuple, list)) and len(first) >= 2 and _valid_card(first[1]):
        return tuple(first[1])

    # Defensive support for a raw card.
    if _valid_card(first):
        return tuple(first)

    return None


def _valid_card(card):
    return (
        isinstance(card, (tuple, list))
        and len(card) == 2
        and card[0] in SUITS
        and isinstance(card[1], int)
        and 7 <= card[1] <= 14
    )


def _iter_history_tricks(gameState):
    history = getattr(gameState, "trick_history", []) or []

    for item in history:
        if isinstance(item, dict):
            plays = item.get("plays", [])
        else:
            plays = item

        if not isinstance(plays, (list, tuple)):
            continue

        normalized = []
        for play in plays:
            if (
                isinstance(play, (tuple, list))
                and len(play) >= 2
                and _valid_card(play[1])
            ):
                normalized.append((play[0], tuple(play[1])))

        if normalized:
            yield normalized


def _tricks_already_won(gameState, my_name, opp_name):
    # Prefer an explicit framework count if available.
    tw = getattr(gameState, "tricks_won", None)
    if isinstance(tw, dict):
        return int(tw.get(my_name, 0)), int(tw.get(opp_name, 0))

    my_count = 0
    opp_count = 0

    for trick in _iter_history_tricks(gameState):
        if len(trick) < 2:
            continue

        lead_player, lead_card = trick[0]
        follow_player, follow_card = trick[1]

        if _card_beats(follow_card, lead_card):
            winner = follow_player
        else:
            winner = lead_player

        if winner == my_name:
            my_count += 1
        elif winner == opp_name:
            opp_count += 1

    return my_count, opp_count


def _state_seed(gameState, salt=0):
    """
    Stable per-position pseudo-random seed.

    Avoids Python's salted hash() so local tests are reproducible across runs.
    """
    x = 2166136261 ^ int(salt)

    def mix(v):
        nonlocal x
        text = repr(v)
        for ch in text:
            x ^= ord(ch)
            x = (x * 16777619) & 0xFFFFFFFF

    mix(getattr(gameState, "phase", None))
    mix(tuple(sorted(getattr(gameState, "your_hand", []) or [])))
    mix(tuple(getattr(gameState, "current_trick", []) or []))
    mix(getattr(gameState, "your_name", None))
    mix(getattr(gameState, "opponent_name", None))
    return x


# ---------------------------------------------------------------------------
# Optional local smoke tests
# ---------------------------------------------------------------------------

def _self_test():
    """Tiny built-in checks; not run by the competition framework."""
    assert _has_sequence([("H", 7), ("H", 8), ("H", 9)])
    assert not _has_sequence([("H", 7), ("H", 9), ("H", 10)])
    assert _has_set([("H", 10), ("D", 10), ("C", 10)])
    assert not _has_set([("H", 9), ("D", 9), ("C", 9)])

    hand = [("H", 7), ("H", 14), ("S", 10)]
    assert _legal_cards(hand, ("H", 10)) == [("H", 7), ("H", 14)]
    assert _card_beats(("H", 14), ("H", 13))
    assert not _card_beats(("S", 14), ("H", 7))

    print("Piquet bot smoke tests passed.")


if __name__ == "__main__":
    _self_test()
