# BotWars 2026 Finals — Team Calit — Spades bot (bitwise rollout candidate)
#
# Same strategy as calit.py; the rollout hot path is rewritten on 52-bit hand
# masks (suit S=0 occupies bits 0-12, H=1, D=2, C=3) so the same time budget
# buys several times more Monte Carlo simulations.

import random
import time

MASK13 = 0x1FFF
SUIT_OF = {"S": 0, "H": 1, "D": 2, "C": 3}
SUIT_CHR = "SHDC"
SUITMASK = tuple(MASK13 << (13 * s) for s in range(4))
NONSPADE = SUITMASK[1] | SUITMASK[2] | SUITMASK[3]
# HIGHER[r] = 13-bit mask of ranks strictly above r
HIGHER = tuple((MASK13 & ~((1 << (r + 1)) - 1)) for r in range(13))

# 50-card deck as ints (2C and 2D removed; 2 has rank index 0)
FULL_DECK_INTS = tuple(
    s * 13 + r for s in range(4) for r in range(13)
    if not (s in (2, 3) and r == 0)
)

CONFIG = {
    "BID_SIMS": 400,
    "PLAY_SIMS": 300,
    "TIME_BUDGET": 0.9,
    "BID_OFFSET": 0.0,
    "NIL_MAX_EST": 2.6,
    "NIL_MIN_P0": 0.78,
}

_RNG = random.Random(20260808)


def _to_int(c):
    return SUIT_OF[c[0]] * 13 + (c[1] - 2)


