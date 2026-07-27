# TeamBinary player for German Whist
# Phase 2: Minimax with alpha-beta pruning + transposition table + heuristic evaluation

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))
_ALL_CARDS = {(s, r) for s in SUITS for r in RANKS}

SEARCH_DEPTH = 26 #For now calculates the total of 13 tricks, reduce for faster performance

# -------------------------
# Phase 1 heuristic config
# -------------------------
DEFAULT_WEIGHTS = {
  "base_rank_scale": 0.9089651147120565,
  "trump_adder": 15.722705462335583,
  "long_suit_threshold": 5,
  "long_suit_bonus": 1.4376178258486898,
  "short_suit_threshold": 2,
  "short_suit_penalty": -2.054916451592156,
  "control_weight": 2.9926427335215204,
  "loss_control_weight": -2.9587326671652927,
  "flexibility_threshold": 6.4177718270965185
}

# Phase-1 tracking
_phase1_initialized = False
_last_face_up = None
_last_lead = None
# Phase1 opponent tracking: known cards and unknown slot count
_opp_known_cards_phase1 = []
_opp_unknown_slots = 13
_played_out_cards = set()   # cards permanently removed from game in completed tricks
_our_last_play = None       # our last played card (to detect played_out at trick completion)
_opp_last_play = None       # opponent's last seen card from current_trick

# ---- Phase 2 state tracking ------------------------------------------------

_phase2_initialized = False
_our_hand = []
_opp_hand = []
_opp_played = set()      # cards opponent has played in phase 2
_seen_cards = set()       # all cards ever observed by this bot

_TT = {}                  # transposition table: state_key -> (score, depth)


# ============================================================================
#  Card helpers
# ============================================================================

def resolve_trick(lead_card, follow_card, trump_suit):
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card

    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    elif follow_suit == trump_suit:
        return False
    else:
        return True


def _same_suit(cards, suit):
    """Return the subset of cards that match a given suit."""
    return [c for c in cards if c[0] == suit]


def get_legal_moves(hand, lead_card, trump_suit):
    """Return legal cards ordered best-first for alpha-beta pruning.

    Leading:    rank descending (strongest first).
    Following:  cheapest winners first, then cheapest losers
                (ascending rank in both groups).
    Can't follow: cheapest trump first, then cheapest other cards.
    """
    if lead_card is None:
        return sorted(hand, key=lambda c: c[1], reverse=True)

    lead_suit = lead_card[0]
    matching = _same_suit(hand, lead_suit)

    if matching:
        lead_rank = lead_card[1]
        winners = sorted(
            [c for c in matching if c[1] > lead_rank],
            key=lambda c: c[1],
        )
        losers = sorted(
            [c for c in matching if c[1] <= lead_rank],
            key=lambda c: c[1],
        )
        return winners + losers

    trump_cards = sorted(
        [c for c in hand if c[0] == trump_suit],
        key=lambda c: c[1],
    )
    other = sorted(
        [c for c in hand if c[0] != trump_suit],
        key=lambda c: c[1],
    )
    return trump_cards + other


# ============================================================================
#  Transposition table helpers
# ============================================================================

def _make_key(our_hand, opp_hand, our_tricks, opp_tricks, current_trick, is_our_turn):
    """Build a transposition-table key for the current search state."""
    return (
        our_hand,
        opp_hand,
        our_tricks,
        opp_tricks,
        current_trick,
        is_our_turn,
    )


# ============================================================================
#  Heuristic evaluation
# ============================================================================

