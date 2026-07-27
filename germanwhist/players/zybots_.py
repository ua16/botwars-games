"""
Titan German Whist Player Bot (Fixed & Optimized)

Strategy Architecture:
- Phase 1 (Recruitment): Card counting pool tracking. Dynamically evaluates 
  prizes (Trumps/Aces/Kings) and manages suit length.
- Phase 2 (Scoring): Exact Opponent Hand Deduction + Master-Card Calculation.
  Plays provable guaranteed winners (Boss Cards) and minimal cost follow-cards.
"""

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))
FULL_DECK = set((s, r) for s in SUITS for r in RANKS)


def legal_cards(hand, lead_card):
    """Return legally playable cards in accordance with follow-suit rules."""
    if lead_card is None:
        return list(hand)
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def resolve_trick(lead_card, follow_card, trump_suit):
    """Returns True if lead_card wins, False if follow_card wins."""
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card

    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    elif follow_suit == trump_suit:
        return False
    return True


# ---------------------------------------------------------------------------
# Persistent Match Memory (Safely auto-resets on every new game)
# ---------------------------------------------------------------------------
class BotMemory:
    def __init__(self):
        self.seen_cards = set()

    def sync(self, view):
        # Auto-reset state when a new game starts (13 cards in hand, stock 25)
        if view.phase == 1 and view.stock_remaining == 25 and len(view.your_hand) == 13:
            self.seen_cards.clear()

        # Track all witnessed cards
        for card in view.your_hand:
            self.seen_cards.add(card)
        if view.face_up_card:
            self.seen_cards.add(view.face_up_card)
        for _, card in view.current_trick:
            self.seen_cards.add(card)

    def deduce_opponent_hand(self, your_hand):
        """In Phase 2, unseen cards are 100% in opponent's hand."""
        unseen = FULL_DECK - self.seen_cards - set(your_hand)
        return list(unseen)


MEMORY = BotMemory()


# ---------------------------------------------------------------------------
# Phase 2 Decision Engine (Master Card & Exact Deduction)
# ---------------------------------------------------------------------------
def solve_phase2_move(hand, opp_hand, trump, lead_card):
    allowed = legal_cards(hand, lead_card)

    def card_power(c):
        return (20 if c[0] == trump else 0) + c[1]

    allowed_sorted = sorted(allowed, key=card_power)

    # 1. LEADING (We play first)
    if lead_card is None:
        # Find "Boss / Master Cards" (Cards that no card left in opp_hand can beat)
        boss_cards = []
        for card in hand:
            c_suit, c_rank = card
            # Opponent cards in the same suit that beat this card
            opp_higher = [
                oc for oc in opp_hand 
                if oc[0] == c_suit and oc[1] > c_rank
            ]
            
            if not opp_higher:
                if c_suit == trump:
                    boss_cards.append(card)
                else:
                    # Non-trump boss card is guaranteed win if opponent has no trumps or must follow suit
                    opp_has_trumps = any(oc[0] == trump for oc in opp_hand)
                    opp_has_suit = any(oc[0] == c_suit for oc in opp_hand)
                    if not opp_has_trumps or opp_has_suit:
                        boss_cards.append(card)

        if boss_cards:
            # Cash in boss cards starting with non-trumps
            non_trump_bosses = [c for c in boss_cards if c[0] != trump]
            if non_trump_bosses:
                return max(non_trump_bosses, key=lambda c: c[1])
            return max(boss_cards, key=lambda c: c[1])

        # If no guaranteed boss card, lead lowest card from our shortest non-trump suit
        non_trumps = [c for c in allowed_sorted if c[0] != trump]
        if non_trumps:
            suit_counts = {}
            for c in non_trumps:
                suit_counts[c[0]] = suit_counts.get(c[0], 0) + 1
            shortest_suit = min(suit_counts, key=suit_counts.get)
            shortest_candidates = [c for c in non_trumps if c[0] == shortest_suit]
            return shortest_candidates[0]

        return allowed_sorted[0]

    # 2. FOLLOWING (Opponent played lead_card)
    else:
        lead_suit = lead_card[0]
        can_follow = (allowed[0][0] == lead_suit)

        if can_follow:
            # Find all legal cards that beat opponent's card
            winners = [c for c in allowed_sorted if c[1] > lead_card[1]]
            if winners:
                return winners[0]  # Play smallest winning card
            return allowed_sorted[0]  # Can't win -> discard lowest card

        # Can't follow suit: Ruff with smallest trump if non-trump lead
        if lead_suit != trump:
            trumps = [c for c in allowed_sorted if c[0] == trump]
            if trumps:
                return trumps[0]

        # Discard lowest value card
        return allowed_sorted[0]


# ---------------------------------------------------------------------------
# Main Bot Entry Point
# ---------------------------------------------------------------------------
def nextMove(view):
    MEMORY.sync(view)

    hand = view.your_hand
    trump = view.trump_suit

    lead_card = None
    if view.current_trick and view.current_trick[0][0] != view.your_name:
        lead_card = view.current_trick[0][1]

    allowed = legal_cards(hand, lead_card)

    # =========================================================================
    # PHASE 1: RECRUITMENT PHASE
    # =========================================================================
    if view.phase == 1:
        prize = view.face_up_card

        # Prize Valuation: Fight for Trumps, Aces, Kings, Queens
        is_good_prize = False
        if prize:
            p_suit, p_rank = prize
            is_good_prize = (p_suit == trump) or (p_rank >= 12)

        # Sort moves: non-trumps low->high, then trumps low->high
        sorted_allowed = sorted(allowed, key=lambda c: (1 if c[0] == trump else 0, c[1]))

        if lead_card is None:
            # LEADING
            if is_good_prize:
                return sorted_allowed[-1]  # Play top card to secure prize
            else:
                # Shed lowest non-trump card to give away bad prize
                non_trumps = [c for c in sorted_allowed if c[0] != trump]
                return non_trumps[0] if non_trumps else sorted_allowed[0]
        else:
            # FOLLOWING
            lead_suit = lead_card[0]
            can_follow = (allowed[0][0] == lead_suit)

            if is_good_prize:
                if can_follow:
                    winners = [c for c in sorted_allowed if c[1] > lead_card[1]]
                    if winners:
                        return winners[0]
                elif trump in [c[0] for c in allowed]:
                    trumps = [c for c in sorted_allowed if c[0] == trump]
                    return trumps[0]
                
                return sorted_allowed[0]
            else:
                # Yield trick to take unseen card instead
                return sorted_allowed[0]

    # =========================================================================
    # PHASE 2: SCORING PHASE
    # =========================================================================
    else:
        opp_hand = MEMORY.deduce_opponent_hand(hand)
        return solve_phase2_move(hand, opp_hand, trump, lead_card)
