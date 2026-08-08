# BotWars 2026 Qualifier - Team Calit
# German Whist Bot
#
# ---------------------------------------------------------------------------
# STEP 1: Information tracking + hand-diff reconciliation foundation.
# STEP 2: Phase-1 recruitment strategy (cost-aware EV + suit building).
# STEP 3: Phase-2 hybrid engine:
#           - exact opponent hand known  -> memoized minimax (perfect play)
#           - uncertain                  -> Monte Carlo over sampled hands with
#                                           a greedy rollout policy
#
# The nextMove() function is stateless, but this module persists for the whole
# tournament, so we keep game state in module-level TRACKER and reset it when a
# new game is detected.
#
# Observability constraint (verified against engine.py):
#   - We ALWAYS see our own hand and the current face-up card.
#   - We see the opponent's card only when THEY lead (it sits in current_trick).
#   - We NEVER see the opponent's card on tricks WE lead.
#   => the opponent's hand is a superset reconstruction; Monte Carlo marginalizes
#      over the remaining uncertainty.
# ---------------------------------------------------------------------------

import random

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))              # 2..14, 14 = Ace
FULL_DECK = [(s, r) for s in SUITS for r in RANKS]

# --- Hand-tuned constants ---
TRUMP_BONUS = 3          # extra value for trump cards (critical in Phase 2)
SUIT_FIT_PER_CARD = 1    # bonus per card we already hold in the face-up's suit
TRUMP_SURPLUS = 4        # holding this many trumps => lead/draw trumps
HIGH_TRUMP_RANK = 12     # Queen+ trump face-up is "high"

# Phase-2 search constants
N_SIMS = 60              # Monte Carlo samples per candidate move
MAX_MINIMAX_CARDS = 9    # only run exact minimax when opp hand is this small
ROLLOUT_TAIL = 0         # in MC rollouts, solve the last N cards-per-hand exactly
                         # with minimax instead of greedy (0 = pure greedy rollout)
USE_VOID_CONSTRAINTS = False  # exclude provably-void suits from MC opp sampling

# Dedicated RNG so Monte Carlo never perturbs the engine's global random state.
_RNG = random.Random(20260722)


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------
def _fresh_tracker():
    return {
        'active': False,                 # seen at least one trick this game?
        'trump_suit': None,
        # Snapshot of the previous call (for hand-diff reconciliation)
        'prev_hand': None,               # our hand at start of previous trick
        'prev_played': None,             # card we played previous trick
        'prev_face_up': None,            # face-up card during previous trick
        'prev_phase': None,              # phase during previous call
        # Accumulated knowledge
        'our_recruitment_plays': [],     # cards we played in Phase 1
        'seen_opp_recruitment_plays': [],  # opp Phase-1 cards we saw (opp led)
        'our_scoring_plays': [],         # cards we played in Phase 2
        'seen_opp_scoring_plays': [],    # opp Phase-2 cards we saw (opp led)
        'our_hidden_draws': [],          # hidden stock cards we received
        'face_up_winners': [],           # (face_up_card, 'me'|'opp') per trick
        'recruitment_tricks_reconciled': 0,
        # Phase-2 trick history (for void inference)
        'prev_tricks_us': 0,             # our trick count at the previous call
        'prev_we_led': False,            # did we lead the previous trick?
        'phase2_led_results': [],        # (led_card, we_won) for tricks we led
    }


TRACKER = _fresh_tracker()


def _reset():
    """Reset TRACKER in place (keeps external references valid)."""
    TRACKER.clear()
    TRACKER.update(_fresh_tracker())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_new_game(gs):
    """Trick 1 of recruitment is the only time phase==1 and stock_remaining==25
    (stock_remaining starts at 25 and drops by 2 each recruitment trick)."""
    return gs.phase == 1 and gs.stock_remaining == 25


