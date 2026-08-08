import math
import random
import time

_EXP = math.exp

_RNG = random.Random(0x5EED9E11)

_SUITIDX = {"H": 0, "D": 1, "C": 2, "S": 3, "h": 0, "d": 1, "c": 2, "s": 3}

_PFEQ_RAW = (
    "502 325 353 539 329 378 354 387 576 344 380 366 390 373 412 611 342 378 "
    "359 406 384 410 395 428 635 343 380 371 396 385 418 399 433 418 452 659 "
    "374 404 380 411 397 426 417 444 436 461 449 479 696 388 425 397 431 396 "
    "441 422 456 446 473 469 490 480 515 726 415 447 423 445 437 466 437 473 "
    "462 492 475 499 494 526 517 546 751 450 476 456 483 460 494 467 500 475 "
    "515 495 525 511 532 521 556 558 573 775 476 504 484 507 489 519 504 534 "
    "510 534 517 538 535 554 550 580 577 595 583 609 798 509 532 511 534 522 "
    "560 529 554 535 563 546 573 556 588 584 600 600 617 608 623 622 632 819 "
    "551 579 557 577 568 596 582 603 569 593 583 612 600 620 607 626 622 650 "
    "632 653 640 660 655 669 846"
)

_STRAIGHT = [-1] * 8192
_TOP5 = [0] * 8192
for _m in range(8192):
    _hi = -1
    for _h in range(12, 3, -1):
        _need = 0
        for _k in range(5):
            _need |= 1 << (_h - _k)
        if _m & _need == _need:
            _hi = _h
            break
    if _hi < 0:
        _wheel = (1 << 12) | 1 | 2 | 4 | 8
        if _m & _wheel == _wheel:
            _hi = 3
    _STRAIGHT[_m] = _hi
    _p = 0
    _n = 0
    for _r in range(12, -1, -1):
        if _m >> _r & 1:
            _p = (_p << 4) | _r
            _n += 1
            if _n == 5:
                break
    if _n < 5:
        _p <<= 4 * (5 - _n)
    _TOP5[_m] = _p


def _evaluate(cards):
    rc = [0] * 13
    sc = [0, 0, 0, 0]
    sm = [0, 0, 0, 0]
    mask = 0
    for c in cards:
        r = c >> 2
        s = c & 3
        rc[r] += 1
        sc[s] += 1
        sm[s] |= 1 << r
        mask |= 1 << r
    if sc[0] >= 5 or sc[1] >= 5 or sc[2] >= 5 or sc[3] >= 5:
        for s in range(4):
            if sc[s] >= 5:
                fm = sm[s]
                st = _STRAIGHT[fm]
                if st >= 0:
                    return (8 << 20) | (st << 16)
                return (5 << 20) | _TOP5[fm]
    quad = -1
    trips = -1
    pairs = []
    for r in range(12, -1, -1):
        n = rc[r]
        if n == 0 or n == 1:
            continue
        if n == 4:
            quad = r
        elif n == 3:
            if trips < 0:
                trips = r
            else:
                pairs.append(r)
        else:
            pairs.append(r)
    if quad >= 0:
        k = 0
        for r in range(12, -1, -1):
            if r != quad and rc[r]:
                k = r
                break
        return (7 << 20) | (quad << 16) | (k << 12)
    if trips >= 0 and pairs:
        return (6 << 20) | (trips << 16) | (pairs[0] << 12)
    st = _STRAIGHT[mask]
    if st >= 0:
        return (4 << 20) | (st << 16)
    if trips >= 0:
        ks = [r for r in range(12, -1, -1) if rc[r] == 1][:2]
        while len(ks) < 2:
            ks.append(0)
        return (3 << 20) | (trips << 16) | (ks[0] << 12) | (ks[1] << 8)
    if len(pairs) >= 2:
        hi = pairs[0]
        lo = pairs[1]
        k = 0
        for r in range(12, -1, -1):
            if rc[r] and r != hi and r != lo:
                k = r
                break
        return (2 << 20) | (hi << 16) | (lo << 12) | (k << 8)
    if pairs:
        p = pairs[0]
        ks = [r for r in range(12, -1, -1) if rc[r] == 1][:3]
        while len(ks) < 3:
            ks.append(0)
        return (1 << 20) | (p << 16) | (ks[0] << 12) | (ks[1] << 8) | (ks[2] << 4)
    return _TOP5[mask]


