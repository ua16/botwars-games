# Random legal moves for Piquet.

import random


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


def nextMove(gameState):
    if gameState.phase == "exchange":
        hand = list(gameState.your_hand)
        if gameState.your_name == gameState.elder:
            n = random.randint(0, min(5, len(hand)))
        else:
            n = random.randint(0, min(gameState.talon_remaining or 0, len(hand)))
        if n == 0:
            return []
        random.shuffle(hand)
        return hand[:n]

    if gameState.phase == "declare":
        if random.random() < 0.5:
            return "pass"
        hand = gameState.your_hand
        cat = gameState.declare_category
        if cat == "set" and max(
            (sum(1 for c in hand if c[1] == r) for r in range(10, 15)), default=0
        ) < 3:
            return "pass"
        if cat == "sequence" and not _has_sequence(hand):
            return "pass"
        return ("claim",)

    hand = list(gameState.your_hand)
    if gameState.current_trick:
        lead_suit = gameState.current_trick[0][1][0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        if same_suit:
            return random.choice(same_suit)
    return random.choice(hand)
