"""
Strategic Spades v2.1
===================

Score-aware two-player Spades bot with malicious bag-feeding capabilities.

Main strategic priorities:

1. Protect our nil.
2. Make our own bid.
3. Break opponent nil.
4. Prevent opponent from making their normal bid.
5. If we are set and opponent made their bid, flood them with bags.
6. Avoid unnecessary bags.
7. Minimize trick cost when the above objectives are satisfied.

Only Python standard-library functionality is used.
"""

from collections import Counter


# ============================================================
# CONSTANTS
# ============================================================

SUITS = ("H", "D", "C", "S")
SPADES = "S"

DECK = [
    (s, r)
    for s in SUITS
    for r in range(2, 15)
    if not (s in ("C", "D") and r == 2)
]


# ============================================================
# BASIC CARD FUNCTIONS
# ============================================================

def card_suit(card):
    return card[0]


def card_rank(card):
    return card[1]


def is_spade(card):
    return card[0] == SPADES


def suit_count(hand, s):
    return sum(1 for c in hand if c[0] == s)


def cards_of_suit(hand, s):
    return [c for c in hand if c[0] == s]


# ============================================================
# LEGAL MOVE GENERATION
# ============================================================

def get_legal_cards(state):
    hand = list(state.your_hand)

    if not hand:
        return []

    # Leading.
    if not state.current_trick:

        if state.spades_broken:
            return hand

        non_spades = [
            c for c in hand
            if not is_spade(c)
        ]

        if non_spades:
            return non_spades

        # All spades.
        return hand

    # Following.
    lead_suit = state.current_trick[0][1][0]

    matching = [
        c for c in hand
        if c[0] == lead_suit
    ]

    if matching:
        return matching

    return hand


# ============================================================
# TRICK RESOLUTION
# ============================================================

def card_beats(our_card, opponent_card, lead_suit):
    """
    True if our_card wins against opponent_card.
    """

    our_suit, our_rank = our_card
    opp_suit, opp_rank = opponent_card

    # Both spades.
    if our_suit == SPADES and opp_suit == SPADES:
        return our_rank > opp_rank

    # Our spade beats non-spade.
    if our_suit == SPADES:
        return opp_suit != SPADES

    # Opponent spade beats us.
    if opp_suit == SPADES:
        return False

    # Neither is spade.
    if our_suit != lead_suit:
        return False

    if opp_suit != lead_suit:
        return True

    return our_rank > opp_rank


def winning_cards(cards, opponent_card):
    lead_suit = opponent_card[0]

    return [
        c
        for c in cards
        if card_beats(c, opponent_card, lead_suit)
    ]


def losing_cards(cards, opponent_card):
    lead_suit = opponent_card[0]

    return [
        c
        for c in cards
        if not card_beats(c, opponent_card, lead_suit)
    ]


def cheapest_winner(cards, opponent_card):
    winners = winning_cards(cards, opponent_card)

    if not winners:
        return None

    # Prefer a non-spade winner.
    # Among those, use the smallest rank.
    return min(
        winners,
        key=lambda c: (
            1 if is_spade(c) else 0,
            c[1]
        )
    )


def cheapest_loser(cards, opponent_card):
    losers = losing_cards(cards, opponent_card)

    if not losers:
        return None

    # Avoid wasting spades.
    return min(
        losers,
        key=lambda c: (
            1 if is_spade(c) else 0,
            c[1]
        )
    )


def lowest_card(cards):
    if not cards:
        return None

    return min(
        cards,
        key=lambda c: (
            1 if is_spade(c) else 0,
            c[1]
        )
    )


def highest_card(cards):
    if not cards:
        return None

    return max(
        cards,
        key=lambda c: (
            1 if is_spade(c) else 0,
            c[1]
        )
    )


# ============================================================
# PUBLIC CARD TRACKING
# ============================================================

def exposed_cards(state):
    """
    Every card whose identity we know.
    """

    seen = set(state.your_hand)

    for trick in state.trick_history:
        for _, card in trick["plays"]:
            seen.add(card)

    for _, card in state.current_trick:
        seen.add(card)

    return seen


def unseen_cards(state):
    seen = exposed_cards(state)

    return [
        c for c in DECK
        if c not in seen
    ]


def remaining_spades(state):
    return [
        c
        for c in unseen_cards(state)
        if c[0] == SPADES
    ]


def count_remaining_rank(state, s, minimum_rank):
    return sum(
        1
        for c in unseen_cards(state)
        if c[0] == s and c[1] >= minimum_rank
    )


# ============================================================
# OPPONENT VOID DETECTION
# ============================================================