_PFEQ = {}
_vals = [int(x) for x in _PFEQ_RAW.split()]
_i = 0
for _hr in range(13):
    for _lr in range(_hr + 1):
        for _su in (0, 1):
            if _su and _hr == _lr:
                continue
            _PFEQ[(_hr, _lr, _su)] = _vals[_i] / 1000.0
            _i += 1


def _combo_count(key):
    hr, lr, su = key
    if hr == lr:
        return 6
    return 4 if su else 12


_PFPCT = {}
_cum = 0
for _k in sorted(_PFEQ, key=lambda k: -_PFEQ[k]):
    _cum += _combo_count(_k)
    _PFPCT[_k] = _cum / 1326.0


def _key2(a, b):
    ra = a >> 2
    rb = b >> 2
    if ra < rb:
        ra, rb = rb, ra
    return (ra, rb, 1 if (a & 3) == (b & 3) else 0)


_PCT_OF = {}
_EQ_OF = {}
_ALLCOMBOS = []
for _a in range(52):
    for _b in range(_a + 1, 52):
        _kk = _key2(_a, _b)
        _PCT_OF[(_a, _b)] = _PFPCT[_kk]
        _EQ_OF[(_a, _b)] = _PFEQ[_kk]
        _ALLCOMBOS.append((_a, _b))
_ALLCOMBOS.sort(key=lambda ab: _PCT_OF[ab])

_TIER_EQ = (0.10, 0.20, 0.28, 0.36, 0.42, 0.55, 0.70, 0.85, 0.93)
_STREETS = ("preflop", "flop", "turn", "river")


def _pf_tier(pct):
    if pct <= 0.035:
        return 8
    if pct <= 0.07:
        return 7
    if pct <= 0.12:
        return 6
    if pct <= 0.20:
        return 5
    if pct <= 0.33:
        return 4
    if pct <= 0.46:
        return 3
    if pct <= 0.62:
        return 2
    if pct <= 0.82:
        return 1
    return 0


class _BoardCtx:
    def __init__(self, board):
        self.cards = list(board)
        self.n = len(board)
        self.mask = 0
        self.ranks = set()
        self.suit = [0, 0, 0, 0]
        self.smask = [0, 0, 0, 0]
        self.rc = [0] * 13
        for c in board:
            r = c >> 2
            s = c & 3
            self.mask |= 1 << r
            self.ranks.add(r)
            self.suit[s] += 1
            self.smask[s] |= 1 << r
            self.rc[r] += 1
        self.top = max(self.ranks) if self.ranks else -1
        self.paired = any(v >= 2 for v in self.rc)
        self.flushy = max(self.suit) if self.n else 0
        self.straighty = 0
        if self.n >= 3:
            cnt = 0
            for r in range(13):
                if _STRAIGHT[self.mask | (1 << r)] >= 0:
                    cnt += 1
            self.straighty = cnt


def _straight_outs(mask, bmask):
    outs = 0
    for r in range(13):
        bit = 1 << r
        if mask & bit:
            continue
        if _STRAIGHT[mask | bit] >= 0 and _STRAIGHT[bmask | bit] < 0:
            outs += 1
    return outs


