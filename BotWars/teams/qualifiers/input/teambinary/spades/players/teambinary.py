"""2-player Spades player for the BotWars final engine.

Implements the engine's ``nextMove(gameState)`` contract (``spades/`` game).
``gameState`` is a ``PlayerView`` exposing:
    your_hand:      list[(suit, rank)]  suit H/D/C/S, rank 2-14 (14=Ace)
    phase:          "bid" | "play"
    your_bid/opponent_bid, your_bags/opponent_bags, your_score/opponent_score
    spades_broken, tricks_won ({name: int}), trick_history, current_trick, lead
    dealer, turn, round_number, kitty_remaining

Returns an int bid (0-13) during ``"bid"`` and a ``(suit, rank)`` card during
``"play"``.  Pure standard library, so it drops into ``spades/players/``
unchanged.
"""

from __future__ import annotations

_SPADES = "S"

# ---------------------------------------------------------------------------
# Hand valuation (ultimate-bot ensemble adapted to (suit, rank) tuples)
# ---------------------------------------------------------------------------

_SIDE_SUITS = ("H", "D", "C")
_SUIT_CODE = {"C": 0, "D": 1, "H": 2, "S": 3}


def _suits_of(hand):
    s = [set(), set(), set(), set()]
    for c in hand:
        code = _SUIT_CODE[c[0]]
        s[code].add(c[1])
    return s


def _suit_cards(hand, suit_char):
    return [c for c in hand if c[0] == suit_char]


def estimate_tricks(hand_cards) -> float:
    tricks = 0.0
    spades = sorted(_suit_cards(hand_cards, _SPADES), key=lambda c: c[1], reverse=True)
    spade_count = len(spades)

    for i, (_s, r) in enumerate(spades):
        if r == 14:
            tricks += 1.0
        elif r == 13:
            tricks += 0.9
        elif r == 12:
            tricks += 0.7 if spade_count >= 3 else 0.4
        elif r == 11:
            tricks += 0.5 if spade_count >= 4 else 0.2
        else:
            if i >= 4 and spade_count >= 5:
                tricks += 0.4

    for suit in _SIDE_SUITS:
        cards = _suit_cards(hand_cards, suit)
        suit_count = len(cards)
        if suit_count == 0:
            if spade_count >= 4:
                tricks += 0.5
            elif spade_count >= 1:
                tricks += 0.25
            continue
        for _s, r in cards:
            if r == 14:
                tricks += 0.95
            elif r == 13:
                tricks += 0.7 if suit_count >= 2 else 0.3
            elif r == 12:
                tricks += 0.4 if suit_count >= 3 else 0.1
        if suit_count == 1 and spade_count >= 2:
            tricks += 0.3
    return tricks


def point_count(hand_cards) -> float:
    by_suit = _suits_of(hand_cards)
    points = 0.0
    for suit in range(4):
        vals = sorted(by_suit[suit])
        n = len(vals)
        if n == 0:
            continue
        if vals[-1] == 14:
            points += 1.0
        if n >= 2 and vals[-2] == 13:
            points += 1.0
        if suit == 3 and 12 in vals:
            if n > 2:
                points += 1.0
            elif n == 2 and vals[-1] == 14:
                points += 1.0
    spades = len(by_suit[3])
    if spades < 2:
        points -= 1.0
    elif spades > 3:
        points += spades - 3
    if spades == 3:
        side_len = [len(by_suit[0]), len(by_suit[1]), len(by_suit[2])]
        if 0 in side_len or 1 in side_len:
            points += 1.0
    return max(0.0, points)


_HS_W = (
    0.701044, 0.007511, 0.881980, -1.999145, -1.273403, -0.883269, 0.558984,
    0.429923, 0.266541, 0.370726, 0.488241, 0.220489, 1.476624,
    2.203615, 1.432062, 0.920113, 0.806798, 0.785587, 0.753077, -0.033648,
    1.882863, 1.416562, 1.157554, 0.515139, 0.888351, 0.441180, 0.298371,
    1.877064, 1.811177, 1.169807, 0.934469, 0.978589, 0.675725, 0.260065,
    1.793521, 1.739455, 1.214013, 0.806248, 0.831830, 0.556648, 0.019048,
    2.081140, 0.738415, 0.667451, 1.104983, 0.265381, -0.123201, -0.185711,
)


