# Game Engine Specification

This document describes how a **turn-based two-player game engine** should be structured, using `germanwhist/engine.py` as the reference implementation. The goal is to let competition organizers and coding agents add new games while keeping the same player and tournament integration pattern used by `germanwhist/main.py`.

## Role of the engine

The engine owns **all game rules**. It:

- Initializes and mutates authoritative game state.
- Enforces legal moves and trick/turn resolution.
- Calls each player’s `nextMove` with a **filtered** view of state.
- Validates moves; invalid moves or exceptions cause **forfeit**.
- Returns a numeric game result and optionally records events via a logger.

The match setter (`main.py`) must **never** implement rules—it only loads players, loops games, scores outcomes, and writes logs.

---

## Architectural layers

German Whist separates state into three conceptual layers. New games should follow the same pattern.

| Layer | Type | Who sees it | Purpose |
|-------|------|-------------|---------|
| **Authoritative state** | `GameState` (internal) | Engine only | Full truth: both hands, stock, turn order, phase, scores, etc. |
| **Player snapshot** | `PlayerView` (public to players) | Passed to `nextMove` | Read-only, per-player slice; copies lists so players cannot mutate engine state |
| **Rules helpers** | Pure functions | Engine | Deck building, trick resolution, legality checks—no I/O |

```
┌─────────────────────────────────────────────────────────┐
│  playGame(name1, func1, name2, func2, logger)           │
│    loop: setup → phases/tricks → result                 │
│      └─► _get_move(gs, player, func, …)                 │
│            ├─ make_player_view(player) → PlayerView     │
│            ├─ legal_cards(hand, lead_card)              │
│            ├─ card = func(view)                         │
│            └─ validate → card or forfeit                │
└─────────────────────────────────────────────────────────┘
```

---

## Core components in `engine.py`

### 1. `playGame` — **required tournament entry point**

```python
def playGame(name1, func1, name2, func2, logger) -> int
```

| Return | Meaning |
|--------|---------|
| `1` | First named player (`name1`) wins |
| `2` | Second named player (`name2`) wins |
| `0` | Draw |

**Contract for any new game:**

- Accept two **string** player names and two **callables** (their `nextMove` functions).
- Accept a `GameLogger` instance; call logger methods at setup, during play, and at end/forfeit.
- Run one complete game from deal/setup through terminal condition.
- Return only `0`, `1`, or `2`—the match setter maps these to scores; it does not interpret game-specific state.

Player order matters: `name1` is “player 1” for setup (e.g. who leads the first trick in German Whist). The tournament alternates who is `name1` across games for fairness.

### 2. `PlayerView` — **required player-facing state**

A small class (or named tuple) built fresh on each move via `GameState.make_player_view(player)`. It should:

- Expose only information that player is allowed to know (typically own hand/resources, public board, phase, scores visible to both, whose turn it is).
- **Copy** mutable collections (`list(hand)`, `dict(tricks_won)`) so `nextMove` cannot corrupt engine state.
- Use stable attribute names documented in `players/example_player.py` for that game.

German Whist attributes (reference):

| Attribute | Type | Notes |
|-----------|------|--------|
| `your_hand` | `list[(suit, rank)]` | Current player’s cards |
| `face_up_card` | card or `None` | Top of stock; `None` in scoring phase |
| `trump_suit` | `str` | `"H"`, `"D"`, `"C"`, `"S"` |
| `current_trick` | `list[(name, card)]` | Empty if leading; one entry if following |
| `phase` | `int` | `1` recruitment, `2` scoring |
| `tricks_won` | `dict[name, int]` | Scoring-phase tricks only |
| `stock_remaining` | `int` | Count excluding face-up card |
| `your_name` / `opponent_name` | `str` | From `playGame` arguments |
| `lead` | `str` | Name of player leading this trick |

New games define their own fields but should keep the same **naming style** and document them in `example_player.py`.

### 3. `GameState` — **internal, game-specific**

Not exported to players. Holds everything needed to advance the game: player names, private hands, deck/stock, phase, turn, trick in progress, win counts, `game_over`, `winner`, etc.

Required patterns:

- `opponent(player)` — resolve the other player’s name.
- `make_player_view(player)` — construct `PlayerView` for that player only.

### 4. Move pipeline: `_get_move` — **required pattern**

Every turn should go through one safe wrapper:

1. Build `PlayerView` for the acting player.
2. Compute `allowed` moves with a `legal_*` helper (game-specific).
3. `try: card = func(view)` — on **any** exception, log and return `None` (forfeit).
4. Validate: move must be in hand/resources **and** in `allowed`.
5. Return the move or `None`.

German Whist uses `legal_cards(hand, lead_card)` and `_forfeit(gs, player, name1, name2, logger)` to assign win to opponent and return `1` or `2`.

### 5. `GameLogger` — **required for match integration**

The match setter constructs one `GameLogger` per pairing and passes it into every `playGame` in that matchup. The engine calls:

| Method | When |
|--------|------|
| `start_game(game_number)` | Start of each game in a series (called by **main**, not engine) |
| `log_setup(gs)` | After initial deal/setup |
| `log_phase_change(phase)` | Optional; phase transitions |
| `log_trick(...)` / equivalent | Per turn or per “action” |
| `log_error(player, message)` | Invalid move or exception |
| `log_forfeit(loser, winner)` | Forfeit |
| `log_result(gs)` | Normal end of game |
| `flush()` | Write buffer to disk (**main** calls after all games in a matchup) |
| `write_leaderboard_csv(filepath, scores)` | **main** calls once after the full tournament; writes `player,score` rows (no rank column) |

`write_leaderboard_csv` is a static method on `GameLogger`. It takes `{player_name: float}`, sorts rows by score descending, and writes a UTF-8 CSV with header `player,score`. Implement it in every game’s `engine.py` so match setters can export results consistently.

Game-specific engines may add methods (e.g. `log_trick`), but **`start_game` and `flush` are owned by the tournament loop** in `main.py`; **`write_leaderboard_csv` is called once at the end** of `run_tournament`.

Implement `GameLogger` in the same module as `playGame` so `main.py` can do:

```python
from engine import GameLogger, playGame
```

### 6. Game-specific helpers — **optional but typical**

- **Constants / encoding**: e.g. `SUITS`, `RANKS`, `build_deck()`, `card_str()`.
- **Resolution**: e.g. `resolve_trick(lead_card, follow_card, trump_suit)`.
- **Legality**: e.g. `legal_cards(hand, lead_card)`.

These stay in `engine.py`; players should not duplicate rule logic if they want to stay valid under validation.

---

## Game loop structure (German Whist)

Illustrates how **game-specific** logic sits inside `playGame`:

1. **Setup** — shuffle, deal, set trump, set first leader, `logger.log_setup(gs)`.
2. **Phase loop(s)** — e.g. 13 recruitment tricks then 13 scoring tricks.
3. **Per trick** — leader move → follower move → resolve → update hands/stock/turn → log.
4. **Terminal** — compare `tricks_won`, set `gs.winner`, `logger.log_result(gs)`, return `1`/`2`/`0`.

Forfeits short-circuit: `_get_move` returns `None` → `_forfeit` → return winner as `1` or `2` (never `0` on forfeit).

---

## Player contract (what the engine expects)

Players are **not** classes. Each competitor submits a `.py` file with:

```python
def nextMove(gameState):
    ...
    return move  # game-specific type; German Whist: (suit, rank) tuple
```

| Requirement | Engine behavior |
|-------------|-----------------|
| Function name `nextMove` | Loaded by `main.py`; passed as `func1`/`func2` |
| Single argument | `PlayerView` instance |
| Return a legal move | Accepted; state updated |
| Return card not in hand | `log_error`, forfeit |
| Return illegal move (e.g. revoke follow-suit) | `log_error`, forfeit |
| Raise any exception | `log_error`, forfeit |

Players **do not** receive `GameLogger`, opponent’s hand, or unrevealed stock cards. They only see `PlayerView`.

See `germanwhist/players/example_player.py` for the canonical attribute list and comments; it is excluded from tournaments but is the template for new submissions.

---

## Checklist: implementing a new game engine

1. **`engine.py`** in a game folder (e.g. `mygame/engine.py`).
2. **`PlayerView`** — document every field in `players/example_player.py`.
3. **`GameState`** — full state + `make_player_view` + `opponent`.
4. **`playGame(names, funcs, logger) -> 0|1|2`** — complete rules, validation, forfeits.
5. **`_get_move`** (or equivalent) — try/except, legality, logging.
6. **`GameLogger`** — buffer lines; `flush()` writes `{playerA}_vs_{playerB}.log` path chosen by main; `write_leaderboard_csv()` for tournament results.
7. **No tournament or import-path logic** in the engine—only game rules and logging hooks.

Optional: unit-test `resolve_*` and `legal_*` helpers without loading players.

---

## What is *not* part of the engine

| Concern | Owner |
|---------|--------|
| Scanning `/players`, importing modules | `main.py` |
| Round-robin pairings, 100 games per pair | `main.py` |
| Alternating `name1` / `name2` order | `main.py` |
| Leaderboard points (1 / 0.5 / 0) | `main.py` |
| `example_player.py` | Template only; skipped by loader |

Keeping this boundary lets agents copy `germanwhist/main.py` with minimal edits (paths, constants) when adding a new game directory.

---

## File layout (per game)

```
<gamename>/
  engine.py          # playGame, PlayerView, GameState, GameLogger, rules
  main.py            # tournament / match setter (see MATCHSETTERSPEC.md)
  players/
    example_player.py   # documentation + skeleton; not loaded
    *.py                # competitor AIs (must define nextMove)
  logs/                 # created by main; one file per pairing
```

Run the tournament from the game directory so `from engine import ...` resolves (as in German Whist).