def _tier_of(a, b, bx, score):
    cat = score >> 20
    if cat >= 5:
        return 8
    if cat == 4 or cat == 3:
        return 7
    if cat == 2:
        return 6
    base = 0
    if cat == 1:
        pr = (score >> 16) & 15
        ra = a >> 2
        rb = b >> 2
        if pr != ra and pr != rb:
            base = 1
        elif pr >= bx.top:
            base = 5
        else:
            above = 0
            for r in bx.ranks:
                if r > pr:
                    above += 1
            base = 4 if above <= 1 else 3
    else:
        hi = max(a >> 2, b >> 2)
        lo = min(a >> 2, b >> 2)
        if bx.top >= 0 and hi > bx.top:
            base = 1 if lo > bx.top else 0
        else:
            base = 0
    if bx.n >= 3 and base < 7:
        sa = a & 3
        sb = b & 3
        fd = 0
        if bx.suit[sa] + (1 if sa == sb else 0) >= 4:
            fd = 1
        elif bx.suit[sb] + (1 if sa == sb else 0) >= 4:
            fd = 1
        if fd and bx.flushy >= 5:
            fd = 0
        mask = bx.mask | (1 << (a >> 2)) | (1 << (b >> 2))
        so = _straight_outs(mask, bx.mask)
        dt = 0
        if fd and so >= 2:
            dt = 5
        elif fd:
            dt = 4 if base <= 1 else 3
        elif so >= 2:
            dt = 3
        elif so == 1:
            dt = 2
        if dt > base:
            base = dt
        elif dt >= 3 and base < 6:
            base += 1
            if base > 6:
                base = 6
    return base


_MEM = {"n": 0, "stats": {}, "hand": -1, "streets": {}}


def _blank():
    return {
        "hands": 0,
        "vpip": 0,
        "pfr": 0,
        "agg": 0,
        "calls": 0,
        "checks": 0,
        "faced": 0,
        "folds": 0,
        "bsum": 0.0,
        "bn": 0,
        "sd": 0,
        "sdw": 0,
    }


def _stat(name):
    s = _MEM["stats"].get(name)
    if s is None:
        s = _blank()
        _MEM["stats"][name] = s
    return s


def _replay_street(actions, committed_before):
    wager = {}
    level = 0
    last = 0
    events = []
    for p, a in actions:
        w = wager.get(p, 0)
        pot = committed_before + sum(wager.values())
        to_call = level - w
        k = a[0]
        events.append((p, k, to_call, pot, a[1] if len(a) > 1 else 0, level, w))
        if k == "call":
            wager[p] = level
        elif k == "bet":
            wager[p] = w + a[1]
            last = wager[p] - level
            level = wager[p]
        elif k == "raise":
            last = a[1] - level
            level = a[1]
            wager[p] = a[1]
    return events, committed_before + sum(wager.values()), level, last


def _ingest(hand_history):
    n = len(hand_history)
    while _MEM["n"] < n:
        h = hand_history[_MEM["n"]]
        _MEM["n"] += 1
        try:
            acts = h.get("actions") or {}
            for p in h.get("seat_order") or []:
                _stat(p)["hands"] += 1
            committed = 0
            last_agg = None
            for street in _STREETS:
                lst = acts.get(street) or []
                events, committed, _lv, _lr = _replay_street(lst, committed)
                for p, k, to_call, pot, amt, level, w in events:
                    st = _stat(p)
                    if to_call > 0:
                        st["faced"] += 1
                        if k == "fold":
                            st["folds"] += 1
                    if street == "preflop":
                        if k in ("call", "bet", "raise"):
                            st["vpip"] += 1
                        if k in ("bet", "raise"):
                            st["pfr"] += 1
                    else:
                        if k in ("bet", "raise"):
                            st["agg"] += 1
                        elif k == "call":
                            st["calls"] += 1
                        elif k == "check":
                            st["checks"] += 1
                    if k in ("bet", "raise"):
                        last_agg = p
                        size = amt - w if k == "raise" else amt
                        base = pot if pot > 0 else size
                        if base > 0:
                            st["bsum"] += min(4.0, size / float(base))
                            st["bn"] += 1
            sd = h.get("showdown")
            if sd:
                board = h.get("board") or []
                bi = [_cint(c) for c in board]
                for p, cards in sd.items():
                    st = _stat(p)
                    st["sd"] += 1
                    if p == last_agg and len(bi) == 5:
                        try:
                            sc = _evaluate([_cint(c) for c in cards] + bi)
                            if sc >> 20 <= 0:
                                st["sdw"] += 1
                        except Exception:
                            pass
        except Exception:
            continue


