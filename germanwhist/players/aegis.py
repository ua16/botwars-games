# ============================================================
# BotWars 2026 – AEGIS German Whist Bot
# ============================================================

SUITS = ("H", "D", "C", "S")
RANKS = tuple(range(2, 15))
ALL_CARDS = frozenset((s, r) for s in SUITS for r in RANKS)


# The tournament engine imports this module once and calls nextMove repeatedly.
# This state is reset at the beginning of every new game.
_ps = {
    "my_played": set(),
    "opp_seen": set(),
    "initialized": False,
    "my_name": None,
    "opp_name": None,
    "prev_stock": None,
}


def _is_new_game(gs):
    """Detect a fresh game without resetting during an existing game."""
    if not _ps["initialized"]:
        return True

    if gs.your_name != _ps["my_name"] or gs.opponent_name != _ps["opp_name"]:
        return True

    prev_stock = _ps["prev_stock"]
    return (
        prev_stock is not None
        and prev_stock < 25
        and gs.phase == 1
        and gs.stock_remaining == 25
        and len(gs.your_hand) == 13
    )


def _reset(gs):
    _ps["my_played"] = set()
    _ps["opp_seen"] = set()
    _ps["initialized"] = True
    _ps["my_name"] = gs.your_name
    _ps["opp_name"] = gs.opponent_name
    _ps["prev_stock"] = None


def _observe(gs):
    """Record opponent cards that are publicly visible in current_trick."""
    for player, card in gs.current_trick:
        if player == gs.opponent_name:
            _ps["opp_seen"].add(card)


def _record_move(card):
    _ps["my_played"].add(card)


def _unknown_pool(gs):
    """Cards not currently known to be elsewhere from our legal view."""
    known = set(gs.your_hand) | _ps["my_played"] | _ps["opp_seen"]

    # The current face-up recruitment reward is public and is not in the
    # opponent's present hand, so it must not be treated as an unknown card.
    if gs.face_up_card is not None:
        known.add(gs.face_up_card)

    return ALL_CARDS - known


def _opp_size(gs):
    """Opponent cards remaining before our move."""
    # When following, the opponent has already placed one card in the trick.
    return max(0, len(gs.your_hand) - (1 if gs.current_trick else 0))


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------
def _card_val(card, trump):
    """Heuristic value of preserving a card."""
    suit, rank = card
    return (100 + rank) if suit == trump else rank


def _lead_wins_trick(lead, follow, trump):
    """Return True when the leading card wins the trick."""
    lead_suit, lead_rank = lead
    follow_suit, follow_rank = follow

    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    if follow_suit == trump:
        return False
    return True