def opponent_void_suits(state):
    """
    If opponent failed to follow a led suit, they are void
    in that suit for the remainder of the round.
    """

    voids = set()

    for trick in state.trick_history:

        plays = trick["plays"]

        if len(plays) != 2:
            continue

        leader_name, leader_card = plays[0]
        follower_name, follower_card = plays[1]

        if follower_name != state.opponent_name:
            continue

        lead_suit = leader_card[0]

        if follower_card[0] != lead_suit:
            voids.add(lead_suit)

    return voids


# ============================================================
# TRICK COUNTERS
# ============================================================

def our_tricks(state):
    return state.tricks_won.get(
        state.your_name,
        0
    )


def opponent_tricks(state):
    return state.tricks_won.get(
        state.opponent_name,
        0
    )


def tricks_remaining(state):
    return 13 - len(state.trick_history)


def our_need(state):
    """
    Additional tricks required to make our bid.
    """

    if state.your_bid == 0:
        return 0

    return max(
        0,
        state.your_bid - our_tricks(state)
    )


def opponent_need(state):
    """
    Additional tricks opponent needs to make their bid.
    """

    if state.opponent_bid == 0:
        return 0

    return max(
        0,
        state.opponent_bid - opponent_tricks(state)
    )


# ============================================================
# BID FEASIBILITY
# ============================================================

def can_we_make_bid(state):
    """
    Pure mathematical feasibility.
    """

    if state.your_bid == 0:
        return our_tricks(state) == 0

    return our_need(state) <= tricks_remaining(state)


def can_opponent_make_bid(state):
    if state.opponent_bid == 0:
        return opponent_tricks(state) == 0

    return opponent_need(state) <= tricks_remaining(state)


# ============================================================
# BID ESTIMATION
# ============================================================

def nil_risk(hand):
    """
    Lower is safer for nil.
    """

    risk = 0.0

    for s, r in hand:

        if s == SPADES:

            if r >= 14:
                risk += 5.0
            elif r >= 13:
                risk += 3.5
            elif r >= 12:
                risk += 2.5
            elif r >= 10:
                risk += 1.3
            elif r >= 7:
                risk += 0.5
            else:
                risk += 0.15

        else:

            if r == 14:
                risk += 4.0
            elif r == 13:
                risk += 2.4
            elif r == 12:
                risk += 1.5
            elif r == 11:
                risk += 0.7

    return risk


def hand_strength(hand):
    """
    Estimate normal trick-taking strength.
    """

    score = 0.0

    # Aces.
    score += sum(
        1.0
        for s, r in hand
        if r == 14
    )

    # Kings.
    for s, r in hand:
        if r == 13:
            n = suit_count(hand, s)

            if n >= 3:
                score += 0.9
            elif n == 2:
                score += 0.65
            else:
                score += 0.30

    # Queens.
    for s, r in hand:
        if r == 12:
            n = suit_count(hand, s)

            if n >= 4:
                score += 0.60
            elif n >= 3:
                score += 0.35
            else:
                score += 0.10

    # Jacks with support.
    for s, r in hand:
        if r == 11 and suit_count(hand, s) >= 4:
            score += 0.25

    # Spade power.
    spades = cards_of_suit(hand, SPADES)

    for _, r in spades:

        if r == 14:
            score += 1.30
        elif r == 13:
            score += 1.05
        elif r == 12:
            score += 0.80
        elif r == 11:
            score += 0.55
        elif r >= 9:
            score += 0.30
        elif r >= 6:
            score += 0.15

    # Long spade suit.
    if len(spades) >= 4:
        score += 0.40

    if len(spades) >= 5:
        score += 0.50

    # Voids create trump opportunities.
    for s in ("H", "D", "C"):

        n = suit_count(hand, s)

        if n == 0:
            score += 0.65
        elif n == 1:
            score += 0.20

    return score


def choose_bid(state):
    hand = state.your_hand

    strength = hand_strength(hand)

    # --------------------------------------------------------
    # NIL
    # --------------------------------------------------------

    if strength < 2.0 and nil_risk(hand) < 3.0:

        if not state.opponent_bid_known:
            return 0

        if state.opponent_bid >= 7:
            return 0

    # --------------------------------------------------------
    # NORMAL BID
    # --------------------------------------------------------

    bid = int(round(strength))

    if state.your_bags >= 8:
        bid -= 1

    if state.opponent_bid_known:

        if state.opponent_bid >= 7:
            bid += 1

        elif state.opponent_bid <= 2:
            bid -= 0

    bid = max(1, bid)
    bid = min(13, bid)

    return bid


# ============================================================
# SCORE STRATEGY
# ============================================================

