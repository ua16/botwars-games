# BotWars Games

This repo contains the games for BotWars 2026. 

## Running Games

To test your code against other code in a tournament cd into a game directory and 
run `main.py`. 

For example, if you're in the qualifying stage and want to test your code in a tournament,
you'd run the following commands:

```bash
mv /path/to/my/file/teamname.py ./germanwhist/players
cd ./germanwhist
python main.py
```

This runs a tournament against all the python files in the `./germanwhist/players/` 
directory. Make sure to only include valid player files in that directory.

## Valid Player Files

All valid player files need to have a `nextMove` function. For example:

```python
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
```

To find out what to name your files, look at the Excel sheet with the team names that has
been shared with you.

## Scoring

Win determination and game logic has also been shared unobfuscated. Note that returning 
an invalid move forfeits the match to the opponent. 

The same code that has been shared here will be used to determine final scores.

Please note that attempts to exploit the tournament engine will be penalised and may
lead to disqualification, you shouldn't look at your opponent's hand or the stock (looking
at the discard piles and similar is allowed however)
