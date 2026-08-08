"""
German Whist Bot - BotWars 2026
================================

Strategy in plain terms:
  - Phase 1 (drawing cards from the stock): play a heuristic that
    weighs whether the face-up card is worth fighting for.
  - Phase 2 (playing out the hand for real): once few enough cards
    remain, brute-force the rest of the game with minimax search,
    running it over several guesses of the opponent's hand (since we
    can't know it for certain) and going with whatever move wins most
    often across those guesses.
  - Throughout: keep track of every card we've actually seen, so our
    guesses about the opponent's hand are as good as possible, and
    detect when the opponent has run out of a suit (voids) using pure
    logic, not guesswork.
"""

import random
import time

# ---------------------------------------------------------------------
# Basic card and rule helpers
# ---------------------------------------------------------------------

# A card is a (suit, rank) pair, e.g. ("H", 14) is the Ace of Hearts.
SUITS = ("H", "D", "C", "S")
RANKS = tuple(range(2, 15))          # 2 .. 14, where 14 = Ace
FULL_DECK = frozenset((s, r) for s in SUITS for r in RANKS)

# How long we're willing to spend searching for a move.
TIME_BUDGET_SECONDS = 1.2
PER_SAMPLE_BUDGET = 0.25
EXACT_SOLVE_MAX_CARDS = 6             # hand size small enough to brute-force
SAMPLES_BY_HAND_SIZE = {1: 1, 2: 60, 3: 45, 4: 30, 5: 18, 6: 10}


def suit_of(card):
    return card[0]


def rank_of(card):
    return card[1]


def legal_moves(hand, led_card):
    """What am I allowed to play? Follow suit if I can, otherwise anything."""
    if led_card is None:
        return list(hand)
    lead_suit = suit_of(led_card)
    same_suit = [c for c in hand if suit_of(c) == lead_suit]
    return same_suit if same_suit else list(hand)


def resolve_trick(lead_card, follow_card, trump_suit):
    """Who wins the trick? Returns True if the LEAD card wins."""
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card
    if follow_suit == lead_suit:
        return lead_rank >= follow_rank      # higher card of the same suit wins
    elif follow_suit == trump_suit:
        return False                          # a trump beats a non-trump lead
    else:
        return True                           # an off-suit discard can't win


# ---------------------------------------------------------------------
# Memory: what do we actually know about the game so far?
#
# The same function gets called for every one of our turns, so we can
# remember things between calls. This is how we do card counting.
# ---------------------------------------------------------------------
_STATES = {}   # one memory bank per player name, in case the bot ever
               # plays against a copy of itself


def _fresh_state():
    return {
        "my_played": set(),        # cards we've played
        "opp_led": set(),          # opponent's cards we've directly seen
        "opp_gains": set(),        # cards we know the opponent is holding
        "opp_void_suits": set(),   # suits we've PROVEN the opponent is out of
        "last_faceup": None,       # the up-card from our previous turn
        "last_lead_suit": None,    # what we led last time we led
        "last_lead_rank": None,
        "last_lead_was_trump": None,
    }


def _get_state(view):
    """Fetch this player's memory, starting fresh at the beginning of a
    new game (stock_remaining == 25 only ever happens on turn 1)."""
    state = _STATES.get(view.your_name)
    if state is None or (view.phase == 1 and view.stock_remaining >= 25):
        state = _fresh_state()
        _STATES[view.your_name] = state
    return state


def _update_state_pre_move(view, state):
    """Before choosing a move, absorb whatever happened since our last turn."""

    # Did we win or lose the last face-up card we saw?
    if state["last_faceup"] is not None:
        if view.lead == view.opponent_name:
            # They led this trick, which means THEY won the last one -
            # so they must have taken that up-card.
            state["opp_gains"].add(state["last_faceup"])
        state["last_faceup"] = None

    # Void detection: if we led a plain (non-trump) suit and still lost,
    # the only way that's possible is if every higher card in that suit
    # is already spoken for and the opponent had to play a trump instead -
    # which only happens if they have none of that suit left.
    if state["last_lead_suit"] is not None and not state["last_lead_was_trump"]:
        if view.lead == view.opponent_name:
            suit = state["last_lead_suit"]
            higher_cards_needed = range(state["last_lead_rank"] + 1, 15)
            already_seen = (state["my_played"] | state["opp_led"] |
                             set(view.your_hand) | state["opp_gains"])
            if all((suit, r) in already_seen for r in higher_cards_needed):
                state["opp_void_suits"].add(suit)
        state["last_lead_suit"] = None
        state["last_lead_rank"] = None
        state["last_lead_was_trump"] = None

    # If we're following, we get to see exactly what the opponent led.
    if view.current_trick:
        opp_card = view.current_trick[0][1]
        state["opp_led"].add(opp_card)
        state["opp_gains"].discard(opp_card)

    # Remember today's up-card so we can figure out who won it next turn.
    state["last_faceup"] = view.face_up_card


