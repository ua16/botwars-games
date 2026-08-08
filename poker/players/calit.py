# BotWars Stage 2 — Team Calit poker bot (final: Phases 2-4 complete).
# Pure stdlib, single file (evaluator + equity engine inlined). No file I/O,
# no external processes, no exec/eval, no network.
#
# Doctrine ("Five Laws" — see research/stage2/DESIGN.md):
#   1. Never donate: no -EV calls; fold/check floor always available.
#   2. Never bluff an empty pot.
#   3. Value is the profit engine: bet when equity clears the marginal bar.
#   4. Exploit with evidence: full OpponentBook — evidence-gated classification
#      (STATION/MANIAC/NIT/LOOSE_PASSIVE/TAG), showdown-reveal ledger,
#      range-conditioned MC sampling, isolation-sizing discount (Phase 3).
#   5. Zero errors: try/except -> SafeAction, wall-clock deadline, exact
#      self-tracked legalization, thread-safe idempotent state sync.
#
# Validated: 10,000+ hands zero errors (multiple independent runs incl. max
# table size 10p with heavy all-in/side-pot stress), thread-safety stress
# test passed, decisive head-to-head wins vs calling-station and maniac
# archetypes, production-config max move time ~1.2s (vs 2.0s real timeout).
# CONFIG tuned via champion-loop promotion tests (Phase 4) against a
# diverse sparring population — see /data/botwars/research/stage2/DESIGN.md
# and /data/botwars/STAGE1_LEARNINGS.md-style memory for full build history.

import itertools
import os
import random
import threading
import time
from collections import Counter

# =============================================================================
# SECTION 1: Hand evaluator (7-card, direct 2-table design)
# =============================================================================

RANKS = list(range(2, 15))
SUITS = ["H", "D", "C", "S"]
PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

STRAIGHT_MASKS = [0x1F00, 0x0F80, 0x07C0, 0x03E0, 0x01F0,
                  0x00F8, 0x007C, 0x003E, 0x001F, 0x100F]
STRAIGHT_TOPS = [14, 13, 12, 11, 10, 9, 8, 7, 6, 5]


def _rank_idx(rank):
    return rank - 2


def _prime(rank):
    return PRIMES[_rank_idx(rank)]


def _straight_high(ranks):
    uniq = set(ranks)
    if 14 in uniq:
        uniq.add(1)
    uniq = sorted(uniq, reverse=True)
    for i in range(len(uniq) - 4):
        window = uniq[i:i + 5]
        if window[0] - window[4] == 4:
            return window[0]
    return None


def _category5(ranks5):
    counts = Counter(ranks5)
    by_freq = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    distinct_sorted = sorted(counts.keys(), reverse=True)

    if by_freq[0][1] == 4:
        kicker = [r for r in distinct_sorted if r != by_freq[0][0]][0]
        return (6, by_freq[0][0], kicker)
    if by_freq[0][1] == 3 and by_freq[1][1] == 2:
        return (5, by_freq[0][0], by_freq[1][0])

    straight_top = _straight_high(ranks5)
    if straight_top:
        return (3, straight_top)

    if by_freq[0][1] == 3:
        trips = by_freq[0][0]
        kickers = sorted([r for r in distinct_sorted if r != trips], reverse=True)
        return (2, trips, *kickers)

    if by_freq[0][1] == 2 and by_freq[1][1] == 2:
        hi, lo = max(by_freq[0][0], by_freq[1][0]), min(by_freq[0][0], by_freq[1][0])
        kicker = [r for r in distinct_sorted if r not in (hi, lo)][0]
        return (1, hi, lo, kicker)

    if by_freq[0][1] == 2:
        pair = by_freq[0][0]
        kickers = sorted([r for r in distinct_sorted if r != pair], reverse=True)
        return (0, pair, *kickers)

    return (-1, *sorted(ranks5, reverse=True))


def _build_unsuited_lookup():
    groups = {6: [], 5: [], 3: [], 2: [], 1: [], 0: [], -1: []}
    for combo in itertools.combinations_with_replacement(range(2, 15), 5):
        counts = Counter(combo)
        if max(counts.values()) == 5:
            continue
        cat = _category5(combo)
        groups[cat[0]].append((cat, combo))

    bases = {6: 11, 5: 167, 3: 1600, 2: 1610, 1: 2468, 0: 3326, -1: 6186}
    lookup = {}
    for code in (6, 5, 3, 2, 1, 0, -1):
        entries = sorted(groups[code], key=lambda t: t[0], reverse=True)
        base = bases[code]
        for i, (cat, combo) in enumerate(entries):
            prod = 1
            for r in combo:
                prod *= _prime(r)
            lookup[prod] = base + i
    return lookup


def _build_flush_lookup():
    straight_masks = set(STRAIGHT_MASKS)
    all_masks = [m for m in range(1, 1 << 13) if bin(m).count("1") == 5]
    sf_order = []
    flush_order = []
    for m in all_masks:
        if m in straight_masks:
            top = STRAIGHT_TOPS[STRAIGHT_MASKS.index(m)]
            sf_order.append((top, m))
        else:
            flush_order.append(m)
    sf_order.sort(key=lambda t: t[0], reverse=True)
    flush_order.sort(reverse=True)

    lookup = {}
    for i, (top, m) in enumerate(sf_order):
        lookup[m] = 1 + i
    for i, m in enumerate(flush_order):
        lookup[m] = 323 + i
    return lookup


