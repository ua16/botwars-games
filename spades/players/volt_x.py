# BotWars 2026 Spades bot

from math import comb

SPADES = "S"
SUITS = ("H", "D", "C", "S")


def nextMove(gameState):
    if gameState.phase == "bid":
        return _choose_bid(gameState)
    return _choose_card(gameState)


def _choose_bid(gameState):
    hand = list(gameState.your_hand)

    suit_cards = {s: sorted([r for s2, r in hand if s2 == s], reverse=True)
                  for s in SUITS}

    spades = suit_cards["S"]
    spade_count = len(spades)

    score = 0.0

    for suit in ("H", "D", "C"):
        cards = suit_cards[suit]
        if not cards:
            continue

        for i, rank in enumerate(cards):
            if rank == 14:
                score += 0.92
            elif rank == 13:
                score += 0.70 if len(cards) >= 2 else 0.56
            elif rank == 12:
                score += 0.47 if len(cards) >= 3 else 0.31
            elif rank == 11:
                score += 0.27 if len(cards) >= 4 else 0.14
            elif rank == 10:
                score += 0.12

        if len(cards) == 1 and spade_count >= 2:
            score += 0.30
        elif len(cards) == 2 and spade_count >= 3:
            score += 0.18

    for rank in spades:
        if rank == 14:
            score += 1.00
        elif rank == 13:
            score += 0.88
        elif rank == 12:
            score += 0.74
        elif rank == 11:
            score += 0.60
        elif rank == 10:
            score += 0.47
        elif rank == 9:
            score += 0.36
        elif rank == 8:
            score += 0.26
        else:
            score += 0.12

    if spade_count >= 5:
        score += 0.35
    if spade_count >= 6:
        score += 0.35

    voids = sum(1 for s in ("H", "D", "C") if len(suit_cards[s]) == 0)
    singletons = sum(1 for s in ("H", "D", "C") if len(suit_cards[s]) == 1)

    score += 0.30 * voids * min(spade_count, 3)
    score += 0.10 * singletons * min(spade_count, 3)

    nil_risk = _nil_risk(hand)
    if nil_risk <= 0.0:
        if gameState.your_score <= gameState.opponent_score + 140:
            return 0

    bid = int(score + 2.35)

    if bid < 1:
        bid = 1
    if bid > 10:
        bid = 10

    if gameState.opponent_bid_known and gameState.opponent_bid is not None:
        opp_bid = gameState.opponent_bid

        if opp_bid == 0:
            bid = max(1, bid)

        if opp_bid >= 7 and bid >= 6:
            bid -= 1

    if gameState.your_bags >= 8 and bid > 1:
        bid += 1

    return max(0, min(13, bid))


def _nil_risk(hand):
    risk = 0.0
    spades = []

    for suit, rank in hand:
        if suit == SPADES:
            spades.append(rank)

        if rank == 14:
            risk += 2.4
        elif rank == 13:
            risk += 1.55
        elif rank == 12:
            risk += 0.95
        elif rank == 11:
            risk += 0.52
        elif rank == 10:
            risk += 0.22

    for rank in spades:
        if rank >= 12:
            risk += 1.5
        elif rank >= 10:
            risk += 0.8
        elif rank >= 8:
            risk += 0.38
        else:
            risk += 0.10

    if len(spades) >= 3:
        risk += 0.65
    if len(spades) >= 4:
        risk += 1.00

    return risk