def _multiset_diff(a, b):
    """Elements of list a not accounted for by list b (multiset difference).
    Guarded so an inconsistent state can never raise (avoids forfeits)."""
    result = list(a)
    for x in b:
        if x in result:
            result.remove(x)
    return result


def _legal_cards(hand, lead_card):
    """Mirror of engine.legal_cards: must follow suit if possible."""
    if lead_card is None:
        return list(hand)
    lead_suit = lead_card[0]
    same = [c for c in hand if c[0] == lead_suit]
    return same if same else list(hand)


def _resolve_trick(lead_card, follow_card, trump):
    """Mirror of engine.resolve_trick: True if the LEAD card wins the trick."""
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card
    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    elif follow_suit == trump:
        return False
    else:
        return True


def _suit_counts(cards):
    counts = {s: 0 for s in SUITS}
    for c in cards:
        counts[c[0]] += 1
    return counts


def _longest_suit(cards):
    counts = _suit_counts(cards)
    return max(counts, key=lambda s: counts[s])


def _shortest_suit(cards):
    counts = _suit_counts(cards)
    present = {s: n for s, n in counts.items() if n > 0}
    return min(present, key=lambda s: present[s])


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
def _reconcile(gs):
    """Deduce the previous trick's outcome from the change in our hand.

    Only recruitment tricks have a draw, so we only reconcile when the previous
    call was phase 1 (this also covers the recruitment->scoring boundary, where
    the previous trick was the last recruitment trick).
    """
    if not TRACKER['active']:
        return
    if TRACKER['prev_phase'] != 1:
        return  # previous trick was a scoring trick: no draw to reconcile

    prev_hand = TRACKER['prev_hand']
    prev_played = TRACKER['prev_played']
    prev_face_up = TRACKER['prev_face_up']

    # Our hand just after playing last trick, before drawing:
    after_play = _multiset_diff(prev_hand, [prev_played])
    # The drawn card is whatever is in the current hand but not in after_play:
    received_list = _multiset_diff(gs.your_hand, after_play)

    if not received_list:
        return  # no draw observed (defensive; shouldn't happen for Phase 1)
    received = received_list[0]

    if received == prev_face_up:
        winner = 'me'
    else:
        winner = 'opp'
        TRACKER['our_hidden_draws'].append(received)

    TRACKER['face_up_winners'].append((prev_face_up, winner))
    TRACKER['recruitment_tricks_reconciled'] += 1


# ---------------------------------------------------------------------------
# Direct observation
# ---------------------------------------------------------------------------
def _update_seen(gs):
    """Record information directly observable at this call."""
    # When we follow, the leader is the opponent; record their lead card.
    if gs.current_trick:
        leader_name, leader_card = gs.current_trick[0]
        if leader_name == gs.opponent_name:
            if gs.phase == 1:
                TRACKER['seen_opp_recruitment_plays'].append(leader_card)
            else:
                TRACKER['seen_opp_scoring_plays'].append(leader_card)


def _update_phase2_history(gs):
    """Record the result of the previous Phase-2 trick when we led it, so we can
    later infer suits the opponent is provably void in."""
    if TRACKER['active'] and TRACKER['prev_phase'] == 2:
        tricks_us = gs.tricks_won[gs.your_name]
        we_won_last = tricks_us > TRACKER['prev_tricks_us']
        if TRACKER['prev_we_led'] and TRACKER['prev_played'] is not None:
            TRACKER['phase2_led_results'].append(
                (TRACKER['prev_played'], we_won_last))