def _cint(card):
    return (card[1] - 2) * 4 + _SUITIDX.get(card[0], 0)


def _fold_rate(name):
    s = _MEM["stats"].get(name)
    if not s:
        return 0.55
    return (s["folds"] + 5.0 * 0.55) / (s["faced"] + 5.0)


def _loose(name):
    fr = _fold_rate(name)
    v = (1.0 - fr) / 0.45
    if v < 0.45:
        v = 0.45
    if v > 1.75:
        v = 1.75
    return v


def _vpip_rate(name):
    s = _MEM["stats"].get(name)
    if not s or s["hands"] == 0:
        return 0.4
    return (s["vpip"] + 4.0 * 0.4) / (s["hands"] + 4.0)


def _pfr_rate(name):
    s = _MEM["stats"].get(name)
    if not s or s["hands"] == 0:
        return 0.2
    return (s["pfr"] + 4.0 * 0.2) / (s["hands"] + 4.0)


def _aggro(name):
    s = _MEM["stats"].get(name)
    if not s:
        return 0.35
    tot = s["agg"] + s["calls"] + s["checks"]
    return (s["agg"] + 3.0 * 0.3) / (tot + 3.0)


def _bluffy(name):
    s = _MEM["stats"].get(name)
    if not s or s["sd"] < 3:
        return 0.28
    return (s["sdw"] + 2.0 * 0.28) / (s["sd"] + 2.0)


def _track_hand(view):
    if _MEM["hand"] != view.hand_number:
        _MEM["hand"] = view.hand_number
        _MEM["streets"] = {}
    cur = _MEM["streets"].get(view.street) or []
    if len(view.action_history) >= len(cur):
        _MEM["streets"][view.street] = list(view.action_history)


def _hand_actions(name):
    out = []
    for street in _STREETS:
        for p, a in _MEM["streets"].get(street) or []:
            if p == name:
                out.append((street, a))
    return out


def _range_threshold(name, street):
    acts = _hand_actions(name)
    thr = 1.0
    invested = False
    raised_pre = False
    raises = 0
    for st, a in acts:
        k = a[0]
        if k in ("call", "bet", "raise"):
            invested = True
        if k in ("bet", "raise"):
            if st == "preflop":
                raised_pre = True
            raises += 1
    if raised_pre:
        thr = _pfr_rate(name) * 1.18
        if thr < 0.05:
            thr = 0.05
        if thr > 0.62:
            thr = 0.62
    elif invested:
        thr = _vpip_rate(name) * 1.12
        if thr < 0.14:
            thr = 0.14
        if thr > 0.9:
            thr = 0.9
    if raises >= 2:
        thr *= 0.65
    if thr < 0.04:
        thr = 0.04
    if thr > 1.0:
        thr = 1.0
    return thr


def _draw_pool(thr):
    n = int(thr * 1326)
    if n < 24:
        n = 24
    if n > 1326:
        n = 1326
    return n


