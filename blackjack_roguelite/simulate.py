"""
Simulation harness: player strategies, capture strategies, reward strategies, batch runner.
"""
import random
from typing import List, Dict

from .config import GameConfig, CLASS_TEMPLATES
from .engine import hand_value, RunEngine, RunResult, Companion, get_non_maxed_talents


# ---------------------------------------------------------------------------
# Player strategies (how the AI decides hit vs stand)
# ---------------------------------------------------------------------------
class Strategy:
    name = "base"

    def decide(self, hand_cards, visible_enemy_value, bust_probability, companions):
        raise NotImplementedError

    def should_fold(self, hand_cards, player, enemy):
        """Override to enable folding. Called before hit/stand."""
        return False

    def should_split(self, hand_cards, player, enemy):
        """Override to enable splitting pairs. Called before hit/stand."""
        return False


class RandomStrategy(Strategy):
    name = "random"

    def decide(self, hand_cards, visible_enemy_value, bust_probability, companions):
        return random.choice(["hit", "stand"])


class ConservativeStrategy(Strategy):
    """Stands on 15+. Plays scared."""
    name = "conservative"

    def decide(self, hand_cards, visible_enemy_value, bust_probability, companions):
        return "stand" if hand_value(hand_cards) >= 15 else "hit"


class BasicStrategy(Strategy):
    """Simplified blackjack basic strategy."""
    name = "basic"

    def decide(self, hand_cards, visible_enemy_value, bust_probability, companions):
        val = hand_value(hand_cards)
        if val >= 17:
            return "stand"
        if val <= 11:
            return "hit"
        # 12-16: hit if enemy shows strength
        if visible_enemy_value >= 7:
            return "hit"
        if val >= 13:
            return "stand"
        return "hit"

    def should_fold(self, hand_cards, player, enemy):
        if player.folds <= 0:
            return False
        val = hand_value(hand_cards)
        hp_pct = player.hp / player.max_hp if player.max_hp > 0 else 0
        # Fold weak hands when HP is critical
        if val <= 12 and hp_pct < 0.25:
            return True
        # Fold weak hands vs high-rage enemies
        if val <= 13 and enemy.bonus_damage >= 4:
            return True
        return False

    def should_split(self, hand_cards, player, enemy):
        val = hand_value(hand_cards)
        rank = hand_cards[0].rank
        # Always split Aces (two chances at 21)
        if rank == "A":
            return True
        # Split 8s (16 is the worst hand)
        if rank == "8":
            return True
        # Never split 10s/faces (20 is great)
        if hand_cards[0].value == 10:
            return False
        # Split low pairs (2-7) vs weak enemies
        if val <= 14:
            return True
        return False


class AggressiveStrategy(Strategy):
    """Hits until 19+. Push-your-luck player."""
    name = "aggressive"

    def decide(self, hand_cards, visible_enemy_value, bust_probability, companions):
        return "stand" if hand_value(hand_cards) >= 19 else "hit"

    def should_fold(self, hand_cards, player, enemy):
        if player.folds <= 0:
            return False
        val = hand_value(hand_cards)
        hp_pct = player.hp / player.max_hp if player.max_hp > 0 else 0
        # Aggressive only folds when truly desperate
        if val <= 11 and hp_pct < 0.15:
            return True
        if val <= 12 and enemy.bonus_damage >= 5:
            return True
        return False

    def should_split(self, hand_cards, player, enemy):
        # Aggressive splits everything except 10s/faces
        if hand_cards[0].value == 10:
            return False
        return True