def _record_move(state, view, chosen_card, led_card):
    """After choosing our move, remember it for next time."""
    state["my_played"].add(chosen_card)
    if led_card is None:
        state["last_lead_suit"] = suit_of(chosen_card)
        state["last_lead_rank"] = rank_of(chosen_card)
        state["last_lead_was_trump"] = (suit_of(chosen_card) == view.trump_suit)


def _candidate_pool(view, state):
    """Every card whose whereabouts we're not 100% sure of."""
    my_hand = set(view.your_hand)
    known_gone = state["my_played"] | state["opp_led"]
    pool = FULL_DECK - my_hand - known_gone - state["opp_gains"]
    filtered = {c for c in pool if suit_of(c) not in state["opp_void_suits"]}
    return pool, filtered


# ---------------------------------------------------------------------
# Exact search: "if I knew the opponent's exact hand, what's my best
# possible outcome from here?" Solved with minimax + memoization.
# ---------------------------------------------------------------------

def _minimax_value(my_hand, opp_hand, leader, trump, memo, deadline):
    if time.time() > deadline:
        raise TimeoutError
    if not my_hand and not opp_hand:
        return 0

    key = (my_hand, opp_hand, leader)
    if key in memo:
        return memo[key]

    lead_hand = my_hand if leader == "me" else opp_hand
    follower_is_me = (leader != "me")
    best = None

    for lead_card in legal_moves(lead_hand, None):
        follow_hand = opp_hand if leader == "me" else my_hand
        best_reply = None
        for follow_card in legal_moves(follow_hand, lead_card):
            lead_wins = resolve_trick(lead_card, follow_card, trump)
            winner = leader if lead_wins else ("opp" if leader == "me" else "me")
            if leader == "me":
                remaining_me, remaining_opp = my_hand - {lead_card}, opp_hand - {follow_card}
            else:
                remaining_opp, remaining_me = opp_hand - {lead_card}, my_hand - {follow_card}

            score = (1 if winner == "me" else 0) + _minimax_value(
                remaining_me, remaining_opp, winner, trump, memo, deadline)

            if best_reply is None:
                best_reply = score
            elif follower_is_me:
                best_reply = max(best_reply, score)      # we pick our best reply
            else:
                best_reply = min(best_reply, score)      # opponent picks their best reply

        if best is None:
            best = best_reply
        elif leader == "me":
            best = max(best, best_reply)
        else:
            best = min(best, best_reply)

    memo[key] = best
    return best


def _best_move_exact(my_hand, opp_hand, leading, led_card, trump, deadline):
    """Given a specific (assumed) opponent hand, what's the single best
    card to play right now?"""
    memo = {}

    if leading:
        best_card, best_score = None, None
        for card in legal_moves(my_hand, None):
            # Assume the opponent replies however hurts us most.
            worst_case = None
            for reply in legal_moves(opp_hand, card):
                lead_wins = resolve_trick(card, reply, trump)
                winner = "me" if lead_wins else "opp"
                score = (1 if winner == "me" else 0) + _minimax_value(
                    my_hand - {card}, opp_hand - {reply}, winner, trump, memo, deadline)
                if worst_case is None or score < worst_case:
                    worst_case = score
            if best_score is None or worst_case > best_score:
                best_score, best_card = worst_case, card
        return best_card

    best_card, best_score = None, None
    for card in legal_moves(my_hand, led_card):
        lead_wins = resolve_trick(led_card, card, trump)
        winner = "opp" if lead_wins else "me"
        score = (1 if winner == "me" else 0) + _minimax_value(
            my_hand - {card}, opp_hand - {led_card}, winner, trump, memo, deadline)
        if best_score is None or score > best_score:
            best_score, best_card = score, card
    return best_card