def evaluate(our_hand, opp_hand, our_tricks, opp_tricks, tricks_remaining, trump_suit):
    """Score a non-terminal state (higher = better for us).

    Uses suit-by-suit head-to-head comparison:
      - Batteries (our top card vs their top card) → ~0.7–1.0 expected trick
      - Extra cards in each suit → partial value based on trump status
    """
    if tricks_remaining <= 0:
        return our_tricks - opp_tricks

    score = our_tricks - opp_tricks

    # Group by suit
    our_by_suit = {s: [] for s in SUITS}
    opp_by_suit = {s: [] for s in SUITS}
    for s, r in our_hand:
        our_by_suit[s].append(r)
    for s, r in opp_hand:
        opp_by_suit[s].append(r)

    for suit in SUITS:
        our_r = sorted(our_by_suit[suit], reverse=True)
        opp_r = sorted(opp_by_suit[suit], reverse=True)

        i = j = 0
        while i < len(our_r) and j < len(opp_r):
            if our_r[i] > opp_r[j]:
                if suit == trump_suit:
                    score += 1.0
                else:
                    score += 0.7
                i += 1
                j += 1
            else:
                j += 1

        extra_us = len(our_r) - i
        extra_opp = len(opp_r) - j

        if suit == trump_suit:
            score += 0.5 * extra_us
            score -= 0.5 * extra_opp
        else:
            score += 0.3 * extra_us
            score -= 0.3 * extra_opp

    return score


# ============================================================================
#  Move application  (returns new state tuple)
# ============================================================================

def _apply_move(our_hand, opp_hand, our_tricks, opp_tricks,
                current_trick, is_our_turn, move_card, trump_suit):
    """Play *move_card* for the current player and return the next state.

    Returns  (our_hand, opp_hand, our_tricks, opp_tricks, current_trick, is_our_turn)
    all fields immutable (tuples).
    """
    our = list(our_hand)
    opp = list(opp_hand)
    trick = list(current_trick)

    if is_our_turn:
        our.remove(move_card)
    else:
        opp.remove(move_card)

    if not current_trick:
        # ---- Leading ----
        trick.append(move_card)
        return (
            tuple(sorted(our)),
            tuple(sorted(opp)),
            our_tricks,
            opp_tricks,
            tuple(trick),
            not is_our_turn,
        )

    # ---- Following — resolve the trick ----
    lead_card = current_trick[0]
    leader_wins = resolve_trick(lead_card, move_card, trump_suit)

    # leader of this trick = whoever played *into* an empty trick
    leader_is_us = not is_our_turn

    if leader_is_us:
        if leader_wins:
            return (tuple(sorted(our)), tuple(sorted(opp)),
                    our_tricks + 1, opp_tricks, (), True)
        else:
            return (tuple(sorted(our)), tuple(sorted(opp)),
                    our_tricks, opp_tricks + 1, (), False)
    else:
        if leader_wins:
            return (tuple(sorted(our)), tuple(sorted(opp)),
                    our_tricks, opp_tricks + 1, (), False)
        else:
            return (tuple(sorted(our)), tuple(sorted(opp)),
                    our_tricks + 1, opp_tricks, (), True)


# ============================================================================
#  Minimax with alpha-beta pruning
# ============================================================================

