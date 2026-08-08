# Rule-heuristic Piquet bot: deterministic, fast, never forfeits.

from engine import (
    legal_cards,
    best_point,
    best_sequence,
    best_set,
    all_sequences_in_hand,
    all_sets_in_hand,
)

_RANK_BASE = {14: 150, 13: 130, 12: 125, 11: 115, 10: 105, 9: 55, 8: 45, 7: 35}
_DISCARD_THRESHOLD = 120


def nextMove(gameState):
    phase = gameState.phase
    if phase == "exchange":
        return _exchange(gameState)
    if phase == "declare":
        return _declare(gameState)
    if phase == "tricks":
        return _trick(gameState)
    return ("pass",)


def _exchange(gameState):
    hand = list(gameState.your_hand)
    if gameState.your_name == gameState.elder:
        max_discard = min(5, len(hand))
    else:
        max_discard = min(gameState.talon_remaining or 0, len(hand))
    if max_discard <= 0:
        return []

    seqs = all_sequences_in_hand(hand)
    sets = all_sets_in_hand(hand)

    protected = set()
    for count, _rank, cards in sets:
        if count == 4:
            protected.update(cards)
    for length, _top, _suit, cards in seqs:
        if length == 4:
            protected.update(cards)

    scored = sorted(
        ((_card_keep_score(c, hand, seqs), c) for c in hand),
        key=lambda item: item[0],
    )

    discard = []
    for _score, card in scored:
        if card in protected:
            continue
        if _score >= _DISCARD_THRESHOLD:
            continue
        discard.append(card)
        if len(discard) >= max_discard:
            break
    return discard


def _card_keep_score(card, hand, seqs):
    suit, rank = card
    score = _RANK_BASE.get(rank, rank)
    suit_len = sum(1 for c in hand if c[0] == suit)
    score += suit_len * 10
    if rank >= 10:
        count = sum(1 for c in hand if c[1] == rank)
        if count == 4:
            score += 250
        elif count == 3:
            score += 90
        elif count == 2:
            score += 30
        else:
            score += 10
    for _length, _top, _suit, cards in seqs:
        if card in cards:
            score += len(cards) * 15
    return score


def _declare(gameState):
    hand = gameState.your_hand
    category = gameState.declare_category
    if category == "point":
        _len, _pips, suit = best_point(hand)
        if suit is not None:
            return ("claim",)
    elif category == "sequence":
        if best_sequence(hand) is not None:
            return ("claim",)
    elif category == "set":
        if best_set(hand) is not None:
            return ("claim",)
    return ("pass",)


def _trick(gameState):
    hand = list(gameState.your_hand)
    lead_card = None
    if gameState.current_trick:
        lead_card = gameState.current_trick[0][1]
    legal = legal_cards(hand, lead_card)
    if lead_card is None:
        return _lead(legal)
    return _follow(legal, lead_card)


def _lead(legal):
    aces = [c for c in legal if c[1] == 14]
    if aces:
        return aces[0]
    by_suit = {}
    for card in legal:
        by_suit.setdefault(card[0], []).append(card)
    suit = max(by_suit, key=lambda s: len(by_suit[s]))
    return max(by_suit[suit], key=lambda c: c[1])


def _follow(legal, lead_card):
    lead_suit = lead_card[0]
    lead_rank = lead_card[1]
    suit_cards = [c for c in legal if c[0] == lead_suit]
    winners = [c for c in suit_cards if c[1] > lead_rank]
    if winners:
        return min(winners, key=lambda c: c[1])
    if suit_cards:
        return min(suit_cards, key=lambda c: c[1])
    return min(legal, key=lambda c: (c[1], c[0]))


def _fallback(gameState):
    hand = list(gameState.your_hand)
    phase = getattr(gameState, "phase", None)
    if phase == "exchange":
        return hand[:1] if hand else []
    if phase == "declare":
        return ("pass",)
    if phase == "tricks" and hand:
        if gameState.current_trick:
            lead_suit = gameState.current_trick[0][1][0]
            same_suit = [c for c in hand if c[0] == lead_suit]
            return same_suit[0] if same_suit else hand[0]
        return hand[0]
    return []