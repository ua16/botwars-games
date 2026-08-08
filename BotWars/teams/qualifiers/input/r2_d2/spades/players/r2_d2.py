#R2_D2 Spades Player 

import random

SUITS = ("H", "D", "C", "S")
SPADES = "S"

_DECK = [(s, r) for s in SUITS for r in range(2, 15)
         if not (s in ("C", "D") and r == 2)]
_DECK_SET = set(_DECK)


# ---------------------------------------------------------------------------
# Per-round state
# ---------------------------------------------------------------------------
_state = {"round_id": None, "seen": set(), "voids": set()}


def _round_id(g):
    return (g.round_number, g.dealer)


def _sync(g):
    rid = _round_id(g)
    if _state["round_id"] != rid:
        _state["round_id"] = rid
        _state["seen"] = set(g.your_hand)
        _state["voids"] = set()

    _state["seen"].update(g.your_hand)
    for _, c in g.current_trick:
        _state["seen"].add(c)

    if g.phase == "play":
        for trick in g.trick_history:
            plays = trick["plays"]
            for _, c in plays:
                _state["seen"].add(c)
            if len(plays) == 2:
                (_, lc), (fn, fc) = plays
                if fn == g.opponent_name and fc[0] != lc[0]:
                    _state["voids"].add(lc[0])


def nextMove(gameState):
    _sync(gameState)
    if gameState.phase == "bid":
        return _choose_bid(gameState)
    return _choose_play(gameState)


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------
def _is_spade(c):
    return c[0] == SPADES


def _suit_count(hand, s):
    return sum(1 for c in hand if c[0] == s)


def _card_beats(a, b, lead_suit):
    if a[0] == SPADES and b[0] == SPADES:
        return a[1] > b[1]
    if a[0] == SPADES:
        return True
    if b[0] == SPADES:
        return False
    if a[0] != lead_suit:
        return False
    if b[0] != lead_suit:
        return True
    return a[1] > b[1]


def _legal_moves(g):
    hand = list(g.your_hand)
    if not hand:
        return []
    if not g.current_trick:
        if g.spades_broken:
            return hand
        non_spades = [c for c in hand if not _is_spade(c)]
        return non_spades if non_spades else hand
    lead_suit = g.current_trick[0][1][0]
    same = [c for c in hand if c[0] == lead_suit]
    return same if same else hand


# ---------------------------------------------------------------------------
# BIDDING - Monte Carlo estimator
# ---------------------------------------------------------------------------
def _sim_resolve(lead, follow):
    ls, lr = lead
    fs, fr = follow
    if ls == SPADES and fs == SPADES:
        return lr > fr
    if ls == SPADES:
        return True
    if fs == SPADES:
        return False
    if fs != ls:
        return True
    return lr > fr


def _sim_legal_lead(hand, spades_broken):
    if spades_broken:
        return hand
    non_spades = [c for c in hand if c[0] != SPADES]
    return non_spades if non_spades else hand


def _sim_legal_follow(hand, lead_card):
    lead_suit = lead_card[0]
    same = [c for c in hand if c[0] == lead_suit]
    return same if same else hand


def _sim_pick_lead(hand, spades_broken):
    legal = _sim_legal_lead(hand, spades_broken)
    non_spades = [c for c in legal if c[0] != SPADES]
    if non_spades:
        aces = [c for c in non_spades if c[1] == 14]
        if aces:
            return max(aces, key=lambda c: sum(1 for x in hand if x[0] == c[0]))
        return max(non_spades, key=lambda c: c[1])
    return max(legal, key=lambda c: c[1])


def _sim_pick_follow(hand, lead_card):
    legal = _sim_legal_follow(hand, lead_card)
    winners = [c for c in legal if _sim_resolve(lead_card, c) is False]
    if winners:
        # play cheapest winner (non-spade preferred)
        return min(winners, key=lambda c: (1 if c[0] == SPADES else 0, c[1]))
    return min(legal, key=lambda c: (1 if c[0] == SPADES else 0, c[1]))


