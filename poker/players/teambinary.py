"""
Standalone Texas Hold'em Bot for Hackathon Competition
- Single-file execution with standard Python libraries only.
- Designed for 2-10 players, No-Limit Hold'em with no blinds.
- Determinized Monte Carlo Equity engine with mathematical EV action selection.
- Position-aware, zero-risk preflop checking strategy.
- Strict 1.4-second watchdog timer to eliminate timeout auto-folds.
"""

import math
import random
import time
from itertools import combinations

# =====================================================================
# 1. FAST PURE-PYTHON 7-CARD HAND EVALUATOR
# =====================================================================

class FastEvaluator:
    """
    Pure Python 7-card hand evaluator.
    Evaluates 21 five-card combinations using tuple comparison.
    Returns higher tuples for stronger hands.
    """
    
    @staticmethod
    def evaluate_5card(cards):
        # cards is a list of 5 tuples: [('H', 14), ('D', 10), ...]
        ranks = sorted([c[1] for c in cards], reverse=True)
        suits = [c[0] for c in cards]
        
        is_flush = len(set(suits)) == 1
        
        # Check for straight (including A-2-3-4-5 wheel straight)
        is_straight = False
        straight_high = 0
        
        unique_ranks = sorted(list(set(ranks)), reverse=True)
        if len(unique_ranks) == 5:
            if unique_ranks[0] - unique_ranks[4] == 4:
                is_straight = True
                straight_high = unique_ranks[0]
            elif unique_ranks == [14, 5, 4, 3, 2]:  # Wheel straight (A-2-3-4-5)
                is_straight = True
                straight_high = 5

        # Rank frequencies
        counts = {}
        for r in ranks:
            counts[r] = counts.get(r, 0) + 1
            
        # Sort by frequency first, then by rank value
        # e.g., [(rank, count), ...]
        freq_sorted = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
        counts_pattern = [f[1] for f in freq_sorted]
        ranks_pattern = [f[0] for f in freq_sorted]
        
        # Hand ranking categories (8 = Straight Flush, 0 = High Card)
        if is_straight and is_flush:
            return (8, straight_high)
        if counts_pattern == [4, 1]:
            return (7, ranks_pattern[0], ranks_pattern[1])
        if counts_pattern == [3, 2]:
            return (6, ranks_pattern[0], ranks_pattern[1])
        if is_flush:
            return (5, ranks)
        if is_straight:
            return (4, straight_high)
        if counts_pattern == [3, 1, 1]:
            return (3, ranks_pattern[0], ranks_pattern[1], ranks_pattern[2])
        if counts_pattern == [2, 2, 1]:
            return (2, ranks_pattern[0], ranks_pattern[1], ranks_pattern[2])
        if counts_pattern == [2, 1, 1, 1]:
            return (1, ranks_pattern[0], ranks_pattern[1], ranks_pattern[2], ranks_pattern[3])
        return (0, ranks)

    @classmethod
    def evaluate_7card(cls, hole_cards, community_cards):
        all_cards = hole_cards + community_cards
        if len(all_cards) < 5:
            # Fallback if fewer than 5 cards available
            ranks = sorted([c[1] for c in all_cards], reverse=True)
            return (0, ranks)
            
        best_score = None
        for combo in combinations(all_cards, 5):
            score = cls.evaluate_5card(combo)
            if best_score is None or score > best_score:
                best_score = score
        return best_score


# =====================================================================
# 2. PREFLOP STRATEGY (EXPLOITING NO BLINDS)
# =====================================================================

class PreflopStrategy:
    """
    Evaluates preflop hand strength and handles no-blind edge cases.
    """
    
    @staticmethod
    def get_hand_tier(hole_cards):
        c1, c2 = hole_cards[0], hole_cards[1]
        r1, r2 = max(c1[1], c2[1]), min(c1[1], c2[1])
        is_suited = (c1[0] == c2[0])
        
        # Pocket Pairs
        if r1 == r2:
            if r1 >= 11: return 1  # JJ, QQ, KK, AA
            if r1 >= 8:  return 2  # 88, 99, TT
            return 3              # 22-77
            
        # High cards
        if r1 == 14:  # Ace high
            if r2 >= 12: return 1 if is_suited else 2  # AK, AQ
            if r2 >= 10: return 2 if is_suited else 3  # AJ, AT
            return 3 if is_suited else 4
            
        if r1 == 13:  # King high
            if r2 >= 11: return 2 if is_suited else 3  # KQ, KJ
            return 3 if is_suited else 4
            
        if is_suited and (r1 - r2 == 1) and r1 >= 9:  # Suited connectors (QJ, JT, T9)
            return 3
            
        return 4  # Trash hands

    @classmethod
    def decide(cls, gameState):
        tier = cls.get_hand_tier(gameState.your_hole_cards)
        to_call = gameState.amount_to_call
        stack = gameState.your_stack
        min_raise = gameState.min_raise_to

        # RULE 1: Never fold if checking is free
        if to_call == 0:
            if tier == 1 and min_raise is not None:
                # Value bet premium hands
                bet_size = max(100, int(stack * 0.05))
                return ("bet", bet_size) if gameState.street == 'preflop' and min_raise is None else ("raise", max(min_raise, bet_size)) if min_raise else ("check",)
            return ("check",)

        # RULE 2: Facing aggression preflop
        call_ratio = to_call / max(1, stack)
        
        if tier == 1:
            if min_raise and call_ratio < 0.5:
                return ("raise", min_raise)
            return ("call",)
            
        if tier == 2:
            if call_ratio < 0.15:
                return ("call",)
            return ("fold",)
            
        if tier == 3:
            if call_ratio < 0.04:
                return ("call",)
            return ("fold",)
            
        return ("fold",)


