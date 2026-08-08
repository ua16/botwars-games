import random
import time


SUITS = ("H", "D", "C", "S")
SPADE = "S"
SIDE_SUITS = ("H", "D", "C")

DECK = tuple(
    (s, r)
    for s in SUITS
    for r in range(2, 15)
    if not (s in ("C", "D") and r == 2)
)

TRICKS_PER_ROUND = 13
BAG_LIMIT = 10
WIN_SCORE = 500
LOSE_SCORE = -200

BAG_VALUE = 8.0
TERMINAL_BONUS = 1000.0
BID_SAMPLES = 36
PLAY_ROLLOUT_BUDGET = 300
MAX_PLAY_SAMPLES = 32
MIN_PLAY_SAMPLES = 4
BID_TIME_LIMIT = 0.40
PLAY_TIME_LIMIT = 0.35


def _legal(hand, lead_card, spades_broken):
    if lead_card is None:
        non_spades = [c for c in hand if c[0] != SPADE]
        if not non_spades or spades_broken:
            return list(hand)
        return non_spades

    lead_suit = lead_card[0]
    same = [c for c in hand if c[0] == lead_suit]
    return same if same else list(hand)


def _follower_wins(lead_card, follow_card):
    ls, lr = lead_card
    fs, fr = follow_card
    if fs == SPADE:
        return ls != SPADE or fr > lr
    if ls == SPADE:
        return False
    return fs == ls and fr > lr


def _score_round(bid, tricks, bags_before):
    if bid == 0:
        return (100 if tricks == 0 else -100), bags_before

    if tricks >= bid:
        over = tricks - bid
        points = bid * 10 + over
        bags = bags_before + over
    else:
        points = -(bid * 10)
        bags = bags_before

    while bags >= BAG_LIMIT:
        points -= 100
        bags -= BAG_LIMIT

    return points, bags


class _Ctx(object):
    __slots__ = (
        "my_bid", "opp_bid", "my_bags", "opp_bags", "my_score", "opp_score",
    )

    def __init__(self, my_bid, opp_bid, my_bags, opp_bags, my_score, opp_score):
        self.my_bid = my_bid
        self.opp_bid = opp_bid
        self.my_bags = my_bags
        self.opp_bags = opp_bags
        self.my_score = my_score
        self.opp_score = opp_score


def _round_value(my_tricks, ctx):
    my_pts, my_bags = _score_round(ctx.my_bid, my_tricks, ctx.my_bags)
    opp_pts, opp_bags = _score_round(
        ctx.opp_bid, TRICKS_PER_ROUND - my_tricks, ctx.opp_bags
    )

    mine = ctx.my_score + my_pts
    theirs = ctx.opp_score + opp_pts

    value = (mine - theirs) - BAG_VALUE * my_bags + BAG_VALUE * opp_bags

    if mine >= WIN_SCORE and mine > theirs:
        value += TERMINAL_BONUS
    elif theirs >= WIN_SCORE and theirs > mine:
        value -= TERMINAL_BONUS
    if theirs <= LOSE_SCORE:
        value += TERMINAL_BONUS
    if mine <= LOSE_SCORE:
        value -= TERMINAL_BONUS

    return value


def _hand_strength(hand):
    strength = 0.0

    spades = sorted((r for s, r in hand if s == SPADE), reverse=True)
    for i, rank in enumerate(spades):
        if rank >= 14 - i:
            strength += 0.95
        elif rank >= 12:
            strength += 0.55
        elif rank >= 10:
            strength += 0.25
    strength += 0.35 * max(0, len(spades) - 3)

    for suit in SIDE_SUITS:
        ranks = sorted((r for s, r in hand if s == suit), reverse=True)
        n = len(ranks)
        if n == 0:
            continue
        if ranks[0] == 14:
            strength += 0.85
        if 13 in ranks:
            strength += 0.60 if n >= 2 else 0.35
        if 12 in ranks:
            strength += 0.30 if n >= 3 else 0.12
        if n >= 5:
            strength += 0.20 * (n - 4)

    return strength


def _quick_bid(hand):
    return max(1, min(13, int(round(_hand_strength(hand)))))


def _nil_plausible(hand):
    if any(r == 14 for _, r in hand):
        return False
    spades = sorted(r for s, r in hand if s == SPADE)
    if len(spades) > 4:
        return False
    if spades and spades[-1] >= 12:
        return False
    if sum(1 for _, r in hand if r == 13) > 1:
        return False
    return sum(1 for _, r in hand if r >= 12) <= 2


def _wants_trick(bid, tricks, opp_bid, opp_tricks, tricks_left):
    if bid == 0:
        return False
    if bid - tricks > 0:
        return True
    if opp_bid > 0:
        opp_need = opp_bid - opp_tricks
        if 0 < opp_need <= tricks_left:
            return True
    return False