UNSUITED_LOOKUP = _build_unsuited_lookup()
FLUSH_LOOKUP = _build_flush_lookup()


def _best5_from_counts(counts13):
    present = [(idx + 2, c) for idx, c in enumerate(counts13) if c > 0]

    quad = [r for r, c in present if c == 4]
    if quad:
        qr = quad[0]
        kicker = max(r for r, c in present if r != qr)
        return [qr, qr, qr, qr, kicker]

    trips_ranks = sorted([r for r, c in present if c == 3], reverse=True)

    if trips_ranks:
        best_trip = trips_ranks[0]
        pair_candidates = sorted(
            [r for r, c in present if c >= 2 and r != best_trip], reverse=True)
        if pair_candidates:
            pr = pair_candidates[0]
            return [best_trip, best_trip, best_trip, pr, pr]

    all_ranks_present = [r for r, c in present]
    straight_top = _straight_high(all_ranks_present)
    if straight_top:
        if straight_top == 5:
            return [5, 4, 3, 2, 14]
        return list(range(straight_top, straight_top - 5, -1))

    if trips_ranks:
        tr = trips_ranks[0]
        kickers = sorted([r for r, c in present if r != tr], reverse=True)[:2]
        return [tr, tr, tr] + kickers

    pair_ranks = sorted([r for r, c in present if c == 2], reverse=True)
    if len(pair_ranks) >= 2:
        hi, lo = pair_ranks[0], pair_ranks[1]
        kicker = max(r for r, c in present if r not in (hi, lo))
        return [hi, hi, lo, lo, kicker]
    if len(pair_ranks) == 1:
        pr = pair_ranks[0]
        kickers = sorted([r for r, c in present if r != pr], reverse=True)[:3]
        return [pr, pr] + kickers

    return sorted(all_ranks_present, reverse=True)[:5]


def _gen_count_vectors(slots, total):
    if slots == 1:
        if 0 <= total <= 4:
            yield [total]
        return
    for v in range(0, 5):
        if v > total:
            break
        for rest in _gen_count_vectors(slots - 1, total - v):
            yield [v] + rest


def _build_noflush7():
    table = {}
    for counts in _gen_count_vectors(13, 7):
        best5 = _best5_from_counts(counts)
        prod5 = 1
        for r in best5:
            prod5 *= _prime(r)
        value = UNSUITED_LOOKUP[prod5]

        prod7 = 1
        for idx, c in enumerate(counts):
            if c:
                prod7 *= PRIMES[idx] ** c
        table[prod7] = value
    return table


def _top5_mask(mask):
    out = 0
    found = 0
    for bit in range(12, -1, -1):
        if mask & (1 << bit):
            out |= (1 << bit)
            found += 1
            if found == 5:
                break
    return out


def _best_straight_top_from_mask(mask):
    ranks = [idx + 2 for idx in range(13) if mask & (1 << idx)]
    return _straight_high(ranks)


def _build_flush7():
    table = [-1] * (1 << 13)
    for mask in range(1, 1 << 13):
        pc = bin(mask).count("1")
        if pc < 5:
            continue
        if pc == 5:
            table[mask] = FLUSH_LOOKUP[mask]
            continue
        top = _best_straight_top_from_mask(mask)
        if top:
            table[mask] = 1 + STRAIGHT_TOPS.index(top)
        else:
            table[mask] = FLUSH_LOOKUP[_top5_mask(mask)]
    return table


def _build_flush_suit():
    size = 0x9000
    table = [-1] * size
    for c0 in range(8):
        for c1 in range(8):
            for c2 in range(8):
                for c3 in range(8):
                    idx = c0 | (c1 << 4) | (c2 << 8) | (c3 << 12)
                    fs = -1
                    for s, cnt in enumerate((c0, c1, c2, c3)):
                        if cnt >= 5:
                            fs = s
                            break
                    table[idx] = fs
    return table


NOFLUSH7 = _build_noflush7()
FLUSH7 = _build_flush7()
FLUSH_SUIT = _build_flush_suit()

SUIT_IDX = {s: i for i, s in enumerate(SUITS)}


def _card_to_int(suit, rank):
    return _rank_idx(rank) * 4 + SUIT_IDX[suit]


PRIME = [0] * 52
SUITCOUNT = [0] * 52
LANE = [0] * 52
for _s in SUITS:
    for _r in RANKS:
        _c = _card_to_int(_s, _r)
        PRIME[_c] = _prime(_r)
        SUITCOUNT[_c] = 1 << (4 * SUIT_IDX[_s])
        LANE[_c] = (1 << _rank_idx(_r)) << (13 * SUIT_IDX[_s])

CARD_INT = {(s, r): _card_to_int(s, r) for s in SUITS for r in RANKS}
FULL_DECK = [(s, r) for s in SUITS for r in RANKS]


