"""
All tunable parameters for the Blackjack Roguelite.
Change values here, re-run simulation, see what shifts.
"""
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------
@dataclass
class DamageConfig:
    # "threshold": damage = hand_value - damage_subtract
    # "differential": damage = winner_value - loser_value (min damage_floor)
    model: str = "threshold"
    # Subtracted from hand value in threshold mode (21 - 14 = 7 max damage)
    damage_subtract: int = 14
    # Minimum damage in differential mode
    damage_floor: int = 2
    # Natural blackjack multiplier (21 with 2 cards)
    natural_21_multiplier: float = 1.5
    # Extra damage taken when YOU bust (multiplied against base damage)
    bust_penalty_multiplier: float = 1.3
    # Beat enemy by this margin for a damage bonus
    margin_bonus_threshold: int = 5
    margin_bonus_multiplier: float = 1.2
    # If both bust, damage each side takes (0 = wash)
    both_bust_damage: int = 0
    # Damage dealt when player folds a hand
    fold_damage: int = 1
    # Player crit
    player_crit_chance: float = 0.10
    crit_multiplier: float = 1.5


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
@dataclass
class PlayerConfig:
    starting_hp: int = 105
    max_companion_slots: int = 3


# ---------------------------------------------------------------------------
# Companions
# ---------------------------------------------------------------------------
@dataclass
class CompanionConfig:
    capture_chance: float = 0.42       # Base chance capture succeeds when attempted
    # Rarity multipliers: rarer Shades are harder to capture.
    capture_rarity_chance_mult: dict[str, float] = field(default_factory=lambda: {
        "common": 1.00,
        "rare": 0.70,
        "elite": 0.50,
        "epic": 0.35,
    })
    # Rarity multipliers: rarer captured Shades have stronger effects.
    capture_rarity_power_mult: dict[str, float] = field(default_factory=lambda: {
        "common": 1.00,
        "rare": 1.08,
        "elite": 1.16,
        "epic": 1.24,
    })
    # Per-encounter roll range by rarity; this creates individual shade variance
    # within the same shade type (e.g., weak/common Sable vs high-roll Sable).
    capture_roll_range_by_rarity: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "common": (0.97, 1.03),
        "rare": (0.98, 1.08),
        "elite": (0.98, 1.10),
        "epic": (0.99, 1.03),
    })
    xp_per_fight: int = 10            # XP gained per fight participated in
    xp_per_level: int = 30            # XP needed to level up
    max_level: int = 5


# ---------------------------------------------------------------------------
# Run structure
# ---------------------------------------------------------------------------
@dataclass
class RunConfig:
    acts: int = 3
    fights_per_act: int = 3
    elites_per_act: int = 1
    # Boss is always the final fight of each act
    heal_between_acts_pct: float = 0.35  # Heal 35% max HP between acts
    act_hp_multipliers: list = field(default_factory=lambda: [1.0, 1.3, 1.6])


@dataclass
class RewardConfig:
    heal_amount: int = 7
    heal_amount_elite: int = 10
    min_deck_size: int = 20


@dataclass
class EnchantmentConfig:
    cards_offered: int = 3       # Random cards shown from deck to enchant
    types_offered: int = 2       # Enchantment types to choose from
    max_per_card: int = 3        # Cap on enchantments per card
    siphon_heal: int = 2         # Base heal when siphon card is in hand
    fury_damage: int = 2         # Base bonus damage on wins with fury card
    ward_reduction: int = 1      # Base damage reduction on losses with ward card
    diminishing: float = 0.5     # Each additional same-type worth this fraction
    # New enchantment types
    gambit_base_damage: int = 1  # Base bonus damage from gambit
    gambit_bust_scaling: float = 4.0  # Multiplied by bust probability when you stood
    hex_bleed_per_play: int = 1  # Bleed counter increment per hex card played


# ---------------------------------------------------------------------------
# Experience quality targets
# These define what "fun" looks like. Simulation measures against these.
# ---------------------------------------------------------------------------
@dataclass
class ExperienceTarget:
    name: str
    description: str
    target_min: float
    target_max: float
    unit: str = "%"


