#!/usr/bin/env python3
"""
Blackjack Roguelite -- Interactive Terminal Game
Run: python3 play.py
"""
import random
import sys
import os
import time
import tty
import termios

from config import GameConfig, ENEMY_TEMPLATES, COMPANION_TEMPLATES
from engine import (Card, Deck, hand_value, is_natural_21, Player, Enemy, Companion,
                     RARITY_BUFFS, RARITY_WEIGHTS, check_activation)


# --- ANSI color for enemy rarity ---
RARITY_COLORS = {
    "common": "",
    "rare":   "\033[33m",       # yellow
    "elite":  "\033[38;5;208m", # orange
    "epic":   "\033[31m",       # red
}
ANSI_RESET = "\033[0m"


def colorize(text, rarity):
    """Wrap text in ANSI color for rarity. No-op for common."""
    code = RARITY_COLORS.get(rarity, "")
    if not code:
        return text
    return f"{code}{text}{ANSI_RESET}"


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


def activation_desc(activation):
    """Full description like 'two red cards (♥♦) in hand'."""
    info = ACTIVATION_INFO.get(activation, {})
    return info.get("desc", "")


SUIT_SYM = {"H": "\u2665", "D": "\u2666", "C": "\u2663", "S": "\u2660"}


def show_card(c):
    return f"{c.rank}{SUIT_SYM[c.suit]}"


def show_hand(cards):
    return "  ".join(show_card(c) for c in cards)


def hp_bar(current, maximum, width=20):
    pct = max(0, current / maximum)
    filled = int(width * pct)
    return "[" + "#" * filled + "." * (width - filled) + "]"


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
    sys.stdout.write(f"  {msg} ")
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


