# Piquet game engine — two-player trick-taking to 100 points.

import csv
import random

# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(7, 15))  # 7..14, where 14 = Ace
TARGET_SCORE = 100

DECLARE_CATEGORIES = ("point", "sequence", "set")


def build_deck():
    """Return a full 32-card Piquet deck as (suit, rank) tuples."""
    return [(s, r) for s in SUITS for r in RANKS]


def card_str(card):
    """Human-readable card string, e.g. ('H', 14) -> 'AH'."""
    rank_names = {14: "A", 13: "K", 12: "Q", 11: "J"}
    r = rank_names.get(card[1], str(card[1]))
    return f"{r}{card[0]}"


def trick_rank(card):
    """Rank for trick-taking (ace high)."""
    return card[1]


def point_pip(card):
    """Pip value for point scoring."""
    rank = card[1]
    if rank == 14:
        return 11
    if rank >= 10:
        return 10
    return rank


def is_face_card(card):
    """K, Q, or J."""
    return card[1] in (11, 12, 13)


# ---------------------------------------------------------------------------
# PlayerView
# ---------------------------------------------------------------------------
class PlayerView:
    """Read-only game state visible to the acting player."""

    def __init__(
        self,
        your_hand,
        phase,
        your_name,
        opponent_name,
        dealer,
        elder,
        turn,
        your_score,
        opponent_score,
        hand_points,
        talon_remaining=None,
        opponent_discarded=None,
        declarations=None,
        declare_category=None,
        elder_claim=None,
        current_trick=None,
        lead=None,
        tricks_won=None,
        hand_history=None,
    ):
        self.your_hand = list(your_hand)
        self.phase = phase
        self.your_name = your_name
        self.opponent_name = opponent_name
        self.dealer = dealer
        self.elder = elder
        self.turn = turn
        self.your_score = your_score
        self.opponent_score = opponent_score
        self.hand_points = dict(hand_points)
        self.talon_remaining = talon_remaining
        self.opponent_discarded = opponent_discarded
        self.declarations = list(declarations) if declarations is not None else []
        self.declare_category = declare_category
        self.elder_claim = elder_claim
        self.current_trick = list(current_trick) if current_trick is not None else []
        self.lead = lead
        self.tricks_won = dict(tricks_won) if tricks_won is not None else {}
        self.hand_history = list(hand_history) if hand_history is not None else []


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------
class GameState:
    def __init__(self, p1, p2):
        self.players = [p1, p2]
        self.hands = {p1: [], p2: []}
        self.talon = []
        self.dealer = None
        self.elder = None
        self.phase = "exchange"
        self.turn = None
        self.trick = []
        self.scores = {p1: 0, p2: 0}
        self.hand_points = {p1: 0, p2: 0}
        self.declarations = []
        self.exchanges = {}
        self.tricks_won = {p1: 0, p2: 0}
        self.trick_history = []
        self.hand_history = []
        self.game_over = False
        self.winner = None
        # Declaration sub-state
        self.declare_category_idx = 0
        self.declare_step = "elder"
        self.elder_claim = None
        self.opponent_discarded = {p1: None, p2: None}

    def opponent(self, player):
        return self.players[1] if player == self.players[0] else self.players[0]

    def make_player_view(self, player):
        opp = self.opponent(player)
        talon_remaining = None
        opponent_discarded = None
        declare_category = None
        elder_claim = None
        current_trick = None
        lead = None
        tricks_won = None

        if self.phase == "exchange":
            talon_remaining = len(self.talon)
            opponent_discarded = self.opponent_discarded.get(opp)
        elif self.phase == "declare":
            if self.declare_category_idx < len(DECLARE_CATEGORIES):
                declare_category = DECLARE_CATEGORIES[self.declare_category_idx]
            if self.declare_step == "younger" and self.elder_claim is not None:
                elder_claim = _claim_summary(self.elder_claim)
        elif self.phase == "tricks":
            current_trick = self.trick
            lead = self.turn
            tricks_won = self.tricks_won

        return PlayerView(
            your_hand=self.hands[player],
            phase=self.phase,
            your_name=player,
            opponent_name=opp,
            dealer=self.dealer,
            elder=self.elder,
            turn=self.turn,
            your_score=self.scores[player],
            opponent_score=self.scores[opp],
            hand_points=self.hand_points,
            talon_remaining=talon_remaining,
            opponent_discarded=opponent_discarded,
            declarations=self.declarations,
            declare_category=declare_category,
            elder_claim=elder_claim,
            current_trick=current_trick,
            lead=lead,
            tricks_won=tricks_won,
            hand_history=self.hand_history,
        )


