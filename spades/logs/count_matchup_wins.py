#!/usr/bin/env python3
import collections
import glob
import os
import re
import sys

WINNER_RE = re.compile(r"Winner:\s*(\S+)")
PLAYERS_RE = re.compile(r"Players:\s*(\S+)\s+vs\s+(\S+)")


def count_matchup(path):
    teams = None
    wins = collections.defaultdict(int)
    with open(path, "r", errors="replace") as f:
        for line in f:
            if teams is None:
                m = PLAYERS_RE.search(line)
                if m:
                    teams = (m.group(1), m.group(2))
            m = WINNER_RE.search(line)
            if m:
                wins[m.group(1)] += 1
    if teams is None:
        teams = (os.path.basename(path).rsplit(".", 1)[0].split("_vs_"))
    return teams, wins


def main():
    exclude = set()
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--exclude", "-x") and i + 1 < len(args):
            exclude.add(args[i + 1].lower())
            i += 2
        elif args[i] == "--help" or args[i] == "-h":
            print("usage: count_matchup_wins.py [--exclude TEAM ...]")
            print("  --exclude TEAM  skip matchups involving TEAM (case-insensitive, repeatable)")
            return 0
        else:
            print(f"Unknown argument: {args[i]}")
            return 1

    logs = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.log")))
    if not logs:
        print("No .log files found")
        return 1

    if exclude:
        print(f"Excluding matchups with: {', '.join(sorted(exclude))}\n")

    header = f"{'Matchup':<30}{'Team A':>17}{'Wins':>6}{'Losses':>8}{'Team B':>18}{'Wins':>6}{'Losses':>8}{'Games':>7}"
    print(header)
    print("-" * len(header))

    skipped = 0
    bad = []
    totals = collections.defaultdict(lambda: [0, 0, 0])
    for path in logs:
        teams, wins = count_matchup(path)
        a, b = teams
        if exclude and (a.lower() in exclude or b.lower() in exclude):
            skipped += 1
            continue
        wa, wb = wins.get(a, 0), wins.get(b, 0)
        totals[a][0] += 1
        totals[a][1] += wa
        totals[a][2] += wb
        totals[b][0] += 1
        totals[b][1] += wb
        totals[b][2] += wa
        total = wa + wb
        if total != 100 or (a, b) is None:
            bad.append((os.path.basename(path), total))
        name = os.path.basename(path).rsplit(".", 1)[0]
        print(f"{name:<30}{a:>17}{wa:>6}{wb:>8}{b:>18}{wb:>6}{wa:>8}{total:>7}")

    print("-" * len(header))
    if skipped:
        print(f"Skipped {skipped} matchup(s) due to exclusion")
    if bad:
        print("Files with unexpected game counts:")
        for f, c in bad:
            print(f"  {f}: {c} games")
    else:
        print("All matchups: 100 games each")

    print()
    print("Team totals (across included matchups):")
    summary = f"{'Team':<17}{'Matchups':>9}{'Wins':>8}{'Losses':>8}{'Win %':>8}"
    print(summary)
    print("-" * len(summary))
    for team in sorted(totals, key=lambda t: (-totals[t][1], t)):
        matchups, w, l = totals[team]
        pct = 100.0 * w / (w + l) if w + l else 0.0
        print(f"{team:<17}{matchups:>9}{w:>8}{l:>8}{pct:>7.1f}%")
    matchups, w, l = sum(v[0] for v in totals.values()) // 2, sum(v[1] for v in totals.values()) // 2, sum(v[2] for v in totals.values()) // 2
    print("-" * len(summary))
    print(f"{'TOTAL':<17}{matchups:>9}{w:>8}{l:>8}{'':>7}")


if __name__ == "__main__":
    sys.exit(main())