def _sample(hole, board, opp_pools, sims, deadline, bx):
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    nopp = len(opp_pools)
    samples = []
    pre = bx.n < 3
    for i in range(sims):
        if (i & 15) == 0 and time.monotonic() > deadline:
            break
        blocked = set(used)
        extra = _RNG.sample(deck, need) if need else []
        for c in extra:
            blocked.add(c)
        full = board + extra
        myf = _evaluate(hole + full)
        row = []
        ok = True
        for pool in opp_pools:
            got = None
            for _ in range(10):
                a, b = _ALLCOMBOS[_RNG.randrange(pool)]
                if a not in blocked and b not in blocked:
                    got = (a, b)
                    break
            if got is None:
                free = [c for c in deck if c not in blocked]
                if len(free) < 2:
                    ok = False
                    break
                got = (free[0], free[1])
            a, b = got
            blocked.add(a)
            blocked.add(b)
            if pre:
                tier = _pf_tier(_PCT_OF[(a, b) if a < b else (b, a)])
            else:
                tier = _tier_of(a, b, bx, _evaluate([a, b] + board))
            row.append((tier, _evaluate([a, b] + full)))
        if not ok:
            continue
        samples.append((myf, row))
    return samples


def _ratio(bet, pot, stack):
    if pot > 0:
        return bet / float(pot)
    if stack <= 0:
        return 4.0
    return 1.8 + 5.0 * (bet / float(stack))


def _p_cont(tier, ratio, loose):
    if ratio < 0.0:
        ratio = 0.0
    req = ratio / (1.0 + ratio)
    m = _TIER_EQ[tier] - req
    if m > 3.0:
        m = 3.0
    elif m < -3.0:
        m = -3.0
    p = 1.0 / (1.0 + _EXP(-9.0 * m))
    p *= loose
    if p > 0.995:
        p = 0.995
    if p < 0.0:
        p = 0.0
    return p


def _ev_aggressive(samples, urand, pot, risk, ratio, looses, locked):
    n = len(samples)
    if n == 0:
        return 0.0
    nopp = len(looses)
    table = []
    for j in range(nopp):
        if locked[j]:
            table.append(None)
        else:
            table.append([_p_cont(t, ratio, looses[j]) for t in range(9)])
    tot = 0.0
    for i in range(n):
        myf, row = samples[i]
        ur = urand[i]
        best = -1
        k = 0
        ties = 0
        for j in range(nopp):
            tb = table[j]
            tier, of = row[j]
            if tb is None or ur[j] < tb[tier]:
                k += 1
                if of > best:
                    best = of
                    ties = 1
                elif of == best:
                    ties += 1
        if k == 0:
            tot += pot
        elif myf > best:
            tot += pot + risk * k
        elif myf == best:
            total = pot + risk * (1 + k)
            tot += total / float(ties + 1) - risk
        else:
            tot -= risk
    return tot / n


def _ev_call(samples, pot, to_call):
    n = len(samples)
    if n == 0:
        return 0.0
    tot = 0.0
    for myf, row in samples:
        best = -1
        ties = 0
        for tier, of in row:
            if of > best:
                best = of
                ties = 1
            elif of == best:
                ties += 1
        if myf > best:
            tot += pot
        elif myf == best:
            tot += (pot + to_call) / float(ties + 1) - to_call
        else:
            tot -= to_call
    return tot / n


def _showdown_share(samples):
    n = len(samples)
    if n == 0:
        return 0.0
    w = 0.0
    for myf, row in samples:
        best = -1
        ties = 0
        for tier, of in row:
            if of > best:
                best = of
                ties = 1
            elif of == best:
                ties += 1
        if myf > best:
            w += 1.0
        elif myf == best:
            w += 1.0 / (ties + 1)
    return w / n


def _improve_prob(samples, curcat):
    n = len(samples)
    if n == 0:
        return 0.0
    c = 0
    target = curcat + 2
    if target < 4:
        target = 4
    for myf, row in samples:
        if (myf >> 20) >= target:
            c += 1
    return c / float(n)


def _my_wager(action_history, me):
    w = 0
    level = 0
    for p, a in action_history:
        k = a[0]
        if k == "bet":
            nw = (w if p == me else 0) + a[1]
            if p == me:
                w = nw
            level = max(level, nw)
        elif k == "raise":
            level = max(level, a[1])
            if p == me:
                w = a[1]
        elif k == "call":
            if p == me:
                w = level
    return w