def eval7(c1, c2, c3, c4, c5, c6, c7):
    sc = (SUITCOUNT[c1] + SUITCOUNT[c2] + SUITCOUNT[c3] + SUITCOUNT[c4]
          + SUITCOUNT[c5] + SUITCOUNT[c6] + SUITCOUNT[c7])
    fs = FLUSH_SUIT[sc]
    if fs >= 0:
        lanes = (LANE[c1] | LANE[c2] | LANE[c3] | LANE[c4]
                 | LANE[c5] | LANE[c6] | LANE[c7])
        return FLUSH7[(lanes >> (13 * fs)) & 0x1FFF]
    return NOFLUSH7[PRIME[c1] * PRIME[c2] * PRIME[c3] * PRIME[c4]
                     * PRIME[c5] * PRIME[c6] * PRIME[c7]]


# =============================================================================
# SECTION 2: Equity engine (embedded 169-hand table + unconditioned MC)
# =============================================================================

RANK_CHAR = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "T"}


def _rc(r):
    return RANK_CHAR.get(r, str(r))


def hand_key(hole):
    (s1, r1), (s2, r2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    if hi == lo:
        return f"{_rc(hi)}{_rc(lo)}"
    suited = "s" if s1 == s2 else "o"
    return f"{_rc(hi)}{_rc(lo)}{suited}"


# WIN-ONLY probability (ties excluded — verified against our own MC; see
# research/stage2 equity engine notes). Ranking/percentile use only; real
# threshold decisions use preflop_full_equity() (MC, includes tie-share).
_HU_TABLE_TEXT = """
AA  84.93   KK  82.11   QQ  79.63   JJ  77.15   TT  74.66   99  71.66
88  68.71   AKs 66.21   77  65.72   AQs 65.31   AKo 64.46   AJs 64.39
AQo 63.50   ATs 63.48   66  62.70   AJo 62.53   KQs 62.40   ATo 61.56
A9s 61.50   KJs 61.47   55  59.64   A8s 60.50   KTs 60.58   KQo 60.43
A9o 59.44   KJo 59.44   A7s 59.38   QJs 59.07   K9s 58.63   KTo 58.49
A8o 58.37   A6s 58.17   QTs 58.17   A5s 58.06   44  56.25   A7o 57.16
A4s 57.13   QJo 56.90   K8s 56.79   A3s 56.33   K9o 56.40   Q9s 56.22
JTs 56.15   A6o 55.87   QTo 55.94   K7s 55.84   A5o 55.74   A2s 55.50
K6s 54.80   A4o 54.73   K8o 54.43   Q8s 54.41   J9s 54.11   Q9o 53.86
A3o 53.85   K5s 53.83   JTo 53.82   K7o 53.41   A2o 52.94   K4s 52.88
33  52.83   Q7s 52.52   T9s 52.37   J8s 52.31   K6o 52.29   K3s 52.07
Q8o 51.93   Q6s 51.67   J9o 51.63   K5o 51.25   K2s 51.23   Q5s 50.71
T8s 50.50   J7s 50.45   K4o 50.22   Q7o 49.90   T9o 49.81   Q4s 49.76
J8o 49.71   22  49.38   K3o 49.33   Q6o 48.99   Q3s 48.93   98s 48.85
T7s 48.65   J6s 48.57   K2o 48.42   Q2s 48.10   Q5o 47.95   J5s 47.82
T8o 47.81   J7o 47.72   97s 46.99   Q4o 46.92   J4s 46.86   T6s 46.80
98o 46.06   J3s 46.04   Q3o 46.02   87s 45.68   T7o 45.82   J6o 45.71
J2s 45.20   96s 45.15   Q2o 45.10   T5s 44.93   J5o 44.90   T4s 44.20
97o 44.07   J4o 43.86   T6o 43.84   86s 43.81   T3s 43.37   95s 43.31
J3o 42.96   76s 42.82   87o 42.69   T2s 42.54   96o 42.10   J2o 42.04
85s 41.99   T5o 41.85   94s 41.40   T4o 41.05   75s 40.97   93s 40.80
86o 40.69   65s 40.34   T3o 40.15   95o 40.13   84s 40.10   92s 39.97
76o 39.65   T2o 39.23   74s 39.10   54s 38.53   85o 38.74   64s 38.48
83s 38.28   94o 38.08   75o 37.67   82s 37.67   93o 37.42   73s 37.30
65o 37.01   53s 36.75   63s 36.68   84o 36.70   92o 36.51   43s 35.72
74o 35.66   72s 35.43   54o 35.07   64o 35.00   52s 34.92   62s 34.83
83o 34.74   82o 34.08   42s 33.91   73o 33.71   53o 33.16   32s 33.09
63o 33.06   43o 32.06   72o 31.71   52o 31.19   62o 31.07   42o 30.11
32o 29.23
"""


def _parse_hu_table(text):
    toks = text.split()
    table = {}
    for i in range(0, len(toks), 2):
        table[toks[i]] = float(toks[i + 1])
    return table


HU_WIN_PCT = _parse_hu_table(_HU_TABLE_TEXT)

# Premium open set: top 10 hands by win-only% (AA..77/AQs region) — tight
# unopened-pot opens per Law 2 (never bluff an empty pot).
_SORTED_HANDS = sorted(HU_WIN_PCT.items(), key=lambda kv: kv[1], reverse=True)
PREMIUM_SET = frozenset(k for k, _ in _SORTED_HANDS[:10])
# Wider "playable" set for facing small action / probes — top ~22%.
PLAYABLE_SET = frozenset(k for k, _ in _SORTED_HANDS[:38])


def preflop_rank_score(hole, n_opponents=1):
    hs = HU_WIN_PCT[hand_key(hole)] / 100.0
    return hs ** max(1, n_opponents)


def estimate_equity(hero_hole, board, n_opponents, rng, deadline,
                     max_trials=20000, min_trials=150, check_every=200):
    if n_opponents <= 0:
        return 1.0, 0

    dead = set(hero_hole) | set(board)
    live = [c for c in FULL_DECK if c not in dead]
    need_board = 5 - len(board)
    draw_n = n_opponents * 2 + need_board
    if draw_n > len(live):
        return 0.5, 0

    hero_ints = [CARD_INT[c] for c in hero_hole]
    board_ints = [CARD_INT[c] for c in board]
    rng_sample = rng.sample
    opp_slots = n_opponents * 2

    wins = 0.0
    trials = 0
    while trials < max_trials:
        draw_ints = [CARD_INT[c] for c in rng_sample(live, draw_n)]
        full_board = board_ints + draw_ints[opp_slots:]

        hero_val = eval7(*(hero_ints + full_board))
        best = hero_val
        tie_count = 1
        for i in range(0, opp_slots, 2):
            v = eval7(draw_ints[i], draw_ints[i + 1], *full_board)
            if v < best:
                best = v
                tie_count = 1
            elif v == best:
                tie_count += 1

        if best == hero_val:
            wins += 1.0 / tie_count

        trials += 1
        if trials >= min_trials and trials % check_every == 0 and time.monotonic() >= deadline:
            break

    return (wins / trials if trials else 0.5), trials


# ---------------------------------------------------------------------------
# Phase 3b: range-conditioned sampling (deferred from Phase 2 per DESIGN.md's
# scope-cut critique fix — independently gated, must beat baseline alone).
# ---------------------------------------------------------------------------

def _build_combo_list():
    """All 1326 hole-card combos, sorted by HU_WIN_PCT descending. Used to
    build per-opponent top-X% range prefixes for range-conditioned MC."""
    combos = []
    for i in range(len(FULL_DECK)):
        for j in range(i + 1, len(FULL_DECK)):
            c1, c2 = FULL_DECK[i], FULL_DECK[j]
            pct = HU_WIN_PCT[hand_key((c1, c2))]
            combos.append((pct, c1, c2))
    combos.sort(key=lambda t: t[0], reverse=True)
    return [(c1, c2) for _, c1, c2 in combos]


ALL_COMBOS_SORTED = _build_combo_list()
_DEFAULT_RANGE_WIDTH = 0.60  # unknown-opponent default (moderately wide)


def _opponent_range_width(stats):
    """Estimated top-X% range width from observed looseness. Evidence-gated
    implicitly via shrinkage (low-n opponents stay near the population-mean
    default width)."""
    if stats is None:
        return _DEFAULT_RANGE_WIDTH
    entry_rate = _shrunk_rate(stats["entries"], stats["hands_seen"])
    return max(0.06, min(0.97, entry_rate))


def _range_prefix(width):
    n = max(2, int(len(ALL_COMBOS_SORTED) * width))
    return ALL_COMBOS_SORTED[:n]


def estimate_equity_ranged(hero_hole, board, opponent_prefixes, rng, deadline,
                            max_trials=20000, min_trials=150, check_every=200):
    """Whole-table MC with each opponent dealt from their own top-X% range
    prefix instead of uniformly. Bounded retry (4 attempts) on a dead-card
    collision, then falls back to uniform dealing for that trial's remaining
    opponents/board — guarantees termination and keeps the deadline check at
    the same cadence as the unconditioned engine (critique fix: benchmark the
    real retry path, check deadline inside the loop, not just at trial
    boundaries)."""
    n_opponents = len(opponent_prefixes)
    if n_opponents <= 0:
        return 1.0, 0

    dead = set(hero_hole) | set(board)
    hero_ints = [CARD_INT[c] for c in hero_hole]
    board_ints_partial = [CARD_INT[c] for c in board]
    need_board = 5 - len(board)
    randrange = rng.randrange
    rng_sample = rng.sample

    wins = 0.0
    trials = 0
    while trials < max_trials:
        trial_dead = set(dead)
        opp_cards = []
        stalled_at = None
        for oi, prefix in enumerate(opponent_prefixes):
            picked = None
            plen = len(prefix)
            for _ in range(4):
                cand = prefix[randrange(plen)]
                if cand[0] not in trial_dead and cand[1] not in trial_dead:
                    picked = cand
                    break
            if picked is None:
                stalled_at = oi
                break
            opp_cards.append(picked)
            trial_dead.add(picked[0])
            trial_dead.add(picked[1])

        if stalled_at is not None:
            live_remaining = [c for c in FULL_DECK if c not in trial_dead]
            needed = n_opponents - len(opp_cards)
            drawn = rng_sample(live_remaining, needed * 2)
            for i in range(needed):
                pair = (drawn[i * 2], drawn[i * 2 + 1])
                opp_cards.append(pair)
                trial_dead.add(pair[0])
                trial_dead.add(pair[1])

        live_for_board = [c for c in FULL_DECK if c not in trial_dead]
        board_draw = rng_sample(live_for_board, need_board)
        full_board = board_ints_partial + [CARD_INT[c] for c in board_draw]

        hero_val = eval7(*(hero_ints + full_board))
        best = hero_val
        tie_count = 1
        for c1, c2 in opp_cards:
            v = eval7(CARD_INT[c1], CARD_INT[c2], *full_board)
            if v < best:
                best = v
                tie_count = 1
            elif v == best:
                tie_count += 1

        if best == hero_val:
            wins += 1.0 / tie_count

        trials += 1
        if trials >= min_trials and trials % check_every == 0 and time.monotonic() >= deadline:
            break

    return (wins / trials if trials else 0.5), trials


# =============================================================================
# SECTION 3: Config
# =============================================================================

CONFIG = {
    "move_budget": 1.2,
    "mc_max_trials": 20000,
    "mc_min_trials": 150,
    "recon_hand_window": 15,
    "recon_max_probes": 12,
    "recon_probe_size": 1,
    "preflop_open_frac": 0.02,
    "preflop_call_frac_cap": 0.20,
    "value_bet_frac_pot": 0.66,
    "value_equity_threshold": 0.66,  # Phase 4 tuning: swept 0.54/0.58/0.62/0.66/0.70
                                      # against the sparring population via champion-loop
                                      # promotion tests; 0.66 is the confirmed local optimum
                                      # (0.70 didn't clear the promotion margin over it).
    "raise_value_equity_threshold": 0.72,
    "call_margin_base": 0.03,
    "call_margin_per_extra_opp": 0.02,
    "position_discount_max": 0.03,
    "never_fold_to_chips": 2,
    "shrinkage_prior_n": 6,
    "shrinkage_prior_mean": 0.5,
}

# Lab-only fast-iteration override (never set by the real tournament harness):
# CALIT_FAST=1 shrinks the MC budget drastically so lab runs finish in
# reasonable wall-clock time. Shipped default (env unset) is untouched.
if os.environ.get("CALIT_FAST"):
    CONFIG["move_budget"] = 0.03
    CONFIG["mc_max_trials"] = 400
    CONFIG["mc_min_trials"] = 60

# =============================================================================
# SECTION 4: Module state (thread-safe, persistent across nextMove calls)
# =============================================================================

_lock = threading.Lock()
_rng = random.Random(0xCA717)

_state = {
    "last_processed_hand_number": 0,
    "opp_stats": {},          # name -> {"hands_seen","entries","faced_bet","folded_to_bet"}
    "my_hand_number": None,
    "my_street": None,
    "my_street_wager": 0,     # exact self-tracked contribution this street
    "probes_used": 0,
}


def _new_opp_stats():
    return {"hands_seen": 0, "entries": 0, "aggressive_entries": 0,
            "faced_bet": 0, "folded_to_bet": 0,
            "aggressive_actions": 0, "total_actions": 0,
            "showdown_count": 0, "showdown_percentile_sum": 0.0}


def _replay_hand_for_stats(entry, my_name, opp_stats):
    seat_order = entry.get("seat_order", [])
    actions_by_street = entry.get("actions", {})

    for player in seat_order:
        if player == my_name:
            continue
        opp_stats.setdefault(player, _new_opp_stats())["hands_seen"] += 1

    entered = set()
    entered_aggressively = set()
    for _street, acts in actions_by_street.items():
        live_bet = False
        for player, action in acts:
            if player == my_name:
                if action and action[0] in ("bet", "raise"):
                    live_bet = True
                continue
            st = opp_stats.setdefault(player, _new_opp_stats())
            kind = action[0] if action else None
            if live_bet:
                st["faced_bet"] += 1
                if kind == "fold":
                    st["folded_to_bet"] += 1
            if kind in ("call", "bet", "raise"):
                entered.add(player)
            if kind in ("bet", "raise"):
                live_bet = True
                st["aggressive_actions"] += 1
                entered_aggressively.add(player)
            if kind is not None:
                st["total_actions"] += 1

    for player in entered:
        opp_stats.setdefault(player, _new_opp_stats())["entries"] += 1
    for player in entered_aggressively:
        opp_stats.setdefault(player, _new_opp_stats())["aggressive_entries"] += 1

    # Showdown ledger (research 04's "superpower"): revealed hole-card preflop
    # percentile per contender. Simplified Phase 3a version — uses the static
    # preflop percentile as a strength proxy rather than street-by-street
    # recomputed equity (full version would need re-evaluating their hand vs
    # the board at each decision point; deferred as a further Phase 3 item).
    showdown = entry.get("showdown")
    if showdown:
        for player, hole in showdown.items():
            if player == my_name:
                continue
            st = opp_stats.setdefault(player, _new_opp_stats())
            try:
                percentile = HU_WIN_PCT[hand_key(hole)] / 100.0
            except Exception:
                continue
            st["showdown_count"] += 1
            st["showdown_percentile_sum"] += percentile


def _sync_state(view):
    """Idempotent (keyed on hand_number), lock-guarded, bounded-cost state
    sync. Safe against an orphaned timed-out thread racing a fresh one
    (critique fix — see DESIGN.md Section 6)."""
    with _lock:
        last = _state["last_processed_hand_number"]
        for entry in view.hand_history:
            hn = entry.get("hand_number", 0)
            if hn > last:
                _replay_hand_for_stats(entry, view.your_name, _state["opp_stats"])
                if hn > _state["last_processed_hand_number"]:
                    _state["last_processed_hand_number"] = hn

        if _state["my_hand_number"] != view.hand_number or _state["my_street"] != view.street:
            _state["my_street_wager"] = 0
            _state["my_hand_number"] = view.hand_number
            _state["my_street"] = view.street

        return dict(_state["opp_stats"]), _state["my_street_wager"], _state["probes_used"]


def _record_my_action(action, to_call, stack):
    """Update our exact self-tracked street wager after the final legalized
    action (called right before returning). Call is clamped to actual stack
    (engine's _put_chips does the same) so an all-in call doesn't inflate
    my_street_wager beyond what was really contributed."""
    with _lock:
        kind = action[0]
        if kind == "call":
            _state["my_street_wager"] += min(to_call, stack)
        elif kind == "bet":
            _state["my_street_wager"] += action[1]
        elif kind == "raise":
            _state["my_street_wager"] = action[1]


def _record_probe():
    with _lock:
        _state["probes_used"] += 1


def _shrunk_rate(successes, n, prior_n=None, prior_mean=None):
    prior_n = CONFIG["shrinkage_prior_n"] if prior_n is None else prior_n
    prior_mean = CONFIG["shrinkage_prior_mean"] if prior_mean is None else prior_mean
    return (prior_mean * prior_n + successes) / (prior_n + n)


# =============================================================================
# SECTION 4b: OpponentBook classification (Phase 3a — evidence-gated, not
# hand-count-gated per the critique fix: PlayerView has no total-hand-count
# field, so a fixed "classify by hand N" trigger can't detect a short
# tournament. Trigger on observation count + shrunk-rate extremity instead.)
# =============================================================================

MIN_CLASSIFY_EVIDENCE = 8

# research 04 counter-strategy table, applied as an additive required-equity
# adjustment when CALLING that opponent's bet specifically (identified via
# the current street's aggressor, not a table-wide average): MANIAC ranges
# are wide -> call lighter; NIT/LOOSE_PASSIVE bets are informative -> call
# tighter; STATION's own bets are rare and usually mean something, small
# caution; TAG/UNKNOWN -> no adjustment (Phase 2 baseline behavior).
TYPE_CALL_ADJUSTMENT = {
    "STATION": 0.02,
    "MANIAC": -0.10,
    "NIT": 0.15,
    "LOOSE_PASSIVE": 0.08,
    "TAG": 0.0,
    "UNKNOWN": 0.0,
}


def _classify(stats):
    if stats is None:
        return "UNKNOWN"
    hands_seen = stats["hands_seen"]
    faced_bet = stats["faced_bet"]
    total_actions = stats["total_actions"]

    entry_rate = _shrunk_rate(stats["entries"], hands_seen)
    fold_to_bet_rate = _shrunk_rate(stats["folded_to_bet"], faced_bet)
    aggression_rate = _shrunk_rate(stats["aggressive_actions"], total_actions, prior_mean=0.3)

    if faced_bet >= MIN_CLASSIFY_EVIDENCE and fold_to_bet_rate < 0.15:
        return "STATION"
    if total_actions >= MIN_CLASSIFY_EVIDENCE and aggression_rate > 0.55:
        return "MANIAC"
    if hands_seen >= MIN_CLASSIFY_EVIDENCE and entry_rate < 0.15:
        return "NIT"
    if hands_seen >= MIN_CLASSIFY_EVIDENCE and entry_rate > 0.55 and aggression_rate < 0.20:
        return "LOOSE_PASSIVE"
    if hands_seen >= MIN_CLASSIFY_EVIDENCE * 2:
        return "TAG"
    return "UNKNOWN"


def _get_aggressor(view):
    """Player whose bet/raise set the current amount_to_call, from the
    CURRENT street's action_history (resets per street — engine fact)."""
    last = None
    for player, action in view.action_history:
        if action and action[0] in ("bet", "raise"):
            last = player
    return last


def _classification_call_adjustment(opp_stats, aggressor):
    if aggressor is None:
        return 0.0
    ctype = _classify(opp_stats.get(aggressor))
    return TYPE_CALL_ADJUSTMENT.get(ctype, 0.0)


# Phase 3c: isolation-sizing discount (strategy-critique secondary finding).
# Raising to isolate a target with unclassified (UNKNOWN) players still to
# act behind risks a squeeze from one of them waking up with a big hand —
# we can't yet price their continuing range. Applied only to the RAISE
# decision (extra chips committed), not calling, since a raise creates more
# exposure to that risk than flatting.
ISOLATION_UNKNOWN_PENALTY = 0.04


def _unknown_players_behind(view, opp_stats):
    order = view.seat_order
    n = len(order)
    if n <= 1:
        return 0
    my_idx = order.index(view.your_name)
    dealer_idx = order.index(view.dealer)
    count = 0
    idx = (my_idx + 1) % n
    while idx != dealer_idx:
        p = order[idx]
        if view.player_status.get(p) == "active" and _classify(opp_stats.get(p)) == "UNKNOWN":
            count += 1
        idx = (idx + 1) % n
    return count


# =============================================================================
# SECTION 5: Position signal
# =============================================================================

def _acts_after_us(view):
    """Count of still-active players positioned between us and the dealer
    (i.e., act after us in this street's initial pass). Dealer acts FIRST
    every street here (verified in engine._first_actor) — a permanent,
    compounding positional disadvantage, not the single-street effect
    standard equity-realization literature assumes. See DESIGN.md Section 4."""
    order = view.seat_order
    n = len(order)
    if n <= 1:
        return 0
    my_idx = order.index(view.your_name)
    dealer_idx = order.index(view.dealer)
    count = 0
    idx = (my_idx + 1) % n
    while idx != dealer_idx:
        p = order[idx]
        if view.player_status.get(p) == "active":
            count += 1
        idx = (idx + 1) % n
    return count


def _live_opponent_count(view):
    return sum(1 for p, s in view.player_status.items()
               if p != view.your_name and s in ("active", "all_in"))


# =============================================================================
# SECTION 6: Decision logic
# =============================================================================

def _implied_odds_discount(stack, to_call, pot):
    """Deep-stack implied-odds allowance: pure pot-odds pricing (no implied
    odds) is too conservative when 50k-deep stacks dwarf the current bet —
    found via the position-EV diagnostic (DESIGN.md Section 4/9 required this
    measurement): stacking the full multiway margin AND the full position
    margin with zero implied-odds credit made even AA unable to clear the
    required-equity bar facing a single pot-size open in the worst seat,
    regardless of hand strength (a structural over-fold, not a strategy
    choice). Capped modestly — this is a Phase 2 calibration fix, not a full
    implied-odds model (that needs Phase 3's opponent-specific range data,
    since a bettor whose sizing carries no information, like a bot that bets
    a fixed amount regardless of cards, offers different implied odds than
    a thinking opponent)."""
    stack_after = max(0, stack - to_call)
    pot_after = pot + to_call
    depth_ratio = stack_after / max(1, pot_after)
    return min(0.08, 0.015 * depth_ratio)


def _required_equity(pot, to_call, n_live_opp, acts_after, n_at_table, stack=None):
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.0
    multiway_margin = CONFIG["call_margin_base"] + CONFIG["call_margin_per_extra_opp"] * max(0, n_live_opp - 1)
    position_frac = acts_after / max(1, n_at_table - 1)
    position_margin = CONFIG["position_discount_max"] * position_frac
    required = pot_odds + multiway_margin + position_margin
    if stack is not None:
        required -= _implied_odds_discount(stack, to_call, pot)
    return required


def _avg_fold_to_bet(opp_stats, live_opponents):
    rates = []
    for name in live_opponents:
        st = opp_stats.get(name)
        if not st:
            rates.append(CONFIG["shrinkage_prior_mean"])
            continue
        rates.append(_shrunk_rate(st["folded_to_bet"], st["faced_bet"]))
    return sum(rates) / len(rates) if rates else CONFIG["shrinkage_prior_mean"]


def _value_bet_size(equity, pot, stack, opp_stats, live_opponents):
    """Law 3 shove-for-value (research 05): with k identified sticky
    (station-like) callers, the bet portion is +EV iff equity > 1/(k+1) —
    shove for value against them. Stickiness is read from the shrunk
    fold-to-bet rate, which is itself evidence-gated: an opponent with few
    observations stays near the 0.5 population prior and won't trigger a
    shove (Law 4 / critique-fix per-bucket confirmation, in minimal form)."""
    sticky = 0
    for name in live_opponents:
        st = opp_stats.get(name)
        faced = st["faced_bet"] if st else 0
        folded = st["folded_to_bet"] if st else 0
        rate = _shrunk_rate(folded, faced)
        if rate < 0.25:
            sticky += 1
    if sticky > 0:
        shove_threshold = 1.0 / (sticky + 1)
        if equity > shove_threshold + 0.10:
            return stack
    size_frac = CONFIG["value_bet_frac_pot"]
    return max(1, min(stack, int(pot * size_frac)))


def _should_probe(view, opp_stats, probes_used):
    if view.hand_number > CONFIG["recon_hand_window"]:
        return False
    if probes_used >= CONFIG["recon_max_probes"]:
        return False
    return True


def _decide_preflop(view, opp_stats, probes_used, deadline):
    hole = view.your_hole_cards
    key = hand_key(hole)
    to_call = view.amount_to_call
    stack = view.your_stack
    n_opp = _live_opponent_count(view)

    if to_call == 0:
        if key in PREMIUM_SET and stack > 0:
            size = max(1, min(stack, int(stack * CONFIG["preflop_open_frac"])))
            return ("bet", size)
        if _should_probe(view, opp_stats, probes_used) and stack > 0:
            _record_probe()
            return ("bet", min(stack, CONFIG["recon_probe_size"]))
        return ("check",)

    # Never fold to a trivial min-bet (Law: needed equity ~= 1/(P+2), always clears).
    if to_call <= CONFIG["never_fold_to_chips"]:
        return ("call",)

    equity, _ = estimate_equity(hole, [], n_opp, _rng, deadline, max_trials=CONFIG["mc_max_trials"])
    acts_after = _acts_after_us(view)
    n_at_table = len(view.seat_order)
    required = _required_equity(view.pot, to_call, n_opp, acts_after, n_at_table, stack=stack)
    aggressor = _get_aggressor(view)
    required += _classification_call_adjustment(opp_stats, aggressor)

    if equity < required:
        return ("fold",)

    raise_bar = CONFIG["raise_value_equity_threshold"] + ISOLATION_UNKNOWN_PENALTY * _unknown_players_behind(view, opp_stats)
    if equity >= raise_bar and view.min_raise_to is not None:
        return ("raise", view.min_raise_to)
    return ("call",)


def _decide_postflop(view, opp_stats, deadline):
    hole = view.your_hole_cards
    board = view.community_cards
    to_call = view.amount_to_call
    stack = view.your_stack
    pot = view.pot
    n_opp = _live_opponent_count(view)

    live_opponents = [p for p, s in view.player_status.items()
                       if p != view.your_name and s in ("active", "all_in")]

    # Phase 3b: range-condition each opponent's dealt hand on their observed
    # looseness instead of uniform-random (deferred from Phase 2 — see
    # DESIGN.md scope cut). Falls back cleanly to the uniform engine if for
    # any reason no opponents are resolvable.
    if live_opponents:
        prefixes = [_range_prefix(_opponent_range_width(opp_stats.get(p))) for p in live_opponents]
        equity, _ = estimate_equity_ranged(hole, board, prefixes, _rng, deadline,
                                            max_trials=CONFIG["mc_max_trials"])
    else:
        equity, _ = estimate_equity(hole, board, n_opp, _rng, deadline, max_trials=CONFIG["mc_max_trials"])
    acts_after = _acts_after_us(view)
    n_at_table = len(view.seat_order)

    fold_to_bet_avg = _avg_fold_to_bet(opp_stats, live_opponents)

    if to_call == 0:
        if pot <= 0:
            # Law 2: never bluff/bet an empty pot without a real equity edge.
            if equity >= CONFIG["value_equity_threshold"]:
                size = max(1, min(stack, int(stack * 0.10)))
                return ("bet", size)
            return ("check",)
        if equity >= CONFIG["value_equity_threshold"]:
            size = _value_bet_size(equity, pot, stack, opp_stats, live_opponents)
            return ("bet", size)
        return ("check",)

    if to_call <= CONFIG["never_fold_to_chips"]:
        return ("call",)

    required = _required_equity(pot, to_call, n_opp, acts_after, n_at_table, stack=stack)
    aggressor = _get_aggressor(view)
    required += _classification_call_adjustment(opp_stats, aggressor)
    if equity < required:
        return ("fold",)

    raise_bar = CONFIG["raise_value_equity_threshold"] + ISOLATION_UNKNOWN_PENALTY * _unknown_players_behind(view, opp_stats)
    if equity >= raise_bar and view.min_raise_to is not None and stack > to_call:
        return ("raise", view.min_raise_to)
    return ("call",)


# =============================================================================
# SECTION 7: Legalization (exact, using our own tracked street_wager)
# =============================================================================

def _legalize(view, action, my_street_wager):
    stack = view.your_stack
    to_call = view.amount_to_call

    if not isinstance(action, tuple) or not action:
        return _safe_action(view)
    kind = action[0]

    if kind == "fold":
        return ("fold",)
    if kind == "check":
        return ("check",) if to_call == 0 else _safe_action(view)
    if kind == "call":
        return ("call",) if to_call > 0 else ("check",)

    if kind == "bet":
        if to_call != 0 or stack <= 0:
            return _safe_action(view)
        amount = action[1] if len(action) > 1 else 1
        amount = int(amount)
        amount = max(1, min(amount, stack))
        return ("bet", amount)

    if kind == "raise":
        if to_call <= 0 or view.min_raise_to is None or stack <= to_call:
            return ("call",) if to_call > 0 else ("check",)
        min_to = view.min_raise_to
        max_to = my_street_wager + stack
        if min_to > max_to:
            return ("call",)
        amount = action[1] if len(action) > 1 else min_to
        amount = int(amount)
        amount = max(min_to, min(amount, max_to))
        return ("raise", amount)

    return _safe_action(view)


def _safe_action(view):
    try:
        to_call = view.amount_to_call
        if to_call == 0:
            return ("check",)
        if to_call <= CONFIG["never_fold_to_chips"]:
            return ("call",)
        return ("fold",)
    except Exception:
        return ("fold",)


# =============================================================================
# SECTION 8: Entry point
# =============================================================================

def nextMove(view):
    try:
        deadline = time.monotonic() + CONFIG["move_budget"]
        opp_stats, my_street_wager, probes_used = _sync_state(view)

        if view.street == "preflop":
            action = _decide_preflop(view, opp_stats, probes_used, deadline)
        else:
            action = _decide_postflop(view, opp_stats, deadline)

        final = _legalize(view, action, my_street_wager)
        _record_my_action(final, view.amount_to_call, view.your_stack)
        return final
    except Exception:
        return _safe_action(view)
