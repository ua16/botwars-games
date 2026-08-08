# This is the game engine for german whist.

# German whist has 2 phases. 
# In the recruitment phase, the players will be given a hand of 13 cards.
# The remaining cards form the stock.
# The top card on the stock is revealed and its suit becomes the trump suit.
# player 1 leads the first trick.
# player 2 must follow suit if they can, otherwise they can play any card.
# the winner of the trick gets the card on top and the loser gets the unrevealed card underneath
# both players add those cards to their hands.
# the top card on the stock is then revealed and the process repeats.
# The winner of the trick leads the next trick.
# This continues until all 13 tricks are played and stock is empty.

# In the scoring phase, the players will use their hands from the recruitment phase to play tricks.
# the winner of the last recruitment trick leads the first scoring trick.
# player 2 must follow suit if they can, otherwise they can play any card.
# tricks are played until both players have played all their cards. (both have the same amount, so 13 tricks)
# the overall winner is the player with the most tricks won.

import csv
import random


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))  # 2..14, where 14 = Ace


def build_deck():
    """Return a full 52-card deck as a list of (suit, rank) tuples."""
    return [(s, r) for s in SUITS for r in RANKS]


def card_str(card):
    """Human-readable string for a card tuple, e.g. ('H', 14) -> 'AH'."""
    rank_names = {14: "A", 13: "K", 12: "Q", 11: "J"}
    r = rank_names.get(card[1], str(card[1]))
    return f"{r}{card[0]}"


# ---------------------------------------------------------------------------
# PlayerView – the filtered snapshot a player's nextMove receives
# ---------------------------------------------------------------------------
class PlayerView:
    """Read-only game state visible to the current player."""

    def __init__(self, your_hand, face_up_card, trump_suit, current_trick,
                 phase, tricks_won, stock_remaining, your_name, opponent_name, lead):
        self.your_hand = list(your_hand)          # copy so players can't mutate engine state
        self.face_up_card = face_up_card           # (suit, rank) or None
        self.trump_suit = trump_suit
        self.current_trick = list(current_trick)   # [(player_name, card), ...]
        self.phase = phase                         # 1 = recruitment, 2 = scoring
        self.tricks_won = dict(tricks_won)         # {name: count}
        self.stock_remaining = stock_remaining     # int
        self.your_name = your_name
        self.opponent_name = opponent_name
        self.lead = lead                           # name of player who leads this trick


# ---------------------------------------------------------------------------
# Internal GameState – full authoritative state kept by the engine
# ---------------------------------------------------------------------------
class GameState:
    def __init__(self, p1, p2):
        self.players = [p1, p2]                    # player name strings
        self.hands = {p1: [], p2: []}
        self.stock = []                            # remaining stock (list of cards, top = index 0)
        self.trump_suit = None                     # suit of the first revealed stock card
        self.face_up_card = None                   # currently revealed top card of stock
        self.turn = None                           # who leads the current trick
        self.trick = []                            # [(player, card), ...]
        self.phase = 1                             # 1 = recruitment, 2 = scoring
        self.tricks_won = {p1: 0, p2: 0}          # scoring-phase tricks only
        self.recruitment_tricks_won = {p1: 0, p2: 0}
        self.game_over = False
        self.winner = None                         # name string or None for draw

    def opponent(self, player):
        """Return the other player's name."""
        return self.players[1] if player == self.players[0] else self.players[0]

    def make_player_view(self, player):
        """Build a PlayerView for *player*."""
        return PlayerView(
            your_hand=self.hands[player],
            face_up_card=self.face_up_card,
            trump_suit=self.trump_suit,
            current_trick=self.trick,
            phase=self.phase,
            tricks_won=dict(self.tricks_won),
            stock_remaining=len(self.stock), # This length excludes the face-up card
            your_name=player,
            opponent_name=self.opponent(player),
            lead=self.turn,
        )


# ---------------------------------------------------------------------------
# Trick resolution
# ---------------------------------------------------------------------------
def resolve_trick(lead_card, follow_card, trump_suit):
    """Return True if the *lead_card* wins the trick, False if *follow_card* wins."""
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card

    if follow_suit == lead_suit:
        # Same suit – higher rank wins
        return lead_rank >= follow_rank
    elif follow_suit == trump_suit:
        # Follower played a trump on a non-trump lead
        return False
    else:
        # Follower played off-suit non-trump – leader wins
        return True


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def legal_cards(hand, lead_card):
    """Return the list of cards a player may legally play.

    If *lead_card* is None the player is leading and may play anything.
    Otherwise they must follow the lead suit if possible.
    """
    if lead_card is None:
        return list(hand)
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