def _nil_ok_handstrength(by_suit) -> bool:
    sp = by_suit[3]
    if len(sp) > 3:
        return False
    if any(r in sp for r in (14, 13, 12)):
        return False
    if sum(1 for r in sp if r >= 9) >= 2:
        return False
    for suit in range(3):
        vals = sorted(by_suit[suit])
        d = len(vals)
        if d == 0:
            continue
        if d <= 2:
            if any(v >= 12 for v in vals):
                return False
        elif d <= 3:
            if any(v >= 13 for v in vals):
                return False
            if any(v >= 12 for v in vals):
                return False
        if sum(1 for v in vals if v >= 9) >= 2:
            return False
        if d >= 4 and (vals[0] > 5 or vals[1] > 9):
            return False
    return True


def hand_strength(hand_cards):
    """Returns (bid, raw_strength). bid 0 signals a recommended Nil."""
    by_suit = _suits_of(hand_cards)
    my_vals = sorted(by_suit[3], reverse=True)
    all_vals = set(range(2, 15))
    opp_vals = sorted(all_vals - set(my_vals), reverse=True)
    sp_tricks = 0
    oi = 0
    for mv in my_vals:
        if oi < len(opp_vals):
            if mv > opp_vals[oi]:
                sp_tricks += 1
            oi += 1
        else:
            sp_tricks += 1

    W = _HS_W
    strength = W[12]
    strength += W[0] * (sp_tricks - 0.6151)
    if sp_tricks > 5:
        strength += W[1] * (sp_tricks - 5)
    if sp_tricks > 8:
        strength += W[2] * (sp_tricks - 8)

    sp_len = len(by_suit[3])
    if sp_len == 0:
        strength += W[3]
    elif sp_len == 1:
        strength += W[4]
    elif sp_len == 2:
        strength += W[5]
    elif sp_len == 5:
        strength += W[6]
    elif sp_len == 6:
        strength += W[7]
    elif sp_len >= 7:
        strength += W[8]

    side_lengths = [len(by_suit[s]) for s in range(3)]
    shortest = min(side_lengths) if side_lengths else 0
    if shortest == 0:
        strength += W[9]
    elif shortest == 1:
        strength += W[10]
    elif shortest == 2:
        strength += W[11]

    for suit in range(3):
        cards = by_suit[suit]
        d = len(cards)
        if d == 0:
            continue
        has_A = 14 in cards
        has_K = 13 in cards
        has_Q = 12 in cards
        if has_A and has_K and has_Q:
            hon = 0
        elif has_A and has_K:
            hon = 1
        elif has_A and has_Q:
            hon = 2
        elif has_K and has_Q:
            hon = 3
        elif has_A:
            hon = 4
        elif has_K:
            hon = 5
        elif has_Q:
            hon = 6
        else:
            continue
        if d == 1:
            bucket = 0
        elif d == 2:
            bucket = 1
        elif d <= 4:
            bucket = 2
        elif d <= 7:
            bucket = 3
        else:
            bucket = 4
        strength += W[13 + bucket * 7 + hon]

    raw = strength
    if _nil_ok_handstrength(by_suit) and raw < 2.0:
        return 0, raw
    return int(max(1, min(13, round(raw)))), raw


def should_bid_nil_v2(hand_cards) -> bool:
    spades = _suit_cards(hand_cards, _SPADES)
    if any(r >= 12 for _s, r in spades):
        return False
    if any(r == 14 for _s, r in hand_cards):
        return False
    non_spade = [r for _s, r in hand_cards if _s != _SPADES]
    max_ns = max(non_spade) if non_spade else 2
    max_suit = max(len(_suit_cards(hand_cards, s)) for s in "HDCS")
    if max_ns <= 10 and max_suit <= 4:
        return True
    if all(r <= 10 for _s, r in hand_cards):
        return True
    return False


