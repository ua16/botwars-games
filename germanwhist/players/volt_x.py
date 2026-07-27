# ============================================================
# Team: VOLT_X
# Competition: BotWars 2026 - German Whist Qualifiers
#
# Strategy:
# - Conservative legal card tracking and game-state memory
# - Remaining higher-card analysis
# - Winner-chain detection
# - Promotion-potential evaluation
# - Cost/reward-based Phase 1 card acquisition
# - Strategic Phase 2 trick control and lead sequencing
# - Distinguishes safe winners from vulnerable high cards
#
# ============================================================


SUITS = ("H", "D", "C", "S")
RANKS = range(2, 15)


# ============================================================
# MEMORY
# ============================================================

_memory = {
    "initialized": False,
    "trump": None,
    "last_phase": None,
    "last_stock_remaining": None,

    "seen_cards": set(),
    "seen_face_up": set(),
    "seen_played": set(),

    "previous_hand": None,

    "turn_calls": 0,
}


# ============================================================
# MEMORY RESET
# ============================================================

def reset_memory(gameState):

    global _memory

    _memory = {
        "initialized": True,

        "trump": gameState.trump_suit,

        "last_phase": gameState.phase,

        "last_stock_remaining":
            gameState.stock_remaining,

        "seen_cards":
            set(gameState.your_hand),

        "seen_face_up":
            set(),

        "seen_played":
            set(),

        "previous_hand":
            set(gameState.your_hand),

        "turn_calls": 0,
    }

    if gameState.face_up_card is not None:

        _memory["seen_face_up"].add(
            gameState.face_up_card
        )

        _memory["seen_cards"].add(
            gameState.face_up_card
        )

    record_current_trick(gameState)


# ============================================================
# NEW GAME DETECTION
# ============================================================

def looks_like_new_game(gameState):

    if not _memory["initialized"]:
        return True

    # Phase 2 -> Phase 1
    if (
        _memory["last_phase"] == 2
        and gameState.phase == 1
    ):
        return True

    previous_stock = (
        _memory["last_stock_remaining"]
    )

    # Stock increasing means new game
    if (
        previous_stock is not None
        and gameState.stock_remaining is not None
        and gameState.stock_remaining
            > previous_stock
    ):
        return True

    # Trump changes only between games
    if (
        _memory["trump"] is not None
        and gameState.trump_suit
            != _memory["trump"]
    ):
        return True

    return False


# ============================================================
# UPDATE MEMORY
# ============================================================

def update_memory(gameState):

    if looks_like_new_game(gameState):
        reset_memory(gameState)

    current_hand = set(
        gameState.your_hand
    )

    previous_hand = (
        _memory["previous_hand"]
    )

    # Cards that disappeared from our hand
    if previous_hand is not None:

        disappeared = (
            previous_hand
            - current_hand
        )

        for card in disappeared:

            _memory["seen_cards"].add(
                card
            )

            _memory["seen_played"].add(
                card
            )

    # Current hand is known
    _memory["seen_cards"].update(
        current_hand
    )

    # Face-up card is public
    if gameState.face_up_card is not None:

        _memory["seen_face_up"].add(
            gameState.face_up_card
        )

        _memory["seen_cards"].add(
            gameState.face_up_card
        )

    # Current trick
    record_current_trick(gameState)

    _memory["previous_hand"] = (
        current_hand
    )

    _memory["last_phase"] = (
        gameState.phase
    )

    _memory["last_stock_remaining"] = (
        gameState.stock_remaining
    )

    _memory["trump"] = (
        gameState.trump_suit
    )

    _memory["turn_calls"] += 1


def record_current_trick(gameState):

    for entry in gameState.current_trick:

        card = entry[1]

        _memory["seen_cards"].add(
            card
        )

        _memory["seen_played"].add(
            card
        )


# ============================================================
# MAIN ENTRY
# ============================================================

def nextMove(gameState):

    hand = list(
        gameState.your_hand
    )

    if not hand:
        return None

    update_memory(gameState)

    trump = gameState.trump_suit

    legal = get_legal_cards(
        hand,
        gameState.current_trick
    )

    if not legal:
        return hand[0]

    if gameState.phase == 1:

        move = phase1_move(
            gameState,
            hand,
            legal,
            trump
        )

    else:

        move = phase2_move(
            gameState,
            hand,
            legal,
            trump
        )

    # Final legality protection
    if move in legal:
        return move

    return legal[0]


# ============================================================
# LEGAL MOVE HANDLING
# ============================================================

def get_legal_cards(
    hand,
    current_trick
):

    if not current_trick:
        return list(hand)

    lead_suit = (
        current_trick[0][1][0]
    )

    follow = [
        card
        for card in hand
        if card[0] == lead_suit
    ]

    if follow:
        return follow

    return list(hand)


