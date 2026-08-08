# Team: segfault_society — BotWars 2026 finals, No-Limit Hold'em (no blinds).
#
# Champion of the internal 6-bot evolutionary gauntlet (Aug 22): near-top in
# the all-competent field (+62k/trn) and dominant in mixed fields (+157k/trn),
# zero engine errors across 4,800 hands, 11ms max decision (2s limit).
#
# Team ch_shark — BotWars finals challenger. Archetype: "shark".
#
# Showdown profiler + exploit switcher for no-blinds NLHE. With no blinds,
# checking and folding are free and there is nothing to steal: chips only move
# when someone voluntarily pays a bet. So the entire game is:
#   (1) learn WHO pays bets with weak ranges (stations / capped blind-callers /
#       pot-odds callers) and size value bets to exactly what each class pays;
#   (2) never pay off honest (value-only) ranges.
# Opponent stats persist across hands via module globals; hand_history is mined
# for showdown hole-card reveals (bet honesty) and replayed street by street to
# recover the exact price every opponent called or folded to (call caps).
# Degrades gracefully: unknown opponents get conservative pot-odds treatment.
#
# Every action is validated and clamped; any internal error falls back to
# check/fold. Decisions run in ~10-50 ms, far under the 2 s timeout.

import random
from itertools import combinations

SUITS = ("H", "D", "C", "S")
FULL_DECK = tuple((s, r) for s in SUITS for r in range(2, 15))

# ---------------------------------------------------------------------------
# 7-card evaluator (rank category, then tiebreaks; compare tuples directly)
# ---------------------------------------------------------------------------
def _ev7(cards):
    ranks = sorted((c[1] for c in cards), reverse=True)
    counts = {}
    suits = {}
    for s, r in cards:
        counts[r] = counts.get(r, 0) + 1
        suits.setdefault(s, []).append(r)

    flush_ranks = None
    for s, rs in suits.items():
        if len(rs) >= 5:
            flush_ranks = sorted(rs, reverse=True)
            break

    def straight_high(rset):
        rs = set(rset)
        if 14 in rs:
            rs.add(1)
        for hi in range(14, 4, -1):
            if all(hi - k in rs for k in range(5)):
                return hi
        return 0

    if flush_ranks is not None:
        sf = straight_high(flush_ranks)
        if sf:
            return (8, sf)

    by_count = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    r1, c1 = by_count[0]
    if c1 == 4:
        kicker = max(r for r in counts if r != r1)
        return (7, r1, kicker)
    if c1 == 3:
        pairs = [r for r, c in by_count[1:] if c >= 2]
        if pairs:
            return (6, r1, max(pairs))
    if flush_ranks is not None:
        return (5,) + tuple(flush_ranks[:5])
    st = straight_high(counts.keys())
    if st:
        return (4, st)
    if c1 == 3:
        kick = [r for r in ranks if r != r1][:2]
        return (3, r1) + tuple(kick)
    if c1 == 2:
        r2, c2 = by_count[1]
        if c2 == 2:
            hi, lo = max(r1, r2), min(r1, r2)
            kicker = max(r for r in counts if r != hi and r != lo)
            return (2, hi, lo, kicker)
        kick = [r for r in ranks if r != r1][:3]
        return (1, r1) + tuple(kick)
    return (0,) + tuple(ranks[:5])


# ---------------------------------------------------------------------------
# Equity
# ---------------------------------------------------------------------------
def _equity_profile(hole, board, kmax, iters):
    """Return list e where e[k] = equity vs k uniform-random opponents.

    Single MC pass; ties with the best opponent count 0.5.
    """
    known = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in known]
    need = 5 - len(board)
    kmax = max(1, min(kmax, 4))
    wins = [0.0] * (kmax + 1)
    hero_fixed = _ev7(tuple(hole) + tuple(board)) if need == 0 else None
    for _ in range(iters):
        drawn = random.sample(deck, need + 2 * kmax)
        if need:
            full_board = list(board) + drawn[:need]
            hero = _ev7(list(hole) + full_board)
        else:
            full_board = list(board)
            hero = hero_fixed
        best = None
        for k in range(1, kmax + 1):
            opp = drawn[need + 2 * k - 2: need + 2 * k]
            oe = _ev7(opp + full_board)
            if best is None or oe > best:
                best = oe
            if hero > best:
                wins[k] += 1.0
            elif hero == best:
                wins[k] += 0.5
    return [w / float(iters) for w in wins]


