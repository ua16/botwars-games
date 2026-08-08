# team_optimal_bot.py
# BotWars Final Round - No-Limit Texas Hold'em (8 players)
# Optimized strategy using hand strength, equity simulation, and position-aware aggression.

import random
import itertools
from collections import Counter

# ---------- Constants ----------
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))  # 2..14 (A=14)
STARTING_STACK = 50000
OPEN_RAISE_SIZE = 1000       # standard open raise (2% of stack)
POT_BET_FRACTION = 0.75      # standard bet size as fraction of pot
MAX_SIMULATIONS = 800        # equity sim count (adjust for speed)
BLUFF_FREQ = 0.10            # bluff when equity is low

# ---------- Hand Evaluation (copied from engine for self-containment) ----------
def _straight_high(ranks):
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
    unique = sorted(set(unique), reverse=True)
    for i in range(len(unique) - 4):
        window = unique[i:i+5]
        if window[0] - window[4] == 4:
            return window[0]
    return None

def _evaluate_five(cards):
    ranks = sorted((c[1] for c in cards), reverse=True)
    suits = [c[0] for c in cards]
    counts = Counter(ranks)
    by_freq = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(ranks)

    if is_flush and straight_high:
        return (8, straight_high)                     # straight flush
    if by_freq[0][1] == 4:
        return (7, by_freq[0][0], by_freq[1][0])      # four of a kind
    if by_freq[0][1] == 3 and by_freq[1][1] == 2:
        return (6, by_freq[0][0], by_freq[1][0])      # full house
    if is_flush:
        return (5, *ranks)                            # flush
    if straight_high:
        return (4, straight_high)                     # straight
    if by_freq[0][1] == 3:
        trips = by_freq[0][0]
        kickers = [r for r in ranks if r != trips]
        return (3, trips, *kickers)                   # three of a kind
    if by_freq[0][1] == 2 and by_freq[1][1] == 2:
        hi, lo = max(by_freq[0][0], by_freq[1][0]), min(by_freq[0][0], by_freq[1][0])
        kicker = [r for r in ranks if r not in (hi, lo)][0]
        return (2, hi, lo, kicker)                    # two pair
    if by_freq[0][1] == 2:
        pair = by_freq[0][0]
        kickers = [r for r in ranks if r != pair]
        return (1, pair, *kickers)                    # one pair
    return (0, *ranks)                                 # high card

def best_hand(hole, board):
    """Return the best 5-card hand rank tuple from hole+board."""
    all_cards = list(hole) + list(board)
    best = None
    for combo in itertools.combinations(all_cards, 5):
        score = _evaluate_five(combo)
        if best is None or score > best:
            best = score
    return best

# ---------- Equity Simulation ----------
def build_deck():
    return [(s, r) for s in SUITS for r in RANKS]

def estimate_equity(hole, board, num_opponents, num_sim=MAX_SIMULATIONS):
    """
    Estimate probability that our hand wins against random opponents.
    Returns (win_prob, tie_prob) as fractions.
    """
    if num_opponents == 0:
        return 1.0, 0.0

    # Known cards: hole + board
    known = set(hole) | set(board)
    deck = [c for c in build_deck() if c not in known]
    remaining_board = 5 - len(board)  # cards still to come

    wins = 0
    ties = 0
    our_rank = best_hand(hole, board)

    for _ in range(num_sim):
        # Shuffle deck (in-place) and deal opponent hands and board cards
        random.shuffle(deck)
        idx = 0
        opp_hands = []
        for _ in range(num_opponents):
            opp_hands.append(deck[idx:idx+2])
            idx += 2
        board_cards = board + deck[idx:idx+remaining_board]
        idx += remaining_board

        # Evaluate all opponents
        best_opp_rank = None
        for opp_hole in opp_hands:
            opp_rank = best_hand(opp_hole, board_cards)
            if best_opp_rank is None or opp_rank > best_opp_rank:
                best_opp_rank = opp_rank

        # Compare our rank (using the full board) with best opponent
        our_rank_full = best_hand(hole, board_cards)
        if our_rank_full > best_opp_rank:
            wins += 1
        elif our_rank_full == best_opp_rank:
            ties += 1

    total = num_sim
    return wins / total, ties / total

# ---------- Preflop Hand Strength (simple ranking) ----------
def preflop_score(hole):
    """Return a numeric strength score for two hole cards (higher = better)."""
    ranks = sorted([c[1] for c in hole], reverse=True)
    suited = hole[0][0] == hole[1][0]
    r1, r2 = ranks[0], ranks[1]
    # Premium pairs
    if r1 == r2:
        if r1 >= 10: return 9   # AA-TT
        if r1 >= 7: return 7    # 99-77
        if r1 >= 4: return 5    # 66-44
        return 3                # 33-22
    # Suited high cards
    if suited:
        if r1 == 14 and r2 >= 12: return 8   # AKs, AQs
        if r1 == 14 and r2 >= 10: return 7   # AJs, ATs
        if r1 == 13 and r2 == 12: return 7   # KQs
        if r1 >= 12 and r2 >= 10: return 6   # QJs, JTs
        if r1 == 14 and r2 >= 6: return 6    # A6s+
        if r1 >= 10 and r2 >= 8: return 5    # T9s, 98s
        return 4
    else:
        if r1 == 14 and r2 == 13: return 7   # AKo
        if r1 == 14 and r2 >= 12: return 6   # AQo, AJo
        if r1 == 14 and r2 >= 10: return 5   # ATo
        if r1 == 13 and r2 == 12: return 5   # KQo
        if r1 >= 12 and r2 >= 10: return 4   # QJo, JTo
        if r1 == 14: return 4                # A9o+
        return 2

