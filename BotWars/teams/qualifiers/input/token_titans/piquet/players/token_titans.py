SUITS = ('H', 'D', 'C', 'S')
ALL32 = frozenset((s, r) for s in SUITS for r in range(7, 15))
_mem  = {}

def _get_m(gs):
    name = gs.your_name
    m    = _mem.get(name)
    hl   = len(getattr(gs, 'hand_history', []))
    if m is None or (gs.phase == 'exchange' and m.get('hl', -1) != hl):
        m = {'hl': hl, 'seen': set(), 'last': None}
        _mem[name] = m
    return m

def _sync(m, gs):
    if m['last'] is not None:
        m['seen'].add(m['last'])
        m['last'] = None
    for pname, card in (list(gs.current_trick) if gs.current_trick else []):
        if pname == gs.opponent_name:
            m['seen'].add(card)

def _suit_score(cards):
    ranks = sorted(c[1] for c in cards)
    best = run = 1
    for i in range(1, len(ranks)):
        if ranks[i] == ranks[i-1] + 1: run += 1
        else:                           run  = 1
        best = max(best, run)
    pip = sum(11 if r == 14 else 10 if r >= 10 else r for r in ranks)
    return (best, len(cards), pip)

def _exchange(gs):
    hand     = list(gs.your_hand)
    is_elder = gs.your_name == gs.elder
    max_disc = 5 if is_elder else (gs.talon_remaining or 0)
    if max_disc == 0 or not hand:
        return []

    by_suit  = {}
    for c in hand:
        by_suit.setdefault(c[0], []).append(c)

    by_rank = {}
    for c in hand:
        if c[1] >= 10:
            by_rank[c[1]] = by_rank.get(c[1], 0) + 1

    quad_ranks = {r for r, cnt in by_rank.items() if cnt >= 4}
    protected  = {c for c in hand if c[1] in quad_ranks}

    best_s = max(by_suit, key=lambda s: _suit_score(by_suit[s]))

    cands = [c for c in hand if c[0] != best_s and c not in protected]
    cands.sort(key=lambda c: (1 if c[1] == 14 else 0, c[1]))

    seen = set()
    out  = []
    for c in cands[:max_disc]:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def _has_seq(hand):
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], set()).add(c[1])
    for ranks in by_suit.values():
        sr  = sorted(ranks)
        run = 1
        for i in range(1, len(sr)):
            if sr[i] == sr[i-1] + 1:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 1
    return False

def _has_set(hand):
    cnt = {}
    for c in hand:
        if c[1] >= 10:
            cnt[c[1]] = cnt.get(c[1], 0) + 1
    return max(cnt.values(), default=0) >= 3

def _declare(gs):
    hand = gs.your_hand
    cat  = gs.declare_category
    if cat == 'point':
        return ('claim',)
    if cat == 'sequence':
        return ('claim',) if _has_seq(hand) else 'pass'
    if cat == 'set':
        return ('claim',) if _has_set(hand) else 'pass'
    return 'pass'

def _is_boss(card, hand_set, seen):
    s, r = card
    for h in range(r + 1, 15):
        c = (s, h)
        if c not in hand_set and c not in seen:
            return False
    return True

def _dump_score(card, hand, hand_set, seen):
    s, r = card
    if r == 14:                            return -200
    if _is_boss(card, hand_set, seen):     return -100
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c[0], []).append(c)
    suit_len = len(by_suit.get(s, []))
    return -r - suit_len * 0.5

def _lead(hand, seen, tricks_me, tricks_opp):
    hand_set = set(hand)
    by_suit  = {}
    for c in hand:
        by_suit.setdefault(c[0], []).append(c)

    opp_poss = ALL32 - hand_set - seen

    bosses = [c for c in hand if _is_boss(c, hand_set, seen)]
    if bosses:
        b_by_suit = {}
        for c in bosses:
            b_by_suit.setdefault(c[0], []).append(c)
        best_bs = max(
            b_by_suit,
            key=lambda s: (len(b_by_suit[s]), len(by_suit.get(s, [])))
        )
        return max(b_by_suit[best_bs], key=lambda c: c[1])

    for s in sorted(by_suit, key=lambda s: -len(by_suit[s])):
        if not any(c[0] == s for c in opp_poss):
            return min(by_suit[s], key=lambda c: c[1])

    longest = max(
        by_suit.values(),
        key=lambda cards: (len(cards), max(c[1] for c in cards))
    )
    return max(longest, key=lambda c: c[1])

def _follow(hand, lead_card, hand_set, seen):
    ls, lr = lead_card
    same   = [c for c in hand if c[0] == ls]
    if same:
        wins = [c for c in same if c[1] > lr]
        return min(wins, key=lambda c: c[1]) if wins else min(same, key=lambda c: c[1])
    return max(hand, key=lambda c: _dump_score(c, hand, hand_set, seen))

def _trick(gs, m):
    hand     = list(gs.your_hand)
    hand_set = set(hand)
    trick    = list(gs.current_trick) if gs.current_trick else []
    me       = gs.your_name
    tw       = gs.tricks_won or {}
    tricks_me  = tw.get(me, 0)
    tricks_opp = tw.get(gs.opponent_name, 0)

    if not trick:
        choice = _lead(hand, m['seen'], tricks_me, tricks_opp)
    else:
        choice = _follow(hand, trick[0][1], hand_set, m['seen'])

    m['last'] = choice
    return choice

def nextMove(gs):
    try:
        m = _get_m(gs)
        _sync(m, gs)
        if gs.phase == 'exchange': return _exchange(gs)
        if gs.phase == 'declare':  return _declare(gs)
        return _trick(gs, m)
    except Exception:
        hand  = list(gs.your_hand)
        phase = gs.phase
        if phase == 'exchange':
            return []
        if phase == 'declare':
            return 'pass'
        trick = list(gs.current_trick) if gs.current_trick else []
        if trick:
            same = [c for c in hand if c[0] == trick[0][1][0]]
            return same[0] if same else (hand[0] if hand else None)
        return hand[0] if hand else None