# ---------------------------------------------------------------------------
# Rules helpers
# ---------------------------------------------------------------------------
def legal_cards(hand, lead_card):
    """Cards legal to play; must follow suit if possible (no trump)."""
    if lead_card is None:
        return list(hand)
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def resolve_trick(lead_card, follow_card):
    """Return True if lead_card wins, False if follow_card wins."""
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card
    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    return True


def best_point(hand):
    """Return (length, pip_total, suit) for the best point claim."""
    by_suit = {s: [] for s in SUITS}
    for card in hand:
        by_suit[card[0]].append(card)
    best_len = 0
    best_pips = 0
    best_suit = None
    for suit, cards in by_suit.items():
        if not cards:
            continue
        length = len(cards)
        pips = sum(point_pip(c) for c in cards)
        if length > best_len or (length == best_len and pips > best_pips):
            best_len, best_pips, best_suit = length, pips, suit
    return best_len, best_pips, best_suit


def compare_point(claim_a, claim_b):
    """Return 1 if a wins, 2 if b wins, 0 for tie."""
    len_a, pips_a, _ = claim_a
    len_b, pips_b, _ = claim_b
    if len_a > len_b:
        return 1
    if len_b > len_a:
        return 2
    if pips_a > pips_b:
        return 1
    if pips_b > pips_a:
        return 2
    return 0


def all_sequences_in_hand(hand):
    """Return list of (length, top_rank, suit, cards) for runs of 3+."""
    results = []
    by_suit = {s: sorted({c[1] for c in hand if c[0] == s}) for s in SUITS}
    for suit, ranks in by_suit.items():
        if len(ranks) < 3:
            continue
        i = 0
        while i < len(ranks):
            start = i
            while i + 1 < len(ranks) and ranks[i + 1] == ranks[i] + 1:
                i += 1
            run_len = i - start + 1
            if run_len >= 3:
                top = ranks[i]
                run_ranks = ranks[start : i + 1]
                cards = [(suit, r) for r in run_ranks]
                results.append((run_len, top, suit, cards))
            i += 1
    return results


def best_sequence(hand):
    """Return best sequence claim or None."""
    seqs = all_sequences_in_hand(hand)
    if not seqs:
        return None
    return max(seqs, key=lambda s: (s[0], s[1]))


def compare_sequence(claim_a, claim_b):
    """Return 1 if a wins, 2 if b wins, 0 tie."""
    if claim_a[0] > claim_b[0]:
        return 1
    if claim_b[0] > claim_a[0]:
        return 2
    if claim_a[1] > claim_b[1]:
        return 1
    if claim_b[1] > claim_a[1]:
        return 2
    return 0


def all_sets_in_hand(hand):
    """Return list of (count, rank, cards) for 3/4 of 10+."""
    by_rank = {}
    for card in hand:
        if card[1] >= 10:
            by_rank.setdefault(card[1], []).append(card)
    results = []
    for rank, cards in by_rank.items():
        if len(cards) >= 3:
            results.append((len(cards), rank, cards[:4]))
    return results


def best_set(hand):
    """Return best set claim or None."""
    sets = all_sets_in_hand(hand)
    if not sets:
        return None
    return max(sets, key=lambda s: (s[1], s[0]))


