# Team: segfault_society — BotWars 2026 finals, two-player Spades (v3).
#
# Internal bake-off champion: Monte Carlo expected-score bidding (simulate
# the round vs sampled opponent hands under the real scoring rules, bag
# discount, nil evaluated) driving a tuned play engine (hypergeometric
# ruff-risk leads, bag panic, nil play/anti-nil, deny mode). Bidding and
# play validated together over thousands of seeded games.
#
# All behaviour is driven by PARAMS so the tuner can search the space.

from math import comb

PARAMS = {
    # --- bidding ---
    "trump_risk": 0.604,        # chance opponent actually ruffs when void
    "long_suit_bonus": 0.335,   # extra tricks per card beyond 3 in a side suit
    "spade_length_bonus": 0.492,# extra tricks per surplus spade over opponent
    "void_ruff_bonus": 0.125,   # ruffing value of a void/singleton side suit
    "bid_aggression": 1.089,    # multiplier on the raw estimate
    "bid_shade": 0.094,         # subtract before rounding (bags are costly)
    # --- nil ---
    "nil_max_tricks": 1.49,    # bid nil when estimate falls below this
    "nil_max_spades": 4,       # never nil with more spades than this
    "nil_max_high_spade": 11,  # never nil holding a spade above this rank
    # --- play ---
    "bag_panic_at": 5,         # above this many bags, refuse all overtricks
    "set_opponent_weight": 1.0,# eagerness to deny the opponent their contract
}

SUITS = ("H", "D", "C", "S")
SPADES = "S"
UNSEEN = 37       # 24 kitty + 13 opponent
OPP_HAND = 13


# ---------------------------------------------------------------------------
# Probability helpers
# ---------------------------------------------------------------------------
def _p_opp_holds_none(k, unseen=UNSEEN, opp=OPP_HAND):
    """P(opponent holds none of k specific unseen cards)."""
    if k <= 0:
        return 1.0
    if unseen - k < opp:
        return 0.0
    return comb(unseen - k, opp) / comb(unseen, opp)


def _suit_size(suit):
    """Clubs and diamonds are missing their 2."""
    return 12 if suit in ("C", "D") else 13


# ---------------------------------------------------------------------------
# Bidding — Monte Carlo simulation (segfault): play the round out against
# sampled opponent hands and pick the expected-score-maximizing bid.
# ---------------------------------------------------------------------------
DECK = tuple((s, r) for s in SUITS for r in range(2, 15)
             if not (s in ("C", "D") and r == 2))

def _sim_lead(hand):
    non_sp = [c for c in hand if c[0] != "S"]
    pool = non_sp if non_sp else hand
    by_suit = {}
    for c in pool:
        by_suit.setdefault(c[0], []).append(c)
    # cash a topped suit if we have one, else develop the longest suit low
    strong = [cs for cs in by_suit.values() if max(r for (_s, r) in cs) >= 13]
    if strong:
        best = max(strong, key=lambda cs: max(r for (_s, r) in cs))
        return max(best, key=lambda c: c[1])
    longest = max(by_suit.values(), key=len)
    return min(longest, key=lambda c: c[1])


def _sim_follow(hand, lead):
    same = [c for c in hand if c[0] == lead[0]]
    if same:
        if lead[0] == "S":
            winners = [c for c in same if c[1] > lead[1]]
        else:
            winners = [c for c in same if c[1] > lead[1]]
        if winners:
            return min(winners, key=lambda c: c[1])
        return max(same, key=lambda c: c[1])       # shed highest loser
    spades = [c for c in hand if c[0] == "S"]
    if spades and lead[0] != "S":
        return min(spades, key=lambda c: c[1])
    non_sp = [c for c in hand if c[0] != "S"]
    if non_sp:
        return max(non_sp, key=lambda c: c[1])
    return min(hand, key=lambda c: c[1])


def _sim_beats(follow, lead):
    if follow[0] == lead[0]:
        return follow[1] > lead[1]
    return follow[0] == "S"


def _sim_round(mine, theirs, i_lead):
    my_tricks = 0
    for _ in range(13):
        if i_lead:
            lc = _sim_lead(mine)
            mine.remove(lc)
            fc = _sim_follow(theirs, lc)
            theirs.remove(fc)
            won = not _sim_beats(fc, lc)
        else:
            lc = _sim_lead(theirs)
            theirs.remove(lc)
            fc = _sim_follow(mine, lc)
            mine.remove(fc)
            won = _sim_beats(fc, lc)
        if won:
            my_tricks += 1
        i_lead = won
    return my_tricks