def should_bid_nil_rl(hand_cards) -> bool:
    by_suit = _suits_of(hand_cards)
    sp = sorted(by_suit[3])
    if len(sp) >= 2:
        if sp[-1] >= 13 or sp[-2] >= 13:
            return False
    elif sp:
        if sp[-1] >= 13:
            return False

    liability = []
    for suit in range(4):
        vals = sorted(by_suit[suit])
        l = 0
        for j, v in enumerate(vals):
            if j == 0 and v > 5:
                l += 1
            elif j == 1 and v > 8:
                l += 1
            elif j == 2 and v > 10:
                l += 1
        liability.append(l)

    if liability[3] > 0:
        return False
    if len(sp) >= 4:
        return False
    empty_suits = sum(1 for s in range(4) if len(by_suit[s]) == 0)
    singles = [s for s in range(4) if len(by_suit[s]) == 1 and liability[s] == 0]
    for suit in range(4):
        if liability[suit] == 0:
            continue
        n = len(by_suit[suit])
        if n > 1.5 * liability[suit]:
            overcome = empty_suits + sum(0.5 for _s in singles if _s != suit)
            liability[suit] = max(0, liability[suit] - overcome)
    return sum(liability) == 0


def nil_votes(hand_cards) -> int:
    votes = 0
    if should_bid_nil_v2(hand_cards):
        votes += 1
    if should_bid_nil_rl(hand_cards):
        votes += 1
    bid, _raw = hand_strength(hand_cards)
    if bid == 0:
        votes += 1
    return votes


def choose_bid_2p(hand_cards, your_bags: int) -> int:
    """2-player bid: Monte Carlo expectation of tricks taken, nil if the
    classifier consensus insists, with bag-pressure damping."""
    votes = nil_votes(hand_cards)
    if votes >= 2:
        return 0
    t_mc = est_tricks_heads_up(hand_cards)
    bid = int(round(t_mc))
    if bid < 1:
        bid = 1
    if bid > 13:
        bid = 13
    if your_bags >= 9:
        bid = max(1, bid - 2)
    elif your_bags >= 7:
        bid = max(1, bid - 1)
    return bid


# ---------------------------------------------------------------------------
# Heads-up trick estimator via Monte Carlo playout
# ---------------------------------------------------------------------------
def _build_mc_deck():
    return [(s, r) for s in ("H", "D", "C", "S") for r in range(2, 15)]


def _mc_legal(hand, lead_card, spades_broken):
    if lead_card is None:
        nons = [c for c in hand if c[0] != _SPADES]
        if not spades_broken and nons:
            return nons
        return list(hand)
    led = lead_card[0]
    same = [c for c in hand if c[0] == led]
    return same if same else list(hand)


def _mc_play(hand, lead_card, spades_broken):
    """Greedy take-tricks playout: follow cheaply, otherwise dump low card."""
    leg = _mc_legal(hand, lead_card, spades_broken)
    if lead_card is None:
        nons = [c for c in leg if c[0] != _SPADES]
        if nons:
            counts = {}
            for c in nons:
                counts[c[0]] = counts.get(c[0], 0) + 1
            return max(nons, key=lambda c: (c[1] == 14, counts[c[0]]))
        if leg:
            return max(leg, key=lambda c: c[1])
        return None
    led = lead_card[0]
    in_suit = [c for c in leg if c[0] == led]
    if in_suit:
        beaters = [c for c in in_suit if beats(c, lead_card, led)]
        if beaters:
            return min(beaters, key=lambda c: c[1])
        return min(in_suit, key=lambda c: c[1])
    nons = [c for c in leg if c[0] != _SPADES]
    if nons:
        return max(nons, key=lambda c: c[1])
    if leg:
        return max(leg, key=lambda c: (c[0] == _SPADES, c[1]))
    return None


def _fl_play(hand, lead_card, spades_broken):
    """First-legal-card policy (basic_player style): cheap, never hunts tricks."""
    leg = _mc_legal(hand, lead_card, spades_broken)
    if not leg:
        return None
    if lead_card is None:
        nons = [c for c in leg if c[0] != _SPADES]
        if nons:
            return nons[0]
        return leg[0]
    led = lead_card[0]
    same = [c for c in leg if c[0] == led]
    if same:
        return same[0]
    if not spades_broken:
        nons = [c for c in leg if c[0] != _SPADES]
        if nons:
            return nons[0]
    return leg[0]