def compare_set(claim_a, claim_b):
    """Return 1 if a wins, 2 if b wins, 0 tie."""
    if claim_a[1] > claim_b[1]:
        return 1
    if claim_b[1] > claim_a[1]:
        return 2
    if claim_a[0] > claim_b[0]:
        return 1
    if claim_b[0] > claim_a[0]:
        return 2
    return 0


def score_point(claim):
    """Points for winning the point category."""
    return claim[0]


def score_sequence(claim):
    """Points for winning a sequence claim."""
    length = claim[0]
    if length == 3:
        return 3
    if length == 4:
        return 4
    return 10 + (length - 5)


def score_set(claim):
    """Points for winning a set claim."""
    count = claim[0]
    return 14 if count >= 4 else 3


def score_tricks(tricks_won, last_trick_winner):
    """Trick-phase points: 1 per trick, last trick +1, majority/capot bonuses."""
    points = {}
    for name, count in tricks_won.items():
        pts = count
        if name == last_trick_winner:
            pts += 1
        points[name] = pts

    names = list(tricks_won.keys())
    if len(names) != 2:
        return points
    a, b = names[0], names[1]
    ca, cb = tricks_won[a], tricks_won[b]
    if ca > cb:
        winner = a
    elif cb > ca:
        winner = b
    else:
        return points

    win_count = tricks_won[winner]
    if win_count == 12:
        points[winner] += 40
    elif win_count >= 7:
        points[winner] += 10
    return points


def _claim_summary(claim):
    """Public summary of a claim for PlayerView."""
    kind = claim["kind"]
    if kind == "point":
        return ("point", claim["length"], claim["suit"])
    if kind == "sequence":
        return ("sequence", claim["length"], claim["top"], claim["suit"])
    return ("set", claim["count"], claim["rank"])


def _build_claim(hand, category):
    """Build engine claim dict from hand for *category*."""
    if category == "point":
        length, pips, suit = best_point(hand)
        if length == 0:
            return None
        return {"kind": "point", "length": length, "pips": pips, "suit": suit}
    if category == "sequence":
        seq = best_sequence(hand)
        if seq is None:
            return None
        length, top, suit, cards = seq
        return {"kind": "sequence", "length": length, "top": top, "suit": suit, "cards": cards}
    if category == "set":
        st = best_set(hand)
        if st is None:
            return None
        count, rank, cards = st
        return {"kind": "set", "count": count, "rank": rank, "cards": cards}
    return None


def _claim_tuple_for_compare(claim):
    if claim["kind"] == "point":
        return (claim["length"], claim["pips"], claim["suit"])
    if claim["kind"] == "sequence":
        return (claim["length"], claim["top"], claim["suit"])
    return (claim["count"], claim["rank"])


def _compare_claims(cat, claim_a, claim_b):
    if cat == "point":
        return compare_point(
            (claim_a["length"], claim_a["pips"], claim_a["suit"]),
            (claim_b["length"], claim_b["pips"], claim_b["suit"]),
        )
    if cat == "sequence":
        return compare_sequence(
            (claim_a["length"], claim_a["top"], claim_a["suit"], None),
            (claim_b["length"], claim_b["top"], claim_b["suit"], None),
        )
    return compare_set(
        (claim_a["count"], claim_a["rank"], None),
        (claim_b["count"], claim_b["rank"], None),
    )


def _score_claim(cat, claim):
    if cat == "point":
        return score_point((claim["length"], claim["pips"], claim["suit"]))
    if cat == "sequence":
        return score_sequence((claim["length"], claim["top"], claim["suit"], None))
    return score_set((claim["count"], claim["rank"], None))


