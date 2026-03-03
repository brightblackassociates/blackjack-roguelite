"""
Game engine: cards, combat, enemies, companions, runs.
Everything that makes the game tick.
"""
import random
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from . import config as _cfg
from .config import GameConfig


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["H", "D", "C", "S"]


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def value(self) -> int:
        if self.rank in ("J", "Q", "K"):
            return 10
        if self.rank == "A":
            return 11
        return int(self.rank)

    def __repr__(self):
        return f"{self.rank}{self.suit}"


def hand_value(cards: List[Card]) -> int:
    """Best hand value, reducing aces from 11 to 1 as needed."""
    total = sum(c.value for c in cards)
    aces = sum(1 for c in cards if c.rank == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def is_natural_21(cards: List[Card]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


ENCHANTMENT_TYPES = ["fury", "siphon", "ward"]


class Deck:
    def __init__(self):
        self.cards: List[Card] = []
        self._template: List[Card] = [Card(r, s) for r in RANKS for s in SUITS]
        self._enchantments: Dict[Card, List[str]] = {}
        self.reset()

    def reset(self):
        self.cards = list(self._template)
        random.shuffle(self.cards)

    def draw(self) -> Card:
        if len(self.cards) < 10:
            self.reset()
        return self.cards.pop()

    def bust_probability(self, hand_cards: List[Card]) -> float:
        """Probability that drawing one more card busts this hand."""
        if not self.cards:
            return 1.0
        busts = sum(1 for c in self.cards if hand_value(hand_cards + [c]) > 21)
        return busts / len(self.cards)

    def remove_rank(self, rank: str) -> bool:
        """Permanently remove one copy of a rank from the template.
        Prefers removing unenchanted copies. Returns True if removed."""
        # Try unenchanted copies first
        for i, card in enumerate(self._template):
            if card.rank == rank and card not in self._enchantments:
                self._template.pop(i)
                return True
        # Fall back to enchanted copy
        for i, card in enumerate(self._template):
            if card.rank == rank:
                removed = self._template.pop(i)
                self._enchantments.pop(removed, None)
                return True
        return False

    def removable_ranks(self, min_size: int = 20) -> List[str]:
        """Ranks that can be removed without going below min deck size."""
        if len(self._template) <= min_size:
            return []
        counts = self.rank_counts()
        return sorted(counts.keys(), key=lambda r: RANKS.index(r) if r in RANKS else 99)

    def rank_counts(self) -> Dict[str, int]:
        """Count of each rank in the template."""
        counts: Dict[str, int] = {}
        for card in self._template:
            counts[card.rank] = counts.get(card.rank, 0) + 1
        return counts

    @property
    def template_size(self) -> int:
        return len(self._template)

    # --- Enchantments ---

    def enchant_card(self, card: Card, ench_type: str, max_per_card: int = 3) -> bool:
        """Add an enchantment to a card. Returns False if at cap."""
        current = self._enchantments.get(card, [])
        if len(current) >= max_per_card:
            return False
        current.append(ench_type)
        self._enchantments[card] = current
        return True

    def get_enchantments(self, card: Card) -> List[str]:
        return self._enchantments.get(card, [])

    def enchantable_cards(self, count: int, max_per_card: int = 3) -> List[Card]:
        """Return up to `count` random cards from template that can accept enchantments."""
        available = [c for c in self._template
                     if len(self._enchantments.get(c, [])) < max_per_card]
        random.shuffle(available)
        return available[:count]

    def total_enchantments(self) -> int:
        return sum(len(v) for v in self._enchantments.values())

    def enchanted_cards_summary(self) -> List[tuple]:
        """Return [(card, enchantment_list), ...] for all enchanted cards."""
        return [(c, list(e)) for c, e in self._enchantments.items() if e]


# ---------------------------------------------------------------------------
# Companions
# ---------------------------------------------------------------------------
@dataclass
class Companion:
    name: str
    companion_type: str
    effect_type: str
    base_value: float
    per_level: float
    activation: str = "always"
    level: int = 1
    xp: int = 0

    @property
    def effect_value(self) -> float:
        return self.base_value + self.per_level * (self.level - 1)

    def gain_xp(self, amount: int, xp_per_level: int, max_level: int):
        self.xp += amount
        while self.xp >= xp_per_level and self.level < max_level:
            self.xp -= xp_per_level
            self.level += 1


def check_activation(cards: List[Card], activation: str) -> bool:
    """Check if a hand meets a companion's activation condition."""
    if activation in ("always", "natural_21", "on_bust"):
        return True  # contextual -- checked by the caller, not by card composition
    if activation == "two_red":
        return sum(1 for c in cards if c.suit in ("H", "D")) >= 2
    if activation == "two_black":
        return sum(1 for c in cards if c.suit in ("C", "S")) >= 2
    return True


# ---------------------------------------------------------------------------
# Enemies
# ---------------------------------------------------------------------------
RARITY_BUFFS = {
    "common": {"hp": 1.0, "threshold": 0, "bonus_damage": 0},
    "rare":   {"hp": 1.15, "threshold": 0, "bonus_damage": 0},
    "elite":  {"hp": 1.25, "threshold": 1, "bonus_damage": 0},
    "epic":   {"hp": 1.4, "threshold": 1, "bonus_damage": 1},
}

RARITY_WEIGHTS = {
    "normal": [("common", 70), ("rare", 20), ("elite", 8), ("epic", 2)],
    "elite":  [("rare", 60), ("elite", 30), ("epic", 10)],
    "boss":   [("rare", 20), ("elite", 50), ("epic", 30)],
}


@dataclass
class Enemy:
    name: str
    hp: int
    max_hp: int
    hit_threshold: int
    tier: str = "normal"
    rarity: str = "common"
    companion_type: str = ""
    bonus_damage: int = 0
    forced_extra_hits: int = 0
    # Abilities
    reckless_extra: int = 0        # Extra hits after reaching threshold
    damage_absorption: int = 0     # Shell: flat damage blocked per hand
    nine_lives_chance: float = 0.0 # Survive lethal once (consumed on trigger)
    rage_per_hand: int = 0         # bonus_damage grows by this each hand
    poison_per_hand: int = 0       # Flat damage to player every hand
    drain: bool = False            # Heal for damage dealt on wins

    @property
    def alive(self) -> bool:
        return self.hp > 0


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
@dataclass
class Player:
    hp: int = 100
    max_hp: int = 100
    companions: List[Companion] = field(default_factory=list)
    max_companion_slots: int = 3
    gold: int = 0
    folds: int = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def heal(self, amount: int):
        self.hp = min(self.max_hp, self.hp + amount)

    def take_damage(self, amount: int):
        self.hp = max(0, self.hp - amount)

    def get_companion_effect(self, effect_type: str, cards: List[Card] = None) -> Optional[float]:
        """Return effect value for first companion with this effect, or None.
        If cards are provided, checks the companion's activation condition."""
        for c in self.companions:
            if c.effect_type == effect_type:
                if cards is not None and not check_activation(cards, c.activation):
                    return None
                return c.effect_value
        return None

    def can_capture(self) -> bool:
        return len(self.companions) < self.max_companion_slots


# ---------------------------------------------------------------------------
# Combat results (data containers)
# ---------------------------------------------------------------------------
@dataclass
class DecisionPoint:
    hand_value: int
    bust_probability: float
    decision: str          # "hit" or "stand"
    visible_enemy_value: int
    is_tense: bool         # bust_prob between 20-70%


@dataclass
class HandResult:
    player_cards: List[Card]
    enemy_cards: List[Card]
    player_value: int
    enemy_value: int
    player_busted: bool
    enemy_busted: bool
    player_natural: bool
    enemy_natural: bool
    damage_dealt: float
    damage_taken: float
    outcome: str               # "win", "lose", "push", "fold"
    decision_points: List[DecisionPoint] = field(default_factory=list)
    companion_effects: List[str] = field(default_factory=list)
    highlights: List[str] = field(default_factory=list)
    siphon_heal: int = 0
    was_split: bool = False
    split_results: List['HandResult'] = field(default_factory=list)
    enemy_ai: Dict[str, int] = field(default_factory=dict)


@dataclass
class FightResult:
    enemy_name: str
    enemy_tier: str
    hands: List[HandResult]
    total_damage_dealt: float
    total_damage_taken: float
    player_won: bool
    companion_captured: str = ""
    player_hp_after: int = 0
    reward_chosen: str = ""  # "remove_card", "heal", "capture", ""


@dataclass
class RunResult:
    fights: List[FightResult]
    survived: bool
    encounters_completed: int
    total_encounters: int
    final_hp: int
    companions_captured: List[str] = field(default_factory=list)
    companion_levels: Dict[str, int] = field(default_factory=dict)
    cards_removed: int = 0
    enchantments_applied: int = 0
    fold_rewards: int = 0
    rewards_chosen: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Combat engine
# ---------------------------------------------------------------------------
class CombatEngine:
    def __init__(self, config: GameConfig):
        self.config = config
        self.deck = Deck()

    @staticmethod
    def _clamp(val: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, val))

    def _play_enemy_hand(self, enemy_cards: List[Card], enemy: Enemy, p_val: int = 0) -> Dict[str, int]:
        """Enemy plays with tier-aware dynamic behavior.

        Normal enemies stay identity-driven and volatile.
        Elite/boss enemies adapt to player totals and current combat state.
        """
        telemetry = {
            "hits": 0,
            "stands": 0,
            "chase_hits": 0,
            "risk_hits": 0,
            "reckless_hits": 0,
            "safe_stands": 0,
        }

        if enemy.tier == "normal":
            target = enemy.hit_threshold
            if enemy.reckless_extra > 0 or enemy.nine_lives_chance > 0:
                target += 1
            if enemy.damage_absorption > 0:
                target -= 1
            target = int(self._clamp(target, 12, 19))

            while hand_value(enemy_cards) <= target:
                if self.deck.bust_probability(enemy_cards) >= 0.35:
                    telemetry["risk_hits"] += 1
                telemetry["hits"] += 1
                enemy_cards.append(self.deck.draw())
            telemetry["stands"] += 1
            e_val = hand_value(enemy_cards)
            if p_val and e_val > p_val:
                telemetry["safe_stands"] += 1
        else:
            while True:
                e_val = hand_value(enemy_cards)
                if e_val >= 21:
                    break

                target = max(enemy.hit_threshold, p_val + 1 if p_val else enemy.hit_threshold)
                if enemy.poison_per_hand > 0 or enemy.drain:
                    target -= 1
                if enemy.hp <= max(2, int(enemy.max_hp * 0.35)):
                    target += 1
                target = int(self._clamp(target, 13, 20))

                bust_prob = self.deck.bust_probability(enemy_cards)
                tolerance = 0.30 if enemy.tier == "elite" else 0.27
                if enemy.reckless_extra > 0:
                    tolerance += 0.05
                if enemy.poison_per_hand > 0 or enemy.drain:
                    tolerance -= 0.04
                tolerance = self._clamp(tolerance, 0.10, 0.55)

                if e_val < target - 1:
                    if p_val and e_val <= p_val:
                        telemetry["chase_hits"] += 1
                    if bust_prob >= 0.35:
                        telemetry["risk_hits"] += 1
                    telemetry["hits"] += 1
                    enemy_cards.append(self.deck.draw())
                    continue
                if e_val < target and bust_prob <= tolerance:
                    if p_val and e_val <= p_val:
                        telemetry["chase_hits"] += 1
                    if bust_prob >= 0.35:
                        telemetry["risk_hits"] += 1
                    telemetry["hits"] += 1
                    enemy_cards.append(self.deck.draw())
                    continue
                if p_val and e_val <= p_val and e_val < 20 and bust_prob <= tolerance - 0.04:
                    telemetry["chase_hits"] += 1
                    if bust_prob >= 0.35:
                        telemetry["risk_hits"] += 1
                    telemetry["hits"] += 1
                    enemy_cards.append(self.deck.draw())
                    continue
                telemetry["stands"] += 1
                if p_val and e_val > p_val:
                    telemetry["safe_stands"] += 1
                break

        # Reckless identity: extra push after normal behavior.
        for _ in range(enemy.reckless_extra):
            if hand_value(enemy_cards) < 21:
                if self.deck.bust_probability(enemy_cards) >= 0.35:
                    telemetry["risk_hits"] += 1
                telemetry["hits"] += 1
                telemetry["reckless_hits"] += 1
                enemy_cards.append(self.deck.draw())

        return telemetry

    def _play_one_sub_hand(self, sub_cards, enemy, strategy, player):
        """Play a single sub-hand (hit/stand loop, no fold). Returns (cards, busted, p_val, decisions)."""
        peek = player.get_companion_effect("peek_enemy", sub_cards)
        # Sub-hands don't see enemy cards -- just use card[0] value
        visible_enemy = 0  # not relevant for sub-hand decisions
        forced_hits = enemy.forced_extra_hits
        decisions = []
        busted = False

        while True:
            val = hand_value(sub_cards)
            if val > 21:
                unbust = player.get_companion_effect("unbust_chance", sub_cards)
                if unbust and random.random() < unbust:
                    sub_cards.pop()
                    continue
                busted = True
                break
            if val == 21:
                break

            bust_prob = self.deck.bust_probability(sub_cards)
            if forced_hits > 0:
                decision = "hit"
                forced_hits -= 1
            else:
                decision = strategy.decide(sub_cards, visible_enemy, bust_prob, player.companions)

            is_tense = 0.20 <= bust_prob <= 0.70
            decisions.append(DecisionPoint(val, bust_prob, decision, visible_enemy, is_tense))

            if decision == "stand":
                break
            sub_cards.append(self.deck.draw())

        return sub_cards, busted, hand_value(sub_cards), decisions

    def _resolve_sub_hand(self, p_val, e_val, player_busted, enemy_busted, player_cards, player):
        """Resolve one sub-hand vs enemy. Returns (damage_dealt, damage_taken, outcome)."""
        companion_effects = []
        if player_busted:
            dmg = self._damage_taken(e_val, p_val, False, player, companion_effects, player_cards)
            dmg *= self.config.damage.bust_penalty_multiplier
            return 0, dmg, "lose"
        if enemy_busted:
            dmg = self._damage_dealt(p_val, e_val, False, player, companion_effects, player_cards)
            return dmg, 0, "win"
        if p_val > e_val:
            dmg = self._damage_dealt(p_val, e_val, False, player, companion_effects, player_cards)
            return dmg, 0, "win"
        if e_val > p_val:
            dmg = self._damage_taken(e_val, p_val, False, player, companion_effects, player_cards)
            return 0, dmg, "lose"
        return 0, 0, "push"

    def _play_split_hand(self, player, enemy, player_cards, enemy_cards, strategy):
        """Handle a split: two sub-hands, one enemy turn, combined result."""
        card_a, card_b = player_cards
        hand_a = [card_a, self.deck.draw()]
        hand_b = [card_b, self.deck.draw()]

        hand_a, busted_a, val_a, decs_a = self._play_one_sub_hand(hand_a, enemy, strategy, player)
        hand_b, busted_b, val_b, decs_b = self._play_one_sub_hand(hand_b, enemy, strategy, player)

        # Enemy plays once, aware of best non-busted hand
        best_p = max(
            (hand_value(h) for h, b in [(hand_a, busted_a), (hand_b, busted_b)] if not b),
            default=0)
        enemy_ai = {}
        if best_p > 0:
            enemy_ai = self._play_enemy_hand(enemy_cards, enemy, p_val=best_p)
        e_val = hand_value(enemy_cards)
        enemy_busted = e_val > 21

        # Resolve each sub-hand
        dealt_a, taken_a, out_a = self._resolve_sub_hand(val_a, e_val, busted_a, enemy_busted, hand_a, player)
        dealt_b, taken_b, out_b = self._resolve_sub_hand(val_b, e_val, busted_b, enemy_busted, hand_b, player)

        # Build sub-hand results for tracking
        sub_a = HandResult(
            hand_a, enemy_cards, val_a, e_val,
            busted_a, enemy_busted, False, False,
            dealt_a, taken_a, out_a,
            decs_a, [], ["split_hand_a"],
        )
        sub_b = HandResult(
            hand_b, enemy_cards, val_b, e_val,
            busted_b, enemy_busted, False, False,
            dealt_b, taken_b, out_b,
            decs_b, [], ["split_hand_b"],
        )

        # Combined result: aggregate damage, worst outcome
        total_dealt = dealt_a + dealt_b
        total_taken = taken_a + taken_b
        if out_a == "win" or out_b == "win":
            combined_outcome = "win" if total_dealt >= total_taken else "lose"
        elif out_a == "lose" and out_b == "lose":
            combined_outcome = "lose"
        else:
            combined_outcome = "push"

        # Use the better hand's cards as the "primary" for enchantment finalization
        primary_cards = hand_a if val_a >= val_b else hand_b
        all_decisions = decs_a + decs_b
        highlights = ["split"]

        return HandResult(
            primary_cards, enemy_cards,
            max(val_a, val_b), e_val,
            busted_a and busted_b, enemy_busted,
            False, False,
            total_dealt, total_taken, combined_outcome,
            all_decisions, [], highlights,
            was_split=True, split_results=[sub_a, sub_b],
            enemy_ai=enemy_ai,
        )

    def play_hand(self, player: Player, enemy: Enemy, strategy) -> HandResult:
        """Play a single hand of blackjack combat."""
        player_cards = [self.deck.draw(), self.deck.draw()]
        enemy_cards = [self.deck.draw(), self.deck.draw()]
        decision_points: List[DecisionPoint] = []
        companion_effects: List[str] = []
        highlights: List[str] = []

        # --- Fold check (before anything else) ---
        if (player.folds > 0
            and hasattr(strategy, 'should_fold')
            and strategy.should_fold(player_cards, player, enemy)):
            player.folds -= 1
            p_val = hand_value(player_cards)
            e_val = hand_value(enemy_cards)
            return HandResult(
                player_cards, enemy_cards, p_val, e_val,
                False, False, False, False,
                0, self.config.damage.fold_damage, "fold",
                decision_points, companion_effects, ["fold"],
            )

        # --- Natural 21 check ---
        p_natural = is_natural_21(player_cards)
        e_natural = is_natural_21(enemy_cards)
        if p_natural or e_natural:
            p_val = hand_value(player_cards)
            e_val = hand_value(enemy_cards)
            if p_natural:
                highlights.append("natural_21")
            if e_natural:
                highlights.append("enemy_natural_21")
            if p_natural and e_natural:
                return HandResult(
                    player_cards, enemy_cards, p_val, e_val,
                    False, False, True, True, 0, 0, "push",
                    decision_points, companion_effects, highlights,
                )
            if p_natural:
                dmg = self._damage_dealt(p_val, e_val, True, player, companion_effects,
                                         player_cards)
                return HandResult(
                    player_cards, enemy_cards, p_val, e_val,
                    False, False, True, False, dmg, 0, "win",
                    decision_points, companion_effects, highlights,
                )
            # Enemy natural
            dmg = self._damage_taken(e_val, p_val, True, player, companion_effects,
                                     player_cards)
            return HandResult(
                player_cards, enemy_cards, p_val, e_val,
                False, False, False, True, 0, dmg, "lose",
                decision_points, companion_effects, highlights,
            )

        # --- Split check ---
        is_pair = (len(player_cards) == 2
                   and player_cards[0].rank == player_cards[1].rank)
        if (is_pair
            and hasattr(strategy, 'should_split')
            and strategy.should_split(player_cards, player, enemy)):
            return self._play_split_hand(player, enemy, player_cards, enemy_cards, strategy)

        # --- What the player can see ---
        peek = player.get_companion_effect("peek_enemy", player_cards)
        if peek:
            visible_enemy = hand_value(enemy_cards)
        else:
            visible_enemy = enemy_cards[0].value

        # --- Player turn ---
        forced_hits = enemy.forced_extra_hits
        player_busted = False

        while True:
            p_val = hand_value(player_cards)
            if p_val > 21:
                # Try unbust companion
                unbust = player.get_companion_effect("unbust_chance", player_cards)
                if unbust and random.random() < unbust:
                    player_cards.pop()
                    companion_effects.append("Goblin Shaman: unbusted!")
                    highlights.append("companion_save")
                    continue
                player_busted = True
                break
            if p_val == 21:
                break

            bust_prob = self.deck.bust_probability(player_cards)

            if forced_hits > 0:
                decision = "hit"
                forced_hits -= 1
            else:
                decision = strategy.decide(
                    player_cards, visible_enemy, bust_prob, player.companions,
                )

            is_tense = 0.20 <= bust_prob <= 0.70
            decision_points.append(
                DecisionPoint(p_val, bust_prob, decision, visible_enemy, is_tense)
            )

            if decision == "stand":
                break

            player_cards.append(self.deck.draw())

        p_val = hand_value(player_cards)

        # --- Player-side highlights ---
        if player_busted and p_val == 22:
            highlights.append("cruel_bust")
        if len(player_cards) >= 5 and not player_busted:
            highlights.append("five_card")

        # --- Enemy turn ---
        # Standard blackjack rule: if player busts, player LOSES.
        # Enemy doesn't need to play. This IS the house edge.
        enemy_busted = False
        enemy_ai = {}
        if not player_busted:
            enemy_ai = self._play_enemy_hand(enemy_cards, enemy, p_val=p_val)
            e_val = hand_value(enemy_cards)
            enemy_busted = e_val > 21
        else:
            e_val = hand_value(enemy_cards)

        # --- Resolve ---
        if player_busted:
            dmg = self._damage_taken(e_val, p_val, False, player, companion_effects,
                                     player_cards)
            dmg *= self.config.damage.bust_penalty_multiplier
            return HandResult(
                player_cards, enemy_cards, p_val, e_val,
                True, False, False, False, 0, dmg, "lose",
                decision_points, companion_effects, highlights,
            )

        if enemy_busted:
            dmg = self._damage_dealt(p_val, e_val, False, player, companion_effects,
                                     player_cards)
            return HandResult(
                player_cards, enemy_cards, p_val, e_val,
                False, True, False, False, dmg, 0, "win",
                decision_points, companion_effects, highlights,
                enemy_ai=enemy_ai,
            )

        # Neither busted: compare values
        if p_val > e_val:
            dmg = self._damage_dealt(p_val, e_val, False, player, companion_effects,
                                     player_cards)
            outcome = "win"
        elif e_val > p_val:
            dmg = self._damage_taken(e_val, p_val, False, player, companion_effects,
                                     player_cards)
            outcome = "lose"
        else:
            outcome = "push"
            dmg = 0

        # Close-call highlights (win/lose by exactly 1)
        if outcome == "win" and p_val - e_val == 1:
            highlights.append("close_win")
        elif outcome == "lose" and e_val - p_val == 1:
            highlights.append("close_loss")

        if outcome == "win":
            return HandResult(
                player_cards, enemy_cards, p_val, e_val,
                False, False, False, False, dmg, 0, outcome,
                decision_points, companion_effects, highlights,
                enemy_ai=enemy_ai,
            )
        elif outcome == "lose":
            return HandResult(
                player_cards, enemy_cards, p_val, e_val,
                False, False, False, False, 0, dmg, outcome,
                decision_points, companion_effects, highlights,
                enemy_ai=enemy_ai,
            )
        # Push
        return HandResult(
            player_cards, enemy_cards, p_val, e_val,
            False, False, False, False, 0, 0, "push",
            decision_points, companion_effects, highlights,
            enemy_ai=enemy_ai,
        )

    # --- Damage helpers ---

    def _base_damage(self, winner_val, loser_val):
        """Apply the configured damage model to raw hand values."""
        cfg = self.config.damage
        if cfg.model == "differential":
            return float(max(winner_val - loser_val, cfg.damage_floor))
        return float(max(winner_val - cfg.damage_subtract, 1))

    def _damage_dealt(self, p_val, e_val, is_natural, player, effects_log,
                      player_cards=None):
        damage = self._base_damage(p_val, e_val)

        if is_natural:
            # Lucky Cat: standalone multiplier on natural 21
            cat_mult = player.get_companion_effect("natural_21_multiplier", player_cards)
            if cat_mult:
                damage *= cat_mult
                effects_log.append(f"Lucky Cat: natural 21 ({cat_mult:.1f}x)")
            else:
                damage *= self.config.damage.natural_21_multiplier

        margin = p_val - e_val
        if not is_natural and margin >= self.config.damage.margin_bonus_threshold:
            damage *= self.config.damage.margin_bonus_multiplier

        # Fire Imp: multiplicative damage on wins (needs activation condition)
        imp_mult = player.get_companion_effect("damage_multiplier", player_cards)
        if imp_mult:
            damage *= imp_mult
            effects_log.append(f"Fire Imp: {imp_mult:.2f}x damage")

        return damage

    def _damage_taken(self, e_val, p_val, is_natural, player, effects_log,
                      player_cards=None):
        damage = self._base_damage(e_val, p_val)

        if is_natural:
            damage *= self.config.damage.natural_21_multiplier

        # Shield Turtle: percentage damage reduction (needs activation condition)
        reduction_pct = player.get_companion_effect("damage_reduction_pct", player_cards)
        if reduction_pct:
            reduced = damage * reduction_pct
            damage = max(0, damage - reduced)
            effects_log.append(f"Shield Turtle: -{reduction_pct*100:.0f}% ({reduced:.0f} blocked)")

        return damage

    # --- Enchantment helpers ---

    @staticmethod
    def _ench_total(base, count, diminishing):
        """Total value from stacked enchantments with diminishing returns."""
        if count <= 0:
            return 0.0
        total = float(base)
        for _ in range(count - 1):
            total += base * diminishing
        return total

    def _finalize_hand(self, result: HandResult) -> HandResult:
        """Apply enchantment effects from player's cards to a resolved hand."""
        if result.outcome == "fold":
            return result

        cfg = self.config.enchantment
        fury_count = siphon_count = ward_count = 0
        for card in result.player_cards:
            for ench in self.deck.get_enchantments(card):
                if ench == "fury":
                    fury_count += 1
                elif ench == "siphon":
                    siphon_count += 1
                elif ench == "ward":
                    ward_count += 1

        if fury_count > 0 and result.outcome == "win":
            bonus = self._ench_total(cfg.fury_damage, fury_count, cfg.diminishing)
            result.damage_dealt += bonus
            result.companion_effects.append(f"Fury x{fury_count}: +{bonus:.0f} dmg")

        if ward_count > 0 and result.outcome == "lose":
            reduction = self._ench_total(cfg.ward_reduction, ward_count, cfg.diminishing)
            result.damage_taken = max(0, result.damage_taken - reduction)
            result.companion_effects.append(f"Ward x{ward_count}: -{reduction:.0f} dmg")

        if siphon_count > 0:
            heal = int(self._ench_total(cfg.siphon_heal, siphon_count, cfg.diminishing))
            result.siphon_heal = heal
            result.companion_effects.append(f"Siphon x{siphon_count}: heal {heal}")

        return result

    # --- Fight (multiple hands against one enemy) ---

    def play_fight(self, player, enemy, strategy, capture_strategy) -> FightResult:
        hands = []
        total_dealt = 0.0
        total_taken = 0.0

        while player.alive and enemy.alive:
            result = self.play_hand(player, enemy, strategy)
            result = self._finalize_hand(result)

            # --- Fold: take fold_damage, but poison/rage still tick ---
            if result.outcome == "fold":
                fold_dmg = int(result.damage_taken)
                player.take_damage(fold_dmg)
                total_taken += fold_dmg
            else:
                # --- Shell: absorb damage dealt to enemy ---
                if result.outcome == "win" and enemy.damage_absorption > 0:
                    orig = result.damage_dealt
                    result.damage_dealt = max(0, result.damage_dealt - enemy.damage_absorption)
                    if result.damage_dealt < orig:
                        result.highlights.append("shell_block")

                # --- Apply damage ---
                if result.outcome == "win":
                    enemy.hp = max(0, enemy.hp - int(result.damage_dealt))
                    total_dealt += result.damage_dealt
                elif result.outcome == "lose":
                    dmg = int(result.damage_taken) + enemy.bonus_damage
                    player.take_damage(dmg)
                    total_taken += dmg
                    # Drain: enemy heals for damage dealt
                    if enemy.drain:
                        heal_amt = int(result.damage_taken)
                        enemy.hp = min(enemy.max_hp, enemy.hp + heal_amt)
                        result.highlights.append("drain_heal")

            # --- Siphon heal from enchanted cards ---
            if result.siphon_heal > 0 and player.alive:
                player.heal(result.siphon_heal)

            # --- Poison: damage every hand regardless (including folds) ---
            if enemy.poison_per_hand > 0 and enemy.alive:
                player.take_damage(enemy.poison_per_hand)
                total_taken += enemy.poison_per_hand
                result.highlights.append("poison_tick")

            # --- Nine lives: survive lethal once ---
            if not enemy.alive and enemy.nine_lives_chance > 0:
                if random.random() < enemy.nine_lives_chance:
                    enemy.hp = 1
                    enemy.nine_lives_chance = 0.0  # Consumed
                    result.highlights.append("nine_lives")

            # --- Clutch win: winning when near death ---
            if result.outcome == "win" and player.hp <= player.max_hp * 0.20:
                result.highlights.append("clutch_win")

            # --- Rage: escalate after each hand (including folds) ---
            if enemy.rage_per_hand > 0:
                enemy.bonus_damage += enemy.rage_per_hand
                result.highlights.append("rage_stack")

            hands.append(result)

        player_won = not enemy.alive

        # Companion XP
        for c in player.companions:
            c.gain_xp(
                self.config.companion.xp_per_fight,
                self.config.companion.xp_per_level,
                self.config.companion.max_level,
            )

        # Capture is now part of the reward system, not automatic
        return FightResult(
            enemy_name=enemy.name,
            enemy_tier=enemy.tier,
            hands=hands,
            total_damage_dealt=total_dealt,
            total_damage_taken=total_taken,
            player_won=player_won,
            player_hp_after=player.hp,
        )


# ---------------------------------------------------------------------------
# Run engine (full roguelite run)
# ---------------------------------------------------------------------------
class RunEngine:
    def __init__(self, config: GameConfig):
        self.config = config
        self.combat = CombatEngine(config)

    def _generate_encounters(self):
        """Build the encounter list for a full run."""
        normals = [k for k, v in _cfg.ENEMY_TEMPLATES.items() if v.get("tier", "normal") == "normal"]
        elites = [k for k, v in _cfg.ENEMY_TEMPLATES.items() if v.get("tier") == "elite"]
        bosses = [k for k, v in _cfg.ENEMY_TEMPLATES.items() if v.get("tier") == "boss"]

        encounters = []
        for act in range(self.config.run.acts):
            for _ in range(self.config.run.fights_per_act):
                encounters.append((random.choice(normals), act))
            for _ in range(self.config.run.elites_per_act):
                encounters.append((random.choice(elites), act))
            encounters.append((random.choice(bosses), act))
        return encounters

    @staticmethod
    def _roll_rarity(tier: str) -> str:
        weights = RARITY_WEIGHTS.get(tier, RARITY_WEIGHTS["normal"])
        names, probs = zip(*weights)
        return random.choices(names, weights=probs, k=1)[0]

    def _create_enemy(self, key: str, act: int = 0) -> Enemy:
        t = _cfg.ENEMY_TEMPLATES[key]
        tier = t.get("tier", "normal")
        rarity = self._roll_rarity(tier)
        buffs = RARITY_BUFFS[rarity]

        # Apply act-based HP scaling, then rarity HP multiplier
        multipliers = self.config.run.act_hp_multipliers
        hp_mult = multipliers[act] if act < len(multipliers) else multipliers[-1]
        scaled_hp = max(1, int(t["hp"] * hp_mult * buffs["hp"]))

        threshold = min(19, t["hit_threshold"] + buffs["threshold"])
        bonus_dmg = t.get("bonus_damage", 0) + buffs["bonus_damage"]

        return Enemy(
            name=t["name"],
            hp=scaled_hp,
            max_hp=scaled_hp,
            hit_threshold=threshold,
            tier=tier,
            rarity=rarity,
            companion_type=t.get("companion_type", ""),
            bonus_damage=bonus_dmg,
            forced_extra_hits=t.get("forced_extra_hits", 0),
            reckless_extra=t.get("reckless_extra", 0),
            damage_absorption=t.get("damage_absorption", 0),
            nine_lives_chance=t.get("nine_lives_chance", 0.0),
            rage_per_hand=t.get("rage_per_hand", 0),
            poison_per_hand=t.get("poison_per_hand", 0),
            drain=t.get("drain", False),
        )

    def play_run(self, strategy, capture_strategy, reward_strategy=None) -> RunResult:
        # Fresh deck each run so template modifications don't carry over
        self.combat.deck = Deck()

        player = Player(
            hp=self.config.player.starting_hp,
            max_hp=self.config.player.starting_hp,
            max_companion_slots=self.config.player.max_companion_slots,
            folds=self.config.fold.starting_folds,
        )

        encounters = self._generate_encounters()
        fights = []
        current_act = -1
        cards_removed = 0
        enchantments_applied = 0
        fold_rewards = 0
        rewards_chosen = []

        for enemy_key, act in encounters:
            if act > current_act and current_act >= 0:
                heal = int(player.max_hp * self.config.run.heal_between_acts_pct)
                player.heal(heal)
            current_act = act

            enemy = self._create_enemy(enemy_key, act)
            result = self.combat.play_fight(player, enemy, strategy, capture_strategy)

            # --- Reward phase (after won fights) ---
            if result.player_won and reward_strategy:
                # Build available reward options
                can_remove = bool(self.combat.deck.removable_ranks(
                    self.config.reward.min_deck_size
                ))
                heal_amount = (
                    self.config.reward.heal_amount_elite
                    if enemy.tier in ("elite", "boss")
                    else self.config.reward.heal_amount
                )
                can_heal = player.hp < player.max_hp

                # Capture opportunity -- always offered, but can fail on attempt
                can_capture = (enemy.companion_type and enemy.tier == "normal"
                               and player.can_capture())

                # Enchant opportunity
                can_enchant = bool(self.combat.deck.enchantable_cards(
                    1, self.config.enchantment.max_per_card
                ))

                choice = reward_strategy.choose_reward(
                    player, self.combat.deck, enemy,
                    can_remove=can_remove,
                    can_heal=can_heal,
                    heal_amount=heal_amount,
                    can_capture=can_capture,
                    can_enchant=can_enchant,
                    can_fold_reward=True,
                )

                if choice == "remove_card":
                    ranks = self.combat.deck.removable_ranks(self.config.reward.min_deck_size)
                    if ranks:
                        rank = reward_strategy.choose_rank_to_remove(
                            ranks, self.combat.deck.rank_counts()
                        )
                        if rank and self.combat.deck.remove_rank(rank):
                            cards_removed += 1
                elif choice == "enchant" and can_enchant:
                    ecfg = self.config.enchantment
                    cards = self.combat.deck.enchantable_cards(
                        ecfg.cards_offered, ecfg.max_per_card
                    )
                    if cards:
                        card = reward_strategy.choose_card_to_enchant(
                            cards, self.combat.deck
                        )
                        if card:
                            offered = random.sample(
                                ENCHANTMENT_TYPES,
                                min(ecfg.types_offered, len(ENCHANTMENT_TYPES)),
                            )
                            etype = reward_strategy.choose_enchantment_type(
                                offered, card
                            )
                            if etype and self.combat.deck.enchant_card(
                                card, etype, ecfg.max_per_card
                            ):
                                enchantments_applied += 1
                elif choice == "fold_reward":
                    player.folds += self.config.fold.fold_reward_amount
                    fold_rewards += 1
                elif choice == "heal":
                    player.heal(heal_amount)
                elif choice == "capture" and can_capture:
                    # Roll for capture success
                    if random.random() < self.config.companion.capture_chance:
                        template = _cfg.COMPANION_TEMPLATES.get(enemy.companion_type)
                        if template:
                            comp = Companion(
                                name=template["name"],
                                companion_type=enemy.companion_type,
                                effect_type=template["effect_type"],
                                base_value=template["base_value"],
                                per_level=template["per_level"],
                                activation=template.get("activation", "always"),
                            )
                            player.companions.append(comp)
                            result.companion_captured = enemy.companion_type

                result.reward_chosen = choice
                rewards_chosen.append(choice)

            fights.append(result)

            if not player.alive:
                break

        return RunResult(
            fights=fights,
            survived=player.alive,
            encounters_completed=len(fights),
            total_encounters=len(encounters),
            final_hp=player.hp,
            companions_captured=[f.companion_captured for f in fights if f.companion_captured],
            companion_levels={c.name: c.level for c in player.companions},
            cards_removed=cards_removed,
            enchantments_applied=enchantments_applied,
            fold_rewards=fold_rewards,
            rewards_chosen=rewards_chosen,
        )
