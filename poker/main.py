# Single-table poker tournament — all players share every hand.

import os
import sys
import importlib.util
import multiprocessing
import random
import threading
import time

from engine import GameLogger, playHand, STARTING_STACK

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HANDS_PER_TOURNAMENT = 40
MIN_PLAYERS = 2
MAX_PLAYERS = 10
MOVE_TIMEOUT_SECONDS = 2.0
PLAYERS_DIR = os.path.join(os.path.dirname(__file__), "players")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

CONCURRENT_WORKERS = os.cpu_count() or 1


# ---------------------------------------------------------------------------
# Move timeout
# ---------------------------------------------------------------------------
def with_move_timeout(next_move, timeout=MOVE_TIMEOUT_SECONDS):
    """Wrap nextMove so calls exceeding *timeout* seconds raise TimeoutError."""

    def timed_next_move(game_state):
        box = {}

        def runner():
            try:
                box["value"] = next_move(game_state)
            except BaseException as e:
                box["error"] = e

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(
                f"nextMove exceeded {timeout} second limit"
            )
        if "error" in box:
            raise box["error"]
        return box["value"]

    return timed_next_move


# ---------------------------------------------------------------------------
# Player loading
# ---------------------------------------------------------------------------
def load_players(players_dir):
    """Scan *players_dir* for .py files and import their nextMove functions."""
    players = {}

    for filename in sorted(os.listdir(players_dir)):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_"):
            continue
        if filename == "example_player.py":
            continue

        name = filename[:-3]
        filepath = os.path.join(players_dir, filename)

        spec = importlib.util.spec_from_file_location(name, filepath)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[WARNING] Could not load player '{name}': {e}")
            continue

        if not hasattr(module, "nextMove") or not callable(module.nextMove):
            print(f"[WARNING] Player '{name}' has no callable nextMove – skipped.")
            continue

        players[name] = with_move_timeout(module.nextMove)
        print(f"Loaded player: {name}")

    return players


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------
_PLAYERS = {}

def _run_tournament(task):
    """Run one full independent tournament inside a worker process.

    The player functions are read from the module-level _PLAYERS dict, which
    fork inherits from the parent process (the wrapped closures are not
    picklable). Returns (run_idx, {player_name: total_chips}) or (run_idx, None).
    """
    run_idx, log_path = task

    try:
        random.seed()
        print(
            f"  [Run {run_idx}] Tournament starting: {len(_PLAYERS)} players, "
            f"{HANDS_PER_TOURNAMENT} hands",
            flush=True,
        )
        logger = GameLogger(log_path)
        scores_run = {name: 0 for name in sorted(_PLAYERS)}
        hand_history = []

        for hand_num in range(1, HANDS_PER_TOURNAMENT + 1):
            logger.start_hand(hand_num)
            ending = playHand(
                _PLAYERS, logger, hand_num, hand_history=hand_history
            )
            for name, stack in ending.items():
                scores_run[name] += stack

            best = max(ending.values())
            winners = sorted(n for n, s in ending.items() if s == best)
            gain = best - STARTING_STACK
            print(
                f"  [Run {run_idx}] Hand {hand_num}/{HANDS_PER_TOURNAMENT} complete — "
                f"winner(s): {', '.join(winners)} ({gain:+d})",
                flush=True,
            )

            if hand_num % 10 == 0:
                logger.flush()

        logger.flush()
        return run_idx, scores_run
    except BaseException:
        try:
            logger.flush()
        except BaseException:
            pass
        return run_idx, None


def run_tournament():
    """Run poker tournaments and print the leaderboard.

    N independent tournaments (one per CPU worker) are played concurrently in
    separate processes; the final leaderboard averages each player's chips
    over all completed runs.
    """

    os.makedirs(LOGS_DIR, exist_ok=True)

    players = load_players(PLAYERS_DIR)
    count = len(players)

    if count < MIN_PLAYERS:
        print(f"Need at least {MIN_PLAYERS} players in /players to run a tournament.")
        sys.exit(1)
    if count > MAX_PLAYERS:
        print(f"At most {MAX_PLAYERS} players allowed; found {count}.")
        sys.exit(1)

    tasks = [
        (run_idx, os.path.join(LOGS_DIR, f"tournament_{run_idx}.log"))
        for run_idx in range(1, CONCURRENT_WORKERS + 1)
    ]

    workers = max(1, min(CONCURRENT_WORKERS, len(tasks)))
    print(
        f"\nStarting {len(tasks)} concurrent tournaments: {count} players, "
        f"{HANDS_PER_TOURNAMENT} hands, {STARTING_STACK} chips/hand\n"
    )

    _PLAYERS.update(players)

    totals = {p: 0 for p in players}
    completed = 0
    total_runs = len(tasks)
    start_time = time.time()

    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(processes=workers) as pool:
        for run_idx, run_scores in pool.imap_unordered(_run_tournament, tasks):
            if run_scores is None:
                print(f"  Run {run_idx} FAILED")
                continue
            completed += 1
            for name, chips in run_scores.items():
                totals[name] += chips

            elapsed = time.time() - start_time
            remaining = total_runs - completed
            eta = elapsed / completed * remaining if remaining else 0
            print(
                f"  Run {run_idx} complete ({completed}/{total_runs}) — "
                f"elapsed {int(elapsed // 60)}m {int(elapsed % 60)}s, "
                f"ETA {int(eta // 60)}m {int(eta % 60)}s",
                flush=True,
            )

    if completed == 0:
        print("All tournament runs failed; no leaderboard output.")
        sys.exit(1)

    scores = {name: totals[name] / completed for name in players}

    print("\n" + "=" * 40)
    print("         FINAL LEADERBOARD (avg per run)")
    print("=" * 40)

    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(ranking, start=1):
        print(f"  {rank}. {name:<20} {score:>12.2f} chips")

    print("=" * 40)

    csv_path = os.path.join(LOGS_DIR, "leaderboard.csv")
    GameLogger.write_leaderboard_csv(csv_path, scores)
    print(f"Tournament logs: {LOGS_DIR}/tournament_*.log")
    print(f"Leaderboard CSV: {csv_path}")


if __name__ == "__main__":
    run_tournament()
