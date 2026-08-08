SUITS     = ('H','D','S','C')
ALL_CARDS = frozenset((s,r) for s in SUITS for r in range(2,15))

def suit(c): return c[0]
def rv(c):   return c[1]
def cv(c, trump): return rv(c) + (20 if suit(c)==trump else 0)

def beats(mine, theirs, trump):
    ms, ts = suit(mine), suit(theirs)
    if trump:
        if ms==trump and ts!=trump: return True
        if ts==trump and ms!=trump: return False
    if ms==ts: return rv(mine) > rv(theirs)
    return False

def win_cheaply(pool, opp, trump):
    ws = [c for c in pool if beats(c, opp, trump)]
    return min(ws, key=lambda c: cv(c,trump)) if ws else None

def is_boss(card, accounted):
    s, r = card
    return all((s,h) in accounted for h in range(r+1,15))

def highest_longest(hand, trump):
    suits = {}
    for c in hand:
        if suit(c) != trump:
            suits.setdefault(suit(c), []).append(c)
    if not suits:
        suits = {}
        for c in hand: suits.setdefault(suit(c),[]).append(c)
    return max(max(suits.values(), key=len), key=rv)



mem = {}

def get_mem(gs):
    name  = getattr(gs, 'your_name', 'p')
    stk   = getattr(gs, 'stock_remaining', None)
    phase = getattr(gs, 'phase', None)
    m     = mem.get(name)
    if m is None or (phase==1 and stk is not None and stk>=25):
        m = {'disc': set(), 'last': None}
        mem[name] = m
    return m

def update(m, gs, hand_set, trick):
    if m['last'] is not None:
        m['disc'].add(m['last']); m['last'] = None
    opp = getattr(gs, 'opponent_name', None)
    for pname, card in trick:
        if opp is None or pname == opp:
            m['disc'].add(card)
    fu = getattr(gs, 'face_up_card', None)
    if fu: m['disc'].add(fu)

def accounted(m, hand): return set(hand) | m['disc']
def opp_hand(m, hand):  return ALL_CARDS - set(hand) - m['disc']



def p1_want(fu, trump):
    """Fight for trump (any) or Q+ of non-trump. Conservative — preserves good cards."""
    if fu is None: return False
    return suit(fu) == trump or rv(fu) >= 12

def p1_follow(legal, opp_c, trump, want):
    if want:
        w = win_cheaply(legal, opp_c, trump)
        return w if w else min(legal, key=lambda c: cv(c,trump))
    losers = [c for c in legal if not beats(c, opp_c, trump)]
    if losers:
        nt = [c for c in losers if suit(c) != trump]
        return min((nt or losers), key=rv)
    return min(legal, key=lambda c: cv(c,trump))

def p1_lead(hand, trump, want):
    nt = [c for c in hand if suit(c) != trump]
    pool = nt if nt else hand
    return max(pool, key=rv) if want else min(pool, key=rv)



def p2_lead(hand, m, trump):
    acc   = accounted(m, hand)
    opp_h = opp_hand(m, hand)
    my_tr  = [c for c in hand  if suit(c)==trump]
    opp_tr = [c for c in opp_h if suit(c)==trump]
    t_boss = [c for c in my_tr if is_boss(c, acc)]

    if t_boss and opp_tr and len(my_tr) >= 4:
        return max(t_boss, key=rv)
    if not opp_tr:
        bosses = [c for c in hand if is_boss(c, acc)]
        if bosses: return max(bosses, key=rv)
    return highest_longest(hand, trump)

def p2_follow(legal, opp_c, trump, hand, m):
    w = win_cheaply(legal, opp_c, trump)
    if w: return w
    acc   = accounted(m, hand)
    opp_h = opp_hand(m, hand)
    def dump_score(c):
        if suit(c)==trump:  return -2000
        if is_boss(c, acc): return -1000
        op_s = [x for x in opp_h if suit(x)==suit(c)]
        return max((rv(x) for x in op_s), default=0) - rv(c)
    return max(legal, key=dump_score)



def nextMove(gameState):
    hand  = list(gameState.your_hand)
    trick = list(gameState.current_trick) if gameState.current_trick else []
    trump = gameState.trump_suit
    phase = getattr(gameState, 'phase', None)
    fu    = getattr(gameState, 'face_up_card', None)

    m = get_mem(gameState)
    update(m, gameState, set(hand), trick)

    if phase is None: phase = 1 if fu is not None else 2

    if trick:
        ls    = trick[0][1][0]
        same  = [c for c in hand if suit(c)==ls]
        legal = same if same else hand
        opp_c = trick[0][1]
    else:
        legal = hand; opp_c = None
    if not legal: legal = hand

    if phase == 2:
        if trick: return p2_follow(legal, opp_c, trump, hand, m)
        else:     return p2_lead(hand, m, trump)

    want = p1_want(fu, trump)
    if trick: return p1_follow(legal, opp_c, trump, want)
    else:     return p1_lead(hand, trump, want)
