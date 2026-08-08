# Match Setter Specification

This document describes how a **tournament / match setter** (`main.py`) integrates with a game engine, using `germanwhist/main.py` as the reference. The match setter runs automated competitions: load AIs, play many games per pairing, log results, and print a leaderboard.

It is intentionally **game-agnostic**: all rules live in `engine.py`. When adding a new game, copy and adapt this file; change only paths, imports, and constants—not scoring or loop structure unless the competition rules change.

---

## Responsibilities

| Match setter (`main.py`) | Game engine (`engine.py`) |
|------------------------|---------------------------|
| Discover and import player modules | `playGame`, rules, validation |
| Wrap each `nextMove` with a per-move time limit | `PlayerView`, internal `GameState` |
| Round-robin schedule | Per-game setup and play |
| Repeat N games per pair | Forfeits and draw/win resolution |
| Alternate who is “player 1” | `GameLogger` event API |
| Aggregate points | Per-game log line content for tricks/errors |
| Print leaderboard and write `logs/leaderboard.csv` | — |
| Create `logs/` directory | — |

---

## Required engine imports

The match setter depends on exactly two symbols from the sibling `engine` module:

```python
from engine import GameLogger, playGame
```

| Symbol | Usage |
|--------|--------|
| `playGame(name1, func1, name2, func2, logger)` | Run one game; returns `1`, `2`, or `0` |
| `GameLogger(filepath)` | One instance per **pairing** (not per game) |

No other engine types need to be imported in `main.py`. Do not import `GameState`, `PlayerView`, or rule helpers in the match setter.

---

## Directory layout and constants

```python
GAMES_PER_MATCHUP = 100
MOVE_TIMEOUT_SECONDS = 2.0
PLAYERS_DIR = os.path.join(os.path.dirname(__file__), "players")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
```

| Path / constant | Purpose |
|-----------------|---------|
| `<game>/players/*.py` | Competitor submissions |
| `<game>/logs/{nameA}_vs_{nameB}.log` | Full transcript for that pairing |
| `<game>/engine.py` | Imported as `engine` when cwd / path is the game folder |
| `MOVE_TIMEOUT_SECONDS` | Max wall-clock seconds allowed per `nextMove` call (default `2.0`) |

Before the tournament: `os.makedirs(LOGS_DIR, exist_ok=True)`.

---

## Player loading

### `load_players(players_dir) -> dict[str, callable]`

Returns `{player_name: nextMove_function}`.

**Discovery rules** (German Whist reference):

- Only `*.py` files.
- Skip filenames starting with `_`.
- Skip `example_player.py` (template/documentation only).
- Player **name** = filename without `.py` (e.g. `smart_player.py` → `smart_player`).

**Import mechanism:**

```python
spec = importlib.util.spec_from_file_location(name, filepath)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
```

**Validation:**

- Module must define callable `nextMove`.
- On import failure or missing `nextMove`: print warning, skip file (do not crash entire tournament).

**Timeout wrapping:** after a successful import, store a timed wrapper—not the raw function:

```python
players[name] = with_move_timeout(module.nextMove)
```

`with_move_timeout` runs each call on a **daemon** worker thread and enforces `MOVE_TIMEOUT_SECONDS` via `thread.join(timeout=…)`. On timeout it raises `TimeoutError` (even if the bot later returns a legal move). The engine’s existing exception path then forfeits the game to the opponent (or, in multi-player poker, folds that action).

Use `daemon=True` so a hung/infinite `nextMove` cannot keep the interpreter from exiting after the tournament finishes. The abandoned worker may still run until process exit (it is not forcibly killed); that is acceptable for tournament use.

**Minimum players:** if fewer than 2 loaded, print message and `sys.exit(1)`.

### Player file contract (for competitors and agents)

Each loaded file must provide:

```python
def nextMove(gameState):
    return <move>
```

- **`gameState`**: engine’s `PlayerView` for that game (documented in `example_player.py`).
- **`return`**: one legal move in the game’s encoding (German Whist: `(suit, rank)` tuple with suit in `H/D/C/S`, rank `2`–`14`).
- Each call must finish within **`MOVE_TIMEOUT_SECONDS`** (2 seconds). Exceeding the limit forfeits even if a legal move is eventually returned.
- No particular class, base type, or registration—just a module-level function.
- Side effects should be avoided; determinism helps reproducibility when debugging logs.

The match setter never passes scores or names into `nextMove`; identity is on `gameState.your_name` / `opponent_name`.

---

## Tournament algorithm

### 1. Initialization

```python
players = load_players(PLAYERS_DIR)
scores = {name: 0.0 for name in players}
matchups = list(combinations(sorted(players.keys()), 2))
```

Round-robin: every unordered pair plays a **matchup** of `GAMES_PER_MATCHUP` games.

### 2. Per matchup `(nameA, nameB)`

```python
log_path = os.path.join(LOGS_DIR, f"{nameA}_vs_{nameB}.log")
logger = GameLogger(log_path)
funcA, funcB = players[nameA], players[nameB]
```

Counters: `a_wins`, `b_wins`, `draws` (wins from A’s perspective in the scoreboard, not “player 1” globally).

### 3. Per game `game_num` in `1 .. GAMES_PER_MATCHUP`

```python
logger.start_game(game_num)

if game_num % 2 == 1:
    result = playGame(nameA, funcA, nameB, funcB, logger)
else:
    result = playGame(nameB, funcB, nameA, funcA, logger)
```

**First-player alternation:** odd games pass `(nameA, …)` as `name1` in `playGame`; even games swap so each AI leads/setup as player 1 equally often. Map `result` to `a_wins` / `b_wins` / `draws` according to which name was `name1` in that call:

| `result` | Odd game (`nameA` is `name1`) | Even game (`nameB` is `name1`) |
|----------|-------------------------------|----------------------------------|
| `1` | `a_wins += 1` | `b_wins += 1` |
| `2` | `b_wins += 1` | `a_wins += 1` |
| `0` | `draws += 1` | `draws += 1` |

After all games in the matchup:

```python
logger.flush()
```

### 4. Scoring (leaderboard points)

Per matchup, after 100 games:

```python
scores[nameA] += a_wins + 0.5 * draws
scores[nameB] += b_wins + 0.5 * draws
```

| Outcome per game | Points |
|------------------|--------|
| Win | `1.0` |
| Draw | `0.5` |
| Loss | `0.0` |

Total tournament score = sum over all matchups. This is **not** handled inside the engine.

### 5. Leaderboard output

Sort `scores` descending; print rank, name, total points (one decimal). No tie-break rules in reference code—ties stand as equal rank.

After printing, write a CSV via `GameLogger`:

```python
csv_path = os.path.join(LOGS_DIR, "leaderboard.csv")
GameLogger.write_leaderboard_csv(csv_path, scores)
```

| CSV column | Content |
|------------|---------|
| `player` | Player name (same as the `.py` filename without extension) |
| `score` | Total tournament points, one decimal (e.g. `42.5`) |

- File path: `logs/leaderboard.csv` (under `LOGS_DIR`).
- Rows sorted by `score` descending (best first).
- **No** rank or position column—only player identity and score.
- Use the engine’s `write_leaderboard_csv` static method so new games share the same export API.

---

## Logging contract between main and engine

```
main                          engine
────                          ──────
GameLogger(path) ────────────► passed into playGame
start_game(n)     ───────────► (before playGame each iteration)
                                log_setup, log_trick, log_error, …
flush()           ◄──────────  (after all games in matchup)
write_leaderboard_csv(path, scores)  (once, after all matchups)
```

- **One log file per pairing**, appended across 100 games via in-memory buffer then single `flush()`.
- **One CSV** for the whole tournament: `leaderboard.csv` in `LOGS_DIR`.
- **main** calls `start_game` and `write_leaderboard_csv`; **engine** calls the rest during `playGame` (and implements `write_leaderboard_csv` on `GameLogger`).
- Log format is game-specific but should remain human-readable for debugging invalid AIs.

---

## CLI entry point

```python
if __name__ == "__main__":
    run_tournament()
```

Run from the game directory:

```bash
cd germanwhist
python main.py
```

Python must resolve `engine` as a local module (same folder as `main.py`).

---

## Checklist: new game match setter

1. Copy `germanwhist/main.py` into `<newgame>/main.py`.
2. Keep `GAMES_PER_MATCHUP`, `MOVE_TIMEOUT_SECONDS`, `with_move_timeout`, scoring, alternation, and `combinations` loop unless competition rules change.
3. Point `PLAYERS_DIR` / `LOGS_DIR` at `<newgame>/players` and `<newgame>/logs`.
4. Ensure `from engine import GameLogger, playGame` refers to `<newgame>/engine.py`.
5. Add `<newgame>/players/example_player.py` documenting `PlayerView` and `nextMove` (skipped by loader).
6. Do **not** duplicate legality or win detection in `main.py`.
7. Call `GameLogger.write_leaderboard_csv` after the tournament to emit `logs/leaderboard.csv`.
8. Wrap loaded `nextMove` with `with_move_timeout` so slow bots forfeit via the engine’s exception path.

---

## Example player template (`example_player.py`)

Not loaded in tournaments. Serves three purposes:

1. **Documentation** — lists every `PlayerView` attribute AI authors may use.
2. **Skeleton** — minimal valid `nextMove` (e.g. first legal card).
3. **Onboarding** — shows follow-suit (or equivalent) logic competitors must mirror.

Competitors add new `*.py` files alongside it; filename becomes leaderboard name.

Reference behavior (German Whist):

- If `current_trick` non-empty, follow lead suit when possible.
- Otherwise play any card (e.g. first in hand).
- Invalid returns/forfeits are defined in **ENGINESPEC.md**, not in main.
- Per-move time limits are enforced by the match setter (`with_move_timeout`); document the 2-second limit in `example_player.py`.

---

## Extending the competition (optional changes)

These are **not** required beyond the reference unless competition rules change—keep them in the match setter, not the engine:

| Feature | Where to implement |
|---------|-------------------|
| Different `GAMES_PER_MATCHUP` | Constant in `main.py` |
| Different `MOVE_TIMEOUT_SECONDS` | Constant in `main.py` (already in reference) |
| Swiss / elimination instead of round-robin | Replace `combinations` loop |
| Parallel game execution | `main.py` (engine must stay thread-safe or one process per game) |
| Other export formats (JSON, etc.) | Extend `GameLogger` or `main.py` alongside `write_leaderboard_csv` |
| Seeded RNG for reproducibility | Pass seed into `playGame` (requires engine API change) |

---

## End-to-end data flow

```
players/*.py
    └─► load_players() ──► { name: with_move_timeout(nextMove) }
                              │
combinations(names, 2)        │
    └─► for each pair ────────┼─► GameLogger
              └─► 100 × playGame(name1, f1, name2, f2, logger)
                        └─► timed nextMove(PlayerView); TimeoutError → forfeit
                        └─► engine validates move
                              └─► 0 / 1 / 2
              └─► aggregate wins/draws ──► scores
    └─► print leaderboard + write logs/leaderboard.csv
```

For engine internals (`PlayerView`, forfeits, `GameLogger` methods), see **ENGINESPEC.md**.