def describe_companion_effect(effect_type):
    labels = {
        "damage_multiplier": "damage multiplier on wins",
        "damage_reduction_pct": "% damage reduction on losses",
        "natural_21_multiplier": "natural 21 damage multiplier",
        "peek_enemy": "see enemy's hole card",
        "unbust_chance": "chance to undo a bust",
    }
    return labels.get(effect_type, effect_type)


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
        )

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
            print(f"  Siphon x{ench['siphon']}: heal {heal}! ({self.player.hp}/{self.player.max_hp})")

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
        parts = [f"HP {bar} {self.player.hp}/{self.player.max_hp}"]
        if self.player.companions:
            comp_strs = []
            for c in self.player.companions:
                hint = activation_hint(c.activation)
                suffix = f" [{hint}]" if hint else ""
                comp_strs.append(f"{c.name} Lv{c.level}{suffix}")
            parts.append(", ".join(comp_strs))
        print(f"  {' | '.join(parts)}")

    # --- Damage application ---

    def hurt_enemy(self, enemy, raw_dmg, show=True):
        if enemy.damage_absorption > 0 and raw_dmg > 0:
            absorbed = min(raw_dmg, enemy.damage_absorption)
            raw_dmg = max(0, raw_dmg - enemy.damage_absorption)
            if show:
                print(f"  -{absorbed:.0f} shell -> {raw_dmg:.0f}")
        actual = int(raw_dmg)
        enemy.hp = max(0, enemy.hp - actual)
        if show:
            ebar = hp_bar(enemy.hp, enemy.max_hp, 10)
            print(f"  >> {actual} to {enemy_display_name(enemy)}  {ebar} {enemy.hp}/{enemy.max_hp}")

    def hurt_player(self, dmg, show=True):
        actual = int(dmg)
        self.player.take_damage(actual)
        if show:
            bar = hp_bar(self.player.hp, self.player.max_hp)
            print(f"  << Take {actual}  {bar} {self.player.hp}/{self.player.max_hp}")

    # --- Inspect panel ---

    def inspect_enemy(self, enemy):
        """Show a box-drawn info panel about the current enemy."""
        name = enemy_display_name(enemy)
        # For width calculation, strip ANSI codes
        plain_name = enemy.name
        if enemy.rarity != "common":
            plain_name = f"{enemy.name} ({enemy.rarity.capitalize()})"
        hp_str = f"{enemy.hp}/{enemy.max_hp}"
        header = f"  {plain_name}        {hp_str}"

        # Build content lines (plain text for width, display text separate)
        lines_plain = []
        lines_display = []

        # Header line
        hdr_plain = f"  {plain_name}  {hp_str}"
        hdr_display = f"  {name}  {hp_str}"
        lines_plain.append(hdr_plain)
        lines_display.append(hdr_display)

        # Plays until
        lines_plain.append(f"  Plays until {enemy.hit_threshold}")
        lines_display.append(f"  Plays until {enemy.hit_threshold}")

        # Blank line
        lines_plain.append("")
        lines_display.append("")

        # Abilities with dynamic state
        abilities = []
        if enemy.reckless_extra:
            abilities.append(f"  Reckless: hits {enemy.reckless_extra} extra time(s)")
        if enemy.damage_absorption:
            abilities.append(f"  Shell: absorbs {enemy.damage_absorption} damage per hand")
        if enemy.nine_lives_chance > 0:
            abilities.append(f"  Nine Lives: {enemy.nine_lives_chance:.0%} chance to survive death")
        elif getattr(enemy, '_nine_lives_spent', False):
            abilities.append(f"  Nine Lives: spent")
        if enemy.rage_per_hand:
            abilities.append(f"  Rage: +{enemy.rage_per_hand} bonus damage per hand.")
            abilities.append(f"        Currently at +{enemy.bonus_damage}.")
        if enemy.poison_per_hand:
            abilities.append(f"  Poison: {enemy.poison_per_hand} damage every hand")
        if enemy.drain:
            abilities.append(f"  Drain: heals when it hurts you")
        if enemy.forced_extra_hits:
            abilities.append(f"  Inferno: forces you to hit {enemy.forced_extra_hits} extra time(s)")
        if enemy.bonus_damage and not enemy.rage_per_hand:
            abilities.append(f"  Bonus damage: +{enemy.bonus_damage}")

        if abilities:
            for a in abilities:
                lines_plain.append(a)
                lines_display.append(a)
        else:
            lines_plain.append("  No special abilities.")
            lines_display.append("  No special abilities.")

        # Calculate box width
        max_width = max(len(lp) for lp in lines_plain) + 2
        max_width = max(max_width, 30)  # minimum width

        print()
        print(f"  \u250c{'─' * max_width}\u2510")
        for lp, ld in zip(lines_plain, lines_display):
            padding = max_width - len(lp)
            print(f"  \u2502{ld}{' ' * padding}\u2502")
        print(f"  \u2514{'─' * max_width}\u2518")
        print()

    # --- Hand logic ---

    def play_hand(self, enemy, hand_num):
        player_cards = [self.deck.draw(), self.deck.draw()]
        enemy_cards = [self.deck.draw(), self.deck.draw()]
        has_peek = self.player.get_companion_effect("peek_enemy", player_cards) is not None

        print(f"\n  -- Hand {hand_num} --")

        # --- Naturals ---
        p_nat = is_natural_21(player_cards)
        e_nat = is_natural_21(enemy_cards)

        if p_nat or e_nat:
            print(f"  You:   {show_hand(player_cards)}  = {hand_value(player_cards)}")
            print(f"  Enemy: {show_hand(enemy_cards)}  = {hand_value(enemy_cards)}")
            beat(0.4)
            if p_nat and e_nat:
                print("  Both natural 21! Push.")
                self._apply_siphon(player_cards)
                return
            if p_nat:
                print("  NATURAL 21!")
                beat(0.3)
                dmg = self._calc_win_damage(21, hand_value(enemy_cards), is_natural=True, player_cards=player_cards)
                self.hurt_enemy(enemy, dmg)
                self._apply_siphon(player_cards)
                return
            print("  Enemy natural 21!")
            beat(0.3)
            dmg = self._calc_loss_damage(21, hand_value(player_cards), is_natural=True,
                                         player_cards=player_cards, bonus_damage=enemy.bonus_damage)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            self._apply_siphon(player_cards)
            return

        # --- Show starting hands ---
        print(f"  You:   {show_hand(player_cards)}  = {hand_value(player_cards)}")
        if has_peek:
            print(f"  Enemy: {show_hand(enemy_cards)}  = {hand_value(enemy_cards)}  [Shadow Thief]")
        else:
            print(f"  Enemy: {show_card(enemy_cards[0])}  ??")

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
                    print(f"  Goblin Shaman saves you! Tossed {show_card(removed)}")
                    print(f"  You:   {show_hand(player_cards)}  = {hand_value(player_cards)}")
                    continue
                player_busted = True
                beat(0.3)
                print(f"  BUST! ({p_val})")
                break

            if p_val == 21:
                print(f"  21!")
                break

            if forced > 0:
                print(f"  Inferno forces you to hit!")
                forced -= 1
                card = self.deck.draw()
                player_cards.append(card)
                print(f"  Drew {show_card(card)}  = {hand_value(player_cards)}")
                first_decision = False
                continue

            bust_pct = self.deck.bust_probability(player_cards) * 100
            deck_ct = len(self.deck.cards)

            arrow_labels = {"right": "HIT", "left": "STAND", "down": "FOLD", "up": "INFO"}

            if first_decision:
                choice = prompt_choice(
                    f"\u2192 Hit  \u2190 Stand  \u2193 Fold  \u2191 Info   (bust: {bust_pct:.0f}% | deck: {deck_ct})",
                    ["right", "left", "down", "up"],
                    arrow_labels,
                )
            else:
                choice = prompt_choice(
                    f"\u2192 Hit  \u2190 Stand  \u2191 Info   (bust: {bust_pct:.0f}% | deck: {deck_ct})",
                    ["right", "left", "up"],
                    arrow_labels,
                )

            if choice == "up":
                self.inspect_enemy(enemy)
                continue

            first_decision = False

            if choice == "down":
                fold_dmg = self.config.damage.fold_damage
                print(f"  Folded. Take {fold_dmg} chip damage.")
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
            beat(0.4)
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
                print(f"  Reckless!    {show_card(card)}  -> {hand_value(enemy_cards)}")

        e_val = hand_value(enemy_cards)
        enemy_busted = e_val > 21

        if enemy_busted:
            beat(0.3)
            print(f"  ENEMY BUSTS! ({e_val})")

        # --- Resolve ---
        beat(0.4)
        if enemy_busted:
            print(f"  You win! {p_val} vs BUST")
            beat(0.2)
            dmg = self._calc_win_damage(p_val, e_val, player_cards=player_cards)
            self.hurt_enemy(enemy, dmg)
        elif p_val > e_val:
            print(f"  You win! {p_val} vs {e_val}")
            beat(0.2)
            dmg = self._calc_win_damage(p_val, e_val, player_cards=player_cards)
            self.hurt_enemy(enemy, dmg)
        elif e_val > p_val:
            print(f"  You lose. {p_val} vs {e_val}")
            beat(0.2)
            dmg = self._calc_loss_damage(e_val, p_val, player_cards=player_cards,
                                         bonus_damage=enemy.bonus_damage)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
        else:
            print(f"  Push. Both {p_val}.")
        self._apply_siphon(player_cards)

    def _calc_win_damage(self, p_val, e_val, is_natural=False, player_cards=None):
        cfg = self.config.damage
        if cfg.model == "differential":
            base = float(max(p_val - e_val, cfg.damage_floor))
            print(f"  {p_val} - {e_val} = {base:.0f}")
        else:
            base = float(max(p_val - cfg.damage_subtract, 1))
            print(f"  {p_val} - {cfg.damage_subtract} = {base:.0f}")
        dmg = base
        if is_natural:
            cat_mult = self.player.get_companion_effect("natural_21_multiplier", player_cards)
            if cat_mult:
                dmg *= cat_mult
                print(f"  x{cat_mult:.1f} Lucky Cat -> {dmg:.0f}")
            else:
                dmg *= cfg.natural_21_multiplier
                print(f"  x{cfg.natural_21_multiplier:.1f} natural -> {dmg:.0f}")
        else:
            margin = p_val - e_val
            if margin >= cfg.margin_bonus_threshold:
                dmg *= cfg.margin_bonus_multiplier
                print(f"  x{cfg.margin_bonus_multiplier:.1f} margin ({margin}pt) -> {dmg:.0f}")
        imp_mult = self.player.get_companion_effect("damage_multiplier", player_cards)
        if imp_mult:
            dmg *= imp_mult
            print(f"  x{imp_mult:.2f} Fire Imp [\u2665\u2666] -> {dmg:.0f}")
        if player_cards:
            ench = self._count_enchantments(player_cards)
            if ench["fury"] > 0:
                fury_bonus = self._ench_total(self.config.enchantment.fury_damage, ench["fury"])
                dmg += fury_bonus
                print(f"  +{fury_bonus:.0f} Fury x{ench['fury']} -> {dmg:.0f}")
        return dmg

    def _calc_loss_damage(self, e_val, p_val, is_natural=False, is_bust=False,
                          player_cards=None, bonus_damage=0):
        cfg = self.config.damage
        if cfg.model == "differential":
            base = float(max(e_val - p_val, cfg.damage_floor))
            print(f"  {e_val} - {p_val} = {base:.0f}")
        else:
            base = float(max(e_val - cfg.damage_subtract, 1))
            print(f"  {e_val} - {cfg.damage_subtract} = {base:.0f}")
        dmg = base
        if is_bust:
            dmg *= cfg.bust_penalty_multiplier
            print(f"  x{cfg.bust_penalty_multiplier:.1f} bust -> {dmg:.0f}")
        if is_natural:
            dmg *= cfg.natural_21_multiplier
            print(f"  x{cfg.natural_21_multiplier:.1f} natural -> {dmg:.0f}")
        reduction_pct = self.player.get_companion_effect("damage_reduction_pct", player_cards)
        if reduction_pct:
            reduced = dmg * reduction_pct
            dmg = max(0, dmg - reduced)
            print(f"  -{reduction_pct*100:.0f}% Shield Turtle [\u2663\u2660] -> {dmg:.0f}")
        if player_cards:
            ench = self._count_enchantments(player_cards)
            if ench["ward"] > 0:
                ward_red = self._ench_total(self.config.enchantment.ward_reduction, ench["ward"])
                dmg = max(0, dmg - ward_red)
                print(f"  -{ward_red:.0f} Ward x{ench['ward']} -> {dmg:.0f}")
        if bonus_damage > 0:
            dmg += bonus_damage
            print(f"  +{bonus_damage} rage -> {dmg:.0f}")
        return dmg

    def _apply_drain(self, enemy, dmg):
        heal = max(1, int(dmg))
        enemy.hp = min(enemy.max_hp, enemy.hp + heal)
        print(f"  Lich drains {heal} HP! ({enemy.hp}/{enemy.max_hp})")

    # --- Fight loop ---

    def show_enemy_status(self, enemy):
        ebar = hp_bar(enemy.hp, enemy.max_hp, 15)
        name = enemy_display_name(enemy)
        tier = f" [{enemy.tier.upper()}]" if enemy.tier != "normal" else ""
        print(f"  {name}{tier}  {ebar} {enemy.hp}/{enemy.max_hp}")

    def play_fight(self, enemy, fight_num, total, act_num):
        clear()
        print()
        print(f"  {'='*44}")
        print(f"  Act {act_num}  |  Fight {fight_num}/{total}")
        self.show_enemy_status(enemy)
        abilities = describe_abilities(enemy)
        for a in abilities:
            print(f"    {a}")
        print(f"  {'='*44}")
        self.show_status()

        hand_num = 0
        while self.player.alive and enemy.alive:
            hand_num += 1
            result = self.play_hand(enemy, hand_num)

            # Show both HP bars after each hand
            if self.player.alive and enemy.alive:
                print()
                self.show_enemy_status(enemy)
                self.show_status()

            # Poison (every hand)
            if enemy.poison_per_hand and enemy.alive and self.player.alive:
                self.player.take_damage(enemy.poison_per_hand)
                print(f"  Poison! -{enemy.poison_per_hand} HP ({self.player.hp}/{self.player.max_hp})")

            # Nine lives
            if not enemy.alive and enemy.nine_lives_chance > 0:
                if random.random() < enemy.nine_lives_chance:
                    enemy.hp = 1
                    enemy.nine_lives_chance = 0.0
                    enemy._nine_lives_spent = True
                    print(f"  NINE LIVES! {enemy_display_name(enemy)} clings on with 1 HP!")

            # Rage escalation
            if enemy.rage_per_hand and enemy.alive:
                enemy.bonus_damage += enemy.rage_per_hand

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
        return won

    # --- Post-fight reward ---

    def post_fight_reward(self, enemy):
        print(f"\n  --- REWARD ---")

        # Build options mapped to arrow directions
        arrows = ["left", "right", "down", "up"]
        arrow_syms = {
            "left": "\u2190",
            "right": "\u2192",
            "down": "\u2193",
            "up": "\u2191",
        }
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

        if action == "remove" and removable:
            self._card_removal_ui()
        elif action == "enchant":
            self._enchantment_ui()
        elif action == "heal":
            old_hp = self.player.hp
            self.player.heal(heal_amount)
            print(f"  Healed {self.player.hp - old_hp} HP ({old_hp} -> {self.player.hp})")
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
                print(f"  {comp.name} joins you! (activates with {desc})")
            else:
                print(f"  {template['name']} escaped!")

        # Level-up notifications
        for c in self.player.companions:
            if c.xp == 0 and c.level > 1:
                print(f"  {c.name} reached level {c.level}!")
        pause()

    def _card_removal_ui(self):
        """Show deck composition and let player pick a rank to remove."""
        counts = self.deck.rank_counts()
        removable = self.deck.removable_ranks(self.config.reward.min_deck_size)
        total_removed = 52 - self.deck.template_size

        print(f"\n  Deck: {self.deck.template_size} cards ({total_removed} removed)")

        # Only show ranks where a copy has been removed (partial sets)
        rank_order = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        modified = [(r, counts.get(r, 0)) for r in rank_order if counts.get(r, 0) < 4]
        removed_ranks = [r for r in rank_order if counts.get(r, 0) == 0]

        if modified:
            parts = [f"{r}:{ct}" for r, ct in modified]
            print(f"  Thinned: {', '.join(parts)}")
        if removed_ranks:
            print(f"  Gone: {', '.join(removed_ranks)}")

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
        print(f"  --- Rest before Act {act_num} ---")
        print(f"  Healed {self.player.hp - old_hp} HP  ({old_hp} -> {self.player.hp})")
        self.show_status()
        pause()

    # --- Main loop ---

    def run(self):
        clear()
        print()
        print("  " + "=" * 40)
        print("        BLACKJACK ROGUELITE")
        print("  " + "=" * 40)
        print()
        print("  Beat enemies at blackjack to deal damage.")
        print("  Get closer to 21 than your enemy.")
        print("  Bust and you take the hit instead.")
        print()
        print("  After each win, choose a reward:")
        print("  Remove a card, enchant a card, heal, or")
        print("  capture a companion. Enchantments stack.")
        print("  Survive 3 acts to win.")
        print()
        print("  Controls: \u2192 hit, \u2190 stand, \u2193 fold, \u2191 info")
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
                print("  " + "=" * 40)
                print("        DEFEAT")
                print("  " + "=" * 40)
                print(f"\n  Fell in fight {i + 1} of {len(encounters)}.")
                print(f"  Killed by: {enemy_display_name(enemy)}")
                self.show_final()
                return

            if won:
                self.post_fight_reward(enemy)

        clear()
        print()
        print("  " + "=" * 40)
        print("        VICTORY!")
        print("  " + "=" * 40)
        print(f"\n  Survived all {len(encounters)} encounters!")
        print(f"  Final HP: {self.player.hp}/{self.player.max_hp}")
        self.show_final()

    def show_final(self):
        if self.player.companions:
            print(f"\n  Companions:")
            for c in self.player.companions:
                effect = describe_companion_effect(c.effect_type)
                desc = activation_desc(c.activation)
                print(f"    {c.name} Lv{c.level} -- {effect}: {c.effect_value:.1f} ({desc})")
        print()


if __name__ == "__main__":
    game = Game()
    game.run()