def _to_tuple(ci):
    return (SUIT_CHR[ci // 13], ci % 13 + 2)


def _mask_of(ints):
    m = 0
    for c in ints:
        m |= 1 << c
    return m


def _fold(mask):
    return ((mask & MASK13) | (mask >> 13) | (mask >> 26) | (mask >> 39)) & MASK13


def _max_rank_card(mask):
    r = _fold(mask).bit_length() - 1
    for s in range(4):
        if (mask >> (13 * s + r)) & 1:
            return 13 * s + r
    return mask.bit_length() - 1


def _min_rank_card(mask):
    f = _fold(mask)
    r = (f & -f).bit_length() - 1
    for s in range(4):
        if (mask >> (13 * s + r)) & 1:
            return 13 * s + r
    return (mask & -mask).bit_length() - 1


def _winners_mask(lead):
    """Mask of all cards that beat *lead* when played as follower."""
    ls, lr = lead // 13, lead % 13
    if ls == 0:
        return HIGHER[lr]                      # only higher spades win
    return (HIGHER[lr] << (13 * ls)) | SUITMASK[0]


def _legal_mask(hand, lead, broken):
    if lead is None:
        non_sp = hand & NONSPADE
        if not non_sp or broken:
            return hand
        return non_sp
    same = hand & SUITMASK[lead // 13]
    return same if same else hand


def _score_round(bid, tricks, bags_before):
    if bid == 0:
        return (100 if tricks == 0 else -100), bags_before
    if tricks >= bid:
        over = tricks - bid
        pts = bid * 10 + over
        bags = bags_before + over
    else:
        pts = -(bid * 10)
        bags = bags_before
    while bags >= 10:
        pts -= 100
        bags -= 10
    return pts, bags


def _lowest_discard_m(mask):
    non_sp = mask & NONSPADE
    if non_sp:
        best_suit_mask = 0
        best_size = 99
        for s in (1, 2, 3):
            sm = mask & SUITMASK[s]
            if sm:
                n = sm.bit_count()
                if n < best_size:
                    best_size = n
                    best_suit_mask = sm
                elif n == best_size:
                    best_suit_mask |= sm
        return _min_rank_card(best_suit_mask)
    return _min_rank_card(mask)


def _policy_m(hand, lead, broken, bid, my_tricks, opp_bid, opp_tricks):
    legal = _legal_mask(hand, lead, broken)
    if legal & (legal - 1) == 0:
        return legal.bit_length() - 1

    nil = (bid == 0)
    need = bid - my_tricks
    opp_need = opp_bid - opp_tricks

    if lead is not None:
        winners = legal & _winners_mask(lead)
        if nil and my_tricks == 0:
            losers = legal & ~winners
            if losers:
                return _max_rank_card(losers)
            return _min_rank_card(legal)
        if need > 0:
            if winners:
                # cheapest winner: same-suit winner lowest, else lowest trump
                ls = lead // 13
                same_w = winners & SUITMASK[ls]
                if same_w:
                    return (same_w & -same_w).bit_length() - 1
                return (winners & -winners).bit_length() - 1
            return _lowest_discard_m(legal)
        # made bid: win only to set the opponent, else shed danger cards
        if opp_need > 0 and winners:
            ls = lead // 13
            same_w = winners & SUITMASK[ls]
            if same_w:
                return (same_w & -same_w).bit_length() - 1
            return (winners & -winners).bit_length() - 1
        losers = legal & ~winners
        if losers:
            return _max_rank_card(losers)
        return _min_rank_card(legal)

    # Leading
    if nil and my_tricks == 0:
        return _min_rank_card(legal)
    if need > 0:
        non_sp = legal & NONSPADE
        if non_sp:
            best = _max_rank_card(non_sp)
            if best % 13 >= 11:                 # King or Ace
                return best
        sp = legal & SUITMASK[0]
        if sp and sp.bit_count() >= 4:
            return sp.bit_length() - 1          # highest spade
        if non_sp:
            best_sm = 0
            best_n = -1
            for s in (1, 2, 3):
                sm = non_sp & SUITMASK[s]
                if sm:
                    n = sm.bit_count()
                    if n > best_n:
                        best_n = n
                        best_sm = sm
            return best_sm.bit_length() - 1     # top of longest suit
        return _max_rank_card(legal)
    return _lowest_discard_m(legal)


def _rollout_m(my_hand, opp_hand, my_lead, lead, broken,
               my_bid, my_tricks, opp_bid, opp_tricks):
    if lead is not None:
        if my_lead:
            c = _policy_m(opp_hand, lead, broken,
                          opp_bid, opp_tricks, my_bid, my_tricks)
            opp_hand &= ~(1 << c)
            if lead < 13 or c < 13:
                broken = True
            if not ((1 << c) & _winners_mask(lead)):
                my_tricks += 1
                my_lead = True
            else:
                opp_tricks += 1
                my_lead = False
        else:
            c = _policy_m(my_hand, lead, broken,
                          my_bid, my_tricks, opp_bid, opp_tricks)
            my_hand &= ~(1 << c)
            if lead < 13 or c < 13:
                broken = True
            if (1 << c) & _winners_mask(lead):
                my_tricks += 1
                my_lead = True
            else:
                opp_tricks += 1
                my_lead = False

    while my_hand:
        if my_lead:
            lead_c = _policy_m(my_hand, None, broken,
                               my_bid, my_tricks, opp_bid, opp_tricks)
            my_hand &= ~(1 << lead_c)
            resp = _policy_m(opp_hand, lead_c, broken,
                             opp_bid, opp_tricks, my_bid, my_tricks)
            opp_hand &= ~(1 << resp)
            if lead_c < 13 or resp < 13:
                broken = True
            if (1 << resp) & _winners_mask(lead_c):
                opp_tricks += 1
                my_lead = False
            else:
                my_tricks += 1
                my_lead = True
        else:
            lead_c = _policy_m(opp_hand, None, broken,
                               opp_bid, opp_tricks, my_bid, my_tricks)
            opp_hand &= ~(1 << lead_c)
            resp = _policy_m(my_hand, lead_c, broken,
                             my_bid, my_tricks, opp_bid, opp_tricks)
            my_hand &= ~(1 << resp)
            if lead_c < 13 or resp < 13:
                broken = True
            if (1 << resp) & _winners_mask(lead_c):
                my_tricks += 1
                my_lead = True
            else:
                opp_tricks += 1
                my_lead = False

    return my_tricks, opp_tricks


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------
def _unseen_and_voids(gs):
    played = []
    opp_played = 0
    voids = set()
    me = gs.your_name
    for t in gs.trick_history:
        lead_suit = SUIT_OF[t["plays"][0][1][0]]
        for name, card in t["plays"]:
            ci = _to_int(card)
            played.append(ci)
            if name != me:
                opp_played += 1
                if ci // 13 != lead_suit and t["plays"][0][0] != name:
                    voids.add(lead_suit)
    for name, card in gs.current_trick:
        played.append(_to_int(card))
        if name != me:
            opp_played += 1

    out = set(_to_int(c) for c in gs.your_hand)
    out.update(played)
    unseen = [c for c in FULL_DECK_INTS if c not in out]
    return unseen, 13 - opp_played, voids


def _opp_fights(gs):
    hist = gs.hand_history
    if not hist:
        return True
    opp = gs.opponent_name
    overs = []
    for h in hist[-6:]:
        b = h["bids"].get(opp, 0)
        t = h["tricks_won"].get(opp, 0)
        if b > 0 and t >= b:
            overs.append(t - b)
    if not overs:
        return True
    return (sum(overs) / len(overs)) >= 0.9


def _opp_model_bid(gs):
    real = gs.opponent_bid if (gs.opponent_bid_known and
                               gs.opponent_bid is not None) else None
    if real == 0:
        return 0
    if _opp_fights(gs):
        return 13
    return real if real is not None else 13


# ---------------------------------------------------------------------------
# Bidding
# ---------------------------------------------------------------------------
def _sample_my_tricks(gs, deadline, duck=False):
    hand_ints = [_to_int(c) for c in gs.your_hand]
    hand_mask = _mask_of(hand_ints)
    hand_set = set(hand_ints)
    unseen = [c for c in FULL_DECK_INTS if c not in hand_set]
    i_lead_first = (gs.dealer != gs.your_name)
    my_bid = 0 if duck else 13
    opp_bid = _opp_model_bid(gs)
    samples = []
    for _ in range(CONFIG["BID_SIMS"]):
        if time.monotonic() > deadline:
            break
        opp_mask = _mask_of(_RNG.sample(unseen, 13))
        mt, _ = _rollout_m(hand_mask, opp_mask, i_lead_first, None, False,
                           my_bid, 0, opp_bid, 0)
        samples.append(mt)
    return samples


def _choose_bid(gs, deadline):
    samples = _sample_my_tricks(gs, deadline, duck=False)
    if not samples:
        return 3
    bags = gs.your_bags
    mean_mt = sum(samples) / len(samples)

    best_bid, best_ev = 1, None
    for b in range(1, 13):
        ev = 0.0
        for mt in samples:
            pts, _ = _score_round(b, mt, bags)
            ev += pts
        ev /= len(samples)
        ev += CONFIG["BID_OFFSET"] * b
        if best_ev is None or ev > best_ev:
            best_ev, best_bid = ev, b

    if mean_mt <= CONFIG["NIL_MAX_EST"]:
        duck_samples = _sample_my_tricks(gs, deadline, duck=True)
        if duck_samples:
            p0 = sum(1 for mt in duck_samples if mt == 0) / len(duck_samples)
            ev_nil = p0 * 100 - (1 - p0) * 100
            if p0 >= CONFIG["NIL_MIN_P0"] and ev_nil > best_ev:
                return 0
    return best_bid


# ---------------------------------------------------------------------------
# Play
# ---------------------------------------------------------------------------
def _choose_play(gs, deadline):
    lead_t = gs.current_trick[0][1] if gs.current_trick else None
    lead = _to_int(lead_t) if lead_t is not None else None
    hand_ints = [_to_int(c) for c in gs.your_hand]
    hand_mask = _mask_of(hand_ints)
    legal = _legal_mask(hand_mask, lead, gs.spades_broken)
    if legal & (legal - 1) == 0:
        return _to_tuple(legal.bit_length() - 1)

    me = gs.your_name
    opp = gs.opponent_name
    my_bid = gs.your_bid
    opp_bid = gs.opponent_bid
    opp_bid_model = _opp_model_bid(gs)
    my_tricks = gs.tricks_won.get(me, 0)
    opp_tricks = gs.tricks_won.get(opp, 0)
    my_bags = gs.your_bags
    opp_bags = gs.opponent_bags

    unseen, opp_size, voids = _unseen_and_voids(gs)
    if opp_size <= 0 or len(unseen) < opp_size:
        return _fallback_play(gs)

    if voids:
        pool = [c for c in unseen if c // 13 not in voids]
        if len(pool) < opp_size:
            pool = unseen
    else:
        pool = unseen

    moves = []
    m = legal
    while m:
        low = m & -m
        moves.append(low.bit_length() - 1)
        m &= m - 1
    moves.sort(key=lambda c: c % 13)

    totals = [0.0] * len(moves)
    n_done = 0
    winners_of_lead = _winners_mask(lead) if lead is not None else 0

    for _ in range(CONFIG["PLAY_SIMS"]):
        if time.monotonic() > deadline:
            break
        opp_mask = _mask_of(_RNG.sample(pool, opp_size))
        for i, mv in enumerate(moves):
            after = hand_mask & ~(1 << mv)
            broken = gs.spades_broken or mv < 13
            if lead is None:
                mt, ot = _rollout_m(after, opp_mask, True, mv, broken,
                                    my_bid, my_tricks, opp_bid_model, opp_tricks)
            else:
                if lead < 13:
                    broken = True
                i_win = bool((1 << mv) & winners_of_lead)
                mt = my_tricks + (1 if i_win else 0)
                ot = opp_tricks + (0 if i_win else 1)
                mt, ot = _rollout_m(after, opp_mask, i_win, None, broken,
                                    my_bid, mt, opp_bid_model, ot)
            my_pts, _ = _score_round(my_bid, mt, my_bags)
            opp_pts, _ = _score_round(opp_bid, ot, opp_bags)
            totals[i] += my_pts - opp_pts
        n_done += 1

    if n_done == 0:
        return _fallback_play(gs)
    best_i = max(range(len(moves)), key=lambda i: totals[i])
    return _to_tuple(moves[best_i])


def _fallback_play(gs):
    hand = list(gs.your_hand)
    trick = gs.current_trick
    if trick:
        lead_suit = trick[0][1][0]
        same = [c for c in hand if c[0] == lead_suit]
        if same:
            return min(same, key=lambda c: c[1])
        return min(hand, key=lambda c: c[1])
    if not gs.spades_broken:
        non_sp = [c for c in hand if c[0] != "S"]
        if non_sp:
            return min(non_sp, key=lambda c: c[1])
    return min(hand, key=lambda c: c[1])


def nextMove(gameState):
    deadline = time.monotonic() + CONFIG["TIME_BUDGET"]
    try:
        if gameState.phase == "bid":
            return _choose_bid(gameState, deadline)
        return _choose_play(gameState, deadline)
    except Exception:
        try:
            if gameState.phase == "bid":
                return 3
            return _fallback_play(gameState)
        except Exception:
            return gameState.your_hand[0]
