def does_beat(my_card, opp_card, trump_suit):
    my_suit, my_rank = my_card
    opp_suit, opp_rank = opp_card

    if my_suit == opp_suit:
        return my_rank > opp_rank
    elif my_suit == trump_suit:
        return True
    else:
        return False

def nextMove(gameState):
    hand = gameState.your_hand
    current_trick = gameState.current_trick
    trump_suit = gameState.trump_suit
    phase = gameState.phase
    face_up = gameState.face_up_card

    # 1. Determine legal moves
    if current_trick:
        lead_suit = current_trick[0][1][0]
        legal_cards = [c for c in hand if c[0] == lead_suit]
        if not legal_cards:
            legal_cards = list(hand)
    else:
        legal_cards = list(hand)

    # Valuation helper for sorting card strength
    def card_strength(card):
        suit, rank = card
        val = rank
        if suit == trump_suit:
            val += 20
        return val

    # Sort legal cards from weakest to strongest
    sorted_legal = sorted(legal_cards, key=card_strength)

    # --- PHASE 1: RECRUITMENT ---
    if phase == 1:
        # Check if the face-up stock card is worth winning
        face_up_str = card_strength(face_up) if face_up else 0
        wants_face_up = (face_up_str >= 10) or (face_up and face_up[0] == trump_suit)

        if current_trick: # Following
            opp_card = current_trick[0][1]
            winning_moves = [c for c in sorted_legal if does_beat(c, opp_card, trump_suit)]
            losing_moves = [c for c in sorted_legal if not does_beat(c, opp_card, trump_suit)]

            if wants_face_up:
                if winning_moves:
                    return winning_moves[0]  # Win with the lowest winning card
                else:
                    return sorted_legal[0]   # Can't win, dump lowest card
            else:
                if losing_moves:
                    return losing_moves[0]   # Lose on purpose, dump lowest losing card
                else:
                    return winning_moves[0]  # Forced to win, use lowest winning card
        else: # Leading
            if wants_face_up:
                return sorted_legal[-1]  # Lead highest card to win good stock
            else:
                return sorted_legal[0]   # Lead lowest card to discard/lose trick

    # --- PHASE 2: SCORING ---
    else:
        if current_trick: # Following
            opp_card = current_trick[0][1]
            winning_moves = [c for c in sorted_legal if does_beat(c, opp_card, trump_suit)]

            if winning_moves:
                return winning_moves[0]  # Win with the lowest possible winning card
            else:
                return sorted_legal[0]   # Dump lowest card
        else: # Leading
            # Lead highest card to capture trick
            return sorted_legal[-1]