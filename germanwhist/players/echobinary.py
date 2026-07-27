"""EchoBinary's German Whist qualifier bot.

Optimized heuristic strategy with 100% legal PlayerView card tracking.
Features:
  - _is_legal_boss: Identifies guaranteed suit bosses by checking if all higher ranks
    in a suit are accounted for in _seen or in our own hand.
  - Phase 1: Stock EV exploitation & fine-tuned upcard recruitment.
  - Phase 2: Trump pulling, boss cashing, high-first suit leading, and selective ruffing.
"""

_seen = set()
_prev_hand = set()

def _reset():
    global _seen, _prev_hand
    _seen = set()
    _prev_hand = set()

def _observe(gs):
    """Record publicly visible cards legally available in PlayerView."""
    global _seen, _prev_hand

    h = set(gs.your_hand)

    if gs.phase == 1 and gs.stock_remaining == 25:
        _reset()

    _seen.update(h)
    if gs.face_up_card:
        _seen.add(gs.face_up_card)

    for _, card in gs.current_trick:
        _seen.add(card)

    if _prev_hand:
        _seen.update(_prev_hand - h)
    _prev_hand = set(h)


def _legal(hand, current_trick):
    if not current_trick:
        return hand[:]
    lead_suit = current_trick[0][1][0]
    following = [c for c in hand if c[0] == lead_suit]
    return following or hand[:]


def _beats(card, lead, trump):
    ls, lr = lead
    s, r = card
    if s == ls:
        return r > lr
    return s == trump and ls != trump


def _slen(suit, hand):
    return sum(1 for s, _ in hand if s == suit)


def _is_legal_boss(card, hand):
    """Check if card is guaranteed boss (all higher ranks in suit seen or in hand)."""
    s, r = card
    for higher_r in range(r + 1, 15):
        if (s, higher_r) not in _seen and (s, higher_r) not in hand:
            return False
    return True


def _fu_val(fu, trump):
    """Evaluate face-up card value."""
    if not fu:
        return 0
    s, r = fu
    val = r
    if s == trump:
        val += 7
    if r == 14:
        val += 5
    elif r == 13:
        val += 3
    elif r == 12:
        val += 1
    return val


def nextMove(gameState):
    _observe(gameState)

    hand = gameState.your_hand
    trump = gameState.trump_suit
    phase = gameState.phase
    legal = _legal(hand, gameState.current_trick)

    # ══════════════════════════════════════════════════════════════════
    # FOLLOWING A TRICK
    # ══════════════════════════════════════════════════════════════════
    if gameState.current_trick:
        lead_card = gameState.current_trick[0][1]
        winners = [c for c in legal if _beats(c, lead_card, trump)]

        if phase == 2:
            if winners:
                cheap = min(
                    winners,
                    key=lambda c: c[1] + (6.0 if c[0] == trump and lead_card[0] != trump else 0.0)
                )
                # Don't waste high trumps (rank >= 11) on low off-suit leads (rank <= 8)
                if cheap[0] == trump and lead_card[0] != trump and lead_card[1] <= 8 and cheap[1] >= 11:
                    non_trumps = [c for c in legal if c[0] != trump]
                    if non_trumps:
                        return min(non_trumps, key=lambda c: c[1])
                return cheap

            # Cannot win — dump lowest non-trump rank card to protect trumps & honors
            return min(
                legal,
                key=lambda c: c[1] + (20.0 if c[0] == trump else 0.0)
            )

        # Phase 1 Following
        fu = gameState.face_up_card
        fuv = _fu_val(fu, trump)

        if winners:
            cheap = min(
                winners,
                key=lambda c: c[1] + (10.0 if c[0] == trump and lead_card[0] != trump else 0.0)
            )
            # High value upcard (Ace / High Trump, fuv >= 16) — win trick
            if fuv >= 16:
                return cheap
            # Good upcard (King/Queen/Trump 6+, fuv >= 12) — win if cost <= 9 without trump penalty
            if fuv >= 12 and cheap[1] <= 9 and (cheap[0] != trump or lead_card[0] == trump):
                return cheap
            # Decent upcard (Jack/Trump 2-5, fuv >= 9) — win if cheap non-trump
            if fuv >= 9 and cheap[1] <= 5 and cheap[0] != trump:
                return cheap

        # Deliberately lose for true junk upcards — discard lowest non-trump rank
        return min(
            legal,
            key=lambda c: c[1] + (20.0 if c[0] == trump else 0.0)
        )

    # ══════════════════════════════════════════════════════════════════
    # LEADING A TRICK
    # ══════════════════════════════════════════════════════════════════
    if phase == 2:
        tc = [c for c in hand if c[0] == trump]

        # 1. Pull trumps if we hold top trump (_is_legal_boss) and have backup trumps
        if tc:
            top_t = max(tc, key=lambda c: c[1])
            if _is_legal_boss(top_t, hand) and len(tc) >= 2:
                return top_t

        # 2. Cash Aces (rank 14) in off-suits, starting with longer suits
        aces = [c for c in hand if c[1] == 14 and c[0] != trump]
        if aces:
            return max(aces, key=lambda c: _slen(c[0], hand))

        # 3. Cash non-trump legal bosses (Kings/Queens where higher ranks seen/held)
        bosses = [c for c in hand if c[0] != trump and _is_legal_boss(c, hand)]
        if bosses:
            return max(bosses, key=lambda c: (_slen(c[0], hand), c[1]))

        # 4. Lead high card (>= 10) from longest off-suit; if top card is low, lead min card to bleed
        off_suits = set(c[0] for c in hand) - {trump}
        if off_suits:
            best_s = max(
                off_suits,
                key=lambda s: (_slen(s, hand), max(c[1] for c in hand if c[0] == s))
            )
            sc = [c for c in hand if c[0] == best_s]
            top_c = max(sc, key=lambda c: c[1])
            if top_c[1] >= 10:
                return top_c
            return min(sc, key=lambda c: c[1])

        # 5. Lead high trump if only trumps remain
        if tc:
            return max(tc, key=lambda c: c[1])

        # Fallback: lowest card
        return min(hand, key=lambda c: c[1])

    # Phase 1 Leading
    fu = gameState.face_up_card
    fuv = _fu_val(fu, trump)

    if fuv >= 15:
        # High upcard — lead strong off-suit honor (rank >= 11) to win
        strong = [c for c in legal if c[0] != trump and c[1] >= 11]
        if strong:
            return max(strong, key=lambda c: c[1])

    # Upcard is mediocre/junk or we lack top non-trump honor:
    # Lead lowest non-trump card to preserve high cards and force opponent
    non_trump = [c for c in legal if c[0] != trump]
    if non_trump:
        return min(non_trump, key=lambda c: c[1])
    return min(legal, key=lambda c: c[1])