def _store_snapshot(gs, played_card):
    """Store state needed to reconcile the next call."""
    if gs.phase == 1:
        TRACKER['our_recruitment_plays'].append(played_card)
    else:
        TRACKER['our_scoring_plays'].append(played_card)
    TRACKER['prev_hand'] = list(gs.your_hand)
    TRACKER['prev_played'] = played_card
    TRACKER['prev_face_up'] = gs.face_up_card
    TRACKER['prev_phase'] = gs.phase
    TRACKER['prev_tricks_us'] = gs.tricks_won[gs.your_name]
    TRACKER['prev_we_led'] = (len(gs.current_trick) == 0)
    TRACKER['active'] = True


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------
def reconstruct_opponent_candidates(gs):
    """Phase-2 START candidate set (used by the tracking test). Superset of the
    true opening hand: also contains opponent recruitment plays we didn't see."""
    known_out = set()
    known_out.update(gs.your_hand)
    known_out.update(TRACKER['our_recruitment_plays'])
    known_out.update(TRACKER['seen_opp_recruitment_plays'])
    return [c for c in FULL_DECK if c not in known_out]


def _opponent_candidates_now(gs):
    """Dynamic candidate set for the opponent's CURRENT hand during Phase 2.

    Removes every card we know is NOT in the opponent's hand right now:
    our current hand, all our discards/plays, and opponent plays we observed.
    The remainder is a superset of the opponent's current hand (it also includes
    the opponent's plays we never saw).
    """
    known_out = set()
    known_out.update(gs.your_hand)
    known_out.update(TRACKER['our_recruitment_plays'])
    known_out.update(TRACKER['our_scoring_plays'])
    known_out.update(TRACKER['seen_opp_recruitment_plays'])
    known_out.update(TRACKER['seen_opp_scoring_plays'])
    return [c for c in FULL_DECK if c not in known_out]


def _opp_hand_pool(gs):
    """Return (pool, opp_size): the candidate pool and how many of those cards
    the opponent currently holds."""
    k = len(gs.your_hand)
    pool = _opponent_candidates_now(gs)
    if gs.current_trick:        # opponent already played their lead this trick
        return pool, k - 1
    return pool, k


def _opp_void_suits(pool):
    """Suits the opponent is provably void in.

    If we led the highest remaining card of a suit and LOST the trick, the
    opponent could not have followed suit (no higher card of that suit was
    available to them), so they must have trumped -> they are void in that suit.
    Conservative: only ever marks a void when certain."""
    voids = set()
    for led_card, we_won in TRACKER['phase2_led_results']:
        if we_won:
            continue
        suit, rank = led_card
        if not any(c[0] == suit and c[1] > rank for c in pool):
            voids.add(suit)
    return voids


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------
def _card_value(card, trump):
    v = card[1]
    if card[0] == trump:
        v += TRUMP_BONUS
    return v


def _face_up_value(card, hand, trump):
    v = card[1]
    if card[0] == trump:
        v += TRUMP_BONUS
    v += SUIT_FIT_PER_CARD * sum(1 for c in hand if c[0] == card[0])
    return v


def _hidden_expected_value(gs):
    """Expected rank of the hidden stock card: average of the unknown pool."""
    known = set()
    known.update(gs.your_hand)
    known.update(TRACKER['our_recruitment_plays'])
    known.update(TRACKER['seen_opp_recruitment_plays'])
    known.update(TRACKER['our_hidden_draws'])
    for fu, _ in TRACKER['face_up_winners']:
        known.add(fu)
    if gs.face_up_card is not None:
        known.add(gs.face_up_card)

    unknown = [c for c in FULL_DECK if c not in known]
    if not unknown:
        return 8.0
    return sum(c[1] for c in unknown) / len(unknown)


def _cheapest_winning_card(hand, lead_card, trump):
    """As follower, the lowest-rank card that wins the trick, or None."""
    lead_suit, lead_rank = lead_card
    same_suit = [c for c in hand if c[0] == lead_suit]
    if same_suit:
        winners = [c for c in same_suit if c[1] > lead_rank]
        if winners:
            return min(winners, key=lambda c: c[1])
        return None
    trumps = [c for c in hand if c[0] == trump]
    if trumps:
        return min(trumps, key=lambda c: c[1])
    return None


