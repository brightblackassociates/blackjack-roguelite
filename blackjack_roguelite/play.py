#!/usr/bin/env python3
"""
Blackjack Roguelite -- Interactive Terminal Game
Run: python3 play.py
"""
import random
import re
import sys
import os
import time
import tty
import termios

from .config import GameConfig, ENEMY_TEMPLATES, COMPANION_TEMPLATES
from .engine import (Card, Deck, hand_value, is_natural_21, Player, Enemy, Companion,
                     RARITY_BUFFS, RARITY_WEIGHTS, RANKS, check_activation)


# --- ANSI color for enemy rarity ---
RARITY_COLORS = {
    "common": "",
    "rare":   "\033[33m",       # yellow
    "elite":  "\033[38;5;208m", # orange
    "epic":   "\033[31m",       # red
}
# --- ANSI formatting constants ---
C_RESET   = "\033[0m"
C_DIM     = "\033[2m"
C_RED     = "\033[31m"
C_GREEN   = "\033[32m"
C_YELLOW  = "\033[33m"
C_CYAN    = "\033[36m"
C_BRED    = "\033[1;31m"   # bold red
C_BGREEN  = "\033[1;32m"   # bold green
C_BYELLOW = "\033[1;33m"   # bold yellow
C_BWHITE  = "\033[1;37m"   # bold white
C_REVERSE = "\033[7m"      # inverse video
C_REV_RED = "\033[7;31m"   # inverse video red


def colorize(text, rarity):
    """Wrap text in ANSI color for rarity. No-op for common."""
    code = RARITY_COLORS.get(rarity, "")
    if not code:
        return text
    return f"{code}{text}{C_RESET}"


def enemy_display_name(enemy):
    """Enemy name with rarity label and color."""
    if enemy.rarity == "common":
        return enemy.name
    label = f"{enemy.name} ({enemy.rarity.capitalize()})"
    return colorize(label, enemy.rarity)


ACTIVATION_INFO = {
    "two_red":    {"hint": "\u2665\u2666", "desc": "two red cards (\u2665\u2666) in hand"},
    "two_black":  {"hint": "\u2663\u2660", "desc": "two black cards (\u2663\u2660) in hand"},
    "natural_21": {"hint": "BJ",  "desc": "natural 21"},
    "on_bust":    {"hint": "",    "desc": "when you bust"},
    "always":     {"hint": "",    "desc": "always active"},
}


def activation_hint(activation):
    """Short hint like '♥♦' for status bar display."""
    info = ACTIVATION_INFO.get(activation, {})
    return info.get("hint", "")


def colorize_hint(activation):
    """Return activation hint with ANSI color (red for suit symbols)."""
    hint = activation_hint(activation)
    if not hint:
        return ""
    if "\u2665" in hint or "\u2666" in hint:
        return f"{C_RED}{hint}{C_RESET}"
    return hint


def activation_desc(activation):
    """Full description like 'two red cards (♥♦) in hand'."""
    info = ACTIVATION_INFO.get(activation, {})
    return info.get("desc", "")


SUIT_SYM = {"H": "\u2665", "D": "\u2666", "C": "\u2663", "S": "\u2660"}

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def plain_len(s):
    """Visible character length, ignoring ANSI escape codes."""
    return len(_ANSI_RE.sub('', s))


def show_card(c):
    text = f" {c.rank}{SUIT_SYM[c.suit]} "
    if c.suit in ("H", "D"):
        return f"{C_REV_RED}{text}{C_RESET}"
    return f"{C_REVERSE}{text}{C_RESET}"


def show_hand(cards):
    return " ".join(show_card(c) for c in cards)


def hp_color(current, maximum):
    """ANSI color code based on HP percentage: green/yellow/red."""
    pct = max(0, current / maximum)
    if pct > 0.5:
        return C_GREEN
    elif pct > 0.25:
        return C_YELLOW
    return C_RED


def hp_bar(current, maximum, width=20):
    pct = max(0, current / maximum)
    filled = int(width * pct)
    color = hp_color(current, maximum)
    return f"{color}{'█' * filled}{C_RESET}{C_DIM}{'░' * (width - filled)}{C_RESET}"


