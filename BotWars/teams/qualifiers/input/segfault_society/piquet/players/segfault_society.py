# Two-player Piquet bot.
#
# Three observations drive this bot:
#
#  1. Declaring is free. The engine builds the claim from our real hand and
#     only publishes the WINNER's claim, so a losing claim costs nothing.
#     We therefore claim in every category where we hold a valid combination.
#     (Claiming a set/sequence we do NOT hold forfeits the match, so the
#     validity check mirrors engine.best_set / best_sequence exactly.)
#
#  2. Tricks dominate scoring: 1/trick, +1 last trick, +10 for 7+, +40 capot.
#     A trick majority is worth more than most declarations combined, so the
#     exchange keeps trick power and we play to win tricks throughout.
#
#  3. PlayerView exposes no trick history for the current deal, so we track
#     seen cards ourselves across calls to know when a card is unbeatable.

PARAMS = {
    "rank_value": {14: 10.0, 13: 8.0, 12: 6.0, 11: 4.0, 10: 3.0, 9: 2.0, 8: 1.0, 7: 0.0},
    "elder_discard": 5,      # elder may exchange up to 5
    "younger_discard": 3,    # younger is limited by the talon remainder
    "guard_rank": 13,        # never discard at or above this rank
    # weights for whole-hand evaluation during the exchange
    "w_point": 0.282,
    "w_seq": 1.184,
    "w_set": 0.0,
    "w_trick": 0.309,
    "w_long": 1.897,
}

SUITS = ("H", "D", "C", "S")

# Per-player memory of cards we have seen this deal.
_SEEN = {}


# ---------------------------------------------------------------------------
# Combination detection — must match the engine exactly
# ---------------------------------------------------------------------------
def _has_sequence(hand):
    """True if any suit holds 3+ consecutive ranks (engine: best_sequence)."""
    for suit in SUITS:
        ranks = sorted({c[1] for c in hand if c[0] == suit})
        if len(ranks) < 3:
            continue
        run = 1
        for i in range(1, len(ranks)):
            run = run + 1 if ranks[i] == ranks[i - 1] + 1 else 1
            if run >= 3:
                return True
    return False


def _has_set(hand):
    """True if 3+ cards share a rank of 10 or higher (engine: best_set)."""
    counts = {}
    for suit, rank in hand:
        if rank >= 10:
            counts[rank] = counts.get(rank, 0) + 1
    return any(v >= 3 for v in counts.values())






# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------


def _hand_value(hand, P):
    """Score a hand we would KEEP: declaration potential plus trick power."""
    # Point: length of longest suit (ties broken on pips, as the engine does).
    by_suit = {}
    for suit, rank in hand:
        by_suit.setdefault(suit, []).append(rank)
    best_len = max((len(v) for v in by_suit.values()), default=0)

    # Sequence: engine pays 3, 4, then 10 + (length - 5).
    best_seq = 0
    for suit, ranks in by_suit.items():
        rs = sorted(set(ranks))
        run = 1
        for i in range(1, len(rs)):
            run = run + 1 if rs[i] == rs[i - 1] + 1 else 1
            best_seq = max(best_seq, run)
    seq_pts = 0 if best_seq < 3 else (best_seq if best_seq < 5 else 10 + best_seq - 5)

    # Set: engine pays 3 for a triple, 14 for a quad.
    counts = {}
    for suit, rank in hand:
        if rank >= 10:
            counts[rank] = counts.get(rank, 0) + 1
    top = max(counts.values(), default=0)
    set_pts = 14 if top >= 4 else (3 if top == 3 else 0)

    trick_power = sum(P["rank_value"].get(r, 0.0) for _, r in hand)
    long_control = sum(max(0, len(v) - 3) for v in by_suit.values())

    return (
        P["w_point"] * best_len
        + P["w_seq"] * seq_pts
        + P["w_set"] * set_pts
        + P["w_trick"] * trick_power
        + P["w_long"] * long_control
    )