def _legal_follows(hand, lead_card):
    lead_suit = lead_card[0]
    same_suit = [card for card in hand if card[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def _get_legal(gs):
    if not gs.current_trick:
        return list(gs.your_hand)
    return _legal_follows(gs.your_hand, gs.current_trick[0][1])


def _is_guaranteed_winner(card, gs):
    """True when no still-possible opponent card can beat this lead."""
    trump = gs.trump_suit
    suit, rank = card

    for unknown_card in _unknown_pool(gs):
        unknown_suit, unknown_rank = unknown_card
        if unknown_suit == suit and unknown_rank > rank:
            return False
        if unknown_suit == trump and suit != trump:
            return False

    return True


# ---------------------------------------------------------------------------
# Phase 1 – original proven recruitment strategy
# ---------------------------------------------------------------------------
def _strongly_want_face_up(face_up, trump):
    if face_up is None:
        return False
    suit, rank = face_up
    return (suit == trump and rank >= 12) or (suit != trump and rank >= 13)


def _phase1_move(gs):
    legal = _get_legal(gs)
    trump = gs.trump_suit
    face_up = gs.face_up_card

    # Use the tuned recruitment thresholds. Normally contest non-trumps
    # from Jack upward; on the final recruitment trick, contest 9 upward.
    threshold = 9 if gs.stock_remaining == 1 else 11
    want = face_up is not None and (
        face_up[0] == trump or face_up[1] >= threshold
    )
    strong = _strongly_want_face_up(face_up, trump)

    if gs.lead == gs.your_name:
        return _lead_p1(legal, trump, want, strong, gs)

    return _follow_p1(legal, gs.current_trick[0][1], trump, want)


def _lead_p1(legal, trump, want, strong, gs):
    if not want:
        non_trumps = [card for card in legal if card[0] != trump]
        if non_trumps:
            return min(non_trumps, key=lambda card: card[1])
        return min(legal, key=lambda card: card[1])

    guaranteed = [card for card in legal if _is_guaranteed_winner(card, gs)]
    if guaranteed:
        return min(guaranteed, key=lambda card: _card_val(card, trump))

    if strong:
        return max(legal, key=lambda card: _card_val(card, trump))

    non_trumps = [card for card in legal if card[0] != trump]
    if non_trumps:
        return max(non_trumps, key=lambda card: card[1])

    return min(legal, key=lambda card: _card_val(card, trump))


def _follow_p1(legal, lead_card, trump, want):
    if want:
        winning = [
            card
            for card in legal
            if not _lead_wins_trick(lead_card, card, trump)
        ]
        if winning:
            return min(winning, key=lambda card: _card_val(card, trump))
        return min(legal, key=lambda card: _card_val(card, trump))

    non_trumps = [card for card in legal if card[0] != trump]
    if non_trumps:
        return min(non_trumps, key=lambda card: card[1])
    return min(legal, key=lambda card: card[1])


# ---------------------------------------------------------------------------
# Phase 2 – original proven scoring strategy
# ---------------------------------------------------------------------------
def _phase2_move(gs):
    legal = _get_legal(gs)
    trump = gs.trump_suit
    unknown = _unknown_pool(gs)
    opponent_size = _opp_size(gs)

    # Exact minimax is used only if public information fully determines the
    # opponent's remaining hand. No guessed or sampled private hand is used.
    if len(unknown) == opponent_size and 0 < opponent_size <= 8:
        opponent_hand = frozenset(unknown)
        memo = {}

        if gs.lead == gs.your_name:
            best = _minimax_best_lead(
                frozenset(gs.your_hand),
                opponent_hand,
                trump,
                memo,
                legal,
            )
        else:
            best = _minimax_best_follow(
                frozenset(gs.your_hand),
                opponent_hand,
                gs.current_trick[0][1],
                trump,
                memo,
                legal,
            )

        if best is not None and best in legal:
            return best

    if gs.lead == gs.your_name:
        return _lead_p2(legal, trump, gs)

    return _follow_p2(legal, gs.current_trick[0][1], trump)


def _lead_p2(legal, trump, gs):
    guaranteed = sorted(
        [card for card in legal if _is_guaranteed_winner(card, gs)],
        key=lambda card: _card_val(card, trump),
    )
    if guaranteed:
        return guaranteed[0]

    non_trumps = [card for card in legal if card[0] != trump]
    if non_trumps:
        by_suit = {}
        for card in non_trumps:
            by_suit.setdefault(card[0], []).append(card)
        longest = max(
            by_suit.values(),
            key=lambda cards: (len(cards), max(c[1] for c in cards)),
        )
        return max(longest, key=lambda card: card[1])

    return min(legal, key=lambda card: card[1])


def _follow_p2(legal, lead_card, trump):
    winning = [
        card
        for card in legal
        if not _lead_wins_trick(lead_card, card, trump)
    ]
    if winning:
        return min(winning, key=lambda card: _card_val(card, trump))
    return min(legal, key=lambda card: _card_val(card, trump))


# ---------------------------------------------------------------------------
# Exact endgame minimax
# ---------------------------------------------------------------------------
def _minimax(my_hand, opponent_hand, i_lead, trump, memo):
    key = (my_hand, opponent_hand, i_lead)
    if key in memo:
        return memo[key]

    if not my_hand:
        memo[key] = 0
        return 0

    if i_lead:
        best = -1
        for lead in my_hand:
            opponent_follows = _legal_follows(opponent_hand, lead)
            if not opponent_follows:
                value = len(my_hand)
            else:
                worst = float("inf")
                for follow in opponent_follows:
                    i_win = _lead_wins_trick(lead, follow, trump)
                    future = _minimax(
                        my_hand - {lead},
                        opponent_hand - {follow},
                        i_win,
                        trump,
                        memo,
                    )
                    value_for_follow = (1 if i_win else 0) + future
                    if value_for_follow < worst:
                        worst = value_for_follow
                value = worst

            if value > best:
                best = value

        result = best
    else:
        worst_for_me = float("inf")
        for lead in opponent_hand:
            my_follows = _legal_follows(my_hand, lead)
            if not my_follows:
                best_response = 0
            else:
                best_response = -float("inf")
                for follow in my_follows:
                    i_win = not _lead_wins_trick(lead, follow, trump)
                    future = _minimax(
                        my_hand - {follow},
                        opponent_hand - {lead},
                        i_win,
                        trump,
                        memo,
                    )
                    value = (1 if i_win else 0) + future
                    if value > best_response:
                        best_response = value

            if best_response < worst_for_me:
                worst_for_me = best_response

        result = worst_for_me

    memo[key] = result
    return result


def _minimax_best_lead(my_hand, opponent_hand, trump, memo, legal):
    best_value = -1
    best_card = None

    for card in legal:
        opponent_follows = _legal_follows(opponent_hand, card)
        if not opponent_follows:
            value = len(my_hand)
        else:
            worst = float("inf")
            for follow in opponent_follows:
                i_win = _lead_wins_trick(card, follow, trump)
                future = _minimax(
                    my_hand - {card},
                    opponent_hand - {follow},
                    i_win,
                    trump,
                    memo,
                )
                value_for_follow = (1 if i_win else 0) + future
                if value_for_follow < worst:
                    worst = value_for_follow
            value = worst

        if value > best_value:
            best_value = value
            best_card = card

    return best_card


def _minimax_best_follow(
    my_hand,
    opponent_hand_after_lead,
    lead_card,
    trump,
    memo,
    legal,
):
    """Choose our response when the opponent's lead is already on the table."""
    best_value = -1
    best_card = None

    for card in legal:
        i_win = not _lead_wins_trick(lead_card, card, trump)

        # opponent_hand_after_lead already excludes the visible lead card.
        future = _minimax(
            my_hand - {card},
            opponent_hand_after_lead,
            i_win,
            trump,
            memo,
        )
        value = (1 if i_win else 0) + future

        if value > best_value:
            best_value = value
            best_card = card

    return best_card


# ---------------------------------------------------------------------------
# Required entry point
# ---------------------------------------------------------------------------
def nextMove(gameState):
    try:
        legal = _get_legal(gameState)
        fallback = legal[0] if legal else gameState.your_hand[0]
    except Exception:
        # The engine should never call the bot with an empty hand, but keep a
        # final defensive fallback for compatibility.
        legal = list(gameState.your_hand)
        fallback = legal[0]

    move = fallback

    try:
        if _is_new_game(gameState):
            _reset(gameState)

        _observe(gameState)

        if gameState.phase == 1:
            candidate = _phase1_move(gameState)
        else:
            candidate = _phase2_move(gameState)

        if candidate in legal:
            move = candidate
    except Exception:
        move = fallback

    # Record the actual returned move even if an emergency fallback was used.
    _record_move(move)
    _ps["prev_stock"] = gameState.stock_remaining
    return move
