# Basic Piquet player — exchange longest suit, claim when possible, follow suit.


def nextMove(gameState):
    if gameState.phase == "exchange":
        return _exchange(gameState)
    if gameState.phase == "declare":
        return _declare(gameState)
    return _trick(gameState)


def _exchange(gameState):
    hand = list(gameState.your_hand)
    by_suit = {}
    for card in hand:
        by_suit.setdefault(card[0], []).append(card)
    shortest_suit = min(by_suit.keys(), key=lambda s: len(by_suit[s]))
    to_discard = [c for c in hand if c[0] == shortest_suit]
    if gameState.your_name == gameState.elder:
        limit = min(5, len(hand))
    else:
        limit = min(gameState.talon_remaining or 0, len(hand))
    return to_discard[:limit]


def _declare(gameState):
    hand = gameState.your_hand
    cat = gameState.declare_category
    if cat == "set" and not _has_set(hand):
        return "pass"
    if cat == "sequence" and not _has_sequence(hand):
        return "pass"
    return ("claim",)


def _has_set(hand):
    counts = {}
    for card in hand:
        if card[1] >= 10:
            counts[card[1]] = counts.get(card[1], 0) + 1
    return max(counts.values(), default=0) >= 3


def _has_sequence(hand):
    by_suit = {}
    for card in hand:
        by_suit.setdefault(card[0], set()).add(card[1])
    for ranks in by_suit.values():
        sorted_ranks = sorted(ranks)
        run = 1
        for i in range(1, len(sorted_ranks)):
            if sorted_ranks[i] == sorted_ranks[i - 1] + 1:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 1
    return False


def _trick(gameState):
    hand = gameState.your_hand
    if gameState.current_trick:
        lead_suit = gameState.current_trick[0][1][0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        if same_suit:
            return max(same_suit, key=lambda c: c[1])
    return max(hand, key=lambda c: c[1])