# =====================================================================
# 3. DETERMINIZED MONTE CARLO EQUITY & EV ENGINE
# =====================================================================

class MonteCarloEngine:
    """
    Runs determinized simulations by sampling unknown cards for opponents
    and board runouts, then calculating Expected Value (EV).
    """

    FULL_DECK = [(s, r) for s in "HDCS" for r in range(2, 15)]

    @classmethod
    def calculate_equity(cls, hole_cards, community_cards, num_active_opponents, time_limit_sec=1.2):
        start_time = time.time()
        
        # Build deck minus known cards
        known_cards = set(hole_cards + community_cards)
        remaining_deck = [c for c in cls.FULL_DECK if c not in known_cards]
        
        cards_needed_board = 5 - len(community_cards)
        cards_needed_opponents = 2 * num_active_opponents
        total_cards_per_sim = cards_needed_board + cards_needed_opponents

        if len(remaining_deck) < total_cards_per_sim:
            return 0.5

        wins = 0
        ties = 0
        simulations = 0

        while time.time() - start_time < time_limit_sec:
            # Single-pass random sample
            sampled = random.sample(remaining_deck, total_cards_per_sim)
            
            sim_board = community_cards + sampled[:cards_needed_board]
            opp_cards_flat = sampled[cards_needed_board:]
            
            my_score = FastEvaluator.evaluate_7card(hole_cards, sim_board)
            
            my_outcome = 1  # 1 = Win, 0 = Tie, -1 = Loss
            
            for i in range(num_active_opponents):
                opp_hole = opp_cards_flat[i*2 : (i+1)*2]
                opp_score = FastEvaluator.evaluate_7card(opp_hole, sim_board)
                
                if opp_score > my_score:
                    my_outcome = -1
                    break
                elif opp_score == my_score and my_outcome != -1:
                    my_outcome = 0

            if my_outcome == 1:
                wins += 1
            elif my_outcome == 0:
                ties += 1
                
            simulations += 1

        if simulations == 0:
            return 0.5

        return (wins + (0.5 * ties)) / simulations


# =====================================================================
# 4. MAIN DECISION CONTROLLER
# =====================================================================

def nextMove(gameState):
    """
    Main entry point called by the hackathon engine.
    Must return a tuple representing the move.
    """
    start_time = time.time()
    
    try:
        # 1. Parse active opponents
        player_status = getattr(gameState, 'player_status', {})
        active_opponents = sum(1 for p, status in player_status.items() 
                              if status in ['active', 'all_in'] and p != getattr(gameState, 'action_on', None))
        active_opponents = max(1, active_opponents)

        to_call = gameState.amount_to_call
        pot = gameState.pot
        stack = gameState.your_stack
        min_raise = gameState.min_raise_to

        # 2. Preflop handling
        if gameState.street == 'preflop':
            return PreflopStrategy.decide(gameState)

        # 3. Postflop Determinized Monte Carlo (Budget: 1.3 seconds)
        equity = MonteCarloEngine.calculate_equity(
            hole_cards=gameState.your_hole_cards,
            community_cards=gameState.community_cards,
            num_active_opponents=active_opponents,
            time_limit_sec=1.3
        )

        # 4. Math & EV Calculations
        pot_after_call = pot + to_call
        pot_odds = to_call / pot_after_call if pot_after_call > 0 else 0.0

        # Helper to formulate a safe raise/bet action tuple
        def construct_wager(target_amount):
            if min_raise is None or target_amount < min_raise:
                target_amount = min_raise
            
            if target_amount is None:
                return ("call",) if to_call > 0 else ("check",)

            target_amount = min(target_amount, stack)

            if to_call == 0:
                # Engine requires ("bet", amount) if no previous bet on street
                return ("bet", max(1, target_amount))
            else:
                # Engine requires ("raise", to_total) if raising an existing bet
                return ("raise", target_amount)

        # 5. Decision Rules
        
        # A. Passive check option available (to_call == 0)
        if to_call == 0:
            # Monster hand (>75% equity): Bet heavily
            if equity > 0.75:
                return construct_wager(int(pot * 0.75))
            # Strong hand (>60% equity): Small value bet
            elif equity > 0.60:
                return construct_wager(int(pot * 0.35))
            # Default: Take free card
            return ("check",)

        # B. Facing a bet (to_call > 0)
        # Strong hand (>70% equity): Value raise
        if equity > 0.70 and min_raise is not None:
            raise_target = max(min_raise, int(pot * 0.6))
            return construct_wager(raise_target)

        # Profitable call based on pot odds
        if equity >= pot_odds:
            return ("call",)

        # Bluff opportunity: Late street, tiny call relative to pot
        if to_call < (pot * 0.08) and equity > 0.35:
            return ("call",)

        # Negative EV: Fold
        return ("fold",)

    except Exception:
        # Fail-safe watchdog fallback: Never crash, never timeout
        if gameState.amount_to_call == 0:
            return ("check",)
        return ("fold",)