# ---------------------------------------------------------------------------
# playGame
# ---------------------------------------------------------------------------
def playGame(name1, func1, name2, func2, logger):
    """Play a full Piquet match to TARGET_SCORE. Returns 1, 2, or 0."""
    funcs = {name1: func1, name2: func2}
    gs = GameState(name1, name2)
    gs.dealer = name1
    hand_num = 0

    while not gs.game_over:
        hand_num += 1
        _setup_hand(gs, hand_num)
        logger.log_setup(gs)

        if _run_exchange(gs, funcs, name1, name2, logger) is not None:
            return _finish_match(gs, name1, name2, logger)

        if _run_declare(gs, funcs, name1, name2, logger) is not None:
            return _finish_match(gs, name1, name2, logger)

        result = _run_tricks(gs, funcs, name1, name2, logger)
        if result is not None:
            return result

        _end_hand(gs, logger)
        if gs.game_over:
            break
        gs.dealer = gs.opponent(gs.dealer)
        gs.elder = gs.opponent(gs.dealer)

    return _match_result(gs, name1, name2, logger)


def _setup_hand(gs, hand_num):
    """Deal a new hand."""
    p1, p2 = gs.players
    deck = build_deck()
    random.shuffle(deck)
    gs.hands[p1] = deck[:12]
    gs.hands[p2] = deck[12:24]
    gs.talon = deck[24:]
    gs.elder = gs.opponent(gs.dealer)
    gs.phase = "exchange"
    gs.turn = gs.elder
    gs.trick = []
    gs.hand_points = {p1: 0, p2: 0}
    gs.declarations = []
    gs.exchanges = {}
    gs.tricks_won = {p1: 0, p2: 0}
    gs.trick_history = []
    gs.declare_category_idx = 0
    gs.declare_step = "elder"
    gs.elder_claim = None
    gs.opponent_discarded = {p1: None, p2: None}


def _max_discard(gs, player):
    if player == gs.elder:
        return min(5, len(gs.hands[player]))
    return min(len(gs.talon), len(gs.hands[player]))


def _run_exchange(gs, funcs, name1, name2, logger):
    """Exchange phase: elder then younger. Return forfeit result or None."""
    for actor in (gs.elder, gs.opponent(gs.elder)):
        gs.turn = actor
        max_disc = _max_discard(gs, actor)
        discard = _get_exchange(gs, actor, funcs[actor], max_disc, logger)
        if discard is None:
            return _forfeit(gs, actor, name1, name2, logger)

        count = len(discard)
        for card in discard:
            gs.hands[actor].remove(card)
        drawn = []
        for _ in range(count):
            if not gs.talon:
                logger.log_error(actor, "talon empty during draw")
                return _forfeit(gs, actor, name1, name2, logger)
            drawn.append(gs.talon.pop(0))
        gs.hands[actor].extend(drawn)
        gs.exchanges[actor] = {"count": count, "discarded": list(discard)}
        gs.opponent_discarded[actor] = count
        logger.log_exchange(gs, actor, discard, drawn)

    gs.phase = "declare"
    gs.declare_category_idx = 0
    gs.declare_step = "elder"
    gs.elder_claim = None
    gs.turn = gs.elder
    logger.log_phase_change("declare")
    return None