def _mc_expected_tricks(hand, n_sims=25):
    hand_set = set(hand)
    unknown = [c for c in _DECK if c not in hand_set]

    total = 0
    for _ in range(n_sims):
        random.shuffle(unknown)
        my_hand = list(hand)
        opp_hand = unknown[:13]
        spades_broken = False
        leader_is_me = random.random() < 0.5
        my_tricks = 0

        for _ in range(13):
            if leader_is_me:
                lead = _sim_pick_lead(my_hand, spades_broken)
                my_hand.remove(lead)
                follow = _sim_pick_follow(opp_hand, lead)
                opp_hand.remove(follow)
            else:
                lead = _sim_pick_lead(opp_hand, spades_broken)
                opp_hand.remove(lead)
                follow = _sim_pick_follow(my_hand, lead)
                my_hand.remove(follow)

            if lead[0] == SPADES or follow[0] == SPADES:
                spades_broken = True

            lead_wins = _sim_resolve(lead, follow)
            if leader_is_me:
                if lead_wins:
                    my_tricks += 1
                    leader_is_me = True
                else:
                    leader_is_me = False
            else:
                if not lead_wins:
                    my_tricks += 1
                    leader_is_me = True
                else:
                    leader_is_me = False

        total += my_tricks

    return total / n_sims


def _nil_risk(hand):
    """Lower = safer nil. Returns +inf if any ace held."""
    by_suit = {s: sorted([c[1] for c in hand if c[0] == s]) for s in SUITS}

    for s in SUITS:
        if 14 in by_suit[s]:
            return 100.0

    risk = 0.0
    for s in ("H", "D", "C"):
        ranks = by_suit[s]
        for r in ranks:
            if r == 13:
                covers = sum(1 for x in ranks if x < r)
                if covers == 0:
                    risk += 6.0
                elif covers == 1:
                    risk += 2.5
                elif covers == 2:
                    risk += 0.7
                else:
                    risk += 0.15
            elif r == 12:
                covers = sum(1 for x in ranks if x < r)
                if covers == 0:
                    risk += 3.0
                elif covers == 1:
                    risk += 1.0
                else:
                    risk += 0.15
            elif r == 11:
                covers = sum(1 for x in ranks if x < r)
                if covers == 0:
                    risk += 1.3
                elif covers == 1:
                    risk += 0.35

    for r in by_suit[SPADES]:
        if r == 13:
            risk += 4.0
        elif r == 12:
            risk += 2.5
        elif r == 11:
            risk += 1.2
        elif r >= 9:
            risk += 0.5
        elif r >= 6:
            risk += 0.2

    sp = len(by_suit[SPADES])
    if sp >= 5:
        risk += 1.8
    if sp >= 6:
        risk += 1.5

    return risk


def _choose_bid(g):
    hand = g.your_hand
    exp = _mc_expected_tricks(hand)
    nil_risk = _nil_risk(hand)

    gap = g.opponent_score - g.your_score
    trailing = gap >= 100
    leading = -gap >= 100

    if g.opponent_bid_known and g.opponent_bid == 0:
        return max(1, min(13, int(round(exp + 1))))

    nil_cap = 2.5
    if trailing:
        nil_cap = 3.8
    if leading and g.your_score >= 350:
        nil_cap = 1.5
    if g.your_bags >= 8:
        nil_cap += 0.5

    if nil_risk <= nil_cap and exp <= 3.0:
        return 0

    if g.opponent_bid_known:
        if g.opponent_bid >= 8:
            exp -= 1.0
        elif g.opponent_bid >= 6:
            exp -= 0.5

    bid = int(round(exp))

    if g.your_bags >= 8:
        bid = max(1, bid - 1)

    if leading and g.your_score >= 350:
        bid = max(1, bid - 1)
    if trailing and gap >= 150:
        bid = min(13, bid + 1)

    return max(1, min(13, bid))


# ---------------------------------------------------------------------------
# PLAY - MODE SELECTION
# ---------------------------------------------------------------------------
def _tricks_left(g):
    return 13 - len(g.trick_history)


def _our_tricks(g):
    return g.tricks_won.get(g.your_name, 0)


def _opp_tricks(g):
    return g.tricks_won.get(g.opponent_name, 0)


def _our_need(g):
    if g.your_bid == 0:
        return 0
    return max(0, g.your_bid - _our_tricks(g))


def _opp_need(g):
    if g.opponent_bid == 0:
        return 0
    return max(0, g.opponent_bid - _opp_tricks(g))