def _policy(hand, lead_card, spades_broken, bid, tricks,
            opp_bid, opp_tricks, tricks_left):
    legal = _legal(hand, lead_card, spades_broken)
    if len(legal) == 1:
        return legal[0]

    want = _wants_trick(bid, tricks, opp_bid, opp_tricks, tricks_left)

    if lead_card is None:
        nil_hunt = opp_bid == 0 and (bid - tricks) < tricks_left
        if want and not nil_hunt:
            aces = [c for c in legal if c[0] != SPADE and c[1] == 14]
            if aces:
                return aces[0]
            spades = [c for c in legal if c[0] == SPADE]
            if spades:
                return max(spades, key=lambda c: c[1])
            return max(legal, key=lambda c: c[1])
        pool = [c for c in legal if c[0] != SPADE] or legal
        return min(pool, key=lambda c: c[1])

    if want:
        winners = [c for c in legal if _follower_wins(lead_card, c)]
        if winners:
            return min(winners, key=lambda c: (c[0] == SPADE, c[1]))
        return min(legal, key=lambda c: (c[0] == SPADE, c[1]))

    losers = [c for c in legal if not _follower_wins(lead_card, c)]
    if losers:
        return max(losers, key=lambda c: (c[0] != SPADE, c[1]))
    return min(legal, key=lambda c: (c[0] == SPADE, c[1]))


def _rollout(my_hand, opp_hand, my_tricks, opp_tricks,
             spades_broken, i_lead, ctx):
    mine = list(my_hand)
    theirs = list(opp_hand)

    while mine and theirs:
        left = len(mine)
        if i_lead:
            first = _policy(mine, None, spades_broken, ctx.my_bid, my_tricks,
                            ctx.opp_bid, opp_tricks, left)
            mine.remove(first)
            second = _policy(theirs, first, spades_broken, ctx.opp_bid,
                             opp_tricks, ctx.my_bid, my_tricks, left)
            theirs.remove(second)
        else:
            first = _policy(theirs, None, spades_broken, ctx.opp_bid,
                            opp_tricks, ctx.my_bid, my_tricks, left)
            theirs.remove(first)
            second = _policy(mine, first, spades_broken, ctx.my_bid, my_tricks,
                             ctx.opp_bid, opp_tricks, left)
            mine.remove(second)

        if first[0] == SPADE or second[0] == SPADE:
            spades_broken = True

        second_wins = _follower_wins(first, second)
        winner_is_me = i_lead != second_wins
        if winner_is_me:
            my_tricks += 1
        else:
            opp_tricks += 1
        i_lead = winner_is_me

    return my_tricks


def _observed(view):
    seen = set(view.your_hand)
    opp_played = 0

    for trick in view.trick_history:
        for name, card in trick["plays"]:
            seen.add(card)
            if name == view.opponent_name:
                opp_played += 1

    for name, card in view.current_trick:
        seen.add(card)
        if name == view.opponent_name:
            opp_played += 1

    voids = set()
    for trick in view.trick_history:
        plays = trick["plays"]
        if len(plays) == 2:
            (_, led), (follower, followed) = plays
            if follower == view.opponent_name and followed[0] != led[0]:
                voids.add(led[0])

    pool = [c for c in DECK if c not in seen]
    return pool, TRICKS_PER_ROUND - opp_played, voids


def _sample_opp_hand(pool, size, voids, target_bid, rng):
    if size <= 0:
        return []

    base = [c for c in pool if c[0] not in voids] if voids else pool
    if len(base) < size:
        base = pool

    if target_bid is None or size < 10:
        return rng.sample(base, size)

    best = None
    best_err = None
    for _ in range(3):
        cand = rng.sample(base, size)
        err = abs(_hand_strength(cand) - target_bid)
        if best_err is None or err < best_err:
            best, best_err = cand, err
        if err <= 1.0:
            break
    return best