# ============================================================
# BASIC HELPERS
# ============================================================

def suit_counts(hand):

    counts = {
        suit: 0
        for suit in SUITS
    }

    for suit, rank in hand:
        counts[suit] += 1

    return counts


def wins_against(
    card,
    lead_card,
    trump
):

    lead_suit, lead_rank = (
        lead_card
    )

    suit, rank = card

    if suit == lead_suit:
        return rank > lead_rank

    if (
        suit == trump
        and lead_suit != trump
    ):
        return True

    return False


# ============================================================
# REMAINING CARD ANALYSIS
# ============================================================

def higher_unseen_count(
    card,
    hand
):

    suit, rank = card

    current_hand = set(hand)

    count = 0

    for higher_rank in range(
        rank + 1,
        15
    ):

        higher_card = (
            suit,
            higher_rank
        )

        # We own it
        if higher_card in current_hand:
            continue

        # Already known played
        if (
            higher_card
            in _memory["seen_played"]
        ):
            continue

        count += 1

    return count


def known_top_card(
    card,
    hand
):

    return (
        higher_unseen_count(
            card,
            hand
        )
        == 0
    )


# ============================================================
# V4: WINNER CHAIN ANALYSIS
# ============================================================

def winner_chain_length(
    suit,
    hand
):
    """
    Count how many sequential top cards we effectively
    control in a suit.
    """

    hand_set = set(hand)

    chain = 0

    rank = 14

    while rank >= 2:

        card = (
            suit,
            rank
        )

        # We own this rank
        if card in hand_set:

            chain += 1
            rank -= 1
            continue

        # This rank has already disappeared
        if (
            card
            in _memory["seen_played"]
        ):

            rank -= 1
            continue

        # Unknown higher card blocks chain
        break

    return chain


def card_in_winner_chain(
    card,
    hand
):

    suit, rank = card

    hand_ranks = sorted(
        [
            r
            for s, r in hand
            if s == suit
        ],
        reverse=True
    )

    chain_length = (
        winner_chain_length(
            suit,
            hand
        )
    )

    if chain_length <= 0:
        return False

    # Determine top controlled cards
    controlled = []

    current_rank = 14

    hand_set = set(hand)

    while (
        current_rank >= 2
        and len(controlled)
            < chain_length
    ):

        c = (
            suit,
            current_rank
        )

        if c in hand_set:

            controlled.append(c)

        elif (
            c
            not in _memory["seen_played"]
        ):

            break

        current_rank -= 1

    return card in controlled


# ============================================================
# PROMOTION POTENTIAL
# ============================================================

def promotion_score(
    card,
    hand,
    trump
):
    """
    Estimate whether leading/keeping this card helps
    establish future winners.
    """

    suit, rank = card

    same_suit = sorted(
        [
            r
            for s, r in hand
            if s == suit
        ],
        reverse=True
    )

    score = 0.0

    higher_unknown = (
        higher_unseen_count(
            card,
            hand
        )
    )

    # Already a known top card
    if higher_unknown == 0:

        score += 10.0

    # Only one unknown higher card:
    # strong promotion potential
    elif higher_unknown == 1:

        score += 4.0

    elif higher_unknown == 2:

        score += 1.5

    # Supported suit
    if len(same_suit) >= 2:

        score += 1.5

    if len(same_suit) >= 3:

        score += 1.0

    # Trump control is valuable,
    # but avoid spending it casually.
    if suit == trump:

        score += 2.0

    return score


# ============================================================
# KEEP VALUE
# ============================================================

def structural_keep_value(
    card,
    hand,
    trump
):

    suit, rank = card

    counts = suit_counts(hand)

    value = float(rank)

    # Trump
    if suit == trump:

        value += 10.0

        if rank >= 11:
            value += 3.0

    # Honors
    if rank == 14:

        value += 6.0

    elif rank == 13:

        value += 3.5

    elif rank == 12:

        value += 2.0

    elif rank == 11:

        value += 1.0

    # Suit structure
    if suit != trump:

        if counts[suit] == 1:

            value -= 3.0

        elif counts[suit] == 2:

            value -= 1.2

        elif counts[suit] >= 4:

            value += 0.8

    # Phase-2 memory intelligence
    if _memory["last_phase"] == 2:

        if known_top_card(
            card,
            hand
        ):

            value += 6.0

        if card_in_winner_chain(
            card,
            hand
        ):

            value += 4.0

        value += (
            promotion_score(
                card,
                hand,
                trump
            )
            * 0.5
        )

    return value


