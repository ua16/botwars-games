# R2_D2 Piquet player.

from itertools import combinations

SUITS = ("H", "D", "C", "S")

_state = {
    "hand_id": None,
    "seen": set(),
}


def nextMove(gameState):
    _sync_state(gameState)
    phase = gameState.phase
    if phase == "exchange":
        return _exchange_move(gameState)
    if phase == "declare":
        return _declare_move(gameState)
    return _trick_move(gameState)


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------
def _hand_key(gameState):
    return (
        gameState.dealer,
        gameState.elder,
        gameState.your_score,
        gameState.opponent_score,
    )


def _sync_state(gameState):
    key = _hand_key(gameState)
    if _state["hand_id"] != key:
        _state["hand_id"] = key
        _state["seen"] = set(gameState.your_hand)
    else:
        _state["seen"].update(gameState.your_hand)
    for _, card in gameState.current_trick:
        _state["seen"].add(card)


def _remember(card):
    _state["seen"].add(card)


# ---------------------------------------------------------------------------
# Exchange phase
# ---------------------------------------------------------------------------
_POINT_PIPS = {14: 11, 13: 10, 12: 10, 11: 10, 10: 10, 9: 9, 8: 8, 7: 7}
_CARD_VALUE = {14: 4.2, 13: 2.3, 12: 1.2, 11: 0.7, 10: 0.4, 9: 0.15, 8: 0.05, 7: 0.0}
_POINT_LEN_BONUS = {0: 0.0, 1: 0.0, 2: 0.0, 3: 3.0, 4: 6.5, 5: 12.5, 6: 17.0, 7: 21.0, 8: 25.0}
_DRAW_EV = 1.9


def _exchange_move(gameState):
    hand = list(gameState.your_hand)
    if gameState.your_name == gameState.elder:
        max_disc = min(5, len(hand))
    else:
        max_disc = min(gameState.talon_remaining or 0, len(hand))

    baseline = _hand_value(hand)
    best_score = baseline
    best_discard = []

    if max_disc > 0:
        indexed = list(range(len(hand)))
        for k in range(1, max_disc + 1):
            draw_bonus = _DRAW_EV * k
            for combo in combinations(indexed, k):
                combo_set = set(combo)
                kept = [hand[i] for i in indexed if i not in combo_set]
                score = _hand_value(kept) + draw_bonus
                if score > best_score:
                    best_score = score
                    best_discard = [hand[i] for i in combo]

    for card in best_discard:
        _remember(card)
    return best_discard


def _hand_value(hand):
    if not hand:
        return 0.0

    by_suit = {s: [] for s in SUITS}
    for c in hand:
        by_suit[c[0]].append(c)

    total = 0.0

    lengths = sorted((len(v) for v in by_suit.values()), reverse=True)
    longest = lengths[0]
    total += _POINT_LEN_BONUS.get(longest, 0.0)

    for cards in by_suit.values():
        L = len(cards)
        if L == 0:
            continue
        if L == longest and L >= 4:
            pips = sum(_POINT_PIPS[c[1]] for c in cards)
            total += 0.035 * pips
        if L >= 4:
            total += 0.5 * (L - 3)

    for cards in by_suit.values():
        if len(cards) < 3:
            continue
        ranks = sorted({c[1] for c in cards})
        i = 0
        while i < len(ranks):
            j = i
            while j + 1 < len(ranks) and ranks[j + 1] == ranks[j] + 1:
                j += 1
            run = j - i + 1
            if run == 3:
                total += 3.0
            elif run == 4:
                total += 4.5
            elif run >= 5:
                total += 11.0 + (run - 5)
            i = j + 1

    counts = {}
    for c in hand:
        if c[1] >= 10:
            counts[c[1]] = counts.get(c[1], 0) + 1
    for rank, cnt in counts.items():
        if cnt >= 4:
            total += 14.0 + 0.06 * rank
        elif cnt == 3:
            total += 3.2 + 0.06 * rank
        elif cnt == 2 and rank >= 12:
            total += 0.35

    for c in hand:
        total += _CARD_VALUE[c[1]]

    for cards in by_suit.values():
        if len(cards) == 1 and cards[0][1] <= 10:
            total -= 0.9
        elif len(cards) == 2 and max(c[1] for c in cards) <= 10:
            total -= 0.4

    return total


# ---------------------------------------------------------------------------
# Declare phase
# ---------------------------------------------------------------------------
def _declare_move(gameState):
    cat = gameState.declare_category
    hand = gameState.your_hand
    if cat == "point":
        return ("claim",)
    if cat == "sequence":
        return ("claim",) if _has_sequence(hand) else "pass"
    if cat == "set":
        return ("claim",) if _has_set(hand) else "pass"
    return "pass"


def _has_set(hand):
    counts = {}
    for c in hand:
        if c[1] >= 10:
            counts[c[1]] = counts.get(c[1], 0) + 1
    return max(counts.values(), default=0) >= 3


def _has_sequence(hand):
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], set()).add(c[1])
    for ranks in by_suit.values():
        srt = sorted(ranks)
        run = 1
        for i in range(1, len(srt)):
            if srt[i] == srt[i - 1] + 1:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 1
    return False


# ---------------------------------------------------------------------------
# Tricks phase
# ---------------------------------------------------------------------------
def _trick_move(gameState):
    hand = list(gameState.your_hand)
    if gameState.current_trick:
        card = _follow(gameState, hand)
    else:
        card = _lead(gameState, hand)
    _remember(card)
    return card


def _follow(gameState, hand):
    lead_card = gameState.current_trick[0][1]
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]

    if same_suit:
        winners = [c for c in same_suit if c[1] > lead_card[1]]
        if winners:
            return min(winners, key=lambda c: c[1])
        return min(same_suit, key=lambda c: c[1])

    return _pick_dump(hand)


def _pick_dump(hand):
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], []).append(c)

    def key(c):
        L = len(by_suit[c[0]])
        if c[1] == 14:
            return (2000, L, 0)
        if c[1] == 13:
            return (1500, L, 0)
        return (c[1], L, c[0])

    return min(hand, key=key)


def _lead(gameState, hand):
    by_suit = {s: [] for s in SUITS}
    for c in hand:
        by_suit[c[0]].append(c)

    aces = [c for c in hand if c[1] == 14]
    if aces:
        return max(aces, key=lambda c: (len(by_suit[c[0]]), c[1]))

    master = _find_master(hand)
    if master is not None:
        return master

    non_empty = [(s, cs) for s, cs in by_suit.items() if cs]
    longest_suit, longest_cards = max(
        non_empty, key=lambda x: (len(x[1]), max(c[1] for c in x[1]))
    )
    return max(longest_cards, key=lambda c: c[1])


def _find_master(hand):
    seen = _state["seen"] | set(hand)
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], []).append(c)

    best = None
    best_key = None
    for s, cards in by_suit.items():
        top = max(cards, key=lambda c: c[1])
        higher_outstanding = False
        for r in range(top[1] + 1, 15):
            if (s, r) not in seen:
                higher_outstanding = True
                break
        if not higher_outstanding and top[1] >= 12:
            key = (len(cards), top[1])
            if best_key is None or key > best_key:
                best_key = key
                best = top
    return best