def _mc_sim(me_hand, opp_hand, opp_style="greedy"):
    """Play one 13-trick deal. *me* hunts tricks, *opp* follows *opp_style*."""
    opp_policy = _mc_play if opp_style == "greedy" else _fl_play
    me = list(me_hand)
    opp = list(opp_hand)
    spades_broken = False
    my_score = 0
    leader = 0  # 0 == me
    for _ in range(13):
        if leader == 0:
            lc = _mc_play(me, None, spades_broken)
            me.remove(lc)
            fc = opp_policy(opp, lc, spades_broken)
            opp.remove(fc)
            win = (lc[0] == _SPADES) != (fc[0] == _SPADES)
            if win:
                win = lc[0] == _SPADES
            elif lc[0] == fc[0]:
                win = lc[1] > fc[1]
            else:
                win = False
        else:
            lc = opp_policy(opp, None, spades_broken)
            opp.remove(lc)
            fc = _mc_play(me, lc, spades_broken)
            me.remove(fc)
            win = (fc[0] == _SPADES) != (lc[0] == _SPADES)
            if win:
                win = fc[0] == _SPADES
            elif fc[0] == lc[0]:
                win = fc[1] > lc[1]
            else:
                win = False
        if win:
            my_score += 1
            leader = 0
        else:
            leader = 1
    return my_score


def est_tricks_heads_up(hand_cards, sims=96):
    """Average tricks taken vs random opponents that mostly play first-legal
    (bar-shaped opponents) sprinkled with a few greedy ones."""
    # try:
    import random as _rng
    # except Exception:
    #     return estimate_tricks(hand_cards)
    me = list(hand_cards)
    deck = [c for c in _build_mc_deck() if c not in me]
    total = 0
    opp = [None] * 13
    for i in range(sims):
        _rng.shuffle(deck)
        opp[:] = deck[:13]
        opp_style = "greedy" if i % 4 == 0 else "fls"
        total += _mc_sim(me, opp, opp_style)
    return total / sims


# ---------------------------------------------------------------------------
# Play helpers
# ---------------------------------------------------------------------------
def beats(challenger, current_best, led_suit) -> bool:
    """True if *challenger* beats *current_best* under Spades trump rules."""
    cs, cr = challenger
    bs, br = current_best
    if cs == _SPADES:
        if bs == _SPADES:
            return cr > br
        return True
    if bs == _SPADES:
        return False
    if cs == led_suit:
        if bs == led_suit:
            return cr > br
        return True
    return False


def _legal_moves(hand, lead_card, spades_broken):
    if lead_card is None:
        non_spades = [c for c in hand if c[0] != _SPADES]
        if not spades_broken and non_spades:
            return non_spades
        return list(hand)
    led = lead_card[0]
    same_suit = [c for c in hand if c[0] == led]
    return same_suit if same_suit else list(hand)


def _choose_follow(hand, opponent_card, want_win):
    led_suit = opponent_card[0]
    in_suit = [c for c in hand if c[0] == led_suit]
    if in_suit:
        if want_win:
            beaters = [c for c in in_suit if beats(c, opponent_card, led_suit)]
            if beaters:
                return min(beaters, key=lambda c: c[1])
        return min(in_suit, key=lambda c: c[1])

    nonspades = sorted((c for c in hand if c[0] != _SPADES), key=lambda c: c[1])
    spades = sorted((c for c in hand if c[0] == _SPADES), key=lambda c: c[1])
    if want_win:
        beaters = [c for c in spades if beats(c, opponent_card, led_suit)]
        if beaters:
            return min(beaters, key=lambda c: c[1])
    if nonspades:
        return max(nonspades, key=lambda c: c[1])
    if spades:
        return min(spades, key=lambda c: c[1])
    return min(hand, key=lambda c: c[1])


def _choose_lead(hand, want_win, spades_broken):
    nons = [c for c in hand if c[0] != _SPADES]
    spades = [c for c in hand if c[0] == _SPADES]
    if want_win:
        aces = [c for c in nons if c[1] == 14]
        if aces:
            counts = {}
            for c in hand:
                counts[c[0]] = counts.get(c[0], 0) + 1
            return min(aces, key=lambda c: counts[c[0]])
        if spades_broken and spades:
            return max(spades, key=lambda c: c[1])
        if nons:
            counts = {}
            for c in nons:
                counts[c[0]] = counts.get(c[0], 0) + 1
            longest = max(counts, key=lambda s: counts[s])
            suit_cards = [c for c in nons if c[0] == longest]
            return max(suit_cards, key=lambda c: c[1])
        return max(hand, key=lambda c: c[1])
    if nons:
        return min(nons, key=lambda c: c[1])
    return min(spades, key=lambda c: c[1])