def read_key():
    """Read a single keypress, returning arrow keys as 'left'/'right'/'up'/'down'."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':  # Escape sequence (arrow keys)
            seq = sys.stdin.read(2)
            arrows = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return arrows.get(seq, ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def prompt_choice(msg, valid, labels=None):
    """Prompt for a choice. valid = list of keys. labels = dict of key->display name."""
    sys.stdout.write(f"  {msg} \033[5m\u25b8\033[0m ")
    sys.stdout.flush()
    while True:
        try:
            ch = read_key()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Goodbye!")
            sys.exit(0)
        if ch == '\x03':  # Ctrl-C
            print("\n\n  Goodbye!")
            sys.exit(0)
        ans = ch.lower() if len(ch) == 1 else ch
        if ans in valid:
            display = labels.get(ans, ans) if labels else ans
            print(display)
            return ans


def pause(msg="  Press any key to continue..."):
    sys.stdout.write(msg)
    sys.stdout.flush()
    try:
        read_key()
    except (EOFError, KeyboardInterrupt):
        print("\n\n  Goodbye!")
        sys.exit(0)
    print()


def beat(seconds=0.3):
    """Pacing pause between hand phases. Creates rhythm without keypresses."""
    sys.stdout.flush()
    time.sleep(seconds)


def clear():
    os.system("clear" if os.name != "nt" else "cls")


# -----------------------------------------------------------------------
# Ability descriptions shown to the player
# -----------------------------------------------------------------------
ABILITY_HINTS = {
    "reckless_extra": "Reckless -- hits extra, might bust or crush you",
    "damage_absorption": "Shell -- absorbs {v} damage per hand",
    "nine_lives_chance": "Nine Lives -- may survive a killing blow",
    "rage_per_hand": "Rage -- bonus damage grows each hand",
    "poison_per_hand": "Poison -- {v} damage every hand, win or lose",
    "drain": "Drain -- heals when it hurts you",
    "forced_extra_hits": "Inferno -- forces you to hit {v} extra time(s)",
}


def describe_abilities(enemy):
    parts = []
    fields = [
        ("reckless_extra", enemy.reckless_extra),
        ("damage_absorption", enemy.damage_absorption),
        ("nine_lives_chance", enemy.nine_lives_chance),
        ("rage_per_hand", enemy.rage_per_hand),
        ("poison_per_hand", enemy.poison_per_hand),
        ("drain", int(enemy.drain)),
        ("forced_extra_hits", enemy.forced_extra_hits),
    ]
    for key, val in fields:
        if val:
            parts.append(ABILITY_HINTS[key].format(v=val))
    return parts


EFFECT_LABELS = {
    "damage_multiplier":     ("dmg on wins",   "damage multiplier on wins"),
    "damage_reduction_pct":  ("dmg reduction", "% damage reduction on losses"),
    "natural_21_multiplier": ("nat 21 dmg",    "natural 21 damage multiplier"),
    "peek_enemy":            ("peek hole card", "see enemy's hole card"),
    "unbust_chance":         ("save on bust",  "chance to undo a bust"),
}


def describe_companion_effect(effect_type, short=False):
    entry = EFFECT_LABELS.get(effect_type)
    if not entry:
        return effect_type
    return entry[0] if short else entry[1]


# -----------------------------------------------------------------------
# Game
# -----------------------------------------------------------------------
class Game:
    def __init__(self):
        self.config = GameConfig()
        self.deck = Deck()
        self.player = Player(
            hp=self.config.player.starting_hp,
            max_hp=self.config.player.starting_hp,
            max_companion_slots=self.config.player.max_companion_slots,
            folds=self.config.fold.starting_folds,
        )

    # --- Rules screen ---

    def show_rules(self):
        print()
        print(f"  {C_BWHITE}{'='*44}{C_RESET}")
        print(f"  {C_BWHITE}  RULES & REFERENCE{C_RESET}")
        print(f"  {C_BWHITE}{'='*44}{C_RESET}")
        print()
        print(f"  {C_BWHITE}Goal:{C_RESET} Survive 3 acts (15 fights total).")
        print(f"  Each fight is a series of blackjack hands.")
        print(f"  Get closer to 21 than the enemy to deal damage.")
        print(f"  Go over 21 and you bust (take extra damage).")
        print()
        print(f"  {C_BWHITE}Controls:{C_RESET}")
        print(f"    {C_GREEN}\u2192{C_RESET} Hit (draw a card)")
        print(f"    {C_GREEN}\u2190{C_RESET} Stand (keep your hand)")
        print(f"    \u2193 Fold (take {self.config.damage.fold_damage} dmg, costs 1 fold)")
        print(f"    \u2191 Info panel (enemy, companions, deck)")
        print(f"    r Rules (this screen)")
        print()
        print(f"  {C_BWHITE}Folds:{C_RESET} Limited resource. Start with {self.config.fold.starting_folds}.")
        print(f"  Folding costs 1 fold and {self.config.damage.fold_damage} HP.")
        print(f"  Better than losing (3-7 HP), but you give up")
        print(f"  the chance to win. Earn +{self.config.fold.fold_reward_amount} folds as a reward after wins.")
        print()
        print(f"  {C_BWHITE}Rewards{C_RESET} (after each win, pick one):")
        print(f"    Remove a card (thin your deck, raise avg hand)")
        print(f"    Enchant a card (fury/siphon/ward)")
        print(f"    Heal HP")
        print(f"    Gain {self.config.fold.fold_reward_amount} folds")
        print(f"    Capture companion (normal enemies only)")
        print()
        print(f"  {C_BWHITE}Companions:{C_RESET} Passive effects during combat.")
        print(f"  Some require specific cards in hand to activate.")
        print(f"  Gain XP each fight and level up (max Lv5).")
        print()
        print(f"  {C_BWHITE}Enchantments:{C_RESET}")
        print(f"    {C_RED}Fury{C_RESET}   +{self.config.enchantment.fury_damage} bonus damage on wins")
        print(f"    {C_CYAN}Siphon{C_RESET} Heal {self.config.enchantment.siphon_heal} per enchanted card in hand")
        print(f"    {C_YELLOW}Ward{C_RESET}   -{self.config.enchantment.ward_reduction} damage on losses")
        print(f"  Stacks diminish: +{self.config.enchantment.diminishing:.0%} per extra copy.")
        print()
        print(f"  {C_BWHITE}Enemy abilities:{C_RESET}")
        print(f"    Reckless: hits extra times (volatile)")
        print(f"    Shell: absorbs damage each hand")
        print(f"    Nine Lives: may survive a killing blow once")
        print(f"    Rage: bonus damage grows each hand")
        print(f"    Poison: flat damage every hand, win or lose")
        print(f"    Drain: heals when it hurts you")
        print(f"    Inferno: forces you to hit extra")
        print()
        pause()

    # --- Enchantment helpers ---

    def _count_enchantments(self, cards):
        """Count enchantment types across cards in hand."""
        counts = {"fury": 0, "siphon": 0, "ward": 0}
        for card in cards:
            for ench in self.deck.get_enchantments(card):
                if ench in counts:
                    counts[ench] += 1
        return counts

    def _ench_total(self, base, count):
        """Total value from stacked enchantments with diminishing returns."""
        if count <= 0:
            return 0.0
        total = float(base)
        for _ in range(count - 1):
            total += base * self.config.enchantment.diminishing
        return total

    def _apply_siphon(self, player_cards):
        """Apply siphon heal from enchanted cards in hand."""
        ench = self._count_enchantments(player_cards)
        if ench["siphon"] > 0:
            heal = int(self._ench_total(self.config.enchantment.siphon_heal, ench["siphon"]))
            self.player.heal(heal)
            print(f"  {C_CYAN}Siphon x{ench['siphon']}: heal {heal}!{C_RESET} ({self.player.hp}/{self.player.max_hp})")

    def base_damage(self, winner_val, loser_val):
        cfg = self.config.damage
        if cfg.model == "differential":
            return max(winner_val - loser_val, cfg.damage_floor)
        return max(winner_val - cfg.damage_subtract, 1)

    # --- Encounter generation ---

    def generate_encounters(self):
        normals = [k for k, v in ENEMY_TEMPLATES.items() if v.get("tier", "normal") == "normal"]
        elites = [k for k, v in ENEMY_TEMPLATES.items() if v.get("tier") == "elite"]
        bosses = [k for k, v in ENEMY_TEMPLATES.items() if v.get("tier") == "boss"]
        encounters = []
        for act in range(self.config.run.acts):
            for _ in range(self.config.run.fights_per_act):
                encounters.append((random.choice(normals), act))
            for _ in range(self.config.run.elites_per_act):
                encounters.append((random.choice(elites), act))
            encounters.append((random.choice(bosses), act))
        return encounters

    @staticmethod
    def _roll_rarity(tier):
        weights = RARITY_WEIGHTS.get(tier, RARITY_WEIGHTS["normal"])
        names, probs = zip(*weights)
        return random.choices(names, weights=probs, k=1)[0]

    def create_enemy(self, key, act=0):
        t = ENEMY_TEMPLATES[key]
        tier = t.get("tier", "normal")
        rarity = self._roll_rarity(tier)
        buffs = RARITY_BUFFS[rarity]

        multipliers = self.config.run.act_hp_multipliers
        hp_mult = multipliers[act] if act < len(multipliers) else multipliers[-1]
        scaled_hp = max(1, int(t["hp"] * hp_mult * buffs["hp"]))
        threshold = min(19, t["hit_threshold"] + buffs["threshold"])
        bonus_dmg = t.get("bonus_damage", 0) + buffs["bonus_damage"]

        return Enemy(
            name=t["name"], hp=scaled_hp, max_hp=scaled_hp,
            hit_threshold=threshold,
            tier=tier, rarity=rarity,
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

    # --- Display helpers ---

    def show_status(self):
        bar = hp_bar(self.player.hp, self.player.max_hp)
        print(f"  You  {bar} {self.player.hp}/{self.player.max_hp}     Folds: {self.player.folds}")
        if self.player.companions:
            for c in self.player.companions:
                hint_c = colorize_hint(c.activation)
                suffix = f" [{hint_c}]" if hint_c else ""
                print(f"  {C_CYAN}{c.name}{C_RESET} Lv{c.level}{suffix}")

    # --- Damage application ---

    def hurt_enemy(self, enemy, raw_dmg, show=True):
        if enemy.damage_absorption > 0 and raw_dmg > 0:
            absorbed = min(raw_dmg, enemy.damage_absorption)
            raw_dmg = max(0, raw_dmg - enemy.damage_absorption)
            if show:
                print(f"  {C_YELLOW}-{absorbed:.0f} shell -> {raw_dmg:.0f}{C_RESET}")
        actual = int(raw_dmg)
        enemy.hp = max(0, enemy.hp - actual)
        if show:
            ebar = hp_bar(enemy.hp, enemy.max_hp, 10)
            print(f"  {C_GREEN}>> {actual} to {enemy_display_name(enemy)}{C_RESET}  {ebar} {enemy.hp}/{enemy.max_hp}")

    def hurt_player(self, dmg, show=True):
        actual = int(dmg)
        self.player.take_damage(actual)
        if show:
            bar = hp_bar(self.player.hp, self.player.max_hp)
            print(f"  {C_RED}<< Take {actual}{C_RESET}  {bar} {self.player.hp}/{self.player.max_hp}")

    # --- Inspect panel ---

    _DIVIDER = object()  # sentinel for section dividers

    def inspect_panel(self, enemy, player_cards):
        """Show info panel: enemy, companions, deck state."""
        lines = []  # display strings (may contain ANSI codes)
        DIV = self._DIVIDER

        def add(line):
            lines.append(line)

        def divider():
            lines.append(DIV)

        # --- Enemy section ---
        name = enemy_display_name(enemy)
        ebar = hp_bar(enemy.hp, enemy.max_hp, 10)
        add(f"  {name}  {ebar} {enemy.hp}/{enemy.max_hp}")
        add(f"  Plays until {enemy.hit_threshold}")

        abilities = []
        if enemy.reckless_extra:
            abilities.append(f"  Reckless: hits {enemy.reckless_extra} extra")
        if enemy.damage_absorption:
            abilities.append(f"  Shell: absorbs {enemy.damage_absorption} dmg/hand")
        if enemy.nine_lives_chance > 0:
            abilities.append(f"  Nine Lives: {enemy.nine_lives_chance:.0%} survive death")
        elif getattr(enemy, '_nine_lives_spent', False):
            abilities.append(f"  Nine Lives: spent")
        if enemy.rage_per_hand:
            abilities.append(f"  Rage: +{enemy.rage_per_hand}/hand (now +{enemy.bonus_damage})")
        if enemy.poison_per_hand:
            abilities.append(f"  Poison: {enemy.poison_per_hand} dmg/hand")
        if enemy.drain:
            abilities.append(f"  Drain: heals on hit")
        if enemy.forced_extra_hits:
            abilities.append(f"  Inferno: forces {enemy.forced_extra_hits} extra hit(s)")
        if enemy.bonus_damage and not enemy.rage_per_hand:
            abilities.append(f"  Bonus damage: +{enemy.bonus_damage}")

        if abilities:
            add("")
            for a in abilities:
                add(f"{C_YELLOW}{a}{C_RESET}")
        else:
            add("")
            add(f"  {C_DIM}No special abilities.{C_RESET}")

        # --- Companions section ---
        divider()
        if self.player.companions:
            add(f"  {C_BWHITE}COMPANIONS{C_RESET} {C_DIM}({len(self.player.companions)}/{self.player.max_companion_slots}){C_RESET}")

            for c in self.player.companions:
                effect_label = describe_companion_effect(c.effect_type, short=True)

                # Format effect value
                if "multiplier" in c.effect_type:
                    val_str = f"x{c.effect_value:.2f}"
                elif "pct" in c.effect_type or "chance" in c.effect_type:
                    val_str = f"{c.effect_value * 100:.0f}%"
                else:
                    val_str = ""

                # Check activation against current hand
                if c.activation in ("two_red", "two_black"):
                    active = check_activation(player_cards, c.activation)
                else:
                    active = None  # contextual, not card-composition

                line = f"  {C_CYAN}{c.name}{C_RESET} Lv{c.level}"
                if val_str:
                    line += f"  {val_str} {effect_label}"
                else:
                    line += f"  {effect_label}"

                # Activation indicator
                hint_c = colorize_hint(c.activation)
                if hint_c:
                    if active is True:
                        line += f"  [{hint_c} {C_GREEN}\u2713{C_RESET}]"
                    elif active is False:
                        hint_raw = activation_hint(c.activation)
                        line += f"  {C_DIM}[{hint_raw}]{C_RESET}"
                    else:
                        line += f"  [{hint_c}]"
                elif c.activation == "on_bust":
                    line += f"  {C_DIM}[on bust]{C_RESET}"
                elif c.activation == "natural_21":
                    line += f"  {C_DIM}[nat 21]{C_RESET}"

                add(line)
        else:
            slots = self.player.max_companion_slots
            add(f"  {C_DIM}No companions (0/{slots}){C_RESET}")

        # --- Folds section ---
        divider()
        add(f"  Folds remaining: {self.player.folds}")

        # --- Deck section ---
        divider()
        total_removed = 52 - self.deck.template_size
        if total_removed > 0:
            add(f"  {C_BWHITE}DECK{C_RESET}  {self.deck.template_size} cards {C_DIM}({total_removed} removed){C_RESET}")
        else:
            add(f"  {C_BWHITE}DECK{C_RESET}  {self.deck.template_size} cards")

        counts = self.deck.rank_counts()
        thinned = [(r, counts.get(r, 0)) for r in RANKS if 0 < counts.get(r, 0) < 4]
        gone = [r for r in RANKS if counts.get(r, 0) == 0]

        if thinned:
            parts = [f"{r}:{ct}" for r, ct in thinned]
            add(f"  Thinned: {', '.join(parts)}")
        if gone:
            add(f"  {C_DIM}Gone: {', '.join(gone)}{C_RESET}")

        ench_summary = self.deck.enchanted_cards_summary()
        if ench_summary:
            ench_counts = {"fury": 0, "siphon": 0, "ward": 0}
            for _card, enchs in ench_summary:
                for e in enchs:
                    if e in ench_counts:
                        ench_counts[e] += 1
            parts = [f"{ct}\u00d7 {n.capitalize()}" for n, ct in ench_counts.items() if ct > 0]
            if parts:
                add(f"  {C_CYAN}Enchanted: {', '.join(parts)}{C_RESET}")

        draw_remaining = len(self.deck.cards)
        add(f"  {C_DIM}Draw pile: {draw_remaining}{C_RESET}")

        # --- Render box ---
        max_width = max((plain_len(l) for l in lines if l is not DIV), default=30) + 2
        max_width = max(max_width, 34)

        print()
        print(f"  {C_DIM}\u250c{'─' * max_width}\u2510{C_RESET}")
        for line in lines:
            if line is DIV:
                print(f"  {C_DIM}\u251c{'─' * max_width}\u2524{C_RESET}")
            else:
                padding = max_width - plain_len(line)
                print(f"  {C_DIM}\u2502{C_RESET}{line}{' ' * padding}{C_DIM}\u2502{C_RESET}")
        print(f"  {C_DIM}\u2514{'─' * max_width}\u2518{C_RESET}")
        print()

    # --- Hand logic ---

    def play_hand(self, enemy, hand_num):
        player_cards = [self.deck.draw(), self.deck.draw()]
        enemy_cards = [self.deck.draw(), self.deck.draw()]
        has_peek = self.player.get_companion_effect("peek_enemy", player_cards) is not None

        hand_label = f"── Hand {hand_num} "
        print(f"\n  {C_DIM}{hand_label}{'─' * (45 - len(hand_label))}{C_RESET}")

        # --- Naturals ---
        p_nat = is_natural_21(player_cards)
        e_nat = is_natural_21(enemy_cards)

        if p_nat or e_nat:
            print(f"  You    {show_card(player_cards[0])}", end="")
            sys.stdout.flush()
            beat(0.15)
            print(f" {show_card(player_cards[1])}   = {hand_value(player_cards)}")
            beat(0.1)
            print(f"  Enemy  {show_hand(enemy_cards)}   = {hand_value(enemy_cards)}")
            beat(0.5)
            if p_nat and e_nat:
                print(f"  {C_YELLOW}Both natural 21! Push.{C_RESET}")
                self._apply_siphon(player_cards)
                return
            if p_nat:
                print(f"  {C_BGREEN}NATURAL 21!{C_RESET}")
                beat(0.5)
                dmg = self._calc_win_damage(21, hand_value(enemy_cards), is_natural=True, player_cards=player_cards)
                self.hurt_enemy(enemy, dmg)
                self._apply_siphon(player_cards)
                return
            print(f"  {C_BRED}Enemy natural 21!{C_RESET}")
            beat(0.4)
            dmg = self._calc_loss_damage(21, hand_value(player_cards), is_natural=True,
                                         player_cards=player_cards, bonus_damage=enemy.bonus_damage)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            self._apply_siphon(player_cards)
            return

        # --- Show starting hands (progressive deal) ---
        print(f"  You    {show_card(player_cards[0])}", end="")
        sys.stdout.flush()
        beat(0.15)
        print(f" {show_card(player_cards[1])}   = {hand_value(player_cards)}")
        beat(0.1)
        threshold_str = f"stands at {enemy.hit_threshold}"
        if has_peek:
            print(f"  Enemy  {show_hand(enemy_cards)}   = {hand_value(enemy_cards)}  {C_CYAN}[Shadow Thief]{C_RESET}")
        else:
            print(f"  Enemy  {show_card(enemy_cards[0])} {C_DIM}??{C_RESET}                   {C_DIM}{threshold_str}{C_RESET}")

        # --- Fold option (first decision only) ---
        first_decision = True
        forced = enemy.forced_extra_hits
        player_busted = False

        while True:
            p_val = hand_value(player_cards)

            if p_val > 21:
                unbust = self.player.get_companion_effect("unbust_chance", player_cards)
                if unbust and random.random() < unbust:
                    removed = player_cards.pop()
                    print(f"  {C_CYAN}Goblin Shaman saves you!{C_RESET} Tossed {show_card(removed)}")
                    print(f"  You    {show_hand(player_cards)}   = {hand_value(player_cards)}")
                    continue
                player_busted = True
                beat(0.4)
                print(f"  {C_BRED}BUST!{C_RESET} ({p_val})")
                break

            if p_val == 21:
                print(f"  {C_GREEN}21!{C_RESET}")
                break

            if forced > 0:
                print(f"  {C_YELLOW}Inferno forces you to hit!{C_RESET}")
                forced -= 1
                card = self.deck.draw()
                player_cards.append(card)
                print(f"  Drew {show_card(card)}  = {hand_value(player_cards)}")
                first_decision = False
                continue

            bust_pct = self.deck.bust_probability(player_cards) * 100
            deck_ct = len(self.deck.cards)

            if bust_pct > 70:
                bust_color = C_RED
            elif bust_pct >= 20:
                bust_color = C_YELLOW
            else:
                bust_color = C_GREEN
            bust_str = f"{bust_color}bust: {bust_pct:.0f}%{C_RESET}"

            arrow_labels = {"right": "HIT", "left": "STAND", "down": "FOLD", "up": "INFO", "r": "RULES"}

            can_fold = first_decision and self.player.folds > 0
            stats_str = f"{bust_str}  deck: {deck_ct} \u25b8"

            print(f"\n  \u2192 Hit   \u2190 Stand                    {stats_str}")
            if can_fold:
                fold_str = f"\u2193 Fold ({self.player.folds})"
                choice = prompt_choice(
                    f"{fold_str}  \u2191 Info  r Rules",
                    ["right", "left", "down", "up", "r"],
                    arrow_labels,
                )
            elif first_decision:
                choice = prompt_choice(
                    f"{C_DIM}\u2193 Fold (0){C_RESET}  \u2191 Info  r Rules",
                    ["right", "left", "up", "r"],
                    arrow_labels,
                )
            else:
                choice = prompt_choice(
                    f"\u2191 Info  r Rules",
                    ["right", "left", "up", "r"],
                    arrow_labels,
                )

            if choice == "up":
                self.inspect_panel(enemy, player_cards)
                continue

            if choice == "r":
                self.show_rules()
                continue

            first_decision = False

            if choice == "down":
                self.player.folds -= 1
                fold_dmg = self.config.damage.fold_damage
                print(f"  Folded. Take {fold_dmg} chip damage. ({self.player.folds} folds left)")
                self.hurt_player(fold_dmg)
                return "fold"

            if choice == "left":
                print(f"  Stand at {p_val}.")
                break

            card = self.deck.draw()
            player_cards.append(card)
            print(f"  Drew {show_card(card)}  = {hand_value(player_cards)}")

        p_val = hand_value(player_cards)

        # --- Player busted: lose immediately ---
        if player_busted:
            beat(0.5)
            e_val = hand_value(enemy_cards)
            print(f"  Enemy had  {show_hand(enemy_cards)}  -> {e_val}")
            beat(0.3)
            dmg = self._calc_loss_damage(e_val, p_val, is_bust=True,
                                         player_cards=player_cards, bonus_damage=enemy.bonus_damage)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            self._apply_siphon(player_cards)
            return

        # --- Enemy turn ---
        beat(0.5)
        print(f"\n  Enemy flips  {show_card(enemy_cards[1])}")
        beat(0.25)
        print(f"  Enemy hand   {show_hand(enemy_cards)}  -> {hand_value(enemy_cards)}")

        while hand_value(enemy_cards) <= enemy.hit_threshold:
            beat(0.3)
            card = self.deck.draw()
            enemy_cards.append(card)
            print(f"  Enemy draws  {show_card(card)}  -> {hand_value(enemy_cards)}")

        for _ in range(enemy.reckless_extra):
            if hand_value(enemy_cards) < 21:
                beat(0.3)
                card = self.deck.draw()
                enemy_cards.append(card)
                print(f"  {C_YELLOW}Reckless!{C_RESET}    {show_card(card)}  -> {hand_value(enemy_cards)}")

        e_val = hand_value(enemy_cards)
        enemy_busted = e_val > 21

        if enemy_busted:
            beat(0.4)
            print(f"  {C_BGREEN}ENEMY BUSTS!{C_RESET} ({e_val})")

        # --- Resolve ---
        print()
        beat(0.3)
        won = False
        lost = False
        if enemy_busted:
            beat(0.3)
            dmg = self._calc_win_damage(p_val, e_val, player_cards=player_cards)
            self.hurt_enemy(enemy, dmg)
            won = True
        elif p_val > e_val:
            print(f"  {C_GREEN}You win!{C_RESET} {p_val} vs {e_val}")
            beat(0.15)
            dmg = self._calc_win_damage(p_val, e_val, player_cards=player_cards)
            self.hurt_enemy(enemy, dmg)
            won = True
        elif e_val > p_val:
            print(f"  {C_RED}You lose.{C_RESET} {p_val} vs {e_val}")
            beat(0.15)
            dmg = self._calc_loss_damage(e_val, p_val, player_cards=player_cards,
                                         bonus_damage=enemy.bonus_damage)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            lost = True
        else:
            print(f"  {C_YELLOW}Push.{C_RESET} Both {p_val}.")
        self._apply_siphon(player_cards)

        # --- Highlight callouts ---
        if p_val == 22 and player_busted:
            beat(0.3)
            print(f"  {C_DIM}Just one over...{C_RESET}")
        if len(player_cards) >= 5 and not player_busted:
            beat(0.2)
            print(f"  {C_BWHITE}Five cards!{C_RESET}")
        if won and not enemy_busted and p_val - e_val == 1:
            beat(0.3)
            print(f"  {C_GREEN}By a hair!{C_RESET}")
        if lost and not player_busted and e_val - p_val == 1:
            beat(0.3)
            print(f"  {C_RED}So close...{C_RESET}")
        if won and self.player.hp <= self.player.max_hp * 0.2:
            beat(0.4)
            print(f"  {C_BGREEN}Clutch!{C_RESET}")

    def _calc_win_damage(self, p_val, e_val, is_natural=False, player_cards=None):
        cfg = self.config.damage
        if cfg.model == "differential":
            base = float(max(p_val - e_val, cfg.damage_floor))
            print(f"  {C_DIM}{p_val} - {e_val} = {base:.0f}{C_RESET}")
        else:
            base = float(max(p_val - cfg.damage_subtract, 1))
            print(f"  {C_DIM}{p_val} - {cfg.damage_subtract} = {base:.0f}{C_RESET}")
        dmg = base
        if is_natural:
            cat_mult = self.player.get_companion_effect("natural_21_multiplier", player_cards)
            if cat_mult:
                dmg *= cat_mult
                print(f"  {C_CYAN}x{cat_mult:.1f} Lucky Cat -> {dmg:.0f}{C_RESET}")
            else:
                dmg *= cfg.natural_21_multiplier
                print(f"  {C_DIM}x{cfg.natural_21_multiplier:.1f} natural -> {dmg:.0f}{C_RESET}")
        else:
            margin = p_val - e_val
            if margin >= cfg.margin_bonus_threshold:
                dmg *= cfg.margin_bonus_multiplier
                print(f"  {C_DIM}x{cfg.margin_bonus_multiplier:.1f} margin ({margin}pt) -> {dmg:.0f}{C_RESET}")
        imp_mult = self.player.get_companion_effect("damage_multiplier", player_cards)
        if imp_mult:
            dmg *= imp_mult
            print(f"  {C_CYAN}x{imp_mult:.2f} Fire Imp [\u2665\u2666] -> {dmg:.0f}{C_RESET}")
        if player_cards:
            ench = self._count_enchantments(player_cards)
            if ench["fury"] > 0:
                fury_bonus = self._ench_total(self.config.enchantment.fury_damage, ench["fury"])
                dmg += fury_bonus
                print(f"  {C_CYAN}+{fury_bonus:.0f} Fury x{ench['fury']} -> {dmg:.0f}{C_RESET}")
        return dmg

    def _calc_loss_damage(self, e_val, p_val, is_natural=False, is_bust=False,
                          player_cards=None, bonus_damage=0):
        cfg = self.config.damage
        if cfg.model == "differential":
            base = float(max(e_val - p_val, cfg.damage_floor))
            print(f"  {C_DIM}{e_val} - {p_val} = {base:.0f}{C_RESET}")
        else:
            base = float(max(e_val - cfg.damage_subtract, 1))
            print(f"  {C_DIM}{e_val} - {cfg.damage_subtract} = {base:.0f}{C_RESET}")
        dmg = base
        if is_bust:
            dmg *= cfg.bust_penalty_multiplier
            print(f"  {C_DIM}x{cfg.bust_penalty_multiplier:.1f} bust -> {dmg:.0f}{C_RESET}")
        if is_natural:
            dmg *= cfg.natural_21_multiplier
            print(f"  {C_DIM}x{cfg.natural_21_multiplier:.1f} natural -> {dmg:.0f}{C_RESET}")
        reduction_pct = self.player.get_companion_effect("damage_reduction_pct", player_cards)
        if reduction_pct:
            reduced = dmg * reduction_pct
            dmg = max(0, dmg - reduced)
            print(f"  {C_CYAN}-{reduction_pct*100:.0f}% Shield Turtle [\u2663\u2660] -> {dmg:.0f}{C_RESET}")
        if player_cards:
            ench = self._count_enchantments(player_cards)
            if ench["ward"] > 0:
                ward_red = self._ench_total(self.config.enchantment.ward_reduction, ench["ward"])
                dmg = max(0, dmg - ward_red)
                print(f"  {C_CYAN}-{ward_red:.0f} Ward x{ench['ward']} -> {dmg:.0f}{C_RESET}")
        if bonus_damage > 0:
            dmg += bonus_damage
            print(f"  {C_DIM}+{bonus_damage} rage -> {dmg:.0f}{C_RESET}")
        return dmg

    def _apply_drain(self, enemy, dmg):
        heal = max(1, int(dmg))
        enemy.hp = min(enemy.max_hp, enemy.hp + heal)
        print(f"  {C_RED}Lich drains {heal} HP!{C_RESET} ({enemy.hp}/{enemy.max_hp})")

    # --- Fight loop ---

    def show_enemy_status(self, enemy):
        ebar = hp_bar(enemy.hp, enemy.max_hp)
        name = enemy_display_name(enemy)
        tier = f" [{enemy.tier.upper()}]" if enemy.tier != "normal" else ""
        print(f"  {name}{tier}  {ebar} {enemy.hp}/{enemy.max_hp}")

    def play_fight(self, enemy, fight_num, total, act_num):
        clear()
        rule = f"{C_DIM}{'─' * 45}{C_RESET}"
        print()
        print(f"  {rule}")
        act_label = f"ACT {act_num}"
        fight_label = f"Fight {fight_num} of {total}"
        padding = 45 - len(act_label) - len(fight_label)
        print(f"  {C_BWHITE}{act_label}{' ' * padding}{fight_label}{C_RESET}")
        print(f"  {rule}")
        print()
        self.show_enemy_status(enemy)
        abilities = describe_abilities(enemy)
        for a in abilities:
            print(f"  {C_YELLOW}{a}{C_RESET}")
        print()
        print(f"  {rule}")
        print()
        self.show_status()

        hand_num = 0
        total_dealt = 0
        total_taken = 0
        prev_levels = {c.name: c.level for c in self.player.companions}

        while self.player.alive and enemy.alive:
            hand_num += 1
            ehp_before, php_before = enemy.hp, self.player.hp
            result = self.play_hand(enemy, hand_num)
            total_dealt += max(0, ehp_before - enemy.hp)
            total_taken += max(0, php_before - self.player.hp)

            # Show both HP bars after each hand
            if self.player.alive and enemy.alive:
                print()
                self.show_enemy_status(enemy)
                self.show_status()
                print(f"  {C_DIM}{'─ ' * 20}{C_RESET}")

            # Poison (every hand)
            if enemy.poison_per_hand and enemy.alive and self.player.alive:
                beat(0.2)
                self.player.take_damage(enemy.poison_per_hand)
                print(f"  {C_RED}Poison! -{enemy.poison_per_hand} HP{C_RESET} ({self.player.hp}/{self.player.max_hp})")

            # Nine lives
            if not enemy.alive and enemy.nine_lives_chance > 0:
                if random.random() < enemy.nine_lives_chance:
                    beat(0.5)
                    enemy.hp = 1
                    enemy.nine_lives_chance = 0.0
                    enemy._nine_lives_spent = True
                    print(f"  {C_YELLOW}NINE LIVES!{C_RESET} {enemy_display_name(enemy)} clings on with 1 HP!")
                    beat(0.3)

            # Rage escalation
            if enemy.rage_per_hand and enemy.alive:
                enemy.bonus_damage += enemy.rage_per_hand
                beat(0.3)
                print(f"  {C_YELLOW}{enemy_display_name(enemy)} grows stronger! (+{enemy.bonus_damage} dmg){C_RESET}")

        # Companion XP (end of fight)
        for c in self.player.companions:
            c.gain_xp(
                self.config.companion.xp_per_fight,
                self.config.companion.xp_per_level,
                self.config.companion.max_level,
            )

        won = not enemy.alive
        if won:
            print(f"\n  {enemy_display_name(enemy)} defeated!")
            print(f"  {C_DIM}{hand_num} hands | {total_dealt} dealt | {total_taken} taken{C_RESET}")

        # Companion level-up and XP display
        for c in self.player.companions:
            if c.level > prev_levels.get(c.name, 0):
                print(f"  {C_CYAN}{c.name} reached level {c.level}!{C_RESET}")
            elif c.level < self.config.companion.max_level:
                print(f"  {C_DIM}{c.name} {c.xp}/{self.config.companion.xp_per_level} XP{C_RESET}")

        return won

    # --- Post-fight reward ---

    def post_fight_reward(self, enemy):
        print(f"\n  {C_BYELLOW}--- REWARD ---{C_RESET}")

        # Build options mapped to arrow directions
        arrows = ["left", "right", "down"]
        arrow_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}
        options = []       # (label, action_id)

        # Option: Remove a card
        removable = self.deck.removable_ranks(self.config.reward.min_deck_size)
        if removable:
            options.append(("Remove a card", "remove"))

        # Option: Heal
        heal_amount = (
            self.config.reward.heal_amount_elite
            if enemy.tier in ("elite", "boss")
            else self.config.reward.heal_amount
        )
        if self.player.hp < self.player.max_hp:
            options.append((f"Heal {heal_amount} HP", "heal"))

        # Option: Enchant a card
        ecfg = self.config.enchantment
        enchantable = self.deck.enchantable_cards(1, ecfg.max_per_card)
        if enchantable:
            options.append(("Enchant a card", "enchant"))

        # Option: Gain folds
        fold_amt = self.config.fold.fold_reward_amount
        options.append((f"Gain {fold_amt} folds", "fold_reward"))

        # Option: Capture companion (always shown, but can fail)
        can_capture = False
        template = None
        if enemy.companion_type and enemy.tier == "normal":
            template = COMPANION_TEMPLATES.get(enemy.companion_type)
            if template and self.player.can_capture():
                can_capture = True
                pct = int(self.config.companion.capture_chance * 100)
                options.append((f"Capture {template['name']} ({pct}% chance)", "capture"))

        if not options:
            print("  No rewards available.")
            pause()
            return

        # Offer 3 random choices per reward
        if len(options) > 3:
            random.shuffle(options)
            options = options[:3]

        valid_keys = []
        labels = {}
        action_map = {}
        for i, (label, action) in enumerate(options):
            key = arrows[i]
            valid_keys.append(key)
            labels[key] = label.upper()
            action_map[key] = action
            print(f"    {arrow_syms[key]} {label}")

        choice = prompt_choice("  Choose:", valid_keys, labels)
        action = action_map[choice]

        if action == "fold_reward":
            self.player.folds += self.config.fold.fold_reward_amount
            print(f"  {C_GREEN}+{self.config.fold.fold_reward_amount} folds!{C_RESET} ({self.player.folds} total)")
        elif action == "remove" and removable:
            self._card_removal_ui()
        elif action == "enchant":
            self._enchantment_ui()
        elif action == "heal":
            old_hp = self.player.hp
            self.player.heal(heal_amount)
            print(f"  {C_GREEN}Healed {self.player.hp - old_hp} HP{C_RESET} ({old_hp} -> {self.player.hp})")
        elif action == "capture" and can_capture and template:
            if random.random() < self.config.companion.capture_chance:
                act_key = template.get("activation", "always")
                comp = Companion(
                    name=template["name"],
                    companion_type=enemy.companion_type,
                    effect_type=template["effect_type"],
                    base_value=template["base_value"],
                    per_level=template["per_level"],
                    activation=act_key,
                )
                self.player.companions.append(comp)
                desc = activation_desc(act_key)
                print(f"  {C_CYAN}{comp.name} joins you!{C_RESET} (activates with {desc})")
            else:
                print(f"  {C_RED}{template['name']} escaped!{C_RESET}")

        pause()

    def _card_removal_ui(self):
        """Show deck composition and let player pick a rank to remove."""
        counts = self.deck.rank_counts()
        removable = self.deck.removable_ranks(self.config.reward.min_deck_size)
        total_removed = 52 - self.deck.template_size

        print(f"\n  Deck: {self.deck.template_size} cards ({total_removed} removed)")

        # Only show ranks where a copy has been removed (partial sets)
        modified = [(r, counts.get(r, 0)) for r in RANKS if counts.get(r, 0) < 4]
        removed_ranks = [r for r in RANKS if counts.get(r, 0) == 0]

        if modified:
            parts = [f"{r}:{ct}" for r, ct in modified]
            print(f"  Thinned: {', '.join(parts)}")
        if removed_ranks:
            print(f"  {C_DIM}Gone: {', '.join(removed_ranks)}{C_RESET}")

        # Show removable ranks
        print(f"  Remove: {' '.join(removable)}")

        while True:
            sys.stdout.write("  > ")
            sys.stdout.flush()
            # Read rank input (1-2 chars)
            ch1 = read_key()
            if ch1 == '\x03':
                print("\n\n  Goodbye!")
                sys.exit(0)
            if ch1 == '1':
                ch2 = read_key()
                if ch2 == '0':
                    rank = "10"
                    print("10")
                else:
                    rank = ch1.upper()
                    print(rank)
            else:
                rank = ch1.upper()
                print(rank)

            if rank in removable:
                if self.deck.remove_rank(rank):
                    print(f"  Removed a {rank} from your deck! ({self.deck.template_size} cards)")
                    return
            print(f"  Can't remove '{rank}'. Try again.")

    def _enchantment_ui(self):
        """Let player pick a card to enchant and an enchantment type."""
        ecfg = self.config.enchantment
        cards = self.deck.enchantable_cards(ecfg.cards_offered, ecfg.max_per_card)
        if not cards:
            print("  No cards available to enchant.")
            return

        print(f"\n  Pick a card to enchant:")
        for i, card in enumerate(cards):
            ench = self.deck.get_enchantments(card)
            ench_str = ""
            if ench:
                tags = ", ".join(e.capitalize() for e in ench)
                ench_str = f"  ({tags})"
            print(f"    {i+1}. {show_card(card)}{ench_str}")

        valid_nums = [str(i + 1) for i in range(len(cards))]
        chosen_card = None
        while True:
            sys.stdout.write("  > ")
            sys.stdout.flush()
            ch = read_key()
            if ch == '\x03':
                print("\n\n  Goodbye!")
                sys.exit(0)
            if ch in valid_nums:
                print(ch)
                chosen_card = cards[int(ch) - 1]
                break

        # Offer enchantment types
        all_types = ["fury", "siphon", "ward"]
        offered = random.sample(all_types, min(ecfg.types_offered, len(all_types)))

        type_labels = {
            "fury": f"Fury (+{ecfg.fury_damage} dmg on wins)",
            "siphon": f"Siphon (heal {ecfg.siphon_heal} any hand)",
            "ward": f"Ward (-{ecfg.ward_reduction} dmg on losses)",
        }

        arrows = ["left", "right", "down"]
        arrow_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}
        valid_keys = []
        labels = {}
        type_map = {}

        print(f"\n  Choose enchantment:")
        for i, etype in enumerate(offered):
            key = arrows[i]
            valid_keys.append(key)
            labels[key] = etype.upper()
            type_map[key] = etype
            print(f"    {arrow_syms[key]} {type_labels[etype]}")

        choice = prompt_choice("  >", valid_keys, labels)
        etype = type_map[choice]

        if self.deck.enchant_card(chosen_card, etype, ecfg.max_per_card):
            ench = self.deck.get_enchantments(chosen_card)
            tags = ", ".join(e.capitalize() for e in ench)
            print(f"  Added {etype.capitalize()} to {show_card(chosen_card)}! ({tags})")

    # --- Between acts ---

    def between_acts(self, act_num):
        heal = int(self.player.max_hp * self.config.run.heal_between_acts_pct)
        old_hp = self.player.hp
        self.player.heal(heal)
        clear()
        print()
        print(f"  {C_BWHITE}--- Rest before Act {act_num} ---{C_RESET}")
        print(f"  {C_GREEN}Healed {self.player.hp - old_hp} HP{C_RESET}  ({old_hp} -> {self.player.hp})")
        self.show_status()
        pause()

    # --- Main loop ---

    def run(self):
        clear()
        print()
        print(f"  {C_BWHITE}" + "=" * 40 + f"{C_RESET}")
        print(f"  {C_BWHITE}      BLACKJACK ROGUELITE{C_RESET}")
        print(f"  {C_BWHITE}" + "=" * 40 + f"{C_RESET}")
        print()
        print("  Beat enemies at blackjack to deal damage.")
        print("  Get closer to 21 than your enemy.")
        print("  Bust and you take the hit instead.")
        print()
        print("  After each win, choose a reward:")
        print("  Remove a card, enchant, heal, gain folds,")
        print("  or capture a companion. Enchantments stack.")
        print("  Survive 3 acts to win.")
        print()
        print("  Controls: \u2192 hit, \u2190 stand, \u2193 fold, \u2191 info, r rules")
        print()
        pause()

        encounters = self.generate_encounters()
        current_act = -1

        for i, (enemy_key, act) in enumerate(encounters):
            if act > current_act and current_act >= 0:
                self.between_acts(act + 1)
            current_act = act

            enemy = self.create_enemy(enemy_key, act)
            won = self.play_fight(enemy, i + 1, len(encounters), act + 1)

            if not self.player.alive:
                print()
                print(f"  {C_BRED}" + "=" * 40 + f"{C_RESET}")
                print(f"  {C_BRED}      DEFEAT{C_RESET}")
                print(f"  {C_BRED}" + "=" * 40 + f"{C_RESET}")
                print(f"\n  {C_DIM}Fell in fight {i + 1} of {len(encounters)}.{C_RESET}")
                print(f"  Killed by: {enemy_display_name(enemy)}")
                self.show_final()
                return

            if won:
                self.post_fight_reward(enemy)

        clear()
        print()
        print(f"  {C_BGREEN}" + "=" * 40 + f"{C_RESET}")
        print(f"  {C_BGREEN}      VICTORY!{C_RESET}")
        print(f"  {C_BGREEN}" + "=" * 40 + f"{C_RESET}")
        print(f"\n  {C_GREEN}Survived all {len(encounters)} encounters!{C_RESET}")
        color = hp_color(self.player.hp, self.player.max_hp)
        print(f"  Final HP: {color}{self.player.hp}/{self.player.max_hp}{C_RESET}")
        self.show_final()

    def show_final(self):
        if self.player.companions:
            print(f"\n  Companions:")
            for c in self.player.companions:
                effect = describe_companion_effect(c.effect_type)
                hint_c = colorize_hint(c.activation)
                suffix = f" [{hint_c}]" if hint_c else ""
                print(f"    {C_CYAN}{c.name}{C_RESET} Lv{c.level} -- {effect}: {c.effect_value:.1f}{suffix}")
        print()


def main():
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
