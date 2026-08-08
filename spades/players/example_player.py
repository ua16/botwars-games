# Example Spades player — documents PlayerView and phase-specific nextMove returns.
# Not loaded in tournaments (see main.py).

# ------------------------------------------------------------------
# gameState (PlayerView) attributes:
#
#   gameState.your_hand          - list of (suit, rank); suit H/D/C/S, rank 2-14 (14=Ace)
#   gameState.phase              - "bid" or "play"
#   gameState.your_name          - your player name
#   gameState.opponent_name      - opponent's name
#   gameState.dealer             - who dealt this round
#   gameState.turn               - who must act now
#   gameState.your_score         - cumulative match score (toward 500)
#   gameState.opponent_score     - opponent's cumulative match score
#   gameState.your_bags          - your bag count (persists across rounds)
#   gameState.opponent_bags      - opponent's bag count
#   gameState.round_number       - current round number (1-based)
#   gameState.kitty_remaining    - int, cards in the kitty (identities not revealed)
#   gameState.hand_history       - list of completed previous rounds (public info only):
#                                  [{"round_number", "dealer", "bids", "tricks",
#                                    "tricks_won", "round_scores", "bags_after",
#                                    "scores_after"}, ...]
#
#   Bidding phase:
#   gameState.your_bid           - your bid if already submitted, else None
#   gameState.opponent_bid       - opponent's bid if known, else None
#   gameState.opponent_bid_known - True once opponent has bid
#
#   Play phase:
#   gameState.your_bid           - your bid this round (0 = nil)
#   gameState.opponent_bid       - opponent's bid this round
#   gameState.opponent_bid_known - always True in play phase
#   gameState.spades_broken      - whether spades have been broken this round
#   gameState.tricks_won         - dict {name: int} tricks won this round
#   gameState.trick_history      - list of completed tricks:
#                                  [{"leader", "plays": [(name, card), ...], "winner"}, ...]
#   gameState.current_trick      - [(player_name, card), ...] for this trick
#   gameState.lead               - name of player leading this trick
#
# Return value depends on phase:
#   bid   -> int from 0 to 13 (0 = nil bid)
#   play  -> (suit, rank) card; must follow suit when possible;
#           cannot lead spades until broken unless you hold only spades
#
# Invalid moves or exceptions forfeit the entire match.
# Each nextMove call must finish within 2 seconds or the match is forfeited.
# ------------------------------------------------------------------


def nextMove(gameState):
    if gameState.phase == "bid":
        return _bid_move(gameState)
    return _play_move(gameState)


def _bid_move(gameState):
    # Simple baseline: bid one trick per ace/king/queen in hand.
    strength = sum(1 for card in gameState.your_hand if card[1] >= 12)
    return min(strength, 13)


def _play_move(gameState):
    hand = gameState.your_hand
    trick = gameState.current_trick

    if trick:
        lead_suit = trick[0][1][0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        if same_suit:
            return same_suit[0]

    if not gameState.spades_broken:
        non_spades = [c for c in hand if c[0] != "S"]
        if non_spades:
            return non_spades[0]

    return hand[0]