def _bid(view):
    import random
    hand = [tuple(c) for c in view.your_hand]
    rest = [c for c in DECK if c not in set(hand)]
    i_lead_first = view.your_name != view.dealer
    bags = view.your_bags or 0

    samples = []
    for _ in range(140):
        random.shuffle(rest)
        samples.append(_sim_round(list(hand), rest[:13], i_lead_first))

    best_bid, best_ev = 1, float("-inf")
    for b in range(0, 14):
        total = 0.0
        for t in samples:
            if b == 0:
                total += 100.0 if t == 0 else -100.0
            elif t >= b:
                over = t - b
                bag_cost = 9.0 * over if bags + over >= 10 else 4.0 * over * ((bags + over) / 10.0)
                total += b * 10 + over - bag_cost
            else:
                total += -(b * 10)
        ev = total / len(samples)
        if ev > best_ev:
            best_ev, best_bid = ev, b
    return best_bid




def _estimate_tricks(hand, P):
    by_suit = {s: sorted((c[1] for c in hand if c[0] == s), reverse=True) for s in SUITS}
    total = 0.0

    # --- side suits ---
    for suit in ("H", "D", "C"):
        mine = by_suit[suit]
        mine_set = set(mine)
        outstanding = _suit_size(suit) - len(mine)
        p_void = _p_opp_holds_none(outstanding)
        p_ruffed = p_void * P["trump_risk"]

        for rank in mine:
            higher_out = sum(1 for r in range(rank + 1, 15) if r not in mine_set)
            total += _p_opp_holds_none(higher_out) * (1.0 - p_ruffed)

        if len(mine) > 3:
            total += (len(mine) - 3) * P["long_suit_bonus"]

    # --- spades (trump) ---
    my_spades = by_suit[SPADES]
    spade_set = set(my_spades)
    for rank in my_spades:
        higher_out = sum(1 for r in range(rank + 1, 15) if r not in spade_set)
        total += _p_opp_holds_none(higher_out)

    outstanding_spades = 13 - len(my_spades)
    exp_opp_spades = outstanding_spades * OPP_HAND / UNSEEN
    surplus = len(my_spades) - exp_opp_spades
    if surplus > 0:
        total += surplus * P["spade_length_bonus"]

    # --- ruffing value of short side suits ---
    if my_spades:
        shorts = sum(1 for s in ("H", "D", "C") if len(by_suit[s]) <= 1)
        total += min(shorts, len(my_spades)) * P["void_ruff_bonus"]

    return total


def _nil_is_safe(hand, P):
    spades = [c[1] for c in hand if c[0] == SPADES]
    if len(spades) > P["nil_max_spades"]:
        return False
    if spades and max(spades) > P["nil_max_high_spade"]:
        return False
    if any(c[1] == 14 for c in hand):
        return False
    return True


def _choose_bid(gs, P):
    return _bid(gs)


def _choose_bid_analytic_unused(gs, P):
    hand = gs.your_hand
    est = _estimate_tricks(hand, P)

    if est < P["nil_max_tricks"] and _nil_is_safe(hand, P):
        return 0

    bid = int(round(est * P["bid_aggression"] - P["bid_shade"]))

    # Near the bag limit, shading down one more trick is cheap insurance.
    if gs.your_bags >= P["bag_panic_at"]:
        bid += 1

    return max(1, min(13, bid))


# ---------------------------------------------------------------------------
# Legality (mirrors engine.legal_cards)
# ---------------------------------------------------------------------------
def _legal_cards(hand, lead_card, spades_broken):
    if lead_card is None:
        non_spades = [c for c in hand if c[0] != SPADES]
        if not non_spades:
            return list(hand)
        return list(hand) if spades_broken else non_spades

    same = [c for c in hand if c[0] == lead_card[0]]
    return same if same else list(hand)


def _beats(challenger, lead_card):
    """True if challenger (played second) wins against lead_card."""
    ls, lr = lead_card
    cs, cr = challenger
    if cs == SPADES and ls != SPADES:
        return True
    if cs == ls:
        return cr > lr
    return False


# ---------------------------------------------------------------------------
# Play
# ---------------------------------------------------------------------------
def _low(cards):
    return min(cards, key=lambda c: (c[0] == SPADES, c[1]))


def _high(cards):
    return max(cards, key=lambda c: (c[0] == SPADES, c[1]))