def _minimax(our_hand, opp_hand, our_tricks, opp_tricks,
             current_trick, is_our_turn, depth, alpha, beta, trump_suit):
    """Return the score (our_tricks - opp_tricks) of the best reachable outcome."""

    key = _make_key(our_hand, opp_hand, our_tricks, opp_tricks,
                    current_trick, is_our_turn)
    cached = _TT.get(key)
    if cached is not None and cached[1] >= depth:
        return cached[0]

    # Terminal
    if not our_hand and not opp_hand and not current_trick:
        score = our_tricks - opp_tricks
        _TT[key] = (score, depth)
        return score

    tricks_remaining = 13 - our_tricks - opp_tricks

    # Depth limit → heuristic
    if depth <= 0:
        score = evaluate(our_hand, opp_hand, our_tricks, opp_tricks,
                         tricks_remaining, trump_suit)
        _TT[key] = (score, depth)
        return score

    # ---- Generate ordered moves ----
    if is_our_turn:
        hand = our_hand
        maximizing = True
    else:
        hand = opp_hand
        maximizing = False

    lead_card = current_trick[0] if current_trick else None
    moves = get_legal_moves(list(hand), lead_card, trump_suit)

    if not moves:
        # No legal moves — treat as terminal (shouldn't occur with consistent state)
        score = our_tricks - opp_tricks
        _TT[key] = (score, depth)
        return score

    # ---- Search ----
    if maximizing:
        best = float('-inf')
        for move in moves:
            ns = _apply_move(our_hand, opp_hand, our_tricks, opp_tricks,
                             current_trick, is_our_turn, move, trump_suit)
            val = _minimax(ns[0], ns[1], ns[2], ns[3], ns[4], ns[5],
                           depth - 1, alpha, beta, trump_suit)
            if val > best:
                best = val
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break
        _TT[key] = (best, depth)
        return best
    else:
        best = float('inf')
        for move in moves:
            ns = _apply_move(our_hand, opp_hand, our_tricks, opp_tricks,
                             current_trick, is_our_turn, move, trump_suit)
            val = _minimax(ns[0], ns[1], ns[2], ns[3], ns[4], ns[5],
                           depth - 1, alpha, beta, trump_suit)
            if val < best:
                best = val
            if best < beta:
                beta = best
            if alpha >= beta:
                break
        _TT[key] = (best, depth)
        return best


# ============================================================================
#  Phase-1 helper (minimal – will be replaced later)
# ============================================================================

def _phase1_move(gameState, played_out):
    """Choose a Phase-1 card using the parameterized heuristic model."""
    return choose_phase1_card(gameState, DEFAULT_WEIGHTS, played_out)


# ------------------
# Phase-1 heuristics
# ------------------
def _hand_counts(hand):
    """Count how many cards of each suit are in a hand."""
    counts = {s: 0 for s in SUITS}
    for s, _ in hand:
        counts[s] += 1
    return counts


def calculate_heuristic_value(card, hand_counts, trump_suit, weights, played_out):
    """Compute effective strategic value for a single card."""
    if card is None:
        return 0.0
    suit, rank = card
    higher_removed = sum(1 for r in RANKS if r > rank and (suit, r) in played_out)
    effective_rank = rank + higher_removed
    val = effective_rank * weights['base_rank_scale']
    if suit == trump_suit:
        val += weights['trump_adder']

    cnt = hand_counts.get(suit, 0)
    if cnt >= weights['long_suit_threshold']:
        val += weights['long_suit_bonus'] * (cnt - (weights['long_suit_threshold'] - 1))
    if suit != trump_suit and cnt <= weights['short_suit_threshold']:
        val += weights['short_suit_penalty']

    return float(val)


def calculate_v_unknown(unseen_pool, hand_counts, trump_suit, weights, played_out):
    """Average heuristic value across unseen pool."""
    if not unseen_pool:
        return 0.0
    vals = [calculate_heuristic_value(c, hand_counts, trump_suit, weights, played_out) for c in unseen_pool]
    return sum(vals) / len(vals)


def calculate_lead_desire(hand, trump_suit, weights, played_out, flexibility_threshold=0.0):
    """Return a lead desirability score for flexible hands.

    Higher values mean the hand has more spread between card values, which is
    a better proxy for "I can choose to win or lose" than just being strong.
    """
    if not hand:
        return 0.0
    hand_counts = _hand_counts(hand)
    vals = [calculate_heuristic_value(c, hand_counts, trump_suit, weights, played_out) for c in hand]
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    std_dev = variance ** 0.5

    # Keep the score higher when the hand is both spread out and near the
    # middle of the heuristic range, which usually means more control.
    balance = max(0.0, 1.0 - abs(mean - 8.0) / 8.0)
    result = std_dev * balance
    if result < flexibility_threshold:
        return 0.0
    return result