def _choose_card(gameState):
    hand = list(gameState.your_hand)
    legal = _legal_cards(gameState)

    my_name = gameState.your_name
    opp_name = gameState.opponent_name

    my_bid = gameState.your_bid
    opp_bid = gameState.opponent_bid

    my_tricks = gameState.tricks_won.get(my_name, 0)
    opp_tricks = gameState.tricks_won.get(opp_name, 0)

    remaining = len(hand)

    my_nil_active = (my_bid == 0 and my_tricks == 0)
    my_nil_failed = (my_bid == 0 and my_tricks > 0)
    opp_nil_active = (opp_bid == 0 and opp_tricks == 0)

    if gameState.current_trick:
        lead_card = gameState.current_trick[0][1]

        if my_nil_active:
            return _follow_avoid(legal, lead_card)

        my_need = max(0, my_bid - my_tricks) if my_bid > 0 else 0
        opp_need = max(0, opp_bid - opp_tricks) if opp_bid > 0 else 0

        should_win = _should_try_to_win(
            gameState,
            my_need,
            opp_need,
            remaining,
            opp_nil_active,
            my_nil_failed
        )

        if should_win:
            winners = [c for c in legal if _card_beats(c, lead_card)]
            if winners:
                return min(winners, key=_winning_cost)

            return _best_discard(gameState, legal, aggressive=True)

        losers = [c for c in legal if not _card_beats(c, lead_card)]
        if losers:
            return max(losers, key=_dump_value)

        return min(legal, key=_winning_cost)

    if my_nil_active:
        return _nil_lead(gameState, legal)

    my_need = max(0, my_bid - my_tricks) if my_bid > 0 else 0
    opp_need = max(0, opp_bid - opp_tricks) if opp_bid > 0 else 0

    if opp_nil_active:
        forced = _lead_to_attack_nil(gameState, legal)
        if forced is not None:
            return forced

    should_win = _should_try_to_win(
        gameState,
        my_need,
        opp_need,
        remaining,
        opp_nil_active,
        my_nil_failed
    )

    if should_win:
        return max(
            legal,
            key=lambda c: _lead_attack_score(gameState, c, remaining)
        )

    return min(
        legal,
        key=lambda c: _safe_lead_score(gameState, c, remaining)
    )

def _legal_cards(gameState):
    hand = list(gameState.your_hand)

    if gameState.current_trick:
        lead_suit = gameState.current_trick[0][1][0]
        same = [c for c in hand if c[0] == lead_suit]
        if same:
            return same
        return hand

    if gameState.spades_broken:
        return hand

    non_spades = [c for c in hand if c[0] != SPADES]
    return non_spades if non_spades else hand


def _should_try_to_win(gameState, my_need, opp_need, remaining,
                       opp_nil_active, my_nil_failed=False):
    if my_nil_failed:
        return True

    if gameState.your_bid == 0:
        return False

    if my_need >= remaining:
        return True

    if my_need > 0:
        pressure = my_need / max(1, remaining)

        if pressure >= 0.34:
            return True

        if gameState.your_score >= 430:
            return True

    if opp_nil_active:
        return my_need > 0

    remaining_after = remaining - 1

    if gameState.opponent_bid and gameState.opponent_bid > 0:
        if opp_need > remaining_after:
            return True

        if my_need == 0 and opp_need > 0:
            opp_pressure = opp_need / max(1, remaining)

            threshold = 0.0

            if gameState.opponent_score >= 400:
                threshold -= 0.15

            if gameState.opponent_score > gameState.your_score + 120:
                threshold -= 0.08

            if gameState.your_bags >= 8:
                threshold += 0.15
            elif gameState.your_bags >= 6:
                threshold += 0.07

            if gameState.your_score >= 470:
                threshold += 0.12

            if opp_pressure >= threshold:
                return True

    if my_need == 0:
        return False

    return True

def _follow_avoid(legal, lead_card):
    losers = [c for c in legal if not _card_beats(c, lead_card)]
    if losers:
        return max(losers, key=_dump_value)
    return min(legal, key=_winning_cost)


def _nil_lead(gameState, legal):
    return min(
        legal,
        key=lambda c: _nil_lead_danger(gameState, c, len(gameState.your_hand))
    )


def _lead_to_attack_nil(gameState, legal):
    non_spades = [c for c in legal if c[0] != SPADES]
    pool = non_spades if non_spades else legal

    candidates = []
    for card in pool:
        p_win = _lead_win_probability(gameState, card, len(gameState.your_hand))
        force_loss_score = 1.0 - p_win
        if card[1] <= 9:
            force_loss_score += 0.12
        candidates.append((force_loss_score, card))

    if not candidates:
        return None

    return max(candidates, key=lambda x: (x[0], -x[1][1]))[1]


def _lead_attack_score(gameState, card, hand_size):
    p = _lead_win_probability(gameState, card, hand_size)

    suit = card[0]
    rank = card[1]

    bonus = 0.0

    if suit == SPADES:
        bonus += 0.08

    if rank >= 12:
        bonus += 0.05

    if _opponent_void_in(gameState, suit) and suit != SPADES:
        bonus -= 0.45

    return p + bonus


def _safe_lead_score(gameState, card, hand_size):
    p = _lead_win_probability(gameState, card, hand_size)

    danger = p

    if card[0] == SPADES:
        danger += 0.18

    if card[1] >= 12:
        danger += 0.12
    elif card[1] >= 10:
        danger += 0.05

    return danger


