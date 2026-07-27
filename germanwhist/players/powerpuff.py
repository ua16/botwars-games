def nextMove(gameState):
    """
    Simple BotWars German Whist bot.
    Always follows suit if possible; otherwise plays the first available card.
    """

    # If another player has already led a card
    if gameState.current_trick:

        lead_suit = gameState.current_trick[0][1][0]

        # Find cards of the same suit
        matching_cards = [
            card for card in gameState.your_hand
            if card[0] == lead_suit
        ]

        # Play the first matching card
        if matching_cards:
            return matching_cards[0]

    # Otherwise play the first card in hand
    return gameState.your_hand[0]