# ---------------------------------------------------------------------------
# playGame – runs one complete game
# ---------------------------------------------------------------------------
def playGame(name1, func1, name2, func2, logger):
    """Play one full game of German Whist.

    Parameters
    ----------
    name1, name2 : str
        Player names.
    func1, func2 : callable
        The nextMove functions for each player.
    logger : GameLogger
        Logger instance that records game events.

    Returns
    -------
    int
        1 if player 1 wins, 2 if player 2 wins, 0 for a draw.
    """
    funcs = {name1: func1, name2: func2}
    gs = GameState(name1, name2)

    # ---- Setup ----
    deck = build_deck()
    random.shuffle(deck)
    gs.hands[name1] = deck[:13]
    gs.hands[name2] = deck[13:26]
    gs.stock = deck[26:]              # 26 cards in stock, index 0 = top

    # Reveal top card – its suit is trump for the whole game
    gs.face_up_card = gs.stock.pop(0)
    gs.trump_suit = gs.face_up_card[0]

    gs.turn = name1                   # player 1 leads the first trick

    logger.log_setup(gs)

    # ------------------------------------------------------------------
    # Phase 1 – Recruitment (13 tricks)
    # ------------------------------------------------------------------
    gs.phase = 1
    for trick_num in range(13):
        leader = gs.turn
        follower = gs.opponent(leader)
        gs.trick = []

        # --- Leader plays ---
        leader_card = _get_move(gs, leader, funcs[leader], lead_card=None, logger=logger)
        if leader_card is None:
            # forfeit
            return _forfeit(gs, leader, name1, name2, logger)
        gs.trick.append((leader, leader_card))
        gs.hands[leader].remove(leader_card)

        # --- Follower plays ---
        follower_card = _get_move(gs, follower, funcs[follower], lead_card=leader_card, logger=logger)
        if follower_card is None:
            return _forfeit(gs, follower, name1, name2, logger)
        gs.trick.append((follower, follower_card))
        gs.hands[follower].remove(follower_card)

        # --- Resolve trick ---
        leader_wins = resolve_trick(leader_card, follower_card, gs.trump_suit)
        trick_winner = leader if leader_wins else follower
        trick_loser = gs.opponent(trick_winner)
        gs.recruitment_tricks_won[trick_winner] += 1

        logger.log_trick(gs.phase, trick_num + 1, leader, leader_card, follower, follower_card, trick_winner)

        # Winner takes the face-up card; loser takes the next (hidden) card
        gs.hands[trick_winner].append(gs.face_up_card)
        if gs.stock:
            hidden_card = gs.stock.pop(0)
            gs.hands[trick_loser].append(hidden_card)
            # Reveal next top card (if any remain)
            if gs.stock:
                gs.face_up_card = gs.stock.pop(0)
            else:
                gs.face_up_card = None
        else:
            gs.face_up_card = None

        # Winner leads next trick
        gs.turn = trick_winner

    # ------------------------------------------------------------------
    # Phase 2 – Scoring (13 tricks)
    # ------------------------------------------------------------------
    gs.phase = 2
    gs.face_up_card = None
    logger.log_phase_change(2)

    for trick_num in range(13):
        leader = gs.turn
        follower = gs.opponent(leader)
        gs.trick = []

        # --- Leader plays ---
        leader_card = _get_move(gs, leader, funcs[leader], lead_card=None, logger=logger)
        if leader_card is None:
            return _forfeit(gs, leader, name1, name2, logger)
        gs.trick.append((leader, leader_card))
        gs.hands[leader].remove(leader_card)

        # --- Follower plays ---
        follower_card = _get_move(gs, follower, funcs[follower], lead_card=leader_card, logger=logger)
        if follower_card is None:
            return _forfeit(gs, follower, name1, name2, logger)
        gs.trick.append((follower, follower_card))
        gs.hands[follower].remove(follower_card)

        # --- Resolve trick ---
        leader_wins = resolve_trick(leader_card, follower_card, gs.trump_suit)
        trick_winner = leader if leader_wins else follower
        gs.tricks_won[trick_winner] += 1

        logger.log_trick(gs.phase, trick_num + 1, leader, leader_card, follower, follower_card, trick_winner)

        gs.turn = trick_winner

    # ------------------------------------------------------------------
    # Determine result
    # ------------------------------------------------------------------
    gs.game_over = True
    if gs.tricks_won[name1] > gs.tricks_won[name2]:
        gs.winner = name1
        result = 1
    elif gs.tricks_won[name2] > gs.tricks_won[name1]:
        gs.winner = name2
        result = 2
    else:
        gs.winner = None
        result = 0

    logger.log_result(gs)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_move(gs, player, func, lead_card, logger):
    """Call a player's nextMove safely. Return the card or None on forfeit."""
    view = gs.make_player_view(player)
    allowed = legal_cards(gs.hands[player], lead_card)

    try:
        card = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    # Validate
    if card not in gs.hands[player]:
        logger.log_error(player, f"played {card!r} which is not in their hand")
        return None
    if card not in allowed:
        logger.log_error(player, f"played {card_str(card)} but must follow suit")
        return None

    return card