def _legal(view, action, my_wager):
    k = action[0]
    to_call = view.amount_to_call
    stack = view.your_stack
    if k == "fold":
        return True
    if k == "check":
        return to_call == 0
    if k == "call":
        return to_call > 0
    if k == "bet":
        return to_call == 0 and 1 <= action[1] <= stack
    if k == "raise":
        if to_call <= 0 or view.min_raise_to is None:
            return False
        return view.min_raise_to <= action[1] <= my_wager + stack
    return False


def nextMove(game_state):
    try:
        return _decide(game_state)
    except Exception:
        try:
            if game_state.amount_to_call == 0:
                return ("check",)
        except Exception:
            pass
        return ("fold",)


def _decide(view):
    t0 = time.monotonic()
    me = view.your_name
    stack = int(view.your_stack)
    to_call = int(view.amount_to_call)
    pot = int(view.pot)
    street = view.street

    if stack <= 0:
        return ("check",) if to_call == 0 else ("fold",)

    try:
        _ingest(view.hand_history)
    except Exception:
        pass
    try:
        _track_hand(view)
    except Exception:
        pass

    hole = [_cint(c) for c in view.your_hole_cards]
    board = [_cint(c) for c in view.community_cards]
    bx = _BoardCtx(board)
    my_wager = _my_wager(view.action_history, me)

    opps = []
    for p in view.seat_order:
        if p == me:
            continue
        stt = view.player_status.get(p)
        if stt == "folded":
            continue
        opps.append(p)

    if not opps:
        return ("check",) if to_call == 0 else ("call",)

    locked = [view.player_status.get(p) == "all_in" or view.player_stacks.get(p, 0) <= 0 for p in opps]
    looses = [_loose(p) for p in opps]
    pools = [_draw_pool(_range_threshold(p, street)) for p in opps]
    nopp = len(opps)

    if to_call == 0 and all(locked):
        return ("check",)

    budget = 26000.0 / (1.0 + 2.0 * nopp)
    sims = int(budget)
    if sims < 400:
        sims = 400
    if sims > 5000:
        sims = 5000
    deadline = t0 + 0.50
    samples = _sample(hole, board, pools, sims, deadline, bx)
    if not samples:
        return ("check",) if to_call == 0 else ("fold",)

    urand = [[_RNG.random() for _ in range(nopp)] for _ in range(len(samples))]

    share = _showdown_share(samples)
    my_score = _evaluate(hole + board) if bx.n >= 3 else 0
    my_tier = _tier_of(hole[0], hole[1], bx, my_score) if bx.n >= 3 else _pf_tier(
        _PCT_OF[(hole[0], hole[1]) if hole[0] < hole[1] else (hole[1], hole[0])]
    )
    curcat = (my_score >> 20) if bx.n >= 3 else 0
    p_imp = _improve_prob(samples, curcat) if street != "river" else 0.0

    seats = list(view.seat_order)
    try:
        di = seats.index(view.dealer)
        mypos = (seats.index(me) - di) % len(seats)
        last = True
        for p in opps:
            if (seats.index(p) - di) % len(seats) > mypos:
                last = False
                break
    except Exception:
        last = False

    aggr_field = 0.0
    for p in opps:
        aggr_field += _aggro(p)
    aggr_field = aggr_field / max(1, nopp)
    loose_avg = sum(looses) / float(nopp)

    best_action = None
    best_ev = None

    if to_call == 0:
        base = _ev_aggressive(samples, urand, pot, 0, 0.0, looses, locked)
        check_ev = share * pot
        if base > check_ev:
            check_ev = base
        best_action = ("check",)
        best_ev = check_ev
        cands = []
        if pot > 0:
            for f in (0.22, 0.35, 0.5, 0.7, 0.95, 1.4, 2.2):
                cands.append(int(pot * f))
        for f in (0.02, 0.035, 0.055, 0.085, 0.13, 0.2, 0.32):
            cands.append(int(stack * f))
        if my_tier >= 7 or share > 0.86:
            cands.append(stack)
        seen = set()
        sized = []
        for b in cands:
            if b < 1:
                b = 1
            if b > stack:
                b = stack
            if b in seen:
                continue
            seen.add(b)
            sized.append(b)
        sized.sort()
        for b in sized:
            if time.monotonic() - t0 > 0.90:
                break
            ratio = _ratio(b, pot, stack)
            ev = _ev_aggressive(samples, urand, pot, b, ratio, looses, locked)
            slack = 0.62 - share
            if slack < 0.0:
                slack = 0.0
            ev -= b * (0.02 + 0.10 * slack)
            ev -= 0.05 * b * aggr_field * (0.5 if last else 1.0)
            if b > 0.3 * stack and share < 0.62:
                ev -= 0.25 * b
            if ev > best_ev:
                best_ev = ev
                best_action = ("bet", b)
    else:
        best_action = ("fold",)
        best_ev = 0.0
        call_cost = to_call if to_call < stack else stack
        ev_call = _ev_call(samples, pot, call_cost)
        if street == "river":
            realize = 1.0
        elif street == "turn":
            realize = 0.94
        elif street == "flop":
            realize = 0.90
        else:
            realize = 0.86
        if last:
            realize += 0.05
        else:
            realize -= 0.03 * (1 if nopp >= 2 else 0)
        if my_tier >= 6:
            realize += 0.06
        elif my_tier >= 3:
            realize += 0.02
        if realize > 1.0:
            realize = 1.0
        ev_call -= share * (1.0 - realize) * (pot + call_cost)
        if street != "river" and 3 <= my_tier <= 5 and p_imp > 0.0:
            eff = min(stack, min(view.player_stacks.get(p, 0) for p in opps) if opps else stack)
            gain = min(1.1 * (pot + call_cost), 0.32 * eff)
            ev_call += 0.42 * p_imp * gain * (loose_avg / 1.0) * (1.15 if last else 0.9)
        if street != "river" and 3 <= my_tier <= 5 and nopp >= 2:
            ev_call -= 0.10 * call_cost * (nopp - 1)
        ev_call -= 0.03 * call_cost
        if call_cost > 0.35 * stack and share < 0.55:
            ev_call -= 0.2 * call_cost
        if ev_call > best_ev:
            best_ev = ev_call
            best_action = ("call",)
        if view.min_raise_to is not None:
            maxto = my_wager + stack
            targets = set()
            targets.add(int(view.min_raise_to))
            for f in (0.45, 0.7, 1.0, 1.5):
                targets.add(int(my_wager + to_call + f * (pot + to_call)))
            if share > 0.8 or my_tier >= 7:
                targets.add(maxto)
            for tt in sorted(targets):
                if time.monotonic() - t0 > 1.05:
                    break
                if tt < view.min_raise_to:
                    tt = int(view.min_raise_to)
                if tt > maxto:
                    tt = maxto
                if tt < view.min_raise_to or tt > maxto:
                    continue
                risk = tt - my_wager
                if risk <= 0:
                    continue
                ratio = _ratio(risk, pot, stack)
                ev = _ev_aggressive(samples, urand, pot, risk, ratio, looses, locked)
                slack = 0.66 - share
                if slack < 0.0:
                    slack = 0.0
                ev -= risk * (0.025 + 0.10 * slack)
                ev -= 0.05 * risk * aggr_field
                if risk > 0.3 * stack and share < 0.66:
                    ev -= 0.3 * risk
                if risk > 0.6 * stack and share < 0.78:
                    ev -= 0.5 * risk
                if ev > best_ev:
                    best_ev = ev
                    best_action = ("raise", int(tt))

    if not _legal(view, best_action, my_wager):
        if best_action[0] == "raise":
            best_action = ("call",)
        elif best_action[0] == "bet":
            best_action = ("check",)
    if not _legal(view, best_action, my_wager):
        best_action = ("check",) if to_call == 0 else ("fold",)
    return best_action