def choose_phase1_card(gameState, weights, played_out):
    """Core selection loop for phase 1 following the provided spec."""
    global _seen_cards, _opp_known_cards_phase1, _opp_unknown_slots

    hand = list(gameState.your_hand)
    hand_counts = _hand_counts(hand)
    trump = gameState.trump_suit

    # unseen pool = all cards not in our hand and not yet seen
    unseen_pool = list(_ALL_CARDS - set(hand) - _seen_cards)

    # Baseline values
    target = gameState.face_up_card
    V_target = calculate_heuristic_value(target, hand_counts, trump, weights, played_out) if target is not None else 0.0
    V_unknown = calculate_v_unknown(unseen_pool, hand_counts, trump, weights, played_out)
    lead_desire = calculate_lead_desire(hand, trump, weights, played_out, weights['flexibility_threshold'])

    # legal moves ordered
    lead_card = gameState.current_trick[0][1] if gameState.current_trick else None
    legal = get_legal_moves(hand, lead_card, trump)

    best = None
    best_score = float('-inf')

    # build opponent candidates (known + unseen)
    opp_candidates = list(_opp_known_cards_phase1) + unseen_pool

    for c in legal:
        V_sacr = calculate_heuristic_value(c, hand_counts, trump, weights, played_out)

        # determine if playing c will win
        if lead_card is None:
            # we lead: check if opponent has any card that can beat c
            loses = False
            for oc in opp_candidates:
                # if opponent has oc and it beats our lead c
                if not resolve_trick(c, oc, trump):
                    loses = True
                    break
            move_wins = not loses
        else:
            # we follow; determine if our card beats the leader
            leader_wins = resolve_trick(lead_card, c, trump)
            move_wins = not leader_wins

        if move_wins:
            V_gained = V_target
            lead_mod = lead_desire * weights['control_weight']
        else:
            V_gained = V_unknown
            lead_mod = lead_desire * weights['loss_control_weight']

        net_gain = V_gained - V_sacr + lead_mod

        if net_gain > best_score:
            best_score = net_gain
            best = c

    # ensure seen updated for the chosen card (we will play it)
    if best is not None:
        _seen_cards.add(best)

    return best if best is not None else hand[0]


# ============================================================================
#  Entry point
# ============================================================================