DEFAULT_EXPERIENCE_TARGETS = [
    ExperienceTarget(
        "decision_tension",
        "Pct of decisions where hit/stand is non-obvious",
        30, 50,
    ),
    ExperienceTarget(
        "highlight_rate",
        "Pct of hands with a memorable moment",
        15, 35,
    ),
    ExperienceTarget(
        "survival_rate",
        "Pct of runs where player survives all encounters",
        20, 40,
    ),
    ExperienceTarget(
        "companion_impact",
        "Pct damage increase from companions vs no companions",
        15, 45,
    ),
    ExperienceTarget(
        "strategy_skill_gap",
        "Survival rate gap: Basic vs Random strategy",
        10, 35, "pp",
    ),
    ExperienceTarget(
        "avg_fight_length",
        "Average hands per fight",
        3, 6, "hands",
    ),
    ExperienceTarget(
        "snowball_ratio",
        "Damage output ratio: last act vs first act",
        1.2, 2.0, "x",
    ),
    ExperienceTarget(
        "fold_rate",
        "Pct of hands where player folds",
        5, 15,
    ),
    ExperienceTarget(
        "deck_trim",
        "Avg cards removed per run",
        4, 10, "cards",
    ),
    ExperienceTarget(
        "power_curve_ratio",
        "Win rate last act vs first act",
        1.02, 1.15, "x",
    ),
    ExperienceTarget(
        "counterplay_success_rate",
        "Pct of enemy chase scenarios where player avoids losing",
        60, 72,
    ),
    ExperienceTarget(
        "reward_variety_rate",
        "Avg per-run reward-type variety (normalized)",
        58, 72,
    ),
    ExperienceTarget(
        "build_pivot_rate",
        "Pct of runs with a meaningful reward-priority pivot mid-run",
        48, 62,
    ),
    ExperienceTarget(
        "synergy_online_rate",
        "Pct of hands with 2+ simultaneous effect procs",
        1.0, 5.0,
    ),
    ExperienceTarget(
        "early_spike_rate",
        "Pct of runs with an early spike in act 1",
        62, 80,
    ),
    ExperienceTarget(
        "midrun_novelty_rate",
        "Pct of act 2+ fights introducing a not-seen-earlier enemy",
        32, 42,
    ),
    ExperienceTarget(
        "companion_attachment_rate",
        "Pct of runs where a companion reaches level 3+",
        55, 75,
    ),
    ExperienceTarget(
        "companion_meaningfulness",
        "Survival gap: >=2 companions captured vs <=1 companions",
        14, 26, "pp",
    ),
    ExperienceTarget(
        "high_total_loss_rate",
        "Pct of non-bust 19+ player hands that still lose",
        12, 18,
    ),
    ExperienceTarget(
        "enemy_hit_rate",
        "Enemy hit decisions as pct of total enemy decisions",
        56, 62,
    ),
    ExperienceTarget(
        "enemy_chase_hit_rate",
        "Enemy chase hits (while not ahead) as pct of enemy hits",
        50, 60,
    ),
    ExperienceTarget(
        "enemy_risk_hit_rate",
        "Enemy high-risk hits (>=35% bust odds) as pct of enemy hits",
        54, 63,
    ),
    ExperienceTarget(
        "enemy_safe_stand_rate",
        "Enemy stands while ahead as pct of enemy stands",
        54, 63,
    ),
    ExperienceTarget(
        "elite_chase_hit_rate",
        "Elite chase hits as pct of elite hits",
        96.5, 99.2,
    ),
    ExperienceTarget(
        "boss_chase_hit_rate",
        "Boss chase hits as pct of boss hits",
        96.0, 98.8,
    ),
]


# ---------------------------------------------------------------------------
# Enemy templates
# hit_threshold: enemy hits on this value or below (like dealer rules)
# HP tuned for 3-5 hand fights with damage_subtract=12
#
# Abilities:
#   reckless_extra    - enemy hits N extra times after reaching threshold
#   damage_absorption - flat damage blocked per hand (shell)
#   nine_lives_chance - pct chance to survive lethal damage once
#   rage_per_hand     - bonus_damage increases by this each hand
#   poison_per_hand   - flat damage to player every hand regardless of outcome
#   drain             - enemy heals for damage dealt when it wins
# ---------------------------------------------------------------------------
ENEMY_TEMPLATES = {
    # --- Normal Shades (capturable) ---
    "dutch_shade": {
        "name": "Dutch",
        "hp": 5,
        "hit_threshold": 17,
        "tier": "normal",
        "companion_type": "dutch",
        "crit_chance": 0.25,
    },
    "nines_shade": {
        "name": "Nines",
        "hp": 5,
        "hit_threshold": 16,
        "tier": "normal",
        "companion_type": "nines",
        "reckless_extra": 1,
    },
    "maggie_shade": {
        "name": "Maggie",
        "hp": 4,
        "hit_threshold": 15,
        "tier": "normal",
        "companion_type": "maggie",
    },
    "priest_shade": {
        "name": "Priest",
        "hp": 8,
        "hit_threshold": 13,
        "tier": "normal",
        "companion_type": "priest",
        "damage_absorption": 1,
    },
    "sable_shade": {
        "name": "Sable",
        "hp": 3,
        "hit_threshold": 18,
        "tier": "normal",
        "companion_type": "sable",
        "nine_lives_chance": 0.5,
    },

    # --- House Dealers (elite) ---
    "dealer_knuckles": {
        "name": "Knuckles",
        "hp": 10,
        "hit_threshold": 17,
        "tier": "elite",
        "companion_type": "",
        "bonus_damage": 2,
        "rage_per_hand": 1,
    },
    "dealer_hemlock": {
        "name": "Hemlock",
        "hp": 9,
        "hit_threshold": 16,
        "tier": "elite",
        "companion_type": "",
        "poison_per_hand": 1,
    },
    "dealer_stiletto": {
        "name": "Stiletto",
        "hp": 9,
        "hit_threshold": 17,
        "tier": "elite",
        "companion_type": "",
        "crit_chance": 0.30,
        "backstab_on_21": True,
    },

    # --- Pit Bosses ---
    "boss_silk": {
        "name": "Silk",
        "hp": 15,
        "hit_threshold": 17,
        "tier": "boss",
        "companion_type": "",
        "silence_shades": True,
    },
    "boss_hollow": {
        "name": "The Hollow",
        "hp": 13,
        "hit_threshold": 17,
        "tier": "boss",
        "companion_type": "",
        "drain": True,
        "reap_shade_on_21": True,
    },
    "boss_croupier": {
        "name": "The Croupier",
        "hp": 14,
        "hit_threshold": 18,
        "tier": "boss",
        "companion_type": "",
        "damage_absorption": 2,
        "reckless_extra": 1,
    },
}