def _run_declare(gs, funcs, name1, name2, logger):
    """Declaration phase. Return forfeit result or None."""
    younger = gs.opponent(gs.elder)

    while gs.declare_category_idx < len(DECLARE_CATEGORIES):
        category = DECLARE_CATEGORIES[gs.declare_category_idx]
        gs.declare_step = "elder"
        gs.elder_claim = None
        gs.turn = gs.elder

        elder_move = _get_declaration(gs, gs.elder, funcs[gs.elder], category, logger)
        if elder_move is None:
            return _forfeit(gs, gs.elder, name1, name2, logger)

        elder_claim = None
        if elder_move == "claim":
            elder_claim = _build_claim(gs.hands[gs.elder], category)
            if elder_claim is None:
                logger.log_error(gs.elder, f"invalid {category} claim (nothing to show)")
                return _forfeit(gs, gs.elder, name1, name2, logger)
            gs.elder_claim = elder_claim

        gs.declare_step = "younger"
        gs.turn = younger
        younger_move = _get_declaration(gs, younger, funcs[younger], category, logger)
        if younger_move is None:
            return _forfeit(gs, younger, name1, name2, logger)

        younger_claim = None
        if younger_move == "claim":
            younger_claim = _build_claim(gs.hands[younger], category)
            if younger_claim is None:
                logger.log_error(younger, f"invalid {category} claim (nothing to show)")
                return _forfeit(gs, younger, name1, name2, logger)

        winner = _resolve_declaration(
            gs, category, elder_move, elder_claim, younger_move, younger_claim, logger
        )
        if winner:
            pts = _score_claim(category, winner["claim"])
            gs.hand_points[winner["name"]] += pts
            gs.declarations.append(
                {
                    "category": category,
                    "winner": winner["name"],
                    "points": pts,
                    "claim": _claim_summary(winner["claim"]),
                }
            )
            logger.log_declaration(category, winner["name"], pts, winner["claim"])

        gs.declare_category_idx += 1

    _check_repique(gs)
    gs.phase = "tricks"
    gs.turn = gs.elder
    gs.trick = []
    logger.log_phase_change("tricks")
    return None


def _resolve_declaration(gs, category, elder_move, elder_claim, younger_move, younger_claim, logger):
    """Determine category winner claim dict or None."""
    elder = gs.elder
    younger = gs.opponent(elder)

    if elder_move == "pass" and younger_move == "pass":
        return None
    if elder_move == "pass" and younger_move == "claim":
        return {"name": younger, "claim": younger_claim}
    if elder_move == "claim" and younger_move == "pass":
        return {"name": elder, "claim": elder_claim}
    if elder_move == "claim" and younger_move == "claim":
        cmp = _compare_claims(category, elder_claim, younger_claim)
        if cmp == 1:
            return {"name": elder, "claim": elder_claim}
        if cmp == 2:
            return {"name": younger, "claim": younger_claim}
        return None
    return None


def _check_repique(gs):
    """60-point bonus if a player reached 30+ before opponent scored this deal."""
    for name in gs.players:
        opp = gs.opponent(name)
        if gs.hand_points[name] >= 30 and gs.hand_points[opp] == 0:
            gs.hand_points[name] += 60


def _run_tricks(gs, funcs, name1, name2, logger):
    """Play 12 tricks. Return forfeit/match result int or None to continue."""
    last_winner = None
    tricks_before = {n: gs.hand_points[n] for n in gs.players}

    for trick_num in range(12):
        leader = gs.turn
        follower = gs.opponent(leader)
        gs.trick = []

        leader_card = _get_trick_card(gs, leader, funcs[leader], lead_card=None, logger=logger)
        if leader_card is None:
            return _forfeit(gs, leader, name1, name2, logger)
        gs.trick.append((leader, leader_card))
        gs.hands[leader].remove(leader_card)

        follower_card = _get_trick_card(
            gs, follower, funcs[follower], lead_card=leader_card, logger=logger
        )
        if follower_card is None:
            return _forfeit(gs, follower, name1, name2, logger)
        gs.trick.append((follower, follower_card))
        gs.hands[follower].remove(follower_card)

        leader_wins = resolve_trick(leader_card, follower_card)
        trick_winner = leader if leader_wins else follower
        gs.tricks_won[trick_winner] += 1
        last_winner = trick_winner
        gs.turn = trick_winner
        gs.trick_history.append(
            {
                "leader": leader,
                "plays": [(leader, leader_card), (follower, follower_card)],
                "winner": trick_winner,
            }
        )

        logger.log_trick(
            trick_num + 1, leader, leader_card, follower, follower_card, trick_winner
        )

    trick_points = score_tricks(gs.tricks_won, last_winner)
    for name, pts in trick_points.items():
        gs.hand_points[name] += pts

    _check_pique(gs, tricks_before)
    return None