def _choose_card(gs, P):
    hand = gs.your_hand
    lead_card = gs.current_trick[0][1] if gs.current_trick else None
    legal = _legal_cards(hand, lead_card, gs.spades_broken)
    if len(legal) == 1:
        return legal[0]

    me, opp = gs.your_name, gs.opponent_name
    my_bid = gs.your_bid or 0
    opp_bid = gs.opponent_bid or 0
    my_tricks = gs.tricks_won.get(me, 0)
    opp_tricks = gs.tricks_won.get(opp, 0)
    need = my_bid - my_tricks
    tricks_left = len(hand)

    # --- I am playing nil: never win a trick ---
    if my_bid == 0:
        return _nil_play(legal, lead_card)

    # --- opponent is playing nil: force them to take a trick ---
    if opp_bid == 0:
        return _break_nil_play(gs, legal, lead_card)

    # Denying the opponent their contract is worth opp_bid * 20 in swing.
    opp_need = opp_bid - opp_tricks
    must_deny = (
        opp_need > 0
        and opp_need >= tricks_left
        and P["set_opponent_weight"] > 0
    )

    want_trick = need > 0 or must_deny
    if need <= 0 and gs.your_bags >= P["bag_panic_at"]:
        want_trick = must_deny  # overtricks now cost 100 points

    if lead_card is not None:
        winners = [c for c in legal if _beats(c, lead_card)]
        if want_trick and winners:
            return _low(winners)          # win as cheaply as possible
        losers = [c for c in legal if not _beats(c, lead_card)]
        if losers:
            # Not contesting: shed the most useless card we can.
            return _high(losers) if not want_trick else _low(losers)
        return _low(legal)

    return _lead_card(gs, legal, want_trick, P)


def _nil_play(legal, lead_card):
    """Playing nil: shed high cards safely, never take a trick."""
    if lead_card is None:
        return _low(legal)
    losers = [c for c in legal if not _beats(c, lead_card)]
    if losers:
        return _high(losers)   # dump the biggest card that still loses
    return _low(legal)         # forced to win — lose as little value as possible


def _break_nil_play(gs, legal, lead_card):
    """Opponent bid nil: make them win. Leading low forces them above us."""
    if lead_card is None:
        by_suit = {}
        for c in legal:
            by_suit.setdefault(c[0], []).append(c)
        # Prefer our longest non-spade suit: opponent is least likely void there.
        best = None
        for suit, cards in by_suit.items():
            if suit == SPADES:
                continue
            key = (len(cards), -min(x[1] for x in cards))
            if best is None or key > best[0]:
                best = (key, min(cards, key=lambda x: x[1]))
        if best:
            return best[1]
        return _low(legal)

    losers = [c for c in legal if not _beats(c, lead_card)]
    return _low(losers) if losers else _low(legal)


def _lead_card(gs, legal, want_trick, P):
    """Choose a card to lead."""
    seen = set()
    for trick in gs.trick_history:
        for _, card in trick["plays"]:
            seen.add(card)
    for card in gs.your_hand:
        seen.add(card)

    if want_trick:
        # Lead a card no outstanding card can beat, cheapest such card first.
        best, best_key = None, None
        for card in legal:
            suit, rank = card
            higher_out = sum(
                1 for r in range(rank + 1, 15)
                if (suit, r) not in seen and not (suit in ("C", "D") and r == 2)
            )
            p_win = _p_opp_holds_none(higher_out)
            if suit != SPADES:
                p_win *= 0.9   # can still be ruffed
            key = (round(p_win, 3), -rank)
            if best_key is None or key > best_key:
                best, best_key = card, key
        return best

    # Not chasing tricks: lead our safest low card, keep spades back.
    non_spades = [c for c in legal if c[0] != SPADES]
    return _low(non_spades) if non_spades else _low(legal)


# ---------------------------------------------------------------------------
# Entry point — never raises, never returns an illegal move
# ---------------------------------------------------------------------------
def nextMove(gameState):
    try:
        if gameState.phase == "bid":
            bid = _choose_bid(gameState, PARAMS)
            return int(bid) if 0 <= bid <= 13 else 3
        card = _choose_card(gameState, PARAMS)
        lead = gameState.current_trick[0][1] if gameState.current_trick else None
        legal = _legal_cards(gameState.your_hand, lead, gameState.spades_broken)
        return card if card in legal else legal[0]
    except Exception:
        # Any failure at all still has to produce a legal move: a forfeit
        # loses the entire 100-game matchup, not just this hand.
        try:
            if gameState.phase == "bid":
                return 3
            lead = gameState.current_trick[0][1] if gameState.current_trick else None
            return _legal_cards(gameState.your_hand, lead, gameState.spades_broken)[0]
        except Exception:
            return gameState.your_hand[0]
