def nextMove(gameState):
    """
    Main dispatcher. Routes to the correct phase instantly.
    """
    phase = getattr(gameState, "phase", None)
    if phase == "exchange":
        return _exchange_phase(gameState)
    if phase == "declare":
        return _declare_phase(gameState)
    return _trick_phase(gameState)


def _exchange_phase(gameState):
    """
    Instantly scores cards based on rank, suit length, and set potential.
    """
    hand = list(getattr(gameState, "your_hand", []) or [])
    is_elder = (getattr(gameState, "your_name", None) == getattr(gameState, "elder", None))
    
    max_discard = min(5, len(hand)) if is_elder else min(getattr(gameState, "talon_remaining", 0) or 0, len(hand))
    if max_discard <= 0:
        return []

    # Count how many cards we have in each suit
    suit_counts = {}
    for s, r in hand:
        suit_counts[s] = suit_counts.get(s, 0) + 1

    def keep_value(card):
        s, r = card
        val = r  # Base value is the card's rank[cite: 19]
        val += suit_counts[s] * 2  # Bonus for being in a long suit[cite: 19]
        
        # Huge bonus for pairs/sets of 10 or higher[cite: 19]
        if r >= 10 and sum(1 for _, rank in hand if rank == r) >= 2:
            val += 10 
        return val

    # Sort cards from weakest to strongest and throw away the weakest
    hand.sort(key=keep_value)
    return hand[:max_discard]


def _declare_phase(gameState):
    """
    Claims valid declarations instantly without deep scanning.
    """
    hand = list(getattr(gameState, "your_hand", []) or [])
    cat = str(getattr(gameState, "declare_category", "") or "").lower()

    if cat == "point" and hand:
        return ("claim",)
        
    if cat == "set":
        counts = {}
        for _, rank in hand:
            if rank >= 10:
                counts[rank] = counts.get(rank, 0) + 1
        if max(counts.values(), default=0) >= 3:
            return ("claim",)

    if cat == "sequence":
        by_suit = {}
        for suit, rank in hand:
            by_suit.setdefault(suit, []).append(rank)
            
        for ranks in by_suit.values():
            ranks.sort()
            run = 1
            for i in range(1, len(ranks)):
                if ranks[i] == ranks[i - 1] + 1:
                    run += 1
                    if run >= 3: 
                        return ("claim",)
                else:
                    run = 1

    return "pass"


def _trick_phase(gameState):
    """
    Uses fast heuristics to win tricks cheaply or safely lose.
    """
    hand = list(getattr(gameState, "your_hand", []) or [])
    if not hand:
        return None

    trick = list(getattr(gameState, "current_trick", []) or [])

    # If we are following the opponent's lead[cite: 19]
    if trick:
        # Extract the card they led[cite: 19]
        lead_card = trick[0][1] if isinstance(trick[0], (list, tuple)) else trick[0]
        lead_suit, lead_rank = lead_card
        
        # Find cards we legally can play (must follow suit)[cite: 19]
        legal_moves = [c for c in hand if c[0] == lead_suit]
        
        if legal_moves:
            winners = [c for c in legal_moves if c[1] > lead_rank]
            if winners:
                return min(winners, key=lambda c: c[1])  # Win with the cheapest card[cite: 19]
            return min(legal_moves, key=lambda c: c[1])  # Lose with the cheapest card[cite: 19]
            
        # We don't have the suit, dump our absolute weakest card[cite: 19]
        return min(hand, key=lambda c: c[1])

    # If we are leading the trick[cite: 19]
    by_suit = {}
    for c in hand: 
        by_suit.setdefault(c[0], []).append(c)
        
    # Lead the highest rank from our longest suit to establish pressure[cite: 19]
    longest_suit = max(by_suit.values(), key=len)
    return max(longest_suit, key=lambda c: c[1])