def score_pressure(state):
    my_score = state.your_score
    opp_score = state.opponent_score

    if my_score >= 400 and my_score >= opp_score:
        return -1

    if opp_score >= 400 and opp_score > my_score:
        return 1

    if opp_score - my_score >= 100:
        return 1

    if my_score - opp_score >= 100:
        return -1

    return 0


def opponent_denial_value(state):
    if state.opponent_bid == 0:
        return 200

    return state.opponent_bid * 20


def bag_cost(state):
    if state.your_bags >= 9:
        return 100

    if state.your_bags >= 8:
        return 50

    if state.your_bags >= 6:
        return 15

    return 1


# ============================================================
# STRATEGIC MODE
# ============================================================

def determine_mode(state):
    """
    Returns one of:

        NIL
        MAKE_BID
        BREAK_NIL
        DENY
        BAG_OPPONENT
        SURVIVE
    """

    if state.your_bid == 0:
        return "NIL"

    if can_we_make_bid(state):
        return "MAKE_BID"

    # Our bid is broken/impossible at this point.
    if state.opponent_bid == 0:
        if opponent_tricks(state) == 0:
            return "BREAK_NIL"
        return "SURVIVE"

    # Opponent still needs tricks to reach their safe zone.
    if opponent_need(state) > 0:
        if can_opponent_make_bid(state):
            return "DENY"
        return "SURVIVE"  # Opponent is also set, no need to deny them

    # If we are set, and the opponent has already secured their bid,
    # switch to absolute sabotage mode: Feed them overtricks.
    return "BAG_OPPONENT"


# ============================================================
# NIL PLAY
# ============================================================

def play_our_nil(state, legal):
    if state.current_trick:

        opponent_card = state.current_trick[0][1]

        losers = losing_cards(
            legal,
            opponent_card
        )

        if losers:
            return cheapest_loser(
                legal,
                opponent_card
            )

        return lowest_card(legal)

    non_spades = [
        c for c in legal
        if not is_spade(c)
    ]

    if non_spades:

        return min(
            non_spades,
            key=lambda c: (
                c[1],
                suit_count(
                    state.your_hand,
                    c[0]
                )
            )
        )

    return lowest_card(legal)


# ============================================================
# BREAK OPPONENT NIL
# ============================================================

def break_opponent_nil(state, legal):
    if state.current_trick:

        opponent_card = state.current_trick[0][1]

        losers = losing_cards(
            legal,
            opponent_card
        )

        if losers:
            return cheapest_loser(
                legal,
                opponent_card
            )

        return lowest_card(legal)

    non_spades = [
        c for c in legal
        if not is_spade(c)
    ]

    if non_spades:

        candidates = sorted(
            non_spades,
            key=lambda c: c[1],
            reverse=True
        )

        for c in candidates:
            if 10 <= c[1] <= 13:
                return c

        return candidates[0]

    return highest_card(legal)


# ============================================================
# DENIAL MODE
# ============================================================

def deny_opponent(state, legal):
    if opponent_need(state) <= 0:
        return survive_mode(state, legal)

    if state.current_trick:

        opponent_card = state.current_trick[0][1]

        winners = winning_cards(
            legal,
            opponent_card
        )

        if not winners:
            return lowest_card(legal)

        return cheapest_winner(
            legal,
            opponent_card
        )

    non_spades = [
        c for c in legal
        if not is_spade(c)
    ]

    if non_spades:

        kings = [
            c for c in non_spades
            if c[1] == 13
        ]

        if kings:
            return kings[0]

        aces = [
            c for c in non_spades
            if c[1] == 14
        ]

        if aces:
            return aces[0]

        return max(
            non_spades,
            key=lambda c: c[1]
        )

    return highest_card(legal)


# ============================================================
# BAG OPPONENT MODE (SABOTAGE)
# ============================================================

def bag_opponent_mode(state, legal):
    """
    We cannot win our bid, and the opponent has already made theirs.
    Force the opponent to win every single remaining trick.
    """
    # Following: Play the lowest losing card to keep the opponent in the lead.
    if state.current_trick:
        opponent_card = state.current_trick[0][1]
        losers = losing_cards(legal, opponent_card)
        if losers:
            return cheapest_loser(legal, opponent_card)
        
        # If forced to win, burn the lowest winning card to conserve high cards
        # for future ducking opportunities.
        return lowest_card(legal)

    # Leading: Lead our absolute lowest cards so the opponent is forced 
    # to win the trick with whatever they have.
    non_spades = [c for c in legal if not is_spade(c)]
    if non_spades:
        # Avoid leading suits where the opponent is void, as they will discard low.
        voids = opponent_void_suits(state)
        safe_leads = [c for c in non_spades if c[0] not in voids]
        
        if safe_leads:
            return min(safe_leads, key=lambda c: c[1])
        return min(non_spades, key=lambda c: c[1])

    return lowest_card(legal)