# ---------------------------------------------------------------------------
# Engine entry point
# ---------------------------------------------------------------------------
def nextMove(gs):
    """Standard tournament interface: return a bid or a (suit, rank) card."""
    # try:
    phase = getattr(gs, "phase", None)
    hand = list(getattr(gs, "your_hand", None) or [])
    if not hand:
        return 0 if phase == "bid" else None
    if phase == "bid":
        your_bags = int(getattr(gs, "your_bags", 0) or 0)
        return choose_bid_2p(hand, your_bags)
    if phase == "play":
        return _play_choice(gs, hand)
    # except Exception:
    #     return _fallback(gs)
    return _fallback(gs)


def bid(gameState) -> int:
    hand = list(getattr(gameState, "your_hand", None) or [])
    your_bags = int(getattr(gameState, "your_bags", 0) or 0)
    return choose_bid_2p(hand, your_bags)


def play(gameState):
    hand = list(getattr(gameState, "your_hand", None) or [])
    return _play_choice(gameState, hand)


def _play_choice(gs, hand):
    if not hand:
        return None
    my_name = getattr(gs, "your_name", None)
    current = list(getattr(gs, "current_trick", None) or [])
    spades_broken = bool(getattr(gs, "spades_broken", False))
    my_bid = getattr(gs, "your_bid", None)
    if my_bid is None:
        my_bid = 0
        for t in getattr(gs, "trick_history", None) or []:
            pass

    opponent_card = None
    if current:
        led_card = current[0][1]
        for name, card in current:
            if my_name is None or name != my_name:
                opponent_card = card
                break
        if opponent_card is None:
            opponent_card = led_card

    legal = _legal_moves(hand, opponent_card, spades_broken)
    if not legal:
        legal = list(hand)
    if len(legal) == 1:
        return legal[0]

    if my_bid == 0:
        if opponent_card is not None:
            return _nil_follow(legal, opponent_card[0])
        return _nil_lead(legal)

    want_win = _want_win(gs, my_name, my_bid, hand)
    if opponent_card is not None:
        return _choose_follow(legal, opponent_card, want_win)
    return _choose_lead(legal, want_win, spades_broken)


def _want_win(gs, my_name, my_bid, hand):
    if my_bid == 0:
        return False
    tricks_played = 13 - len(hand)
    won = dict(getattr(gs, "tricks_won", None) or {})
    won_me = won.get(my_name, 0)
    won_opp = won.get(getattr(gs, "opponent_name", None), 0)
    remaining = 13 - tricks_played
    need = my_bid - won_me
    opp_bid = int(getattr(gs, "opponent_bid", 0) or 0)
    opp_need = opp_bid - won_opp
    your_bags = int(getattr(gs, "your_bags", 0) or 0)

    # Still short of our own contract: go for the trick (bid is worth it).
    if need > 0:
        return need <= remaining or your_bags < 10

    # Contract met but the opponent can still fall short: deny them cheaply.
    if 0 < opp_need <= remaining:
        return your_bags < 8

    return False


def _nil_follow(legal, led_suit):
    in_suit = [c for c in legal if c[0] == led_suit]
    if in_suit:
        return min(in_suit, key=lambda c: c[1])
    nonsn = [c for c in legal if c[0] != _SPADES]
    if nonsn:
        return max(nonsn, key=lambda c: c[1])
    return min(legal, key=lambda c: c[1])


def _nil_lead(legal):
    nonsn = [c for c in legal if c[0] != _SPADES]
    if nonsn:
        return min(nonsn, key=lambda c: c[1])
    return min(legal, key=lambda c: c[1])


def _fallback(gs):
    phase = getattr(gs, "phase", None)
    hand = list(getattr(gs, "your_hand", None) or [])
    if not hand:
        return 0
    if phase == "bid":
        b = int(round(estimate_tricks(hand)))
        return max(1, min(13, b))
    trick = list(getattr(gs, "current_trick", None) or [])
    if trick:
        led_suit = trick[0][1][0]
        same = [c for c in hand if c[0] == led_suit]
        if same:
            return same[0]
    if not getattr(gs, "spades_broken", False):
        non = [c for c in hand if c[0] != _SPADES]
        if non:
            return non[0]
    return hand[0]