def _determine_mode(g):
    left = _tricks_left(g)
    theirs = _opp_tricks(g)

    if g.your_bid == 0:
        return "NIL"

    our_need = _our_need(g)

    if our_need == 0:
        if g.opponent_bid == 0 and theirs == 0:
            return "BREAK_NIL"
        return "AVOID_BAGS"

    if our_need > left:
        if g.opponent_bid == 0 and theirs == 0:
            return "BREAK_NIL"
        opp_need = _opp_need(g)
        if g.opponent_bid > 0 and opp_need == 0:
            return "BAG_OPP"
        if opp_need > 0 and opp_need <= left:
            return "DENY"
        return "SURVIVE"

    if g.opponent_bid == 0 and theirs == 0:
        return "BREAK_NIL"
    return "MAKE_BID"


def _choose_play(g):
    legal = _legal_moves(g)
    if not legal:
        return g.your_hand[0]

    mode = _determine_mode(g)

    if mode == "NIL":
        chosen = _play_nil(g, legal)
    elif mode == "MAKE_BID":
        chosen = _play_make_bid(g, legal)
    elif mode == "BREAK_NIL":
        chosen = _play_break_nil(g, legal)
    elif mode == "DENY":
        chosen = _play_deny(g, legal)
    elif mode == "BAG_OPP":
        chosen = _play_bag_opp(g, legal)
    elif mode == "AVOID_BAGS":
        chosen = _play_avoid_bags(g, legal)
    else:
        chosen = _play_survive(g, legal)

    return _endgame_override(g, legal, chosen, mode)


# ---------------------------------------------------------------------------
# PLAY MODES
# ---------------------------------------------------------------------------
def _play_nil(g, legal):
    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        losers = [c for c in legal if not _card_beats(c, opp_card, lead_suit)]
        if losers:
            # dump biggest loser (shed danger)
            return max(losers, key=lambda c: (0 if _is_spade(c) else 1, c[1]))
        # forced to win, use lowest winner
        return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    non_spades = [c for c in legal if not _is_spade(c)]
    if non_spades:
        return min(non_spades,
                   key=lambda c: (c[1], _suit_count(g.your_hand, c[0])))
    return min(legal, key=lambda c: c[1])


