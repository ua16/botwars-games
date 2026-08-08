# Piquet tournament bot.


RANK_ACE = 14


def point_pip(rank):
    """Pip value used for Point scoring (A=11, K/Q/J/10=10, else face value)."""
    if rank == RANK_ACE:
        return 11
    if rank >= 10:
        return 10
    return rank


def suit_groups(hand):
    groups = {}
    for c in hand:
        groups.setdefault(c[0], []).append(c)
    return groups


def best_point_info(hand):
    """(length, pips, suit) of the strongest suit for the Point category."""
    groups = suit_groups(hand)
    best_len, best_pips, best_suit = 0, 0, None
    for suit, cards in groups.items():
        length = len(cards)
        pips = sum(point_pip(c[1]) for c in cards)
        if length > best_len or (length == best_len and pips > best_pips):
            best_len, best_pips, best_suit = length, pips, suit
    return best_len, best_pips, best_suit


def sequences_in_hand(hand):
    """All runs of 3+ consecutive ranks within a suit."""
    groups = suit_groups(hand)
    results = []
    for suit, cards in groups.items():
        ranks = sorted(set(c[1] for c in cards))
        i = 0
        while i < len(ranks):
            start = i
            while i + 1 < len(ranks) and ranks[i + 1] == ranks[i] + 1:
                i += 1
            length = i - start + 1
            if length >= 3:
                results.append((length, ranks[i], suit, set(ranks[start:i + 1])))
            i += 1
    return results


def best_sequence_info(hand):
    seqs = sequences_in_hand(hand)
    if not seqs:
        return None
    return max(seqs, key=lambda s: (s[0], s[1]))


def sets_in_hand(hand):
    """All 3-or-4-of-a-kind groups among ranks 10+."""
    by_rank = {}
    for c in hand:
        if c[1] >= 10:
            by_rank.setdefault(c[1], []).append(c)
    return [(len(cards), rank) for rank, cards in by_rank.items() if len(cards) >= 3]


def best_set_info(hand):
    sets = sets_in_hand(hand)
    if not sets:
        return None
    return max(sets, key=lambda s: (s[1], s[0]))


def _card_score(card, hand, point_info, seq_info, set_info):
    """Higher = more worth keeping."""
    suit, rank = card
    _, _, point_suit = point_info
    score = point_pip(rank) * 0.15

    if seq_info is not None and seq_info[2] == suit and rank in seq_info[3]:
        score += 40 + seq_info[0] * 3
    if set_info is not None and rank == set_info[1] and rank >= 10:
        score += 38 + set_info[0] * 3
    if suit == point_suit:
        length = point_info[0]
        score += 4 + length * 2 + point_pip(rank) * 0.3

    if rank == 14:
        score += 6
    elif rank == 13:
        score += 3
    return score


def _exchange_move(gs):
    hand = list(gs.your_hand)
    if gs.your_name == gs.elder:
        max_disc = min(5, len(hand))
    else:
        max_disc = min(gs.talon_remaining or 0, len(hand))
    if max_disc <= 0:
        return []

    point_info = best_point_info(hand)
    seq_info = best_sequence_info(hand)
    set_info = best_set_info(hand)

    ranked = sorted(
        hand,
        key=lambda c: _card_score(c, hand, point_info, seq_info, set_info),
    )
    return ranked[:max_disc]


def _declare_move(gs):
    hand = gs.your_hand
    cat = gs.declare_category
    if cat == "point":
        # Always legal (any nonempty hand has a longest suit); never skip it.
        return ("claim",)
    if cat == "sequence":
        if best_sequence_info(hand) is not None:
            return ("claim",)
        return "pass"
    if cat == "set":
        if best_set_info(hand) is not None:
            return ("claim",)
        return "pass"
    return "pass"


def _trick_move(gs):
    hand = list(gs.your_hand)
    trick = gs.current_trick

    if trick:
        # Following.
        _, lead_card = trick[0]
        lead_suit = lead_card[0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        if same_suit:
            winning = [c for c in same_suit if c[1] > lead_card[1]]
            if winning:
                return min(winning, key=lambda c: c[1])  # win as cheaply as possible
            return min(same_suit, key=lambda c: c[1])  # can't win: duck low
        # Void in suit: shed the weakest card (lowest pip value, then rank).
        return min(hand, key=lambda c: (point_pip(c[1]), c[1]))

    # Leading.
    groups = suit_groups(hand)
    cards_left = len(hand)
    if cards_left <= 4:
        # Endgame: cash in your best card while you still control it.
        return max(hand, key=lambda c: c[1])

    longest_suit = max(groups.keys(), key=lambda s: len(groups[s]))
    suit_cards = sorted(groups[longest_suit], key=lambda c: c[1])
    return suit_cards[0]  # lead low from your longest suit to develop it


def nextMove(gameState):
    if gameState.phase == "exchange":
        return _exchange_move(gameState)
    if gameState.phase == "declare":
        return _declare_move(gameState)
    return _trick_move(gameState)
