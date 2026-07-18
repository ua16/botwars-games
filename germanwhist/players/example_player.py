# This is an example player for German Whist.
# It is only here to show the structure of a player file.
# In the actual tournament, files created by the players will be pulled here.
# The name of the file (without .py) will be the player's name.

# ------------------------------------------------------------------
# gameState (a PlayerView object) has the following attributes:
#
#   gameState.your_hand        - list of (suit, rank) tuples in your hand
#                                suit: "H", "D", "C", "S"
#                                rank: 2-14 (14 = Ace, 13 = King, 12 = Queen, 11 = Jack)
#   gameState.face_up_card     - (suit, rank) top card of stock (None in scoring phase)
#   gameState.trump_suit       - the trump suit for this game ("H", "D", "C", or "S")
#   gameState.current_trick    - list of (player_name, card) already played this trick
#                                empty if you are leading, one entry if you are following
#   gameState.phase            - 1 (recruitment) or 2 (scoring)
#   gameState.tricks_won       - dict {player_name: int} scoring-phase tricks won
#   gameState.stock_remaining  - number of cards left in the stock (excluding face_up_card)
#   gameState.your_name        - your player name (string)
#   gameState.opponent_name    - opponent's player name (string)
#   gameState.lead             - name of the player leading this trick
#
# Your function must return one card (suit, rank) from gameState.your_hand.
# You MUST follow suit if you can (play a card matching the lead card's suit).
# If you cannot follow suit, you may play any card.
# Returning an invalid card or raising an exception will forfeit the game.
# ------------------------------------------------------------------


def nextMove(gameState):
    # Trivial strategy: always play the first legal card in hand.

    if gameState.current_trick:
        # We are following – must follow suit if possible
        lead_suit = gameState.current_trick[0][1][0]
        same_suit = [c for c in gameState.your_hand if c[0] == lead_suit]
        if same_suit:
            return same_suit[0]

    # Leading or no cards of the lead suit – play anything
    return gameState.your_hand[0]