def _nil_lead_danger(gameState, card, hand_size):
    p = _lead_win_probability(gameState, card, hand_size)

    danger = p

    if card[0] == SPADES:
        danger += 0.35

    if card[1] >= 11:
        danger += 0.25

    return danger


def _lead_win_probability(gameState, card, opp_hand_size):
    unseen = _unseen_cards(gameState)

    # Once the opponent has failed to follow a suit, every remaining unseen
    # card of that suit is known to be in the kitty, not in their hand.
    void_suits = _opponent_void_suits(gameState)
    pool = [c for c in unseen if c[0] not in void_suits]

    N = len(pool)
    n = min(opp_hand_size, N)

    if N <= 0 or n <= 0:
        return 1.0

    suit, rank = card

    if suit in void_suits:
        if suit == SPADES:
            return 1.0
        spades = [c for c in pool if c[0] == SPADES]
        return _prob_no_category(N, len(spades), n)

    if suit == SPADES:
        higher = [c for c in pool if c[0] == SPADES and c[1] > rank]
        return _prob_no_category(N, len(higher), n)

    suit_cards = [c for c in pool if c[0] == suit]
    higher_same = [c for c in suit_cards if c[1] > rank]
    spades = [c for c in pool if c[0] == SPADES]

    lower_same = [c for c in suit_cards if c[1] < rank]

    p_has_lower_no_higher = _prob_at_least_one_from_group_while_avoiding(
        N, n, len(higher_same), len(lower_same)
    )

    forbidden_if_void = len(suit_cards) + len(spades)
    p_void_and_no_spade = _prob_no_category(N, forbidden_if_void, n)

    p = p_has_lower_no_higher + p_void_and_no_spade
    return max(0.0, min(1.0, p))

def _prob_no_category(N, bad_count, n):
    if bad_count <= 0:
        return 1.0
    if N - bad_count < n:
        return 0.0
    return comb(N - bad_count, n) / comb(N, n)


def _prob_at_least_one_from_group_while_avoiding(N, n, avoid_count, wanted_count):
    available_without_avoid = N - avoid_count

    if available_without_avoid < n:
        return 0.0

    total = comb(N, n)
    no_avoid = comb(available_without_avoid, n)

    without_avoid_or_wanted = N - avoid_count - wanted_count

    if without_avoid_or_wanted >= n:
        none_wanted = comb(without_avoid_or_wanted, n)
    else:
        none_wanted = 0

    return (no_avoid - none_wanted) / total


def _unseen_cards(gameState):
    deck = [
        (s, r)
        for s in SUITS
        for r in range(2, 15)
        if not (s in ("C", "D") and r == 2)
    ]

    seen = set(gameState.your_hand)

    for trick in gameState.trick_history:
        for _, card in trick["plays"]:
            seen.add(card)

    for _, card in gameState.current_trick:
        seen.add(card)

    return [c for c in deck if c not in seen]


def _opponent_void_suits(gameState):
    opp = gameState.opponent_name
    voids = set()

    for trick in gameState.trick_history:
        plays = trick["plays"]
        if len(plays) < 2:
            continue

        lead_card = plays[0][1]
        follow_name, follow_card = plays[1]

        if follow_name == opp and follow_card[0] != lead_card[0]:
            voids.add(lead_card[0])

    return voids


def _opponent_void_in(gameState, suit):
    opp = gameState.opponent_name

    for trick in gameState.trick_history:
        plays = trick["plays"]
        if len(plays) < 2:
            continue

        lead_card = plays[0][1]
        follow_name, follow_card = plays[1]

        if follow_name == opp:
            if lead_card[0] == suit and follow_card[0] != suit:
                return True

    return False


def _card_beats(card, lead_card):
    suit, rank = card
    lead_suit, lead_rank = lead_card

    if suit == SPADES and lead_suit != SPADES:
        return True

    if suit == lead_suit:
        return rank > lead_rank

    return False


def _winning_cost(card):
    suit, rank = card
    trump_cost = 20 if suit == SPADES else 0
    return trump_cost + rank


def _dump_value(card):
    suit, rank = card
    trump_penalty = -6 if suit == SPADES else 0
    return rank + trump_penalty


def _best_discard(gameState, legal, aggressive=False):
    non_spades = [c for c in legal if c[0] != SPADES]

    if non_spades:
        if aggressive:
            return min(non_spades, key=lambda c: c[1])
        return max(non_spades, key=lambda c: c[1])

    return min(legal, key=lambda c: c[1])