def nextMove(gameState):
    """Choose the next move while updating tracked phase state."""
    global _our_hand, _opp_hand, _opp_played, _seen_cards, _phase2_initialized, _TT
    global _phase1_initialized, _last_face_up, _last_lead, _opp_known_cards_phase1, _opp_unknown_slots
    global _played_out_cards, _our_last_play, _opp_last_play

    # ---- Track everything we see ----
    _seen_cards.update(gameState.your_hand)
    for name, card in gameState.current_trick:
        _seen_cards.add(card)
    if gameState.face_up_card is not None:
        _seen_cards.add(gameState.face_up_card)

    # Track opponent's play from current trick for played_out detection
    for name, card in gameState.current_trick:
        if name == gameState.opponent_name:
            _opp_last_play = card

    # ---- Phase 1: tracking + action selection ----
    if gameState.phase == 1:
        # initialize phase-1 trackers on first call
        if not _phase1_initialized:
            _phase1_initialized = True
            _last_face_up = gameState.face_up_card
            _last_lead = gameState.lead
            _opp_known_cards_phase1 = []
            _opp_unknown_slots = 13

        # Detect completion of a trick by change in face_up card or lead
        # (engine updates face_up_card after resolving a trick)
        if _last_face_up is not None and _last_face_up != gameState.face_up_card:
            # previous trick finished; winner is now the current lead
            trick_winner = gameState.lead
            # determine loser name
            trick_loser = gameState.opponent_name if trick_winner == gameState.your_name else gameState.your_name

            # winner took the previous face-up card
            prev_face = _last_face_up
            if prev_face is not None:
                if trick_winner == gameState.opponent_name:
                    # opponent received the face-up card -> add to known
                    _opp_known_cards_phase1.append(prev_face)
                else:
                    # we received the face-up card; mark as seen (already added)
                    pass

            # loser received hidden card — unknown to us, track via unknown_slots
            if trick_loser == gameState.opponent_name:
                _opp_unknown_slots += 1

            # Track played-out cards from completed trick
            if _our_last_play is not None:
                _played_out_cards.add(_our_last_play)
                _our_last_play = None
            if _opp_last_play is not None:
                _played_out_cards.add(_opp_last_play)
                _opp_last_play = None

            # reset last face-up to current
            _last_face_up = gameState.face_up_card
            _last_lead = gameState.lead

        # Track opponent plays within current trick
        for name, card in gameState.current_trick:
            if name == gameState.opponent_name:
                # opponent played this card; mark as seen and remove from known if present
                _seen_cards.add(card)
                if card in _opp_known_cards_phase1:
                    _opp_known_cards_phase1.remove(card)
                else:
                    # opponent played a card that was previously unknown
                    if _opp_unknown_slots > 0:
                        _opp_unknown_slots -= 1

        # If phase will end on next transition, we will finalize opponent hand in phase2 init
        chosen = _phase1_move(gameState, _played_out_cards)
        _our_last_play = chosen
        return chosen

    # ==================================================================
    #  Phase 2  –  Minimax search
    # ==================================================================

    if not _phase2_initialized:
        _phase2_initialized = True
        _TT.clear()
        _our_hand = list(gameState.your_hand)
        _opp_played = set()

        # Build opponent hand from phase-1 tracking:
        # Known cards collected during recruitment + fill remaining slots from unknown pool.
        try:
            known = list(_opp_known_cards_phase1)
            unknown_pool = list(_ALL_CARDS - set(_our_hand) - _seen_cards - set(known))
        except NameError:
            known = []
            unknown_pool = list(_ALL_CARDS - set(_our_hand) - _seen_cards)

        unknown_pool.sort(key=lambda c: c[1], reverse=True)
        slots = 13 - len(known)
        filled = known + unknown_pool[:slots]
        # ensure length 13
        _opp_hand = filled[:13]

        # clear phase-1 trackers
        _phase1_initialized = False
        _last_face_up = None
        _last_lead = None
        _opp_known_cards_phase1 = []
        _opp_unknown_slots = 13
        _our_last_play = None
        _opp_last_play = None

    # Update tracking from current trick
    _our_hand = list(gameState.your_hand)
    for name, card in gameState.current_trick:
        if name == gameState.opponent_name:
            _opp_played.add(card)
            if card in _opp_hand:
                _opp_hand.remove(card)

    # ---- Build immutable search state ----
    our_hand_t = tuple(sorted(gameState.your_hand))
    opp_hand_t = tuple(sorted(_opp_hand))
    current_trick = tuple(card for _, card in gameState.current_trick)
    is_our_turn = True  # engine only calls our nextMove when it's our turn

    our_tricks = gameState.tricks_won[gameState.your_name]
    opp_tricks = gameState.tricks_won[gameState.opponent_name]

    # ---- Root search: pick the best move ----
    lead_card = current_trick[0] if current_trick else None
    moves = get_legal_moves(gameState.your_hand, lead_card, gameState.trump_suit)

    best_move = moves[0]
    best_score = float('-inf')
    alpha = float('-inf')
    beta = float('inf')
    trump_suit = gameState.trump_suit

    for move in moves:
        ns = _apply_move(our_hand_t, opp_hand_t, our_tricks, opp_tricks,
                         current_trick, is_our_turn, move, trump_suit)
        val = _minimax(ns[0], ns[1], ns[2], ns[3], ns[4], ns[5],
                       SEARCH_DEPTH - 1, alpha, beta, trump_suit)
        if val > best_score:
            best_score = val
            best_move = move
        if val > alpha:
            alpha = val

    return best_move