def best_discard(
    cards,
    hand,
    trump
):

    return min(
        cards,
        key=lambda card: (
            structural_keep_value(
                card,
                hand,
                trump
            ),
            card[1]
        )
    )


# ============================================================
# PHASE 1 VALUE MODEL
# ============================================================

def reward_value(
    card,
    hand,
    trump
):

    if card is None:
        return 0.0

    suit, rank = card

    counts = suit_counts(hand)

    value = float(rank)

    if suit == trump:

        value += 9.0

        if rank >= 11:
            value += 3.0

    if rank == 14:

        value += 6.0

    elif rank == 13:

        value += 3.5

    elif rank == 12:

        value += 2.0

    elif rank == 11:

        value += 1.0

    if counts[suit] >= 3:

        value += 1.0

    return value


def sacrifice_cost(
    card,
    hand,
    trump
):

    suit, rank = card

    counts = suit_counts(hand)

    cost = float(rank)

    if suit == trump:

        cost += 9.0

        if rank >= 11:
            cost += 3.0

    if rank == 14:

        cost += 6.0

    elif rank == 13:

        cost += 3.5

    elif rank == 12:

        cost += 2.0

    elif rank == 11:

        cost += 1.0

    if suit != trump:

        if counts[suit] == 1:

            cost -= 2.5

        elif counts[suit] == 2:

            cost -= 0.8

    return cost


# ============================================================
# PHASE 1
# ============================================================

def phase1_move(
    gameState,
    hand,
    legal,
    trump
):

    face_up = (
        gameState.face_up_card
    )

    reward = reward_value(
        face_up,
        hand,
        trump
    )

    # Leading
    if not gameState.current_trick:

        return phase1_lead(
            hand,
            legal,
            trump,
            reward
        )

    # Following
    lead_card = (
        gameState.current_trick[0][1]
    )

    winning_cards = [
        card
        for card in legal
        if wins_against(
            card,
            lead_card,
            trump
        )
    ]

    if not winning_cards:

        return best_discard(
            legal,
            hand,
            trump
        )

    cheapest_winner = min(
        winning_cards,
        key=lambda card: (
            sacrifice_cost(
                card,
                hand,
                trump
            ),
            card[1]
        )
    )

    cost = sacrifice_cost(
        cheapest_winner,
        hand,
        trump
    )

    net_value = (
        reward - cost
    )

    premium_reward = False

    if face_up is not None:

        reward_suit, reward_rank = (
            face_up
        )

        premium_reward = (
            reward_rank >= 12
            or reward_suit == trump
        )

    if reward >= 23.0:

        return cheapest_winner

    if net_value >= 1.5:

        return cheapest_winner

    if (
        premium_reward
        and net_value >= -5.0
    ):

        return cheapest_winner

    if (
        cost <= 10.0
        and reward >= 9.0
    ):

        return cheapest_winner

    return best_discard(
        legal,
        hand,
        trump
    )


# ============================================================
# PHASE 1 LEAD
# ============================================================

def phase1_lead(
    hand,
    legal,
    trump,
    reward
):

    counts = suit_counts(hand)

    non_trumps = [
        card
        for card in legal
        if card[0] != trump
    ]

    # Very valuable face-up card
    if reward >= 23.0:

        strong_non_trumps = [
            card
            for card in non_trumps
            if card[1] >= 11
        ]

        if strong_non_trumps:

            return max(
                strong_non_trumps,
                key=lambda card: (
                    card[1],
                    counts[
                        card[0]
                    ]
                )
            )

        if non_trumps:

            return max(
                non_trumps,
                key=lambda card:
                    card[1]
            )

        return max(
            legal,
            key=lambda card:
                card[1]
        )

    # Medium reward
    if reward >= 15.0:

        candidates = [
            card
            for card in non_trumps
            if 9 <= card[1] <= 13
        ]

        if candidates:

            return max(
                candidates,
                key=lambda card: (
                    card[1],
                    counts[
                        card[0]
                    ]
                )
            )

    # Weak reward
    return best_discard(
        legal,
        hand,
        trump
    )


# ============================================================
# PHASE 2
# ============================================================

def phase2_move(
    gameState,
    hand,
    legal,
    trump
):

    if not gameState.current_trick:

        return phase2_lead(
            hand,
            legal,
            trump
        )

    return phase2_follow(
        gameState,
        hand,
        legal,
        trump
    )


# ============================================================
# PHASE 2 FOLLOW
# ============================================================