def _check_pique(gs, tricks_before):
    """30-point bonus for scoring 30+ in tricks before opponent scores in tricks."""
    for name in gs.players:
        opp = gs.opponent(name)
        trick_gain = gs.hand_points[name] - tricks_before[name]
        opp_trick_gain = gs.hand_points[opp] - tricks_before[opp]
        if trick_gain >= 30 and opp_trick_gain == 0:
            gs.hand_points[name] += 30


def _end_hand(gs, logger):
    """Add hand points to match scores and check for game end."""
    p1, p2 = gs.players
    for name in gs.players:
        gs.scores[name] += gs.hand_points[name]

    logger.log_hand_result(gs)
    gs.hand_history.append(
        {
            "dealer": gs.dealer,
            "elder": gs.elder,
            "exchange_counts": {
                name: gs.exchanges.get(name, {}).get("count", 0) for name in gs.players
            },
            "declarations": list(gs.declarations),
            "tricks": list(gs.trick_history),
            "tricks_won": dict(gs.tricks_won),
            "hand_points": dict(gs.hand_points),
            "scores_after": dict(gs.scores),
        }
    )

    over = [n for n in gs.players if gs.scores[n] >= TARGET_SCORE]
    if len(over) == 1:
        gs.game_over = True
        gs.winner = over[0]
    elif len(over) == 2:
        gs.game_over = True
        if gs.scores[p1] > gs.scores[p2]:
            gs.winner = p1
        elif gs.scores[p2] > gs.scores[p1]:
            gs.winner = p2
        else:
            gs.winner = None


def _match_result(gs, name1, name2, logger):
    logger.log_result(gs)
    if gs.winner is None:
        return 0
    return 1 if gs.winner == name1 else 2


def _finish_match(gs, name1, name2, logger):
    logger.log_result(gs)
    return 1 if gs.winner == name1 else 2


# ---------------------------------------------------------------------------
# Move helpers
# ---------------------------------------------------------------------------
def _get_exchange(gs, player, func, max_discard, logger):
    view = gs.make_player_view(player)
    try:
        discard = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    if not isinstance(discard, list):
        logger.log_error(player, f"exchange must return a list, got {type(discard).__name__}")
        return None
    if len(discard) > max_discard:
        logger.log_error(
            player, f"discarded {len(discard)} cards but max is {max_discard}"
        )
        return None
    hand = gs.hands[player]
    for card in discard:
        if card not in hand:
            logger.log_error(player, f"discarded {card!r} not in hand")
            return None
    if len(set(discard)) != len(discard):
        logger.log_error(player, "duplicate cards in discard")
        return None
    if player == gs.elder and len(discard) > 5:
        logger.log_error(player, "elder may discard at most 5 cards")
        return None
    return discard


def _parse_declaration(move):
    if move == "pass" or move == ("pass",):
        return "pass"
    if isinstance(move, tuple):
        if len(move) >= 1 and move[0] == "pass":
            return "pass"
        if len(move) >= 1 and move[0] == "claim":
            return "claim"
    if move == "claim" or move == ("claim",):
        return "claim"
    return None


def _get_declaration(gs, player, func, category, logger):
    view = gs.make_player_view(player)
    try:
        move = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    parsed = _parse_declaration(move)
    if parsed is None:
        logger.log_error(
            player,
            f"declaration must be 'pass' or ('claim', ...), got {move!r}",
        )
        return None

    if gs.phase != "declare":
        logger.log_error(player, "not in declare phase")
        return None

    if view.declare_category != category:
        logger.log_error(player, f"wrong category (expected {category})")
        return None

    if parsed == "claim" and category == "set" and best_set(gs.hands[player]) is None:
        logger.log_error(player, "no valid set to claim")
        return None

    return parsed


