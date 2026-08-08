"""
r2_d2.py - German Whist Competition Bot
Strategy: Card tracking, valuation heuristics in Phase 1, perfect-information play in Phase 2.
"""

# tracking across tricks within the same module memory
_MEMORY = {
    "seen_cards": set(),
    "last_hand_len": 0,
}


def _get_legal_moves(hand, current_trick):
    """Return legal cards to play from hand."""
    if not current_trick:
        return list(hand)
    lead_suit = current_trick[0][1][0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def _card_value(card, trump_suit):
    """Estimate single card strength."""
    suit, rank = card
    base = rank
    if suit == trump_suit:
        base += 15  
    return base


def _update_memory(gameState):
    """Track all cards revealed or played so far."""
    global _MEMORY

    # Reset memory on new game detection
    if len(gameState.your_hand) == 13 and gameState.stock_remaining == 25 and len(gameState.current_trick) == 0:
        _MEMORY["seen_cards"] = set(gameState.your_hand)
        _MEMORY["last_hand_len"] = 13

    # Always track current hand and visible stock card
    for c in gameState.your_hand:
        _MEMORY["seen_cards"].add(c)
    if gameState.face_up_card:
        _MEMORY["seen_cards"].add(gameState.face_up_card)

    # Track cards played in current trick
    for _, card in gameState.current_trick:
        _MEMORY["seen_cards"].add(card)


def nextMove(gameState):
    """Main decision engine called by tournament runner."""
    try:
        _update_memory(gameState)

        hand = gameState.your_hand
        legal = _get_legal_moves(hand, gameState.current_trick)
        trump = gameState.trump_suit

        # PHASE 1
        if gameState.phase == 1:
            target = gameState.face_up_card
            target_val = _card_value(target, trump) if target else 10
            is_desirable = target_val >= 12  # High card or Trump

            # FOLLOWING
            if gameState.current_trick:
                opponent_card = gameState.current_trick[0][1]
               
                # Check which legal cards can win this trick
                winning_cards = []
                for c in legal:
                    # Same suit higher rank OR trumping non-trump
                    if (c[0] == opponent_card[0] and c[1] > opponent_card[1]) or \
                       (c[0] == trump and opponent_card[0] != trump):
                        winning_cards.append(c)

                if is_desirable:
                    # Try to win with the lowest effective winning card
                    if winning_cards:
                        return min(winning_cards, key=lambda c: _card_value(c, trump))
                    # Otherwise, ditch lowest card
                    return min(legal, key=lambda c: _card_value(c, trump))
                else:
                    # Try to lose: play lowest non-winning card
                    losing_cards = [c for c in legal if c not in winning_cards]
                    if losing_cards:
                        return min(losing_cards, key=lambda c: _card_value(c, trump))
                    return min(legal, key=lambda c: _card_value(c, trump))

            # LEADING
            else:
                if is_desirable:
                    # Lead a high card to secure the desirable stock card
                    return max(legal, key=lambda c: _card_value(c, trump))
                else:
                    # Lead a low non-trump card to lose intentionally
                    non_trumps = [c for c in legal if c[0] != trump]
                    if non_trumps:
                        return min(non_trumps, key=lambda c: c[1])
                    return min(legal, key=lambda c: _card_value(c, trump))

        # PHASE 2
        else:
            # Reconstruct opponent's hand by elimination
            all_cards = {(s, r) for s in ["H", "D", "C", "S"] for r in range(2, 15)}
            known_opponent_hand = all_cards - _MEMORY["seen_cards"] - set(hand)

            # FOLLOWING 
            if gameState.current_trick:
                opponent_card = gameState.current_trick[0][1]
               
                winning_cards = []
                for c in legal:
                    if (c[0] == opponent_card[0] and c[1] > opponent_card[1]) or \
                       (c[0] == trump and opponent_card[0] != trump):
                        winning_cards.append(c)

                if winning_cards:
                    # Win with the lowest winning card
                    return min(winning_cards, key=lambda c: _card_value(c, trump))
                else:
                    # Discard lowest card
                    return min(legal, key=lambda c: _card_value(c, trump))

            # LEADING 
            else:
                # Find boss/unbeatable cards in hand
                boss_cards = []
                for c in legal:
                    c_suit, c_rank = c
                    higher_opp_cards = [
                        op for op in known_opponent_hand
                        if op[0] == c_suit and op[1] > c_rank
                    ]
                    if not higher_opp_cards:
                        boss_cards.append(c)

                # Cash in boss cards first
                if boss_cards:
                    return max(boss_cards, key=lambda c: _card_value(c, trump))

                # Lead safe lowest non-trump card
                non_trumps = [c for c in legal if c[0] != trump]
                if non_trumps:
                    return min(non_trumps, key=lambda c: c[1])

                return min(legal, key=lambda c: _card_value(c, trump))

    except Exception:
        # Emergency Fallback: Ensure bot never forfeits due to unhandled exceptions
        if gameState.current_trick:
            lead_suit = gameState.current_trick[0][1][0]
            same_suit = [c for c in gameState.your_hand if c[0] == lead_suit]
            if same_suit:
                return same_suit[0]
        return gameState.your_hand[0]