# ============================================================
# MAKE OUR BID
# ============================================================

def make_bid_mode(state, legal):
    need = our_need(state)

    if state.current_trick:

        opponent_card = state.current_trick[0][1]

        winners = winning_cards(
            legal,
            opponent_card
        )

        if need > 0:

            if winners:
                return cheapest_winner(
                    legal,
                    opponent_card
                )

            return lowest_card(legal)

        if state.your_bags >= 8:

            losers = losing_cards(
                legal,
                opponent_card
            )

            if losers:
                return cheapest_loser(
                    legal,
                    opponent_card
                )

        if opponent_need(state) > 0:

            if winners and opponent_need(state) <= 1:
                return cheapest_winner(
                    legal,
                    opponent_card
                )

        losers = losing_cards(
            legal,
            opponent_card
        )

        if losers:
            return cheapest_loser(
                legal,
                opponent_card
            )

        return lowest_card(legal)

    if need > 0:

        non_spades = [
            c for c in legal
            if not is_spade(c)
        ]

        if non_spades:

            aces = [
                c for c in non_spades
                if c[1] == 14
            ]

            if aces:
                return aces[0]

            kings = [
                c for c in non_spades
                if c[1] == 13
                and suit_count(
                    state.your_hand,
                    c[0]
                ) >= 2
            ]

            if kings:
                return kings[0]

            return max(
                non_spades,
                key=lambda c: c[1]
            )

        return highest_card(legal)

    return lowest_card(legal)


# ============================================================
# SURVIVAL / BAG CONTROL
# ============================================================

def survive_mode(state, legal):
    if state.current_trick:

        opponent_card = state.current_trick[0][1]

        losers = losing_cards(
            legal,
            opponent_card
        )

        if losers:
            return cheapest_loser(
                legal,
                opponent_card
            )

        return lowest_card(legal)

    non_spades = [
        c for c in legal
        if not is_spade(c)
    ]

    if non_spades:

        return min(
            non_spades,
            key=lambda c: (
                c[1],
                suit_count(
                    state.your_hand,
                    c[0]
                )
            )
        )

    return lowest_card(legal)


# ============================================================
# ENDGAME LOGIC
# ============================================================

def endgame_override(state, legal, card, mode):
    left = tricks_remaining(state)

    if state.your_bid > 0:

        need = our_need(state)

        if need >= left and left > 0:

            if state.current_trick:

                opponent_card = state.current_trick[0][1]

                winners = winning_cards(
                    legal,
                    opponent_card
                )

                if winners:
                    return cheapest_winner(
                        legal,
                        opponent_card
                    )

            return highest_card(legal)

    if state.opponent_bid > 0:

        opp_need = opponent_need(state)

        if opp_need >= left and left > 0:

            if state.current_trick:

                opponent_card = state.current_trick[0][1]

                winners = winning_cards(
                    legal,
                    opponent_card
                )

                if winners:
                    return cheapest_winner(
                        legal,
                        opponent_card
                    )

            return highest_card(legal)

    # If we are deliberately feeding them bags, override normal bag control
    if mode == "BAG_OPPONENT":
        return card

    if state.your_bags >= 9:

        if state.current_trick:

            opponent_card = state.current_trick[0][1]

            losers = losing_cards(
                legal,
                opponent_card
            )

            if losers:
                return cheapest_loser(
                    legal,
                    opponent_card
                )

        return lowest_card(legal)

    return card


# ============================================================
# MAIN PLAY DECISION
# ============================================================

def choose_play(state):

    legal = get_legal_cards(state)

    if not legal:
        return state.your_hand[0]

    mode = determine_mode(state)

    if mode == "NIL":
        card = play_our_nil(state, legal)

    elif mode == "MAKE_BID":
        card = make_bid_mode(state, legal)

    elif mode == "BREAK_NIL":
        card = break_opponent_nil(state, legal)

    elif mode == "DENY":
        card = deny_opponent(state, legal)

    elif mode == "BAG_OPPONENT":
        card = bag_opponent_mode(state, legal)

    else:
        card = survive_mode(state, legal)

    return endgame_override(
        state,
        legal,
        card,
        mode
    )


# ============================================================
# PUBLIC API
# ============================================================

def nextMove(gameState):

    if gameState.phase == "bid":
        return choose_bid(gameState)

    return choose_play(gameState)