# ---------------------------------------------------------------------------
# Phase 1: Recruitment strategy
# ---------------------------------------------------------------------------
def _recruitment_follow(gs, fu_val, hid_ev):
    trump = gs.trump_suit
    lead_card = gs.current_trick[0][1]
    legal = _legal_cards(gs.your_hand, lead_card)

    lose_card = min(legal, key=lambda c: _card_value(c, trump))
    win_card = _cheapest_winning_card(gs.your_hand, lead_card, trump)

    if win_card is None:
        return lose_card

    benefit = (fu_val - hid_ev) - (
        _card_value(win_card, trump) - _card_value(lose_card, trump))
    return win_card if benefit > 0 else lose_card


def _recruitment_lead(gs, fu_val, hid_ev):
    hand = gs.your_hand
    trump = gs.trump_suit
    want_to_win = fu_val > hid_ev

    trumps = [c for c in hand if c[0] == trump]
    non_trumps = [c for c in hand if c[0] != trump]
    face_up = gs.face_up_card
    face_up_is_high_trump = (
        face_up is not None and face_up[0] == trump and face_up[1] >= HIGH_TRUMP_RANK)

    if want_to_win:
        if face_up_is_high_trump and trumps:
            return max(trumps, key=lambda c: c[1])
        if len(trumps) >= TRUMP_SURPLUS:
            return max(trumps, key=lambda c: c[1])
        if non_trumps:
            longest = _longest_suit(non_trumps)
            suit_cards = [c for c in non_trumps if c[0] == longest]
            return max(suit_cards, key=lambda c: c[1])
        return max(trumps, key=lambda c: c[1])

    if non_trumps:
        shortest = _shortest_suit(non_trumps)
        suit_cards = [c for c in non_trumps if c[0] == shortest]
        return min(suit_cards, key=lambda c: c[1])
    return min(trumps, key=lambda c: c[1])


def _recruitment_play(gs):
    fu_val = _face_up_value(gs.face_up_card, gs.your_hand, gs.trump_suit)
    hid_ev = _hidden_expected_value(gs)
    if gs.current_trick:
        return _recruitment_follow(gs, fu_val, hid_ev)
    return _recruitment_lead(gs, fu_val, hid_ev)


# ---------------------------------------------------------------------------
# Phase 2: greedy policy (rollout policy + safe fallback)
# ---------------------------------------------------------------------------
def _greedy_play(hand, trump, lead_card):
    """Fast greedy choice used for Monte Carlo rollouts (both players)."""
    legal = _legal_cards(hand, lead_card)
    if lead_card is not None:
        win = _cheapest_winning_card(hand, lead_card, trump)
        if win is not None:
            return win
        return min(legal, key=lambda c: _card_value(c, trump))
    trumps = [c for c in hand if c[0] == trump]
    non_trumps = [c for c in hand if c[0] != trump]
    if len(trumps) >= TRUMP_SURPLUS:
        return max(trumps, key=lambda c: c[1])
    if non_trumps:
        longest = _longest_suit(non_trumps)
        suit_cards = [c for c in non_trumps if c[0] == longest]
        return max(suit_cards, key=lambda c: c[1])
    return max(trumps, key=lambda c: c[1])


def _scoring_play_greedy(gs):
    """One-step greedy heuristic (rollout policy and safe fallback)."""
    lead_card = gs.current_trick[0][1] if gs.current_trick else None
    return _greedy_play(gs.your_hand, gs.trump_suit, lead_card)


