#!/usr/bin/env bash
# Build per-team submission folders under ./BotWars/teams/<round>/input.
#
# Structure created for each team:
#   BotWars/teams/<round>/input/<teamName>/<game>/
#       engine.py              (copied from <game>/engine.py)
#       main.py                (copied from <game>/main.py)
#       players/<teamName>.py  (copied from <game>/players/<teamName>.py)
#
# Games are auto-detected: repo directories containing both engine.py and
# main.py. Teams are auto-detected from each game's players/ directory using
# the same discovery rules as the match setter (main.py): skip example_player*.py
# and files starting with an underscore.
#
# Usage:
#   ./build_teams.sh [--force] [round]
#     round    name of the output round folder (default: qualifiers)
#     --force  also build folders for teams with fewer than 3 games
set -euo pipefail

FORCE=0
if [[ "${1:-}" == "--force" || "${1:-}" == "-f" ]]; then
  FORCE=1
  shift
fi

ROUND="${1:-qualifiers}"
MIN_GAMES=3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/BotWars/teams/${ROUND}/input"

# --- Detect games (dirs with engine.py and main.py) -------------------------
games=()
for dir in "${SCRIPT_DIR}"/*/; do
  game="$(basename "${dir}")"
  if [[ -f "${dir}/engine.py" && -f "${dir}/main.py" ]]; then
    games+=("${game}")
  fi
done
mapfile -t games < <(printf '%s\n' "${games[@]}" | sort)

if [[ ${#games[@]} -eq 0 ]]; then
  echo "Error: no game directories (with engine.py and main.py) found" >&2
  exit 1
fi

# --- Detect teams from every game's players/ dir ----------------------------
teams=()
for game in "${games[@]}"; do
  for player in "${SCRIPT_DIR}/${game}"/players/*.py; do
    [[ -f "${player}" ]] || continue
    name="$(basename "${player}" .py)"
    [[ "${name}" == _* || "${name}" == "example_player"* ]] && continue
    teams+=("${name}")
  done
done
mapfile -t unique_teams < <(printf '%s\n' "${teams[@]}" | sort -u)

if [[ ${#unique_teams[@]} -eq 0 ]]; then
  echo "Error: no player files found in any game" >&2
  exit 1
fi

# --- Build the tree for each team -------------------------------------------
built=0
skipped=0
for team in "${unique_teams[@]}"; do
  team_games=()
  for game in "${games[@]}"; do
    if [[ -f "${SCRIPT_DIR}/${game}/players/${team}.py" ]]; then
      team_games+=("${game}")
    fi
  done

  if [[ ${#team_games[@]} -lt ${MIN_GAMES} && ${FORCE} -eq 0 ]]; then
    echo "SKIP  ${team}  only ${#team_games[@]} game(s); needs ${MIN_GAMES} (use --force to include)"
    skipped=$((skipped + 1))
    continue
  fi

  for game in "${team_games[@]}"; do
    mkdir -p "${OUT_DIR}/${team}/${game}/players"
    cp "${SCRIPT_DIR}/${game}/engine.py" "${OUT_DIR}/${team}/${game}/"
    cp "${SCRIPT_DIR}/${game}/main.py" "${OUT_DIR}/${team}/${game}/"
    cp "${SCRIPT_DIR}/${game}/players/${team}.py" "${OUT_DIR}/${team}/${game}/players/"
  done

  echo "OK    ${team}  ${#team_games[@]} game(s): ${team_games[*]}"
  built=$((built + 1))
done

echo
echo "Games:   ${games[*]}"
echo "Output:  ${OUT_DIR}"
echo "Built:   ${built} team(s)"
if [[ ${skipped} -gt 0 ]]; then
  echo "Skipped: ${skipped} team(s) with fewer than ${MIN_GAMES} games" >&2
fi

if [[ ${built} -eq 0 || ( ${skipped} -gt 0 && ${FORCE} -eq 0 ) ]]; then
  exit 1
fi