def _choose_bid(view, rng, deadline):
    hand = view.your_hand
    held = set(hand)
    pool = [c for c in DECK if c not in held]

    known_bid = view.opponent_bid if view.opponent_bid_known else None
    i_lead_first_trick = view.dealer != view.your_name

    samples = []
    for _ in range(BID_SAMPLES):
        if time.perf_counter() > deadline:
            break
        opp_hand = _sample_opp_hand(pool, TRICKS_PER_ROUND, set(), known_bid, rng)
        opp_bid = known_bid if known_bid is not None else _quick_bid(opp_hand)
        samples.append((opp_hand, opp_bid))

    if not samples:
        return _quick_bid(hand)

    estimates = []
    for opp_hand, opp_bid in samples:
        ctx = _Ctx(13, opp_bid, view.your_bags, view.opponent_bags,
                   view.your_score, view.opponent_score)
        estimates.append(
            _rollout(hand, opp_hand, 0, 0, False, i_lead_first_trick, ctx)
        )

    lo = max(1, min(estimates) - 1)
    hi = min(13, max(estimates) + 1)
    if hi - lo > 5:
        mid = sum(estimates) / float(len(estimates))
        lo = max(1, int(mid) - 2)
        hi = min(13, int(mid) + 3)

    candidates = list(range(lo, hi + 1))
    if _nil_plausible(hand):
        candidates.insert(0, 0)

    best_bid = _quick_bid(hand)
    best_value = None

    for bid in candidates:
        if time.perf_counter() > deadline and best_value is not None:
            break
        total = 0.0
        for opp_hand, opp_bid in samples:
            ctx = _Ctx(bid, opp_bid, view.your_bags, view.opponent_bags,
                       view.your_score, view.opponent_score)
            tricks = _rollout(hand, opp_hand, 0, 0, False,
                              i_lead_first_trick, ctx)
            total += _round_value(tricks, ctx)
        value = total / len(samples)
        if best_value is None or value > best_value:
            best_bid, best_value = bid, value

    return int(best_bid)


def _choose_card(view, rng, deadline):
    hand = view.your_hand
    lead_card = view.current_trick[0][1] if view.current_trick else None
    legal = _legal(hand, lead_card, view.spades_broken)

    if len(legal) == 1:
        return legal[0]

    my_tricks = view.tricks_won.get(view.your_name, 0)
    opp_tricks = view.tricks_won.get(view.opponent_name, 0)
    ctx = _Ctx(view.your_bid, view.opponent_bid, view.your_bags,
               view.opponent_bags, view.your_score, view.opponent_score)

    pool, opp_size, voids = _observed(view)
    if opp_size < 0 or len(pool) < opp_size:
        return _fallback_card(legal, lead_card, ctx, my_tricks)

    n_samples = max(MIN_PLAY_SAMPLES,
                    min(MAX_PLAY_SAMPLES, PLAY_ROLLOUT_BUDGET // len(legal)))

    totals = dict((card, 0.0) for card in legal)
    rounds_done = 0

    for _ in range(n_samples):
        if rounds_done and time.perf_counter() > deadline:
            break
        opp_hand = _sample_opp_hand(pool, opp_size, voids, ctx.opp_bid, rng)

        for card in legal:
            rest = list(hand)
            rest.remove(card)
            theirs = list(opp_hand)
            broken = view.spades_broken or card[0] == SPADE

            if lead_card is None:
                reply = _policy(theirs, card, broken, ctx.opp_bid, opp_tricks,
                                ctx.my_bid, my_tricks, len(hand))
                theirs.remove(reply)
                if reply[0] == SPADE:
                    broken = True
                won = not _follower_wins(card, reply)
            else:
                if lead_card[0] == SPADE:
                    broken = True
                won = _follower_wins(lead_card, card)

            mt = my_tricks + (1 if won else 0)
            ot = opp_tricks + (0 if won else 1)
            final = _rollout(rest, theirs, mt, ot, broken, won, ctx)
            totals[card] += _round_value(final, ctx)

        rounds_done += 1

    if not rounds_done:
        return _fallback_card(legal, lead_card, ctx, my_tricks)

    return max(legal, key=lambda c: (totals[c], -c[1], -SUITS.index(c[0])))


def _fallback_card(legal, lead_card, ctx, my_tricks):
    return _policy(legal, lead_card, True, ctx.my_bid, my_tricks,
                   ctx.opp_bid, 0, len(legal))


def _seed(view):
    value = 1469598103
    for suit, rank in view.your_hand:
        value = (value * 131 + SUITS.index(suit) * 20 + rank) & 0xFFFFFFFF
    return (value * 1000003
            + view.round_number * 97
            + len(view.trick_history) * 7
            + len(view.current_trick)) & 0xFFFFFFFF


def nextMove(gameState):
    try:
        if gameState.phase == "bid":
            deadline = time.perf_counter() + BID_TIME_LIMIT
            return _choose_bid(gameState, random.Random(_seed(gameState)), deadline)

        deadline = time.perf_counter() + PLAY_TIME_LIMIT
        return _choose_card(gameState, random.Random(_seed(gameState)), deadline)

    except Exception:
        try:
            if gameState.phase == "bid":
                return _quick_bid(gameState.your_hand)
            lead = gameState.current_trick[0][1] if gameState.current_trick else None
            return _legal(gameState.your_hand, lead, gameState.spades_broken)[0]
        except Exception:
            return 3 if gameState.phase == "bid" else gameState.your_hand[0]