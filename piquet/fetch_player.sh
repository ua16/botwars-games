#!/usr/bin/env bash
# Download each team's qualifier player from their public GitHub repo into players/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_FILE="${SCRIPT_DIR}/Repo-to-team-name.csv"
PLAYERS_DIR="${SCRIPT_DIR}/players"

mkdir -p "${PLAYERS_DIR}"

if [[ ! -f "${CSV_FILE}" ]]; then
  echo "CSV not found: ${CSV_FILE}" >&2
  exit 1
fi

downloaded=0
failed=0

# Strip optional .git suffix and trailing slash from a GitHub repo URL,
# then return owner/repo.
repo_slug() {
  local url="$1"
  url="${url%.git}"
  url="${url%/}"
  # https://github.com/owner/repo -> owner/repo
  echo "${url#https://github.com/}"
}

download_player() {
  local team="$1"
  local repo_url="$2"
  local slug
  slug="$(repo_slug "${repo_url}")"
  local dest="${PLAYERS_DIR}/${team}.py"
  local path="piquet/${team}.py"

  for branch in main master; do
    local raw_url="https://raw.githubusercontent.com/${slug}/${branch}/${path}"
    if curl -fsSL "${raw_url}" -o "${dest}"; then
      echo "OK  ${team}  (${branch})"
      downloaded=$((downloaded + 1))
      return 0
    fi
  done

  echo "MISSING  ${team}  ${path} not found on main or master (${repo_url})" >&2
  rm -f "${dest}"
  failed=$((failed + 1))
  return 0
}

# Skip header; read team,repo_link
while IFS=',' read -r team repo_url || [[ -n "${team}" ]]; do
  team="$(echo "${team}" | tr -d '[:space:]')"
  repo_url="$(echo "${repo_url}" | tr -d '[:space:]')"

  [[ -z "${team}" || "${team}" == "file_name" ]] && continue
  [[ -z "${repo_url}" ]] && continue

  download_player "${team}" "${repo_url}"
done < "${CSV_FILE}"

echo
echo "Downloaded: ${downloaded}"
echo "Missing:    ${failed}" >&2

if [[ "${failed}" -gt 0 ]]; then
  exit 1
fi