def _play_make_bid(g, legal):
    need = _our_need(g)

    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        winners = [c for c in legal if _card_beats(c, opp_card, lead_suit)]
        losers = [c for c in legal if not _card_beats(c, opp_card, lead_suit)]

        if need > 0:
            if winners:
                return min(winners,
                           key=lambda c: (1 if _is_spade(c) else 0, c[1]))
            if losers:
                return min(losers,
                           key=lambda c: (1 if _is_spade(c) else 0, c[1]))
            return legal[0]

        if losers:
            return max(losers,
                       key=lambda c: (0 if _is_spade(c) else 1, c[1]))
        return min(winners, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    if need > 0:
        return _lead_for_win(g, legal)
    return _lead_low(g, legal, prefer_voids=_opp_need(g) > 0)


def _play_break_nil(g, legal):
    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        losers = [c for c in legal if not _card_beats(c, opp_card, lead_suit)]
        if losers:
            return max(losers, key=lambda c: (0 if _is_spade(c) else 1, c[1]))
        return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    non_spades = [c for c in legal if not _is_spade(c)]
    voids = _state["voids"]
    candidates = [c for c in non_spades if c[0] not in voids] or non_spades

    if candidates:
        for target_rank in (12, 13, 11, 14, 10):
            matched = [c for c in candidates if c[1] == target_rank]
            if matched:
                return max(matched,
                           key=lambda c: _suit_count(g.your_hand, c[0]))
        return max(candidates, key=lambda c: c[1])

    return max(legal, key=lambda c: c[1])


def _play_deny(g, legal):
    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        winners = [c for c in legal if _card_beats(c, opp_card, lead_suit)]
        if winners:
            return min(winners, key=lambda c: (1 if _is_spade(c) else 0, c[1]))
        return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    return _lead_for_win(g, legal)


def _play_bag_opp(g, legal):
    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        losers = [c for c in legal if not _card_beats(c, opp_card, lead_suit)]
        if losers:
            return max(losers, key=lambda c: (0 if _is_spade(c) else 1, c[1]))
        return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    # opp already made bid; opp will duck. Avoid opp's voids (they'd dump).
    return _lead_low(g, legal, prefer_voids=False)


def _play_avoid_bags(g, legal):
    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        losers = [c for c in legal if not _card_beats(c, opp_card, lead_suit)]
        if losers:
            return max(losers, key=lambda c: (0 if _is_spade(c) else 1, c[1]))
        return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    # If opp still needs tricks, opp will trump voids -> lead INTO voids.
    # If opp made bid, opp will dump -> avoid voids.
    return _lead_low(g, legal, prefer_voids=_opp_need(g) > 0)


def _play_survive(g, legal):
    if g.current_trick:
        opp_card = g.current_trick[0][1]
        lead_suit = opp_card[0]
        losers = [c for c in legal if not _card_beats(c, opp_card, lead_suit)]
        if losers:
            return min(losers, key=lambda c: (1 if _is_spade(c) else 0, c[1]))
        return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    return _lead_low(g, legal, prefer_voids=False)


# ---------------------------------------------------------------------------
# LEAD HELPERS
# ---------------------------------------------------------------------------
def _lead_for_win(g, legal):
    non_spades = [c for c in legal if not _is_spade(c)]

    aces = [c for c in non_spades if c[1] == 14]
    if aces:
        return max(aces, key=lambda c: _suit_count(g.your_hand, c[0]))

    master = _find_master(g, non_spades)
    if master is not None:
        return master

    spade_master = _find_master(g, [c for c in legal if _is_spade(c)])
    if spade_master is not None and g.spades_broken:
        return spade_master

    if non_spades:
        return max(non_spades,
                   key=lambda c: (c[1], _suit_count(g.your_hand, c[0])))
    return max(legal, key=lambda c: c[1])


def _lead_low(g, legal, prefer_voids):
    non_spades = [c for c in legal if not _is_spade(c)]
    voids = _state["voids"]

    if non_spades:
        if prefer_voids and voids:
            void_cards = [c for c in non_spades if c[0] in voids]
            if void_cards:
                return min(void_cards, key=lambda c: c[1])
            return min(non_spades, key=lambda c: c[1])
        if not prefer_voids and voids:
            safe = [c for c in non_spades if c[0] not in voids]
            if safe:
                return min(safe, key=lambda c: c[1])
        return min(non_spades, key=lambda c: c[1])

    return min(legal, key=lambda c: c[1])


def _find_master(g, cards):
    if not cards:
        return None
    seen = _state["seen"]
    hand_set = set(g.your_hand)
    best = None
    best_key = None
    for c in cards:
        s, r = c
        if r < 12:
            continue
        outstanding = False
        for x in range(r + 1, 15):
            other = (s, x)
            if other not in _DECK_SET:
                continue
            if other not in seen and other not in hand_set:
                outstanding = True
                break
        if not outstanding:
            key = (_suit_count(g.your_hand, s), r)
            if best_key is None or key > best_key:
                best_key = key
                best = c
    return best


# ---------------------------------------------------------------------------
# ENDGAME OVERRIDE
# ---------------------------------------------------------------------------
def _endgame_override(g, legal, chosen, mode):
    left = _tricks_left(g)
    if left <= 0:
        return chosen

    if g.your_bid > 0:
        need = _our_need(g)
        if 0 < need >= left:
            if g.current_trick:
                opp_card = g.current_trick[0][1]
                lead_suit = opp_card[0]
                winners = [c for c in legal
                           if _card_beats(c, opp_card, lead_suit)]
                if winners:
                    return min(winners,
                               key=lambda c: (1 if _is_spade(c) else 0, c[1]))
            return max(legal,
                       key=lambda c: (0 if _is_spade(c) else 1, c[1]))

    if mode not in ("BAG_OPP", "AVOID_BAGS") and g.opponent_bid > 0:
        opp_need = _opp_need(g)
        if 0 < opp_need >= left:
            if g.current_trick:
                opp_card = g.current_trick[0][1]
                lead_suit = opp_card[0]
                winners = [c for c in legal
                           if _card_beats(c, opp_card, lead_suit)]
                if winners:
                    return min(winners,
                               key=lambda c: (1 if _is_spade(c) else 0, c[1]))
            return max(legal,
                       key=lambda c: (0 if _is_spade(c) else 1, c[1]))

    if mode == "BAG_OPP":
        return chosen

    if g.your_bags >= 9 and g.your_bid > 0:
        need = _our_need(g)
        if need <= 0:
            if g.current_trick:
                opp_card = g.current_trick[0][1]
                lead_suit = opp_card[0]
                losers = [c for c in legal
                          if not _card_beats(c, opp_card, lead_suit)]
                if losers:
                    return min(losers,
                               key=lambda c: (1 if _is_spade(c) else 0, c[1]))
            return min(legal, key=lambda c: (1 if _is_spade(c) else 0, c[1]))

    return chosen