# ---------------------------------------------------------------------------
# Phase 2: Monte Carlo rollout
# ---------------------------------------------------------------------------
def _rollout(our_hand, opp_hand, trump, us_to_play, lead_card, leader_is_us,
             tricks_us, tricks_them):
    """Play the rest of Phase 2 with both hands known. Plays a greedy body, then
    hands off to exact minimax once both hands shrink to ROLLOUT_TAIL cards
    (ROLLOUT_TAIL=0 means a pure greedy rollout). Returns the game score from
    our view: 1.0 win, 0.5 draw, 0.0 loss."""
    our_hand = list(our_hand)
    opp_hand = list(opp_hand)

    while our_hand or opp_hand:
        if ROLLOUT_TAIL and len(our_hand) <= ROLLOUT_TAIL and len(opp_hand) <= ROLLOUT_TAIL:
            return _minimax(our_hand, opp_hand, trump, us_to_play, lead_card,
                            leader_is_us, tricks_us, tricks_them, {})
        if lead_card is None:
            # Leader plays.
            if us_to_play:
                c = _greedy_play(our_hand, trump, None)
                our_hand.remove(c)
                lead_card, leader_is_us, us_to_play = c, True, False
            else:
                c = _greedy_play(opp_hand, trump, None)
                opp_hand.remove(c)
                lead_card, leader_is_us, us_to_play = c, False, True
        else:
            # Follower plays, then the trick resolves.
            if us_to_play:
                c = _greedy_play(our_hand, trump, lead_card)
                our_hand.remove(c)
            else:
                c = _greedy_play(opp_hand, trump, lead_card)
                opp_hand.remove(c)
            lead_wins = _resolve_trick(lead_card, c, trump)
            we_win = lead_wins if leader_is_us else (not lead_wins)
            if we_win:
                tricks_us += 1
            else:
                tricks_them += 1
            us_to_play, leader_is_us, lead_card = we_win, we_win, None

    if tricks_us > tricks_them:
        return 1.0
    if tricks_us < tricks_them:
        return 0.0
    return 0.5


def _best_move_mc(gs, legal, pool, opp_size):
    """Monte Carlo move selection: for each legal move, average the greedy
    rollout outcome over N_SIMS sampled opponent hands; pick the best."""
    trump = gs.trump_suit
    tricks_us = gs.tricks_won[gs.your_name]
    tricks_them = gs.tricks_won[gs.opponent_name]
    following = bool(gs.current_trick)
    lead_card = gs.current_trick[0][1] if following else None

    if USE_VOID_CONSTRAINTS:
        voids = _opp_void_suits(pool)
        if voids:
            filtered = [c for c in pool if c[0] not in voids]
            if len(filtered) >= opp_size:   # guard: never shrink below opp_size
                pool = filtered

    best_score = -1.0
    best_move = legal[0]
    for m in legal:
        our_after = list(gs.your_hand)
        our_after.remove(m)
        if following:
            lead_wins = _resolve_trick(lead_card, m, trump)
            we_win = not lead_wins          # opponent led
            t_us = tricks_us + (1 if we_win else 0)
            t_them = tricks_them + (0 if we_win else 1)
            next_us, next_lead, next_leader = we_win, None, we_win
        else:
            t_us, t_them = tricks_us, tricks_them
            next_us, next_lead, next_leader = False, m, True

        total = 0.0
        for _ in range(N_SIMS):
            opp_hand = _RNG.sample(pool, opp_size) if opp_size > 0 else []
            total += _rollout(our_after, opp_hand, trump,
                              next_us, next_lead, next_leader, t_us, t_them)
        avg = total / N_SIMS
        if avg > best_score:
            best_score = avg
            best_move = m
    return best_move