def _monte_carlo_choice(view, hand_list, led_card, trump, state, deadline):
    """We don't know the opponent's exact hand, so guess it several
    times (consistent with everything we've actually observed), solve
    each guess exactly, and go with whichever move comes out on top
    most often."""
    my_hand = frozenset(hand_list)
    pool, filtered = _candidate_pool(view, state)
    opp_hand_size = len(hand_list)              # both hands are always equal in size
    unknown_cards_needed = max(0, opp_hand_size - len(state["opp_gains"]))

    usable_pool = list(filtered) if len(filtered) >= unknown_cards_needed else list(pool)
    hand_is_fully_known = len(usable_pool) == unknown_cards_needed
    num_samples = 1 if hand_is_fully_known else SAMPLES_BY_HAND_SIZE.get(opp_hand_size, 8)

    votes = {}
    for _ in range(num_samples):
        if time.time() > deadline:
            break
        if len(usable_pool) >= unknown_cards_needed:
            guessed_unknowns = random.sample(usable_pool, unknown_cards_needed)
        else:
            guessed_unknowns = usable_pool
        guessed_opp_hand = frozenset(state["opp_gains"] | set(guessed_unknowns))

        sample_deadline = min(deadline, time.time() + PER_SAMPLE_BUDGET)
        try:
            card = _best_move_exact(my_hand, guessed_opp_hand, led_card is None,
                                     led_card, trump, sample_deadline)
        except TimeoutError:
            continue
        if card is not None:
            votes[card] = votes.get(card, 0) + 1

    if not votes:
        return None
    return max(votes.items(), key=lambda item: item[1])[0]


# ---------------------------------------------------------------------
# Heuristic play - used in phase 1, and as a fallback in phase 2 when
# there are still too many cards left to search exactly.
# ---------------------------------------------------------------------

def _phase1_heuristic(view, legal, led_card, trump, state):
    upcard = view.face_up_card
    upcard_is_worth_fighting_for = upcard is not None and (
        rank_of(upcard) >= 12 or suit_of(upcard) == trump)

    if led_card is None:
        non_trump = [c for c in legal if suit_of(c) != trump] or legal

        # If the opponent is void in a suit, leading it is a free hit or
        # forces them to burn a trump.
        void_leads = [c for c in non_trump if suit_of(c) in state["opp_void_suits"]]
        if void_leads:
            return max(void_leads, key=rank_of)

        if upcard_is_worth_fighting_for:
            return max(non_trump, key=rank_of)   # go for it
        return min(legal, key=rank_of)             # don't bother, play cheap

    # We're following.
    can_win_with = [c for c in legal if not resolve_trick(led_card, c, trump)]
    if upcard_is_worth_fighting_for and can_win_with:
        return min(can_win_with, key=rank_of)       # win as cheaply as possible
    non_trump = [c for c in legal if suit_of(c) != trump] or legal
    return min(non_trump, key=rank_of)               # let it go, discard low


def _phase2_heuristic(legal, led_card, trump, state):
    if led_card is None:
        non_trump = [c for c in legal if suit_of(c) != trump] or legal
        void_leads = [c for c in non_trump if suit_of(c) in state["opp_void_suits"]]
        if void_leads:
            return max(void_leads, key=rank_of)
        return min(non_trump, key=rank_of)

    can_win_with = [c for c in legal if not resolve_trick(led_card, c, trump)]
    if can_win_with:
        return min(can_win_with, key=rank_of)
    non_trump = [c for c in legal if suit_of(c) != trump] or legal
    return min(non_trump, key=rank_of)


def _heuristic_move(view, legal, led_card, trump, state):
    if view.phase == 2:
        return _phase2_heuristic(legal, led_card, trump, state)
    return _phase1_heuristic(view, legal, led_card, trump, state)


# ---------------------------------------------------------------------
# Putting it all together
# ---------------------------------------------------------------------

def _choose_move(view, hand, led_card, trump, state, legal):
    if len(legal) == 1:
        return legal[0]     # only one option, no need to think

    # Late in the scoring phase, few enough cards remain that we can
    # actually search the rest of the game out.
    if view.phase == 2 and len(hand) <= EXACT_SOLVE_MAX_CARDS:
        deadline = time.time() + TIME_BUDGET_SECONDS
        try:
            card = _monte_carlo_choice(view, hand, led_card, trump, state, deadline)
            if card is not None and card in legal:
                return card
        except Exception:
            pass  # if anything goes wrong, fall through to the heuristic

    return _heuristic_move(view, legal, led_card, trump, state)


def nextMove(gameState):
    """Entry point the tournament engine calls on every one of our turns."""
    try:
        view = gameState
        state = _get_state(view)
        _update_state_pre_move(view, state)

        hand = list(view.your_hand)
        trick = list(view.current_trick)
        led_card = trick[0][1] if trick else None
        trump = view.trump_suit

        legal = legal_moves(hand, led_card)
        chosen = _choose_move(view, hand, led_card, trump, state, legal)
        if chosen not in legal:
            chosen = legal[0]     # safety net, should never trigger

        _record_move(state, view, chosen, led_card)
        return chosen

    except Exception:
        # No matter what goes wrong above, always return a legal card
        # rather than crashing or forfeiting.
        hand = list(gameState.your_hand)
        trick = list(gameState.current_trick)
        led_card = trick[0][1] if trick else None
        legal = legal_moves(hand, led_card)
        return legal[0] if legal else hand[0]
