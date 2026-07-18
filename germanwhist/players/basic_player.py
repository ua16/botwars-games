# Basic player: always plays the first legal card in hand.
# This is the simplest valid strategy — a baseline for testing.

def nextMove(gameState):
    if gameState.current_trick:
        lead_suit = gameState.current_trick[0][1][0]
        same_suit = [c for c in gameState.your_hand if c[0] == lead_suit]
        if same_suit:
            return same_suit[0]

    return gameState.your_hand[0]