def _choose_discard(gs, P):
    """Pick the discard SET that leaves the strongest hand.

    Greedy per-card discarding breaks combinations (throwing one link out of a
    four-card run costs 4 points to save a low card), so we score every
    candidate subset of the fixed discard size and keep the best remainder.
    The draw size is fixed, so unknown drawn cards are a constant across
    candidates and can be ignored in the comparison.
    """
    from itertools import combinations

    hand = list(gs.your_hand)
    talon = gs.talon_remaining or 0

    if gs.your_name == gs.elder:
        limit = min(P["elder_discard"], 5, talon, len(hand))
    else:
        limit = min(P["younger_discard"], talon, len(hand))
    if limit <= 0:
        return []

    # Protect the very top cards; they are never worth exchanging.
    candidates = [c for c in hand if c[1] < P["guard_rank"]]
    if len(candidates) < limit:
        limit = len(candidates)
    if limit <= 0:
        return []

    best, best_score = None, None
    for combo in combinations(candidates, limit):
        keep = [c for c in hand if c not in combo]
        score = _hand_value(keep, P)
        if best_score is None or score > best_score:
            best, best_score = combo, score
    return list(best)


# ---------------------------------------------------------------------------
# Declaration — claim whenever we legally can
# ---------------------------------------------------------------------------
def _choose_declaration(gs):
    category = gs.declare_category
    hand = gs.your_hand

    if category == "point":
        return ("claim",) if hand else "pass"
    if category == "sequence":
        return ("claim",) if _has_sequence(hand) else "pass"
    if category == "set":
        return ("claim",) if _has_set(hand) else "pass"
    return "pass"


# ---------------------------------------------------------------------------
# Trick play
# ---------------------------------------------------------------------------
def _legal_cards(hand, lead_card):
    if lead_card is None:
        return list(hand)
    same = [c for c in hand if c[0] == lead_card[0]]
    return same if same else list(hand)


def _remember(gs):
    """Accumulate every card we have observed this deal."""
    key = gs.your_name
    state = _SEEN.get(key)
    if state is None or state["deal"] != _deal_id(gs):
        state = {"deal": _deal_id(gs), "cards": set()}
        _SEEN[key] = state
    state["cards"].update(gs.your_hand)
    for _, card in gs.current_trick:
        state["cards"].add(card)
    return state["cards"]


def _deal_id(gs):
    """Deals are identified by cumulative scores plus who is elder."""
    return (gs.your_score, gs.opponent_score, gs.elder)


def _outstanding_higher(card, seen):
    """Cards above `card` in its suit that we have not yet seen."""
    suit, rank = card
    return sum(1 for r in range(rank + 1, 15) if (suit, r) not in seen)


def _choose_card(gs, P):
    hand = gs.your_hand
    lead_card = gs.current_trick[0][1] if gs.current_trick else None
    legal = _legal_cards(hand, lead_card)
    if len(legal) == 1:
        return legal[0]

    seen = _remember(gs)

    if lead_card is not None:
        winners = [c for c in legal if c[0] == lead_card[0] and c[1] > lead_card[1]]
        if winners:
            return min(winners, key=lambda c: c[1])   # win as cheaply as possible
        return min(legal, key=lambda c: c[1])         # cannot win, throw the cheapest

    # Leading: prefer a card nothing outstanding can beat, longest suit first.
    best, best_key = None, None
    for card in legal:
        suit, rank = card
        boss = _outstanding_higher(card, seen) == 0
        length = sum(1 for c in hand if c[0] == suit)
        key = (1 if boss else 0, length, rank)
        if best_key is None or key > best_key:
            best, best_key = card, key
    return best


# ---------------------------------------------------------------------------
# Entry point — never raises, never returns an illegal move
# ---------------------------------------------------------------------------
def nextMove(gameState):
    phase = getattr(gameState, "phase", None)
    try:
        if phase == "exchange":
            discard = _choose_discard(gameState, PARAMS)
            hand = gameState.your_hand
            limit = min(
                5 if gameState.your_name == gameState.elder else (gameState.talon_remaining or 0),
                gameState.talon_remaining or 0,
                len(hand),
            )
            discard = [c for c in discard if c in hand][:max(0, limit)]
            return discard
        if phase == "declare":
            return _choose_declaration(gameState)
        card = _choose_card(gameState, PARAMS)
        lead = gameState.current_trick[0][1] if gameState.current_trick else None
        legal = _legal_cards(gameState.your_hand, lead)
        return card if card in legal else legal[0]
    except Exception:
        # A forfeit loses the whole match, so every failure path still
        # returns something the engine will accept.
        try:
            if phase == "exchange":
                return []
            if phase == "declare":
                return "pass"
            lead = gameState.current_trick[0][1] if gameState.current_trick else None
            return _legal_cards(gameState.your_hand, lead)[0]
        except Exception:
            return "pass"
