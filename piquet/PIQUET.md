# Piquet — Core Rules

Piquet is a classic two-player trick-taking game using a 32-card deck:

* 7, 8, 9, 10, J, Q, K, A in each suit
* Aces are high

It looks complicated initially because scoring happens in phases, but the underlying gameplay is structured and logical.

---

# Objective

Score more points than your opponent through:

* combinations in hand
* trick-taking
* strategic discarding/drawing

Traditionally played to 100 points.

---

# Card rankings

For trick-taking:

A > K > Q > J > 10 > 9 > 8 > 7

For combinations (sets/sequences), ace is also high.

---

# Deal

Each player gets 12 cards.

The remaining 8 cards form the talon (stock).

Dealer alternates every hand.

---

# Structure of a hand

Each hand has 3 major phases:

1. Discard and draw
2. Declare combinations
3. Play tricks

---

# 1. Discard and draw phase

This is one of the strategic cores of Piquet.

## Elder hand vs younger hand

The non-dealer is called the **elder hand** and acts first.

The dealer is the **younger hand**.

---

## Elder hand exchange

The elder hand may discard:

* 1 to 5 cards

Then draws the same number from the talon.

The elder hand has first access to the stock, which is a major advantage.

---

## Younger hand exchange

Then the younger hand may discard:

* up to the number of remaining talon cards

Usually fewer remain because elder hand drew first.

---

# 2. Declaration phase

Players score combinations in this order:

1. Point
2. Sequences
3. Sets

The elder hand declares first in each category.

Opponent may respond if they beat it.

---

# POINT (most cards in one suit)

Count the number of cards in your longest suit.

Example:

* 5 hearts beats 4 clubs

If tied in length:

* higher total pip value wins

Card values for point:

* A = 11
* K/Q/J/10 = 10
* 9/8/7 face value

The winner scores:

* number of cards in the suit

Example:

* Best suit length = 5
* Winner scores 5 points

---

# SEQUENCES (runs)

Runs of 3+ consecutive cards in the same suit.

Examples:

* 7-8-9
* 10-J-Q-K
* Q-K-A

Scoring:

* 3-card run = 3
* 4-card run = 4
* 5+ card run = 10 plus extra cards

Examples:

* Run of 5 = 10
* Run of 6 = 11
* Run of 7 = 12
* Run of 8 = 13

Highest run wins declarations.

Priority:

1. longer run
2. higher top card

---

# SETS

Three or four of a kind:

* only 10s or higher count

So:

* 10s
* Jacks
* Queens
* Kings
* Aces

Scoring:

* 3 of a kind = 3 points
* 4 of a kind = 14 points

Higher rank wins ties.

---

# Example declaration round

Player A:

* run of 4
* four queens

Player B:

* run of 5
* three aces

Results:

* B wins sequence category
* A wins set category

Each scores only in categories they win.

---

# 3. Trick-taking phase

After declarations, players play 12 tricks.

Rules:

* Elder hand leads first
* Must follow suit if possible
* No trump suit

Each trick:

* winner leads next trick

---

# Trick scoring

* Each trick won = 1 point
* Last trick bonus = 1 extra point

Sweep bonus:

* Winning 7+ tricks earns additional bonuses depending on ruleset

Common bonuses:

* Capot = win all 12 tricks
* Majority of tricks bonus

---

# Important special scores

## Carte Blanche

If dealt no face cards:

* no K/Q/J

You may reveal hand before exchanges for bonus points.

Traditionally:

* 10 points

---

## Repique

Large bonus for scoring 30+ before opponent scores anything.

Usually:

* 60 bonus points

---

## Pique

Scoring 30+ during trick play before opponent scores.

Also a major bonus.

---

# Why Piquet is deep

The strategy comes from:

* imperfect information
* discard inference
* memory tracking
* declaration concealment
* tempo in trick play

The discard phase alone creates substantial psychological play.

---

# Technical implementation

Follow the same engine layout as `germanwhist/engine.py` and **ENGINESPEC.md**: authoritative `GameState`, filtered `PlayerView`, pure rule helpers, `playGame` + `GameLogger`. `main.py` only loads players and runs tournaments — no rules there.

## File layout

```
piquet/
  engine.py              # rules, playGame, PlayerView, GameState, GameLogger
  main.py                # copy germanwhist/main.py pattern
  players/
    example_player.py    # documents PlayerView + nextMove per phase
  PIQUET.md              # this file
```

## Cards and deck

- Represent cards as `(suit, rank)` tuples; suits `"H"`, `"D"`, `"C"`, `"S"`.
- Ranks `7`–`14` where `14` = Ace (same encoding as German Whist, smaller deck).
- `build_deck()` → 32 cards; `card_str()` for logging.

## GameState (engine-only)

Holds full truth. Suggested fields:

| Field | Purpose |
|-------|---------|
| `players`, `hands` | Both hands; mutate on deal, exchange, tricks |
| `talon` | Remaining stock (`list`; engine `pop`s on draw; **never** exposed to players) |
| `dealer`, `elder` | Dealer name; elder = non-dealer, acts first in exchange/declare/tricks |
| `phase` | `"exchange"` → `"declare"` → `"tricks"` |
| `turn` | Who must act now (actor name) |
| `trick` | Current trick: `[(name, card), ...]` during tricks phase |
| `scores` | Cumulative match points `{name: int}` toward 100 |
| `hand_points` | Points scored in the current deal only |
| `declarations` | Public declaration log (what was claimed and shown) |
| `exchanges` | Record of each player’s discard count (and optionally discarded cards for logging) |
| `tricks_won` | Trick counts this deal |
| `game_over`, `winner` | Set when a player reaches target score |

`make_player_view(player)` builds a **fresh** `PlayerView` each call with **copied** lists/dicts so bots cannot mutate engine state.

## PlayerView (what bots see)

Expose only legal information. Never include opponent’s hand or unrevealed talon cards.

| Attribute | When | Notes |
|-----------|------|-------|
| `your_hand` | always | Copy of acting player’s cards |
| `phase` | always | `"exchange"`, `"declare"`, or `"tricks"` |
| `your_name`, `opponent_name` | always | From `playGame` args |
| `dealer`, `elder` | always | Who dealt; who is elder this hand |
| `turn` | always | Name of player who must act |
| `talon_remaining` | exchange | **Count only**, like `stock_remaining` in German Whist |
| `your_score`, `opponent_score` | always | Cumulative match totals |
| `hand_points` | always | Points so far this deal (both players) |
| `opponent_discarded` | after exchange | How many cards opponent exchanged (infer their draw) |
| `declarations` | declare+ | Public claims from declaration phase |
| `current_trick`, `lead` | tricks | In-play trick and who led it |
| `tricks_won` | tricks | `{name: count}` this deal |

Document every attribute in `players/example_player.py`.

## Privacy model

Same pattern as German Whist:

- **Hidden:** opponent hand, talon order/contents until drawn into your hand.
- **Public:** phase, whose turn, cumulative scores, declaration results, completed tricks, trick winner.
- **Inference:** elder’s exchange reduces `talon_remaining` before younger acts; log opponent discard *count* (cards optional in logger only).

## `playGame` loop

```python
def playGame(name1, func1, name2, func2, logger) -> int  # 1, 2, or 0
```

One call = full **match to 100** (or configured target), not a single 12-trick deal:

1. **Setup hand** — shuffle, deal 12 each, 8 to `talon`, set dealer/elder, log full state (logger only).
2. **Exchange** — elder discards/draws, then younger; validate counts vs talon size; update hands.
3. **Declare** — point → sequences → sets; elder first per category; engine scores from revealed best claims.
4. **Tricks** — 12 tricks, elder leads first; `legal_cards(hand, lead_card)` + `resolve_trick` (no trump); update `turn` to trick winner.
5. **End hand** — apply trick bonuses, repique/pique if applicable, add to `scores`.
6. Repeat from step 1 (alternate dealer) until `scores[name] >= 100` or draw rule fires.
7. Return `1` / `2` / `0` for `name1` win / `name2` win / draw.

Invalid move or exception → forfeit (other player wins), same as `_get_move` in German Whist.

## `nextMove` contract

Single entry point; **return type depends on `phase`** (bots branch on `gameState.phase`):

| Phase | Return | Validation |
|-------|--------|------------|
| `exchange` | `list` of cards to discard (0–5 elder; 0–`talon_remaining` younger) | Subset of `your_hand`; draw count = discard count |
| `declare` | e.g. `("pass")` or `("claim", category, detail)` | Engine-defined; must match declaration order |
| `tricks` | `(suit, rank)` card | In hand and in `legal_cards(...)` |

Use `_get_exchange`, `_get_declaration`, `_get_trick_card` helpers mirroring `_get_move`: build view → call `func(view)` → validate → forfeit on failure.

## Turns

| Phase | Order |
|-------|-------|
| Exchange | Elder → younger |
| Declare | Elder declares first in each category; opponent responds |
| Tricks | Elder leads trick 1; thereafter winner of previous trick leads |

Track with `gs.turn`; only call `nextMove` for the acting player.

## Rules helpers (pure functions in `engine.py`)

- `legal_cards(hand, lead_card)` — follow suit if possible (no trump).
- `resolve_trick(lead_card, follow_card)` — ace high, no trump.
- `score_point`, `score_sequences`, `score_sets`, `score_tricks` — used by engine during declare/trick resolution.
- Players should **not** reimplement scoring; engine is authoritative.

## GameLogger

Logger sees **everything** (both hands, talon, discards) for replay; bots never receive the logger. Buffer events (`log_setup`, `log_exchange`, `log_declaration`, `log_trick`, `log_hand_result`, `log_result`) and `flush()` to file — same pattern as German Whist.

## Agent checklist

1. Read this file for rules; read `germanwhist/engine.py` + **ENGINESPEC.md** for patterns.
2. Implement `engine.py` before `main.py`.
3. Ship `players/example_player.py` documenting `PlayerView` and phase-specific `nextMove` returns.
4. Keep all rule changes in the engine; tournament code stays generic.

---

# Beginner advice

## Keep track of:

* discarded suits
* revealed sequences
* high cards already shown

## Early priorities:

* preserve long suits
* value 5-card runs highly
* aces are extremely strong