def _get_trick_card(gs, player, func, lead_card, logger):
    view = gs.make_player_view(player)
    allowed = legal_cards(gs.hands[player], lead_card)
    try:
        card = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    if not isinstance(card, tuple) or len(card) != 2:
        logger.log_error(player, f"trick play must be (suit, rank), got {card!r}")
        return None
    if card not in gs.hands[player]:
        logger.log_error(player, f"played {card!r} which is not in their hand")
        return None
    if card not in allowed:
        logger.log_error(player, f"played {card_str(card)} illegally")
        return None
    return card


def _forfeit(gs, forfeiting_player, name1, name2, logger):
    gs.game_over = True
    winner = gs.opponent(forfeiting_player)
    gs.winner = winner
    logger.log_forfeit(forfeiting_player, winner)
    return 1 if winner == name1 else 2


# ---------------------------------------------------------------------------
# GameLogger
# ---------------------------------------------------------------------------
class GameLogger:
    def __init__(self, filepath):
        self.filepath = filepath
        self._lines = []

    def start_game(self, game_number):
        self._lines.append(f"\n{'='*60}")
        self._lines.append(f"Game {game_number}")
        self._lines.append(f"{'='*60}")

    def log_setup(self, gs):
        self._lines.append(f"Players: {gs.players[0]} vs {gs.players[1]}")
        self._lines.append(f"Dealer: {gs.dealer}  |  Elder: {gs.elder}")
        self._lines.append(f"Match scores: {gs.scores[gs.players[0]]} - {gs.scores[gs.players[1]]}")
        self._lines.append(f"Talon ({len(gs.talon)}): {_hand_str(gs.talon)}")
        self._lines.append(f"{gs.players[0]} hand: {_hand_str(gs.hands[gs.players[0]])}")
        self._lines.append(f"{gs.players[1]} hand: {_hand_str(gs.hands[gs.players[1]])}")

    def log_phase_change(self, phase):
        self._lines.append(f"\n--- Phase: {phase} ---")

    def log_exchange(self, gs, player, discarded, drawn):
        self._lines.append(
            f"  Exchange {player}: discard {_hand_str(discarded)} "
            f"-> draw {_hand_str(drawn)} (talon {len(gs.talon)} left)"
        )

    def log_declaration(self, category, winner, points, claim):
        self._lines.append(
            f"  Declare {category}: {winner} wins {points} pts ({_claim_summary(claim)})"
        )

    def log_trick(self, trick_num, leader, leader_card, follower, follower_card, winner):
        self._lines.append(
            f"  Trick {trick_num:>2}: {leader} leads {card_str(leader_card)}, "
            f"{follower} plays {card_str(follower_card)} -> {winner} wins"
        )

    def log_hand_result(self, gs):
        p1, p2 = gs.players
        self._lines.append(
            f"  Hand: {p1} +{gs.hand_points[p1]} / {p2} +{gs.hand_points[p2]} "
            f"(tricks {gs.tricks_won[p1]}-{gs.tricks_won[p2]})"
        )
        self._lines.append(
            f"  Match total: {p1} {gs.scores[p1]} - {gs.scores[p2]} {p2}"
        )

    def log_error(self, player, message):
        self._lines.append(f"  ERROR ({player}): {message}")

    def log_forfeit(self, loser, winner):
        self._lines.append(f"  FORFEIT: {loser} forfeits. {winner} wins match.")

    def log_result(self, gs):
        p1, p2 = gs.players
        self._lines.append(f"  Final: {p1} {gs.scores[p1]} - {gs.scores[p2]} {p2}")
        if gs.winner:
            self._lines.append(f"  Winner: {gs.winner}")
        else:
            self._lines.append("  Draw")

    def flush(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self._lines) + "\n")

    @staticmethod
    def write_leaderboard_csv(filepath, scores):
        rows = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["player", "score"])
            for name, score in rows:
                writer.writerow([name, f"{score:.1f}"])


def _hand_str(hand):
    return " ".join(card_str(c) for c in sorted(hand, key=lambda c: (c[0], c[1])))