def _forfeit(gs, forfeiting_player, name1, name2, logger):
    """Handle a forfeit – the other player wins."""
    gs.game_over = True
    winner = gs.opponent(forfeiting_player)
    gs.winner = winner
    logger.log_forfeit(forfeiting_player, winner)
    return 1 if winner == name1 else 2


# ---------------------------------------------------------------------------
# GameLogger – writes per-game events to a file
# ---------------------------------------------------------------------------
class GameLogger:
    """Simple file-based logger for a matchup between two players."""

    def __init__(self, filepath):
        self.filepath = filepath
        self._lines = []

    # -- public API called by playGame --

    def start_game(self, game_number):
        self._lines.append(f"\n{'='*60}")
        self._lines.append(f"Game {game_number}")
        self._lines.append(f"{'='*60}")

    def log_setup(self, gs):
        self._lines.append(f"Players: {gs.players[0]} vs {gs.players[1]}")
        self._lines.append(f"Trump suit: {gs.trump_suit}")
        self._lines.append(f"Face-up card: {card_str(gs.face_up_card)}")
        self._lines.append(f"{gs.players[0]} hand: {_hand_str(gs.hands[gs.players[0]])}")
        self._lines.append(f"{gs.players[1]} hand: {_hand_str(gs.hands[gs.players[1]])}")

    def log_phase_change(self, phase):
        self._lines.append(f"\n--- Phase {phase} {'(Scoring)' if phase == 2 else '(Recruitment)'} ---")

    def log_trick(self, phase, trick_num, leader, leader_card, follower, follower_card, winner):
        self._lines.append(
            f"  P{phase} Trick {trick_num:>2}: "
            f"{leader} leads {card_str(leader_card)}, "
            f"{follower} plays {card_str(follower_card)} -> "
            f"{winner} wins"
        )

    def log_error(self, player, message):
        self._lines.append(f"  ERROR ({player}): {message}")

    def log_forfeit(self, loser, winner):
        self._lines.append(f"  FORFEIT: {loser} forfeits. {winner} wins.")

    def log_result(self, gs):
        p1, p2 = gs.players
        self._lines.append(
            f"  Result: {p1} {gs.tricks_won[p1]} - {gs.tricks_won[p2]} {p2}"
        )
        if gs.winner:
            self._lines.append(f"  Winner: {gs.winner}")
        else:
            self._lines.append(f"  Draw")

    # -- file I/O --

    def flush(self):
        """Write all buffered lines to the log file."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self._lines) + "\n")

    @staticmethod
    def write_leaderboard_csv(filepath, scores):
        """Write tournament scores to a CSV file.

        *scores* is {player_name: float}. Rows are sorted by score descending.
        No rank/position column — only player name and score.
        """
        rows = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["player", "score"])
            for name, score in rows:
                writer.writerow([name, f"{score:.1f}"])


def _hand_str(hand):
    """Pretty-print a hand."""
    return " ".join(card_str(c) for c in sorted(hand, key=lambda c: (c[0], c[1])))
