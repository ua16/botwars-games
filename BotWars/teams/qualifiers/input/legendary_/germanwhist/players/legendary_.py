# memory to track cards played in the game
seen_cards = set()

def is_prize_good(card, trump_suit):
    """Checks if the face-up card is worth fighting for."""
    if not card:
        return False
    suit, rank = card
    return suit == trump_suit or rank >= 11

def can_beat_lead(lead_card, my_card, trump_suit):
    """Returns True if my_card can beat the lead_card."""
    lead_suit, lead_rank = lead_card
    my_suit, my_rank = my_card
    
    if my_suit == lead_suit:
        return my_rank > lead_rank
    if my_suit == trump_suit:
        return True
    return False

def get_lowest_card(hand, trump_suit):
    """Finds the cheapest card to throw away (prefers non-trumps)."""
    non_trumps = [c for c in hand if c[0] != trump_suit]
    if non_trumps:
        return min(non_trumps, key=lambda c: c[1])
    return min(hand, key=lambda c: c[1])

def get_highest_card(hand, trump_suit):
    """Finds the strongest card to lead with (prefers non-trumps)."""
    non_trumps = [c for c in hand if c[0] != trump_suit]
    if non_trumps:
        return max(non_trumps, key=lambda c: c[1])
    return max(hand, key=lambda c: c[1])


# --- MAIN BOT LOGIC ---

def nextMove(gameState):
    global seen_cards

    hand = gameState.your_hand
    trump = gameState.trump_suit
    phase = gameState.phase
    trick = gameState.current_trick
    open_card = gameState.face_up_card
    
    # 1. Reset our memory if a brand new game just started
    if phase == 1 and gameState.stock_remaining >= 25:
        if not trick or len(seen_cards) > 2:
            seen_cards = set()
            
    # 2. Add the opponent's card to memory if they played first
    if trick:
        opp_card = trick[0][1]
        seen_cards.add(opp_card)

    # 3. Figure out what cards we are allowed to play
    allowed_cards = hand
    if trick:
        lead_suit = trick[0][1][0]
        matching_suit = [c for c in hand if c[0] == lead_suit]
        if matching_suit:
            allowed_cards = matching_suit

    my_choice = None

    # ==========================================
    # PHASE 1: THE SHOPPING PHASE
    # ==========================================
    if phase == 1:
        want_prize = is_prize_good(open_card, trump)
        
        if not trick: 
            # WE ARE LEADING
            if want_prize:
                my_choice = get_highest_card(hand, trump)
            else:
                my_choice = get_lowest_card(hand, trump)
                
        else: 
            # WE ARE FOLLOWING
            lead_card = trick[0][1]
            winning_cards = [c for c in allowed_cards if can_beat_lead(lead_card, c, trump)]
            
            if want_prize:
                # Try to win as cheaply as possible
                if winning_cards:
                    my_choice = min(winning_cards, key=lambda c: c[1])
                else:
                    my_choice = get_lowest_card(allowed_cards, trump)
            else:
                # Try to lose as cheaply as possible
                losing_cards = [c for c in allowed_cards if not can_beat_lead(lead_card, c, trump)]
                if losing_cards:
                    my_choice = min(losing_cards, key=lambda c: c[1])
                elif winning_cards:
                    my_choice = min(winning_cards, key=lambda c: c[1])
                else:
                    my_choice = min(allowed_cards, key=lambda c: c[1])

    # ==========================================
    # PHASE 2: THE BATTLE PHASE
    # ==========================================
    else:
        # Reconstruct the opponent's exact hand using our memory
        full_deck = [(s, r) for s in ['H', 'C', 'S', 'D'] for r in range(2, 15)]
        opp_hand = [c for c in full_deck if c not in hand and c not in seen_cards]
        
        if not trick: 
            # WE ARE LEADING
            # Look for a safe winner (a high card the opponent cannot beat)
            safe_winner = None
            for my_card in sorted(hand, key=lambda c: c[1], reverse=True):
                opp_matching = [c for c in opp_hand if c[0] == my_card[0]]
                opp_trumps = [c for c in opp_hand if c[0] == trump]
                
                # If they have the suit, make sure ours is higher
                if opp_matching:
                    if my_card[1] > max(opp_matching, key=lambda c: c[1])[1]:
                        safe_winner = my_card
                        break
                # If they don't have the suit, make sure they don't have trumps to cut us
                elif my_card[0] != trump and not opp_trumps:
                    safe_winner = my_card
                    break
            
            if safe_winner:
                my_choice = safe_winner
            else:
                my_choice = get_lowest_card(hand, trump)
                
        else: 
            # WE ARE FOLLOWING
            lead_card = trick[0][1]
            winning_cards = [c for c in allowed_cards if can_beat_lead(lead_card, c, trump)]
            
            if winning_cards:
                my_choice = min(winning_cards, key=lambda c: c[1])
            else:
                my_choice = min(allowed_cards, key=lambda c: c[1])

    # 4. Save our choice to memory before returning it
    seen_cards.add(my_choice)
    return my_choice