class SmartStrategy(Strategy):
    """Adjusts based on bust probability, companion effects, and folding."""
    name = "smart"

    def decide(self, hand_cards, visible_enemy_value, bust_probability, companions):
        val = hand_value(hand_cards)
        if val >= 20:
            return "stand"
        if val <= 11:
            return "hit"

        has_unbust = any(c.effect_type == "unbust_chance" for c in companions)
        has_shield = any(c.effect_type == "damage_reduction_pct" for c in companions)

        # Adapt bust tolerance to companion safety net
        threshold = 0.55
        if has_unbust:
            threshold = 0.70
        if has_shield:
            threshold += 0.05

        if bust_probability < threshold:
            return "hit"
        return "stand"

    def should_fold(self, hand_cards, player, enemy):
        """Fold weak hands when low HP or vs raging enemies. Requires folds remaining."""
        if player.folds <= 0:
            return False

        val = hand_value(hand_cards)
        hp_pct = player.hp / player.max_hp if player.max_hp > 0 else 0

        # Fold very weak hands (<14) when low HP
        if val < 14 and hp_pct < 0.30:
            return True

        # Fold weak hands against raging enemies with high bonus damage
        if val < 14 and enemy.bonus_damage >= 3:
            return True

        return False

    def should_split(self, hand_cards, player, enemy):
        rank = hand_cards[0].rank
        # Always split Aces
        if rank == "A":
            return True
        # Always split 8s (16 is terrible)
        if rank == "8":
            return True
        # Never split 10s/faces (20 is strong)
        if hand_cards[0].value == 10:
            return False
        # Never split 5s (10 is a good hitting hand)
        if rank == "5":
            return False
        # Split low pairs vs weak-showing enemies
        if hand_value(hand_cards) <= 14 and enemy.hit_threshold <= 16:
            return True
        # Split 9s unless enemy is likely to stay low
        if rank == "9" and enemy.hit_threshold >= 17:
            return True
        return False


ALL_STRATEGIES = [
    RandomStrategy(),
    ConservativeStrategy(),
    BasicStrategy(),
    AggressiveStrategy(),
    SmartStrategy(),
]

STRATEGIES_BY_NAME = {s.name: s for s in ALL_STRATEGIES}


# ---------------------------------------------------------------------------
# Capture strategies
# ---------------------------------------------------------------------------
class CaptureStrategy:
    name = "base"

    def should_capture(self, player, companion_type):
        raise NotImplementedError


class AlwaysCaptureStrategy(CaptureStrategy):
    name = "always"

    def should_capture(self, player, companion_type):
        return player.can_capture()


class NeverCaptureStrategy(CaptureStrategy):
    name = "never"

    def should_capture(self, player, companion_type):
        return False