# ---------------------------------------------------------------------------
# Phase 2: exact minimax (opponent hand fully known)
# ---------------------------------------------------------------------------
def _minimax(our_hand, opp_hand, trump, us_to_play, lead_card, leader_is_us,
             tricks_us, tricks_them, memo):
    """Perfect-information zero-sum minimax. Returns our final game score
    (1.0 win / 0.5 draw / 0.0 loss) under optimal play by both sides."""
    if not our_hand and not opp_hand:
        if tricks_us > tricks_them:
            return 1.0
        if tricks_us < tricks_them:
            return 0.0
        return 0.5

    key = (tuple(sorted(our_hand)), tuple(sorted(opp_hand)), us_to_play,
           lead_card, leader_is_us, tricks_us, tricks_them)
    if key in memo:
        return memo[key]

    if us_to_play:
        best = -1.0
        for c in _legal_cards(our_hand, lead_card):
            nh = list(our_hand)
            nh.remove(c)
            if lead_card is None:
                v = _minimax(nh, opp_hand, trump, False, c, True,
                             tricks_us, tricks_them, memo)
            else:
                we_win = not _resolve_trick(lead_card, c, trump)  # opp led
                v = _minimax(nh, opp_hand, trump, we_win, None, we_win,
                             tricks_us + (1 if we_win else 0),
                             tricks_them + (0 if we_win else 1), memo)
            if v > best:
                best = v
                if best == 1.0:
                    break
    else:
        best = 2.0
        for c in _legal_cards(opp_hand, lead_card):
            nh = list(opp_hand)
            nh.remove(c)
            if lead_card is None:
                v = _minimax(our_hand, nh, trump, True, c, False,
                             tricks_us, tricks_them, memo)
            else:
                we_win = _resolve_trick(lead_card, c, trump)      # we led
                v = _minimax(our_hand, nh, trump, we_win, None, we_win,
                             tricks_us + (1 if we_win else 0),
                             tricks_them + (0 if we_win else 1), memo)
            if v < best:
                best = v
                if best == 0.0:
                    break

    memo[key] = best
    return best


def _best_move_exact(gs, legal, opp_hand):
    """Pick the move maximizing the minimax game score with a known opp hand."""
    trump = gs.trump_suit
    tricks_us = gs.tricks_won[gs.your_name]
    tricks_them = gs.tricks_won[gs.opponent_name]
    following = bool(gs.current_trick)
    lead_card = gs.current_trick[0][1] if following else None
    memo = {}

    best_score = -1.0
    best_move = legal[0]
    for m in legal:
        nh = list(gs.your_hand)
        nh.remove(m)
        if following:
            we_win = not _resolve_trick(lead_card, m, trump)
            v = _minimax(nh, list(opp_hand), trump, we_win, None, we_win,
                         tricks_us + (1 if we_win else 0),
                         tricks_them + (0 if we_win else 1), memo)
        else:
            v = _minimax(nh, list(opp_hand), trump, False, m, True,
                         tricks_us, tricks_them, memo)
        if v > best_score:
            best_score = v
            best_move = m
    return best_move


# ---------------------------------------------------------------------------
# Phase 2: hybrid dispatch
# ---------------------------------------------------------------------------
def _scoring_play_smart(gs):
    lead_card = gs.current_trick[0][1] if gs.current_trick else None
    legal = _legal_cards(gs.your_hand, lead_card)
    if len(legal) == 1:
        return legal[0]

    pool, opp_size = _opp_hand_pool(gs)
    if opp_size < 0 or len(pool) < opp_size:
        return _scoring_play_greedy(gs)   # defensive

    if len(pool) == opp_size:
        # Opponent hand fully determined.
        if opp_size <= MAX_MINIMAX_CARDS:
            return _best_move_exact(gs, legal, list(pool))
        return _scoring_play_greedy(gs)   # exact but too large to solve

    return _best_move_mc(gs, legal, pool, opp_size)


def _scoring_play(gs):
    """Hybrid Phase-2 play with a safe greedy fallback so a search bug can
    never cause a forfeit."""
    try:
        return _scoring_play_smart(gs)
    except Exception:
        return _scoring_play_greedy(gs)


# ---------------------------------------------------------------------------
# Dispatch + entry point
# ---------------------------------------------------------------------------
def _choose_play(gs):
    if gs.phase == 1:
        return _recruitment_play(gs)
    return _scoring_play(gs)


def nextMove(gameState):
    if _is_new_game(gameState):
        _reset()
    else:
        _reconcile(gameState)
        _update_phase2_history(gameState)

    _update_seen(gameState)
    TRACKER['trump_suit'] = gameState.trump_suit

    play = _choose_play(gameState)

    _store_snapshot(gameState, play)
    return play