def phase2_follow(
    gameState,
    hand,
    legal,
    trump
):

    lead_card = (
        gameState.current_trick[0][1]
    )

    lead_suit = (
        lead_card[0]
    )

    winning_cards = [
        card
        for card in legal
        if wins_against(
            card,
            lead_card,
            trump
        )
    ]

    # --------------------------------------------------------
    # CAN WIN
    # --------------------------------------------------------

    if winning_cards:

        same_suit_winners = [
            card
            for card in winning_cards
            if card[0]
                == lead_suit
        ]

        # Cheapest sufficient same-suit winner
        if same_suit_winners:

            return min(
                same_suit_winners,
                key=lambda card:
                    card[1]
            )

        # Cheapest trump winner
        trump_winners = [
            card
            for card in winning_cards
            if card[0] == trump
        ]

        if trump_winners:

            return min(
                trump_winners,
                key=lambda card:
                    card[1]
            )

        return min(
            winning_cards,
            key=lambda card: (
                sacrifice_cost(
                    card,
                    hand,
                    trump
                ),
                card[1]
            )
        )

    # Cannot win
    return best_discard(
        legal,
        hand,
        trump
    )


# ============================================================
# V4 PHASE 2 LEAD
# ============================================================

def phase2_lead(
    hand,
    legal,
    trump
):

    counts = suit_counts(hand)

    non_trumps = [
        card
        for card in legal
        if card[0] != trump
    ]

    trumps = [
        card
        for card in legal
        if card[0] == trump
    ]

    # ========================================================
    # PRIORITY 1:
    # KNOWN WINNER CHAINS
    #
    # If we control consecutive top cards, cash the highest
    # one first while retaining the lead.
    # ========================================================

    chain_cards = [
        card
        for card in non_trumps
        if card_in_winner_chain(
            card,
            hand
        )
    ]

    if chain_cards:

        # Prefer suit with longest winner chain
        # then highest card.
        return max(
            chain_cards,
            key=lambda card: (
                winner_chain_length(
                    card[0],
                    hand
                ),
                card[1],
                counts[
                    card[0]
                ]
            )
        )

    # ========================================================
    # PRIORITY 2:
    # KNOWN TOP CARDS
    # ========================================================

    known_top = [
        card
        for card in non_trumps
        if known_top_card(
            card,
            hand
        )
    ]

    if known_top:

        return max(
            known_top,
            key=lambda card: (
                promotion_score(
                    card,
                    hand,
                    trump
                ),
                card[1],
                counts[
                    card[0]
                ]
            )
        )

    # ========================================================
    # PRIORITY 3:
    # ACES
    #
    # Still very strong even if our incomplete memory does
    # not classify them through another rule.
    # ========================================================

    aces = [
        card
        for card in non_trumps
        if card[1] == 14
    ]

    if aces:

        return max(
            aces,
            key=lambda card: (
                counts[
                    card[0]
                ],
                promotion_score(
                    card,
                    hand,
                    trump
                )
            )
        )

    # ========================================================
    # PRIORITY 4:
    # PROMOTABLE HIGH CARDS
    #
    # Prefer honors with few unknown higher cards and
    # supporting cards in the same suit.
    # ========================================================

    promotable = [
        card
        for card in non_trumps
        if (
            card[1] >= 11
            and higher_unseen_count(
                card,
                hand
            ) <= 2
            and counts[
                card[0]
            ] >= 2
        )
    ]

    if promotable:

        return max(
            promotable,
            key=lambda card: (
                promotion_score(
                    card,
                    hand,
                    trump
                ),
                card[1],
                counts[
                    card[0]
                ]
            )
        )

    # ========================================================
    # PRIORITY 5:
    # DEVELOP LONG SUITS
    #
    # Preserve honors while using low cards from long suits.
    # ========================================================

    long_suit_cards = [
        card
        for card in non_trumps
        if counts[
            card[0]
        ] >= 3
    ]

    if long_suit_cards:

        return min(
            long_suit_cards,
            key=lambda card: (
                card[1],
                -counts[
                    card[0]
                ]
            )
        )

    # ========================================================
    # PRIORITY 6:
    # CONTROLLED NON-TRUMP DISCARD
    # ========================================================

    if non_trumps:

        return best_discard(
            non_trumps,
            hand,
            trump
        )

    # ========================================================
    # PRIORITY 7:
    # ONLY TRUMPS REMAIN
    # ========================================================

    if trumps:

        # If we have an established top trump,
        # cash it.
        known_top_trumps = [
            card
            for card in trumps
            if known_top_card(
                card,
                hand
            )
        ]

        if known_top_trumps:

            return max(
                known_top_trumps,
                key=lambda card:
                    card[1]
            )

        # Otherwise preserve high trump.
        return min(
            trumps,
            key=lambda card:
                card[1]
        )

    return legal[0]