# ---------------------------------------------------------------------------
# Reward strategies (post-fight: remove card, heal, or capture)
# ---------------------------------------------------------------------------
class RewardStrategy:
    name = "base"

    RANK_VAL = {"A": 14, "K": 13, "Q": 12, "J": 11, "10": 10,
                "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2}

    def choose_reward(self, player, deck, enemy,
                      can_remove=True, can_heal=True,
                      heal_amount=0, can_capture=False, can_enchant=False,
                      can_fold_reward=False, can_class_upgrade=False):
        """Return 'remove_card', 'heal', 'capture', 'enchant', 'fold_reward', or 'class_upgrade'."""
        raise NotImplementedError

    def choose_class_talent(self, player):
        """Pick which talent to upgrade. Override in class-aware strategies."""
        non_maxed = get_non_maxed_talents(player)
        return random.choice(non_maxed) if non_maxed else None

    def choose_rank_to_remove(self, removable_ranks, rank_counts):
        """Pick which rank to remove from the deck."""
        raise NotImplementedError

    def choose_card_to_enchant(self, cards, deck):
        """Pick which card to enchant from offered set."""
        if not cards:
            return None
        return max(cards, key=lambda c: self.RANK_VAL.get(c.rank, 0))

    def choose_enchantment_type(self, types, card):
        """Pick which enchantment type to apply."""
        pref = ["fury", "siphon", "ward"]
        for p in pref:
            if p in types:
                return p
        return types[0] if types else None


class SmartRewardStrategy(RewardStrategy):
    """Prioritizes deck trimming, heals when low, captures when available.
    Balances removal and enchanting: roughly 2 removals per 1 enchantment."""
    name = "smart"

    def choose_reward(self, player, deck, enemy,
                      can_remove=True, can_heal=True,
                      heal_amount=0, can_capture=False, can_enchant=False,
                      can_fold_reward=False, can_class_upgrade=False):
        hp_pct = player.hp / player.max_hp if player.max_hp > 0 else 0

        # Capture remains high-value, but reserve one slot for build flexibility.
        if can_capture and player.can_capture() and len(player.companions) < 2:
            return "capture"

        # Replenish folds only when empty to avoid starving deck progression.
        if can_fold_reward and player.folds <= 0:
            return "fold_reward"

        # Heal when critically low
        if can_heal and hp_pct < 0.38:
            return "heal"

        # Balance removal and enchanting based on deck state
        cards_removed = 52 - deck.template_size
        total_enchants = deck.total_enchantments()
        if can_enchant and can_remove and cards_removed >= 5:
            # Keep enchantments meaningful, but do not starve deck trimming.
            if total_enchants < max(1, int(cards_removed * 0.45)):
                return "enchant"

        # Trim the deck
        if can_remove:
            return "remove_card"

        # Enchant when can't remove
        if can_enchant:
            return "enchant"

        # Fall back to heal
        if can_heal:
            return "heal"

        return "remove_card"

    def choose_rank_to_remove(self, removable_ranks, rank_counts):
        """Remove low-value cards first (2-6) to increase average hand."""
        low_ranks = ["2", "3", "4", "5", "6"]
        for rank in low_ranks:
            if rank in removable_ranks and rank_counts.get(rank, 0) > 0:
                return rank
        # If no low cards left, remove whatever has most copies
        if removable_ranks:
            return max(removable_ranks, key=lambda r: rank_counts.get(r, 0))
        return None

    def choose_enchantment_type(self, types, card):
        """Fury on high cards, ward on low cards, siphon in between."""
        val = self.RANK_VAL.get(card.rank, 0)
        if val >= 10:
            pref = ["fury", "siphon", "ward"]
        elif val <= 6:
            pref = ["ward", "siphon", "fury"]
        else:
            pref = ["siphon", "fury", "ward"]
        for p in pref:
            if p in types:
                return p
        return types[0]


class HealFirstRewardStrategy(RewardStrategy):
    """Always heals first, then removes cards."""
    name = "heal_first"

    def choose_reward(self, player, deck, enemy,
                      can_remove=True, can_heal=True,
                      heal_amount=0, can_capture=False, can_enchant=False,
                      can_fold_reward=False, can_class_upgrade=False):
        if can_capture and player.can_capture():
            return "capture"
        if can_heal:
            return "heal"
        if can_remove:
            return "remove_card"
        if can_enchant:
            return "enchant"
        return "heal"

    def choose_rank_to_remove(self, removable_ranks, rank_counts):
        low_ranks = ["2", "3", "4", "5", "6"]
        for rank in low_ranks:
            if rank in removable_ranks and rank_counts.get(rank, 0) > 0:
                return rank
        if removable_ranks:
            return removable_ranks[0]
        return None


class RemoveFirstRewardStrategy(RewardStrategy):
    """Always removes cards first, heals only when desperate."""
    name = "remove_first"

    def choose_reward(self, player, deck, enemy,
                      can_remove=True, can_heal=True,
                      heal_amount=0, can_capture=False, can_enchant=False,
                      can_fold_reward=False, can_class_upgrade=False):
        if can_capture and player.can_capture():
            return "capture"
        if can_remove:
            return "remove_card"
        if can_enchant:
            return "enchant"
        if can_heal:
            return "heal"
        return "remove_card"

    def choose_rank_to_remove(self, removable_ranks, rank_counts):
        low_ranks = ["2", "3", "4", "5", "6"]
        for rank in low_ranks:
            if rank in removable_ranks and rank_counts.get(rank, 0) > 0:
                return rank
        if removable_ranks:
            return removable_ranks[0]
        return None


# ---------------------------------------------------------------------------
# Class-aware reward strategy
# ---------------------------------------------------------------------------
# Soft goals per class: stat -> target value
_CLASS_SOFT_GOALS = {
    "thief": {"crit_chance": 0.22, "crit_mult_bonus": 0.45},
    "warrior": {"damage_reduction_pct": 0.20, "max_hp_bonus": 30},
    "mage": {"effect_power_pct": 0.35, "bust_penalty_reduction": 0.15},
}


class ClassAwareRewardStrategy(SmartRewardStrategy):
    """Three-category reward logic: sustain -> class_upgrade -> deck."""
    name = "class_aware"

    def choose_reward(self, player, deck, enemy,
                      can_remove=True, can_heal=True,
                      heal_amount=0, can_capture=False, can_enchant=False,
                      can_fold_reward=False, can_class_upgrade=False):
        hp_pct = player.hp / player.max_hp if player.max_hp > 0 else 0

        # Capture still high-value early
        if can_capture and player.can_capture() and len(player.companions) < 2:
            return "capture"

        # Sustain: HP critically low
        if can_heal and hp_pct < 0.35:
            return "heal"

        # Replenish folds when empty
        if can_fold_reward and player.folds <= 0:
            return "fold_reward"

        # Class upgrade: if any key stat is below soft goal
        if can_class_upgrade and player.class_id:
            goals = _CLASS_SOFT_GOALS.get(player.class_id, {})
            for stat, target in goals.items():
                current = getattr(player.class_stats, stat, 0)
                if current < target:
                    return "class_upgrade"

        # Fall through to deck improvement (SmartRewardStrategy logic)
        cards_removed = 52 - deck.template_size
        total_enchants = deck.total_enchantments()
        if can_enchant and can_remove and cards_removed >= 5:
            if total_enchants < max(1, int(cards_removed * 0.45)):
                return "enchant"
        if can_remove:
            return "remove_card"
        if can_enchant:
            return "enchant"
        if can_heal:
            return "heal"
        return "remove_card"

    def choose_class_talent(self, player):
        """Pick talent whose stat has the largest gap below its soft goal."""
        if not player.class_id:
            return None
        goals = _CLASS_SOFT_GOALS.get(player.class_id, {})
        non_maxed = get_non_maxed_talents(player)
        if not non_maxed:
            return None

        template = CLASS_TEMPLATES[player.class_id]
        best_key = None
        best_gap = -999

        for key in non_maxed:
            td = template["talents"][key]
            stat = td["stat"]
            target = goals.get(stat)
            if target is not None:
                current = getattr(player.class_stats, stat, 0)
                gap = target - current
                if gap > best_gap:
                    best_gap = gap
                    best_key = key

        # If no goal-driven talent found, pick first non-maxed
        return best_key if best_key else non_maxed[0]


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
class Simulator:
    def __init__(self, config: GameConfig = None):
        self.config = config or GameConfig()

    def run(
        self,
        num_runs: int = 1000,
        strategy: Strategy = None,
        capture_strategy: CaptureStrategy = None,
        reward_strategy: RewardStrategy = None,
        class_id: str = None,
    ) -> List[RunResult]:
        strategy = strategy or BasicStrategy()
        capture_strategy = capture_strategy or AlwaysCaptureStrategy()
        reward_strategy = reward_strategy or SmartRewardStrategy()

        engine = RunEngine(self.config)
        return [
            engine.play_run(strategy, capture_strategy, reward_strategy,
                            class_id=class_id)
            for _ in range(num_runs)
        ]

    def compare_strategies(
        self,
        num_runs: int = 1000,
        reward_strategy: RewardStrategy = None,
        class_id: str = None,
    ) -> Dict[str, List[RunResult]]:
        """Run every strategy and return {name: results}."""
        return {
            s.name: self.run(num_runs, s,
                             reward_strategy=reward_strategy,
                             class_id=class_id)
            for s in ALL_STRATEGIES
        }