# ---------------------------------------------------------------------------
# Companion templates
# effect_type determines WHEN and HOW the companion modifies combat.
#   damage_multiplier     - multiplies damage dealt on wins (1.25x = +25%)
#   damage_reduction_pct  - percentage damage reduction on losses (0.25 = 25%)
#   natural_21_multiplier - standalone multiplier on natural 21 damage
#   peek_enemy            - see enemy hole card (binary, value ignored)
#   unbust_chance         - pct chance to undo a bust (remove last drawn card)
#
# Multiplicative companions compound with deck improvement for power curve.
# ---------------------------------------------------------------------------
COMPANION_TEMPLATES = {
    "dutch": {
        "name": "Dutch",
        "effect_type": "peek_enemy",
        "activation": "always",
        "base_value": 1,
        "per_level": 0,
    },
    "maggie": {
        "name": "Maggie",
        "effect_type": "damage_multiplier",
        "activation": "two_black",     # needs two black cards (♣♠) in hand
        "base_value": 1.40,
        "per_level": 0.05,
    },
    "priest": {
        "name": "Priest",
        "effect_type": "damage_reduction_pct",
        "activation": "two_red",       # needs two red cards (♥♦) in hand
        "base_value": 0.30,
        "per_level": 0.03,
    },
    "sable": {
        "name": "Sable",
        "effect_type": "natural_21_multiplier",
        "activation": "natural_21",    # only on natural blackjack
        "base_value": 2.5,
        "per_level": 0.25,
    },
    "nines": {
        "name": "Nines",
        "effect_type": "unbust_chance",
        "activation": "on_bust",
        "base_value": 0.30,
        "per_level": 0.05,
    },
}


# ---------------------------------------------------------------------------
# Fold resource
# ---------------------------------------------------------------------------
@dataclass
class FoldConfig:
    starting_folds: int = 3
    fold_reward_amount: int = 2


# ---------------------------------------------------------------------------
# Map (branching node system per act)
# ---------------------------------------------------------------------------
@dataclass
class MapConfig:
    vigil_heal_pct: float = 0.25
    vigil_commune_xp: int = 20
    vigil_offering_folds: int = 2
    vigil_offering_hp_cost: int = 8
    crossroads_win_heal: int = 5
    crossroads_loss_damage: int = 5


GRAVE_CARDS = {
    "dead_ace":   {"name": "Dead Man's Ace",  "rank": "A",  "suit": "S", "enchantment": "siphon",
                   "desc": "An ace that heals when played."},
    "bone_ten":   {"name": "Bone Ten",        "rank": "10", "suit": "C", "enchantment": "fury",
                   "desc": "Hits hard when you win."},
    "ghost_jack": {"name": "Ghost Jack",      "rank": "J",  "suit": "D", "enchantment": "ward",
                   "desc": "Absorbs pain when you lose."},
    "iron_king":  {"name": "Iron King",       "rank": "K",  "suit": "S", "enchantment": "fury",
                   "desc": "Heavy iron. Hits heavier."},
    "pale_queen": {"name": "Pale Queen",      "rank": "Q",  "suit": "H", "enchantment": "siphon",
                   "desc": "Draws life from the fallen."},
}


ACT_NAMES = [
    "The Shallow Plots",
    "The Dealer's Row",
    "The Bone Parlor",
]


# ---------------------------------------------------------------------------
# Master config
# ---------------------------------------------------------------------------
@dataclass
class GameConfig:
    damage: DamageConfig = field(default_factory=DamageConfig)
    player: PlayerConfig = field(default_factory=PlayerConfig)
    companion: CompanionConfig = field(default_factory=CompanionConfig)
    run: RunConfig = field(default_factory=RunConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    enchantment: EnchantmentConfig = field(default_factory=EnchantmentConfig)
    fold: FoldConfig = field(default_factory=FoldConfig)
    map: MapConfig = field(default_factory=MapConfig)
    experience_targets: list = field(
        default_factory=lambda: list(DEFAULT_EXPERIENCE_TARGETS)
    )
