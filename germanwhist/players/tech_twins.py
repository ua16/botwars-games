RANK_NAMES = {14: "A", 13: "K", 12: "Q", 11: "J"}
SUITS = ("H", "D", "C", "S")
RANKS = tuple(range(2, 15))


def _full_deck():
    return {(s, r) for s in SUITS for r in RANKS}


def _suit_groups(hand):
    """Return {suit: [cards...]} grouped from hand."""
    groups = {}
    for card in hand:
        groups.setdefault(card[0], []).append(card)
    return groups


def _legal_cards(hand, lead_card):
    """Cards you're allowed to play: follow suit if you can."""
    if lead_card is None:
        return list(hand)
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def _wins_against(candidate, lead_card, trump_suit):
    """Would `candidate` beat `lead_card` if played as the follower?"""
    lead_suit, lead_rank = lead_card
    cand_suit, cand_rank = candidate
    if cand_suit == lead_suit:
        return cand_rank > lead_rank
    if cand_suit == trump_suit:
        return True
    return False


def _lowest(cards):
    return min(cards, key=lambda c: c[1])


def _highest(cards):
    return max(cards, key=lambda c: c[1])


def _longest_suit(hand):
    groups = _suit_groups(hand)
    return max(groups.values(), key=len)


def _shortest_suit_nontrump(hand, trump_suit):
    groups = _suit_groups(hand)
    non_trump_groups = {s: c for s, c in groups.items() if s != trump_suit}
    if not non_trump_groups:
        return list(hand)
    return min(non_trump_groups.values(), key=len)


_seen = set()


def _update_tracking(gameState):
    if gameState.phase == 1 and gameState.stock_remaining == 25 and len(gameState.your_hand) == 13:
        _seen.clear()

    _seen.update(gameState.your_hand)
    if gameState.face_up_card is not None:
        _seen.add(gameState.face_up_card)
    for _, card in gameState.current_trick:
        _seen.add(card)


def _unseen_cards(gameState):
    return _full_deck() - _seen - set(gameState.your_hand)


def _is_guaranteed_winner(card, unseen):
    """True if no unseen card of the same suit outranks this one."""
    suit, rank = card
    return not any(s == suit and r > rank for s, r in unseen)


def _recruitment_lead(gameState):
    hand = gameState.your_hand
    face_up = gameState.face_up_card
    unseen = _unseen_cards(gameState)

    guaranteed = [c for c in hand if _is_guaranteed_winner(c, unseen)]
    if guaranteed and face_up is not None and face_up[1] >= 6:
        return _lowest(guaranteed)

    if face_up is not None and face_up[1] >= 10:
        longest = _longest_suit(hand)
        return _highest(longest)

    longest = _longest_suit(hand)
    return _lowest(longest)


def _recruitment_follow(gameState):
    hand = gameState.your_hand
    lead_player, lead_card = gameState.current_trick[0]
    trump_suit = gameState.trump_suit
    face_up = gameState.face_up_card

    legal = _legal_cards(hand, lead_card)
    winners = [c for c in legal if _wins_against(c, lead_card, trump_suit)]

    cheap_win_available = winners and _lowest(winners)[1] <= 5
    want_to_win = (face_up is not None and face_up[1] >= 8) or cheap_win_available

    if want_to_win and winners:
        return _lowest(winners)

    if not want_to_win and winners and len(winners) < len(legal):
        losers = [c for c in legal if c not in winners]
        return _lowest(losers)

    return _lowest(legal)


def _scoring_lead(gameState):
    hand = gameState.your_hand
    unseen = _unseen_cards(gameState)

    guaranteed = [c for c in hand if _is_guaranteed_winner(c, unseen)]
    if guaranteed:
        return _lowest(guaranteed)

    longest = _longest_suit(hand)
    return _lowest(longest)


def _scoring_follow(gameState):
    hand = gameState.your_hand
    lead_player, lead_card = gameState.current_trick[0]
    trump_suit = gameState.trump_suit

    legal = _legal_cards(hand, lead_card)
    winners = [c for c in legal if _wins_against(c, lead_card, trump_suit)]

    if winners:
        return _lowest(winners)

    shortest = _shortest_suit_nontrump(hand, trump_suit)
    candidates = [c for c in legal if c in shortest]
    if candidates:
        return _lowest(candidates)
    return _lowest(legal)


def nextMove(gameState):
    _update_tracking(gameState)

    leading = not gameState.current_trick

    if gameState.phase == 1:
        return _recruitment_lead(gameState) if leading else _recruitment_follow(gameState)
    else:
        return _scoring_lead(gameState) if leading else _scoring_follow(gameState)