def should_raise_preflop(hand_score, position, players_left):
    """
    position: 0 = earliest (UTG), higher = later.
    players_left: number of players still to act after us.
    """
    # Tighten up as position gets worse (earlier)
    if position <= 1:  # early
        threshold = 7
    elif position <= 3:  # middle
        threshold = 6
    else:  # late
        threshold = 5
    # Adjust for number of opponents left to act (more opponents = tighter)
    if players_left >= 6:
        threshold += 1
    elif players_left <= 2:
        threshold -= 1
    return hand_score >= threshold

# ---------- Main Bot Logic ----------
def nextMove(gameState):
    # Extract view
    hole = gameState.your_hole_cards
    board = gameState.community_cards
    stack = gameState.your_stack
    pot = gameState.pot
    to_call = gameState.amount_to_call
    min_raise = gameState.min_raise_to
    street = gameState.street
    position = gameState.seat_order.index(gameState.your_name)
    num_players = len(gameState.seat_order)
    active_players = [p for p in gameState.seat_order if gameState.player_status[p] != 'folded']
    num_active = len(active_players)
    # Number of players still to act (including us? We are action_on)
    # We compute players_left_to_act as number of active players after us in rotation.
    # Since action_on is us, we can count how many active players are after us.
    # But for preflop open raise, we want to know how many players can still act after we act.
    # Simple: use num_active - 1 (excluding ourselves) as a rough indicator.
    players_left = num_active - 1

    # ----- Preflop -----
    if street == "preflop":
        hand_score = preflop_score(hole)
        # If we are first to act or facing no bet
        if to_call == 0:
            if should_raise_preflop(hand_score, position, players_left):
                # Raise to open size
                raise_size = max(OPEN_RAISE_SIZE, min_raise if min_raise else OPEN_RAISE_SIZE)
                raise_size = min(raise_size, stack)
                return ("raise", raise_size)
            else:
                return ("check",)
        else:
            # Facing a bet
            # If we have a strong hand, raise; if mediocre, call; else fold.
            if hand_score >= 8:
                # Premium: raise
                raise_size = max(OPEN_RAISE_SIZE * 2, min_raise if min_raise else OPEN_RAISE_SIZE * 2)
                raise_size = min(raise_size, stack)
                if raise_size > to_call:
                    return ("raise", raise_size)
                else:
                    return ("call",)
            elif hand_score >= 6:
                # Good hand: call if bet is reasonable
                if to_call <= stack * 0.1:
                    return ("call",)
                else:
                    # If too large, fold unless we have good odds
                    pot_odds = to_call / (pot + to_call)
                    # Rough equity vs random: preflop we estimate ~hand_score/10
                    equity = (hand_score / 10.0) * 0.9  # discount
                    if equity >= pot_odds:
                        return ("call",)
                    else:
                        return ("fold",)
            else:
                # Weak hand: fold unless we are in steal position and pot odds good
                if players_left <= 2 and to_call <= stack * 0.05:
                    # Late position steal attempt
                    return ("call",)
                else:
                    return ("fold",)

    # ----- Postflop (flop, turn, river) -----
    else:
        # Compute our absolute hand strength (rank tuple)
        our_rank = best_hand(hole, board)
        # Estimate equity via simulation
        num_opponents = num_active - 1
        if num_opponents == 0:
            # Only us left, we win
            return ("check",) if to_call == 0 else ("call",)
        win_prob, tie_prob = estimate_equity(hole, board, num_opponents, MAX_SIMULATIONS)
        equity = win_prob + 0.5 * tie_prob

        # Basic pot odds
        pot_odds = to_call / (pot + to_call) if pot + to_call > 0 else 0

        # If we can check
        if to_call == 0:
            # Bet if we have a strong hand or bluff
            if equity > 0.6:
                # Strong hand: bet for value
                bet_size = int(max(POT_BET_FRACTION * pot, OPEN_RAISE_SIZE))
                bet_size = min(bet_size, stack)
                if bet_size > 0:
                    return ("bet", bet_size)
                else:
                    return ("check",)
            elif equity > 0.35:
                # Medium strength: check
                return ("check",)
            else:
                # Weak: bluff occasionally
                if random.random() < BLUFF_FREQ and pot > 0:
                    bluff_size = int(max(POT_BET_FRACTION * pot, OPEN_RAISE_SIZE))
                    bluff_size = min(bluff_size, stack)
                    if bluff_size > 0:
                        return ("bet", bluff_size)
                return ("check",)

        # Facing a bet
        else:
            # If we have a very strong hand, raise
            if equity > 0.7:
                raise_size = int(max(POT_BET_FRACTION * (pot + to_call), min_raise if min_raise else OPEN_RAISE_SIZE))
                raise_size = min(raise_size, stack)
                if raise_size > to_call:
                    return ("raise", raise_size)
                else:
                    return ("call",)
            # If equity is good, call
            elif equity > pot_odds + 0.05:   # small margin
                return ("call",)
            # If equity is marginal, consider calling if pot odds are good
            elif equity > pot_odds - 0.05 and to_call <= stack * 0.2:
                return ("call",)
            # Otherwise fold, but maybe bluff-raise if we have a draw and pot is big
            elif equity > 0.25 and pot > 3 * to_call and random.random() < 0.1:
                # Semi-bluff raise
                raise_size = int(max(POT_BET_FRACTION * (pot + to_call), min_raise if min_raise else OPEN_RAISE_SIZE))
                raise_size = min(raise_size, stack)
                if raise_size > to_call:
                    return ("raise", raise_size)
                else:
                    return ("call",)
            else:
                return ("fold",)

# ---------- (Optional) For testing, include a main guard ----------
if __name__ == "__main__":
    # This won't be used in tournament, but can be used for local testing.
    print("Bot loaded.")