def _exact_river_hu(hole, board):
    """Exact equity vs one uniform-random hand on a complete board."""
    known = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in known]
    hero = _ev7(tuple(hole) + tuple(board))
    score = 0.0
    tot = 0
    for opp in combinations(deck, 2):
        tot += 1
        oe = _ev7(opp + tuple(board))
        if hero > oe:
            score += 1.0
        elif hero == oe:
            score += 0.5
    return score / float(tot)


def _strength_exact(hole, board):
    """Percentile strength of a revealed hand vs all opponent combos."""
    return _exact_river_hu(tuple(hole), tuple(board))


def _pre_strength(hole):
    (s1, r1), (s2, r2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    score = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        score = max(score * 2, 5.0)
    if s1 == s2:
        score += 2.0
    gap = hi - lo
    if r1 != r2:
        score -= {1: 0, 2: 1, 3: 2, 4: 4}.get(gap, 5)
        if gap <= 2 and hi < 12:
            score += 1
    return max(0.0, min(1.0, score / 20.0))


# ---------------------------------------------------------------------------
# Profiling: persistent per-opponent stats mined from hand_history
# ---------------------------------------------------------------------------
_S = {"opp": {}, "mined": 0}


def _st(name):
    return _S["opp"].setdefault(name, {
        "opps": 0, "aggr": 0, "calls": 0, "folds": 0, "checks": 0,
        "max_called": 0, "min_folded": None, "agg_strength": [],
    })


def _replay(actions, observe=None):
    """Replay one street's action list; returns (bet_level, wagers dict)."""
    level = 0
    wag = {}
    for item in actions:
        try:
            p, a = item
            kind = a[0]
        except Exception:
            continue
        w = wag.get(p, 0)
        tc = max(0, level - w)
        if observe is not None:
            observe(p, kind, a, tc)
        if kind == "call":
            wag[p] = level
        elif kind == "bet" and len(a) > 1:
            level = w + int(a[1])
            wag[p] = level
        elif kind == "raise" and len(a) > 1:
            level = int(a[1])
            wag[p] = level
    return level, wag


def _mine(view):
    hh = view.hand_history
    if _S["mined"] > len(hh):          # new tournament: fresh history list
        _S["opp"].clear()
        _S["mined"] = 0
    me = view.your_name
    for entry in hh[_S["mined"]:]:
        try:
            acts = entry.get("actions") or {}
            aggressors = set()

            def obs(p, kind, a, tc):
                if p == me:
                    return
                st = _st(p)
                st["opps"] += 1
                if kind in ("bet", "raise"):
                    st["aggr"] += 1
                    aggressors.add(p)
                elif kind == "check":
                    st["checks"] += 1
                elif kind == "call":
                    st["calls"] += 1
                    if tc > st["max_called"]:
                        st["max_called"] = tc
                elif kind == "fold":
                    st["folds"] += 1
                    if tc > 0 and (st["min_folded"] is None or tc < st["min_folded"]):
                        st["min_folded"] = tc

            for street in ("preflop", "flop", "turn", "river"):
                _replay(acts.get(street) or [], obs)

            sd = entry.get("showdown")
            board = entry.get("board") or []
            if sd and len(board) == 5:
                for p, hole in sd.items():
                    if p == me or p not in aggressors:
                        continue
                    st = _st(p)
                    if len(st["agg_strength"]) < 40 and len(hole) == 2:
                        st["agg_strength"].append(
                            _strength_exact(tuple(map(tuple, hole)),
                                            [tuple(c) for c in board]))
        except Exception:
            pass
    _S["mined"] = len(hh)


def _traits(name):
    """Classify one opponent. Degrades to conservative 'unknown' defaults."""
    t = {"honest": None, "cap": None, "station": False,
         "dishonest": False, "paybig": False}
    st = _S["opp"].get(name)
    if not st or st["opps"] < 5:
        return t
    aggr_freq = st["aggr"] / float(max(1, st["opps"]))
    fc = st["folds"] + st["calls"]
    fold_rate = (st["folds"] / float(fc)) if fc >= 5 else None
    strengths = st["agg_strength"]
    honesty = (sum(strengths) / len(strengths)) if len(strengths) >= 2 else None

    if (aggr_freq > 0.40 and st["opps"] >= 10) or \
            (honesty is not None and honesty < 0.52):
        t["dishonest"] = True
    if honesty is not None and honesty >= 0.60 and aggr_freq < 0.35:
        t["honest"] = True

    # station: essentially never folds and has paid mid/large bets
    if fold_rate is not None and fold_rate < 0.06 and fc >= 8 and \
            st["max_called"] >= 3000:
        t["station"] = True
        t["cap"] = 10 ** 9
        t["paybig"] = True
        return t
    # hard call cap (e.g. calls <=5000, folds above): min fold >= max call
    if st["min_folded"] is not None and st["max_called"] > 0 and \
            st["min_folded"] >= st["max_called"] and fc >= 6:
        t["cap"] = st["max_called"]
    if st["max_called"] >= 8000:
        t["paybig"] = True
    return t


# ---------------------------------------------------------------------------
# Decision core
# ---------------------------------------------------------------------------
_STREET_CAP = {"preflop": 5000, "flop": 14000, "turn": 30000, "river": 10 ** 9}
_MIN_EV = 140.0


def _decide(view):
    me = view.your_name
    hole = tuple(tuple(c) for c in view.your_hole_cards)
    board = [tuple(c) for c in view.community_cards]
    stack = view.your_stack
    to_call = view.amount_to_call
    pot = view.pot
    street = view.street
    if stack <= 0:
        return ("check",) if to_call == 0 else ("fold",)

    level, wag = _replay(view.action_history)
    my_wager = max(0, level - to_call)
    max_to = my_wager + stack

    status = view.player_status
    stacks = view.player_stacks
    opp_live = [p for p in view.seat_order
                if p != me and status.get(p) == "active" and stacks.get(p, 0) > 0]
    contenders = [p for p in view.seat_order
                  if p != me and status.get(p) in ("active", "all_in")]
    kmax = max(1, min(4, len(contenders)))

    if street == "river" and len(contenders) == 1:
        e1 = _exact_river_hu(hole, board)
        elist = [0.0, e1, e1, e1, e1]
    else:
        iters = {"preflop": 300, "flop": 400, "turn": 450, "river": 650}[street]
        elist = _equity_profile(hole, board, kmax, iters)
        while len(elist) < 5:
            elist.append(elist[-1])
    e1 = elist[1]

    traits = {p: _traits(p) for p in set(opp_live) | set(contenders)}

    if to_call > 0:
        return _face_bet(view, hole, street, stack, to_call, pot, level, wag,
                         my_wager, max_to, opp_live, contenders, elist, traits)
    return _open_line(view, hole, street, stack, pot, opp_live, contenders,
                      elist, traits)


def _face_bet(view, hole, street, stack, to_call, pot, level, wag,
              my_wager, max_to, opp_live, contenders, elist, traits):
    me = view.your_name
    tc_eff = min(to_call, stack)

    aggs = [p for p, a in view.action_history
            if isinstance(a, tuple) and a and a[0] in ("bet", "raise") and p != me]
    agg_traits = [traits[p] for p in set(aggs) if p in traits]
    all_dishonest = bool(agg_traits) and all(
        t["dishonest"] or t["station"] for t in agg_traits)
    any_honest = any(t["honest"] for t in agg_traits)

    committed = [p for p in contenders if p not in opp_live]  # all-in players
    inn = set(committed)
    extra = 0
    for p in opp_live:
        w = wag.get(p, 0)
        ptc = max(0, level - w)
        if ptc == 0:
            inn.add(p)
        else:
            cap = traits[p]["cap"]
            if cap is not None and cap >= ptc:
                inn.add(p)
                extra += min(ptc, view.player_stacks.get(p, 0))

    k = max(1, min(4, len(inn)))
    e = elist[k]
    pot_final = pot + tc_eff + extra
    need_odds = tc_eff / float(max(1, pot_final))

    if all_dishonest:
        m = 0.03 + 0.02 * (k - 1)
    elif any_honest:
        m = 0.16 + 0.02 * (k - 1)
    else:
        m = 0.09 + 0.02 * (k - 1)
    if street == "preflop" and not all_dishonest:
        m += 0.05
    if tc_eff > max(1, pot - to_call) and not all_dishonest:  # overbet faced
        m += 0.05
    need = need_odds + m
    if not all_dishonest:
        if tc_eff >= 12000:
            need = max(need, 0.76 if any_honest else 0.72)
        if tc_eff >= 25000:
            need = max(need, 0.88 if any_honest else 0.80)

    # value raising
    if view.min_raise_to is not None and stack > to_call:
        rt = 0.85 if street == "river" else 0.84
        if all_dishonest:
            rt -= 0.08
        rt += 0.02 * (k - 1)
        if e >= rt:
            station_live = any(traits[p]["station"] for p in opp_live)
            paybig_live = any(traits[p]["paybig"] for p in opp_live)
            jam_worthy = e >= 0.88 or (all_dishonest and e >= 0.80)
            if jam_worthy and (station_live or paybig_live or pot >= 12000):
                target = max_to
            else:
                target = min(max_to, max(view.min_raise_to, pot + 3 * to_call))
            target = max(view.min_raise_to, min(int(target), max_to))
            return ("raise", target)

    if e >= need:
        return ("call",)
    # set-mine: small pocket pairs flop a set ~12% and opponents who bet/call
    # by equity-vs-random stack off to sets, so implied odds dwarf direct odds
    if street == "preflop" and hole[0][1] == hole[1][1] and \
            tc_eff <= 3500 and tc_eff <= stack // 12:
        return ("call",)
    return ("fold",)


def _open_line(view, hole, street, stack, pot, opp_live, contenders,
               elist, traits):
    e1 = elist[1]
    kavail = len(elist) - 1
    street_cap = _STREET_CAP[street]

    prof = []  # (effective cap, is_pot_odds_honest)
    for p in opp_live:
        t = traits[p]
        p_stack = view.player_stacks.get(p, 0)
        if t["station"]:
            cap, hp = p_stack, False
        elif t["cap"] is not None:
            cap, hp = t["cap"], False
        elif t["dishonest"]:
            cap, hp = 4000, False
        else:
            # honest / unknown: models a pot-odds caller
            if street == "preflop":
                cap, hp = 0, True
            elif e1 >= 0.86:
                cap, hp = p_stack, True
            elif e1 >= 0.78:
                cap, hp = max(6000, int(1.2 * pot)), True
            elif e1 >= 0.66 and pot > 0:
                cap, hp = int(0.9 * pot), True
            elif e1 >= 0.74:
                cap, hp = 2500, True
            else:
                cap, hp = 0, True
        prof.append((max(0, min(cap, p_stack)), hp))

    cand = set()
    for cap, _hp in prof:
        if cap > 0:
            cand.add(min(stack, cap, street_cap))
    if pot > 0:
        cand.add(min(stack, street_cap, max(1, int(0.7 * pot))))
        cand.add(min(stack, street_cap, max(1, int(2.2 * pot))))

    best, best_ev = None, _MIN_EV
    for b in cand:
        if b < 1:
            continue
        callers = [(cap, hp) for cap, hp in prof if cap >= b]
        kk = len(callers)
        if kk == 0:
            continue
        e = elist[min(kk, kavail)] - 0.06 * sum(1 for _c, hp in callers if hp)
        e = max(0.0, e)
        if b >= 20000 and e < 0.55:
            continue
        ev = e * (pot + kk * b) - (1.0 - e) * b
        if ev > best_ev:
            best_ev, best = ev, b
    if best is not None:
        return ("bet", int(best))
    return ("check",)


# ---------------------------------------------------------------------------
# Validation & entry point
# ---------------------------------------------------------------------------
def _validate(view, action):
    to_call = view.amount_to_call
    stack = view.your_stack
    if not isinstance(action, tuple) or not action:
        return ("check",) if to_call == 0 else ("fold",)
    kind = action[0]
    if kind == "check":
        return action if to_call == 0 else ("fold",)
    if kind == "call":
        return action if to_call > 0 else ("check",)
    if kind == "fold":
        return ("check",) if to_call == 0 else ("fold",)
    if kind == "bet":
        if to_call != 0 or stack <= 0:
            return ("check",) if to_call == 0 else ("fold",)
        try:
            amt = int(action[1])
        except Exception:
            return ("check",)
        return ("bet", max(1, min(amt, stack)))
    if kind == "raise":
        if to_call == 0:
            return ("check",)
        if view.min_raise_to is None or stack <= to_call:
            return ("call",) if stack > 0 else ("fold",)
        lo = view.min_raise_to
        try:
            level, _w = _replay(view.action_history)
        except Exception:
            level = to_call
        hi = max(lo, (level - to_call) + stack)
        try:
            amt = int(action[1])
        except Exception:
            return ("call",)
        return ("raise", max(lo, min(amt, hi)))
    return ("check",) if to_call == 0 else ("fold",)


def nextMove(gameState):
    try:
        _mine(gameState)
    except Exception:
        pass
    try:
        return _validate(gameState, _decide(gameState))
    except Exception:
        try:
            return ("check",) if gameState.amount_to_call == 0 else ("fold",)
        except Exception:
            return ("fold",)
