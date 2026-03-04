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
from collections import Counter
import tty
import termios

from .config import GameConfig, ENEMY_TEMPLATES, COMPANION_TEMPLATES, GRAVE_CARDS, ACT_NAMES
from .engine import (Card, Deck, hand_value, is_natural_21, Player, Enemy, Companion,
                     RARITY_BUFFS, RARITY_WEIGHTS, RANKS, check_activation,
                     capture_roll_for_rarity, capture_chance_for_rarity,
                     enemy_deck_removed_ranks, enemy_deck_quality_label, build_enemy_deck_from_removed_ranks,
                     companion_power_multiplier_for_rarity,
                     NodeType, MapNode, ActMap, generate_act_map, COMBAT_NODE_TYPES)


# --- ANSI color for enemy rarity ---
RARITY_COLORS = {
    "common": "",
    "rare":   "\033[33m",       # yellow
    "elite":  "\033[38;5;208m", # orange
    "epic":   "\033[31m",       # red
}
# --- ANSI formatting constants (CRT phosphor palette) ---
C_RESET   = "\033[0m"
C_DIM     = "\033[2m"
C_RED     = "\033[31m"
C_GREEN   = "\033[32m"          # Primary text
C_AMBER   = "\033[38;5;214m"   # Warnings, Shade abilities
C_BRED    = "\033[1;31m"       # Defeat, bust
C_BGREEN  = "\033[1;32m"       # Wins, emphasis
C_BWHITE  = "\033[1;37m"       # Headers
C_PHANTOM = "\033[38;5;245m"   # Shade whispers (fallback)

# Per-shade colors: each companion gets a unique hue
SHADE_COLORS = {
    "dutch":  "\033[38;5;33m",   # Steel blue -- cool, observant
    "maggie": "\033[38;5;196m",  # Flame red -- volatile, fierce
    "priest": "\033[38;5;251m",  # Silver white -- calm, stoic
    "sable":  "\033[38;5;141m",  # Violet -- elegant, deadly
    "nines":  "\033[38;5;178m",  # Burnished gold -- street tough
}
C_REVERSE = "\033[7m"          # inverse video
C_REV_RED = "\033[7;31m"       # inverse video red


def colorize(text, rarity):
    """Wrap text in ANSI color for rarity. No-op for common."""
    code = RARITY_COLORS.get(rarity, "")
    if not code:
        return text
    return f"{code}{text}{C_RESET}"


def enemy_display_name(enemy):
    """Enemy name with tier-aware label and rarity color."""
    tier_prefix = {"normal": "", "elite": "Dealer ", "boss": "Pit Boss "}
    prefix = tier_prefix.get(enemy.tier, "")
    base = f"{prefix}{enemy.name}" if prefix else enemy.name
    if enemy.rarity == "common":
        return base
    label = f"{base} ({enemy.rarity.capitalize()})"
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


def p_val_str(cards):
    """Player hand total in bold green."""
    return f"{C_BGREEN}{hand_value(cards)}{C_RESET}"


def e_val_str(cards):
    """Enemy hand total in amber."""
    return f"{C_AMBER}{hand_value(cards)}{C_RESET}"


TIER_LABELS = {"normal": " [SHADE]", "elite": " [DEALER]", "boss": " [PIT BOSS]"}


def hp_color(current, maximum):
    """ANSI color code based on chip percentage: green/amber/red."""
    pct = max(0, current / maximum)
    if pct > 0.5:
        return C_GREEN
    elif pct > 0.25:
        return C_AMBER
    return C_RED


def progress_bar(current, maximum, width=20, color=None,
                  filled_char='█', empty_char='░'):
    pct = max(0.0, min(1.0, current / maximum)) if maximum > 0 else 0
    filled = int(width * pct)
    if color is None:
        color = C_GREEN
    return f"{color}{filled_char * filled}{C_RESET}{C_DIM}{empty_char * (width - filled)}{C_RESET}"


def hp_bar(current, maximum, width=20):
    return progress_bar(current, maximum, width, hp_color(current, maximum), '█', '░')


def xp_bar(xp, xp_max, width=12):
    return progress_bar(xp, xp_max, width, C_GREEN, '▮', '▯')


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
    sys.stdout.write(f"{msg} \033[5m\u25b8\033[0m ")
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
# Visual effects
# -----------------------------------------------------------------------

def typewrite(text, delay=0.025, end="\n"):
    """Print text character by character for dramatic moments."""
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write(end)
    sys.stdout.flush()


def flash_text(text, hold=0.08):
    """Flash text with a bright reverse-video pulse, then settle."""
    clean = _ANSI_RE.sub('', text)
    sys.stdout.write(f"\033[7;1m{clean}\033[0m")
    sys.stdout.flush()
    time.sleep(hold)
    sys.stdout.write(f"\r\033[2K{text}")
    sys.stdout.flush()
    time.sleep(0.02)
    print()


def shake_line(text, intensity=2, count=4, delay=0.04):
    """Shake text horizontally to simulate screen impact."""
    for _ in range(count):
        offset = random.randint(0, intensity)
        pad = " " * (2 + offset)
        sys.stdout.write(f"\r\033[2K{pad}{text}")
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write(f"\r\033[2K  {text}\n")
    sys.stdout.flush()


def erase_lines(n):
    """Move cursor up n lines, clearing each."""
    for _ in range(n):
        sys.stdout.write("\033[A\033[2K")
    sys.stdout.write("\r")
    sys.stdout.flush()


def animate_hp_change(old_hp, new_hp, max_hp, width=20, steps=8, delay=0.025):
    """Animate HP bar ticking down or up."""
    if old_hp == new_hp:
        bar = hp_bar(new_hp, max_hp, width)
        print(f"  {bar} {new_hp}/{max_hp}")
        return
    for i in range(1, steps + 1):
        t = i / steps
        current = int(old_hp + (new_hp - old_hp) * t)
        bar = hp_bar(current, max_hp, width)
        sys.stdout.write(f"\r\033[2K  {bar} {current}/{max_hp}")
        sys.stdout.flush()
        time.sleep(delay)
    print()


def static_burst(width=47, height=3, duration=0.15):
    """Brief burst of random characters simulating CRT static."""
    chars = "░▒▓█▄▀│─┤├╳·:;^~"
    steps = max(2, int(duration / 0.04))
    for step in range(steps):
        for _ in range(height):
            line = "".join(random.choice(chars) for _ in range(width))
            print(f"  {C_DIM}{line}{C_RESET}")
        sys.stdout.flush()
        time.sleep(0.04)
        erase_lines(height)


def crt_wipe(width=49, delay=0.005):
    """Horizontal CRT scanline wipe effect."""
    for i in range(width + 1):
        sys.stdout.write(f"\r  {C_GREEN}{'─' * i}{C_RESET}")
        sys.stdout.flush()
        time.sleep(delay)
    print()


# -----------------------------------------------------------------------
# Multi-line card art
# -----------------------------------------------------------------------

def card_art(card, hidden=False):
    """Return (top, mid, bot) strings for a single card."""
    if hidden:
        return (
            f"{C_DIM}┌───┐{C_RESET}",
            f"{C_DIM}│▓▓▓│{C_RESET}",
            f"{C_DIM}└───┘{C_RESET}",
        )
    sym = SUIT_SYM[card.suit]
    color = C_RED if card.suit in ("H", "D") else C_BWHITE
    rank = card.rank
    inner = f"{rank}{sym}" if len(rank) == 2 else f" {rank}{sym}"
    return (
        f"{C_DIM}┌───┐{C_RESET}",
        f"{C_DIM}│{C_RESET}{color}{inner}{C_RESET}{C_DIM}│{C_RESET}",
        f"{C_DIM}└───┘{C_RESET}",
    )


def hand_art_lines(cards, hidden_indices=None):
    """Return (top, mid, bot) combined for multiple cards side by side."""
    hidden = hidden_indices or set()
    arts = [card_art(c, hidden=(i in hidden)) for i, c in enumerate(cards)]
    top = " ".join(a[0] for a in arts)
    mid = " ".join(a[1] for a in arts)
    bot = " ".join(a[2] for a in arts)
    return top, mid, bot


def print_cards(label, cards, value_str=None, suffix="", hidden_indices=None):
    """Print 3-line card display with label aligned to middle row."""
    top, mid, bot = hand_art_lines(cards, hidden_indices)
    lw = plain_len(label)
    pad = " " * lw
    val_part = f"   = {value_str}" if value_str else ""
    suf_part = f"  {suffix}" if suffix else ""
    print(f"  {pad}{top}")
    print(f"  {label}{mid}{val_part}{suf_part}")
    print(f"  {pad}{bot}")


# -----------------------------------------------------------------------
# Ability descriptions shown to the player
# -----------------------------------------------------------------------
ABILITY_HINTS = {
    "reckless_extra": "Wild Card -- hits extra, might bust or crush you",
    "damage_absorption": "House Edge -- absorbs {v} damage per hand",
    "nine_lives_chance": "Last Breath -- may survive a killing blow",
    "rage_per_hand": "Tilt -- bonus damage grows each hand",
    "poison_per_hand": "Bleed -- {v} damage every hand, win or lose",
    "drain": "Siphon -- heals when it hurts you",
    "forced_extra_hits": "Rigged -- forces you to hit {v} extra time(s)",
    "crit_chance": "Sharp -- {v:.0%} chance to deal extra damage",
    "backstab_on_21": "Dead Hand -- guaranteed crit on 21",
    "silence_shades": "Shroud -- your Shades are silenced",
    "reap_shade_on_21": "Reaper -- claims a Shade when it hits 21",
}

SHADE_SIGNATURES = {
    "dutch": "7\u2663", "maggie": "J\u2660", "priest": "4\u2665",
    "sable": "A\u2666", "nines": "9\u2660",
}

SHADE_QUOTES = {
    "dutch": "I used to count cards for the Mob.",
    "maggie": "I burned down three casinos in my life.",
    "priest": "I prayed for luck. Luck never answered.",
    "sable": "The ace always finds its way home.",
    "nines": "Second chances are my specialty.",
}

SHADE_ABILITY_DESC = {
    "peek_enemy": ("Peek", "See the dealer's hole card", "Always active"),
    "damage_multiplier": ("Burn", "Multiply damage on wins", "Two black cards"),
    "damage_reduction_pct": ("Shield", "Reduce damage on losses", "Two red cards"),
    "natural_21_multiplier": ("Ace High", "Multiply natural 21 damage", "Natural blackjack"),
    "unbust_chance": ("Second Chance", "Chance to undo a bust", "On bust"),
}

SHADE_WHISPERS = {
    "dutch": {
        "proc": [
            "Dealer's hiding a {card}.",
            "I see what they've got.",
            "They can't bluff me.",
        ],
        "fight_start": [
            "I'll keep my eyes open.",
            "Let me watch the table.",
            "Already counting.",
        ],
        "win": [
            "Read 'em like a pamphlet.",
            "Knew that hand was ours.",
        ],
        "loss": [
            "Should've seen that coming.",
            "Bad read. Won't happen again.",
        ],
        "enemy_bust": [
            "Got greedy. They always do.",
        ],
        "low_hp": [
            "Careful. We're thin.",
            "Not much room left to play with.",
        ],
    },
    "maggie": {
        "proc": [
            "Watch it burn.",
            "That one's going to leave a mark.",
            "Nothing left but ashes.",
        ],
        "fight_start": [
            "Light it up.",
            "This one won't last.",
        ],
        "win": [
            "Scorched.",
            "They felt that.",
        ],
        "loss": [
            "We'll get 'em back double.",
            "That just makes me angrier.",
        ],
        "enemy_bust": [
            "Burned themselves out.",
            "Flame eats everything.",
        ],
        "low_hp": [
            "Not dead yet.",
            "Pain is fuel.",
        ],
    },
    "priest": {
        "proc": [
            "I'll take the hit.",
            "Stay behind me.",
            "Some prayers do get answered.",
        ],
        "fight_start": [
            "Stay steady.",
            "Keep your head.",
        ],
        "win": [
            "Patience wins.",
            "That's discipline talking.",
        ],
        "loss": [
            "Hold together.",
            "Endure. That's all we need to do.",
        ],
        "enemy_bust": [
            "No pity for the reckless.",
        ],
        "low_hp": [
            "I'll hold the line.",
            "Not our time.",
            "Stand firm.",
        ],
    },
    "sable": {
        "proc": [
            "The ace always finds its way home.",
            "Twenty-one. Clean.",
            "That's how it's done.",
        ],
        "fight_start": [
            "Let's make this quick.",
            "Watch for the opening.",
        ],
        "win": [
            "Elegant.",
            "Clean finish.",
        ],
        "loss": [
            "Won't miss next time.",
            "Sharpen up.",
        ],
        "enemy_bust": [
            "Sloppy play. Predictable.",
        ],
        "low_hp": [
            "Nine lives, remember?",
            "Almost out of tricks.",
        ],
    },
    "nines": {
        "proc": [
            "Not your time yet.",
            "Second chance. Don't waste it.",
            "I've pulled worse from the grave.",
        ],
        "fight_start": [
            "I got your back.",
            "Stay loose.",
        ],
        "win": [
            "That's how the street does it.",
            "Another one down.",
        ],
        "loss": [
            "Shake it off.",
            "We've been worse off.",
        ],
        "enemy_bust": [
            "Serves 'em right.",
            "Choked under pressure.",
        ],
        "low_hp": [
            "I've come back from worse.",
            "Just need one good hand.",
        ],
    },
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
        ("crit_chance", enemy.crit_chance),
        ("backstab_on_21", int(enemy.backstab_on_21)),
        ("silence_shades", int(enemy.silence_shades)),
        ("reap_shade_on_21", int(enemy.reap_shade_on_21)),
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


def format_effect_value(effect_type, value):
    """Format a companion's effect value for display."""
    if "multiplier" in effect_type:
        return f"x{value:.2f}"
    if "pct" in effect_type or "chance" in effect_type:
        return f"{value * 100:.0f}%"
    return ""


def format_hand_summary(result):
    """One-line dim summary of a resolved hand. Returns string or None."""
    if result is None or not isinstance(result, dict):
        return None
    action = result.get("action", "")
    if action == "split":
        return None
    p_val = result.get("p_val", 0)
    e_val = result.get("e_val", 0)
    dmg_dealt = result.get("dmg_dealt", 0)
    dmg_taken = result.get("dmg_taken", 0)
    won = result.get("won", False)
    lost = result.get("lost", False)
    enemy_busted = result.get("enemy_busted", False)

    if action == "folded":
        return f"{C_DIM}Folded. Lost {dmg_taken} chips.{C_RESET}"
    if action == "natural_push":
        return f"{C_DIM}Both natural 21. Push.{C_RESET}"
    if action == "natural":
        return f"{C_DIM}Natural 21! Took {dmg_dealt} chips from the dead.{C_RESET}"
    if action == "natural_loss":
        return f"{C_DIM}Spirit natural 21. Lost {dmg_taken} chips.{C_RESET}"
    if action == "busted":
        return f"{C_DIM}Busted ({p_val}), spirit had {e_val}. Lost {dmg_taken} chips.{C_RESET}"
    if won:
        if enemy_busted:
            return f"{C_DIM}Stood on {p_val}, spirit busted ({e_val}). Took {dmg_dealt} chips.{C_RESET}"
        return f"{C_DIM}Stood on {p_val} vs {e_val}. Took {dmg_dealt} chips.{C_RESET}"
    if lost:
        return f"{C_DIM}Stood on {p_val} vs {e_val}. Lost {dmg_taken} chips.{C_RESET}"
    # Push
    return f"{C_DIM}Push at {p_val}.{C_RESET}"


# -----------------------------------------------------------------------
# Game
# -----------------------------------------------------------------------
class Game:
    def __init__(self):
        self.config = GameConfig()
        self.deck = Deck()
        self.enemy_deck = Deck()
        self._last_capture_bonus = 0.0
        self._last_capture_bonus_reasons = []
        self._fight_num = 0
        self._silenced = False
        self._last_bust_prob = 0.0  # Bust probability when player last stood
        self._hex_bleed_counter = 0  # Cumulative hex bleed for current fight
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
        print(f"  {C_BWHITE}Goal:{C_RESET} Survive 3 acts. Each act has 5 séances")
        print(f"  and 2 branch points where you choose your path.")
        print(f"  Each séance is a series of blackjack hands.")
        print(f"  Get closer to 21 than the spirit to take their chips.")
        print(f"  Go over 21 and you bust (lose extra chips).")
        print(f"  Your deck is yours; the dead draw from their own.")
        print()
        print(f"  {C_BWHITE}Controls:{C_RESET}")
        print(f"    {C_GREEN}\u2192{C_RESET} Hit (draw a card)")
        print(f"    {C_GREEN}\u2190{C_RESET} Stand (keep your hand)")
        print(f"    \u2193 Fold (take {self.config.damage.fold_damage} dmg, costs 1 fold)")
        print(f"    \u2191 Info panel (spirit, your Shades, deck)")
        print(f"    r Rules (this screen)")
        print(f"    s Split (pairs only, plays two hands)")
        print()
        print(f"  {C_BWHITE}Split:{C_RESET} When dealt a pair, press s to split into")
        print(f"  two hands. Each gets a new second card and plays")
        print(f"  separately. Both resolve against the spirit's single")
        print(f"  hand. Lose both and you take damage twice.")
        print()
        print(f"  {C_BWHITE}Folds:{C_RESET} Limited resource. Start with {self.config.fold.starting_folds}.")
        print(f"  Folding costs 1 fold and {self.config.damage.fold_damage} chips.")
        print(f"  Better than losing (3-7 chips), but you give up")
        print(f"  the chance to win. Earn +{self.config.fold.fold_reward_amount} folds as a reward after wins.")
        print(f"  {C_AMBER}Final Wager:{C_RESET} If chips hit 0 and you have 3+ shades,")
        print(f"  all shades are sacrificed to survive at 1 chip (once per run).")
        print()
        print(f"  {C_BWHITE}Rewards{C_RESET} (after each win, pick one):")
        print(f"    Remove a card (thin your deck, raise avg hand)")
        print(f"    Enchant a card (fury/siphon/ward/echo/gambit/hex)")
        print(f"    Heal chips")
        print(f"    Gain {self.config.fold.fold_reward_amount} folds")
        print(f"    Recruit a Shade (normal Shades only)")
        print()
        print(f"  {C_BWHITE}The Path:{C_RESET} Between fights, the road forks.")
        print(f"    {C_GREEN}Barrow{C_RESET}     Bury a card or exhume a grave card")
        print(f"    {C_AMBER}Vigil{C_RESET}      Rest (heal), commune (shade XP), or")
        print(f"               burn offering (HP for folds)")
        print(f"    {C_PHANTOM}Crossroads{C_RESET} Random event: gamble, scout, or wager")
        print()
        print(f"  {C_BWHITE}Shades:{C_RESET} Spirits of the dead, bound to serve you.")
        print(f"  Some require specific cards in hand to activate.")
        print(f"  Gain XP each séance and level up (max Lv5).")
        print()
        print(f"  {C_BWHITE}Enchantments:{C_RESET}")
        print(f"    {C_RED}Fury{C_RESET}     +{self.config.enchantment.fury_damage} bonus damage on wins")
        print(f"    {C_GREEN}Siphon{C_RESET}   Heal {self.config.enchantment.siphon_heal} per enchanted card in hand")
        print(f"    {C_AMBER}Ward{C_RESET}     -{self.config.enchantment.ward_reduction} damage on losses")
        print(f"    {C_GREEN}Echo{C_RESET}     Duplicates other enchantments on same card")
        print(f"    {C_GREEN}Gambit{C_RESET}   +dmg that scales with bust risk when you stand")
        print(f"    {C_RED}Hex{C_RESET}      +{self.config.enchantment.hex_bleed_per_play} bleed/round, stacks all fight")
        print(f"  Stacks diminish: +{self.config.enchantment.diminishing:.0%} per extra copy.")
        print()
        print(f"  {C_BWHITE}Shade abilities:{C_RESET}")
        print(f"    Wild Card: hits extra times (volatile)")
        print(f"    House Edge: absorbs damage each hand")
        print(f"    Last Breath: may survive a killing blow once")
        print(f"    Tilt: bonus damage grows each hand")
        print(f"    Bleed: flat damage every hand, win or lose")
        print(f"    Siphon: heals when it hurts you")
        print(f"    Rigged: forces you to hit extra")
        print(f"    Sharp: chance to deal {self.config.damage.crit_multiplier:.1f}x damage")
        print(f"    Dead Hand: guaranteed crit when hand is exactly 21")
        print(f"    Shroud: silences your Shades (no companion effects)")
        print(f"    Reaper: claims one of your Shades when it hits 21")
        print()
        pause()

    # --- Shade whisper ---

    def _whisper(self, shade_key, category="proc", **kwargs):
        """Show a random Shade whisper line in the shade's color."""
        shade_data = SHADE_WHISPERS.get(shade_key)
        if not shade_data:
            return
        lines = shade_data.get(category, shade_data.get("proc", []))
        if not lines:
            return
        name = COMPANION_TEMPLATES.get(shade_key, {}).get("name", shade_key)
        color = SHADE_COLORS.get(shade_key, C_PHANTOM)
        line = random.choice(lines)
        try:
            line = line.format(**kwargs)
        except (KeyError, IndexError):
            pass
        typewrite(f"  {color}\"{line}\" -- {name}{C_RESET}", delay=0.02)

    def _shade_proc(self, shade_name, effect, detail=""):
        """High-visibility callout when a Shade effect actually triggers."""
        shade_key = shade_name.lower()
        color = SHADE_COLORS.get(shade_key, C_BGREEN)
        print(f"  {color}\u25c6 {shade_name}{C_RESET} -- {effect}")
        if detail:
            print(f"  {color}    {detail}{C_RESET}")

    def _shade_chatter(self, category, chance=0.35):
        """Maybe show an ambient line from a random active companion."""
        if self._silenced:
            return
        companions = self.player.companions
        if not companions:
            return
        if random.random() > chance:
            return
        c = random.choice(companions)
        self._whisper(c.companion_type, category=category)

    @staticmethod
    def _capture_bonus_from_flags(hand_count, had_natural, had_bust, had_fold, high_total_finish):
        """Return (bonus, reasons) for skill-based capture chance."""
        bonus = 0.0
        reasons = []
        if hand_count <= 3:
            bonus += 0.04
            reasons.append("quick finish +4%")
        if had_natural:
            bonus += 0.05
            reasons.append("natural 21 +5%")
        if not had_bust and not had_fold:
            bonus += 0.06
            reasons.append("clean fight +6%")
        if high_total_finish:
            bonus += 0.03
            reasons.append("high-total finish +3%")
        return min(0.18, bonus), reasons

    # --- Enchantment helpers ---

    def _count_enchantments(self, cards):
        """Count enchantment types across cards in hand, with echo duplication."""
        counts = {"fury": 0, "siphon": 0, "ward": 0, "echo": 0, "gambit": 0, "hex": 0}
        for card in cards:
            for ench in self.deck.get_enchantments(card):
                if ench in counts:
                    counts[ench] += 1
        # Echo: each echo duplicates other enchantments on the same card
        if counts["echo"] > 0:
            for card in cards:
                card_enchs = self.deck.get_enchantments(card)
                card_echoes = card_enchs.count("echo")
                if card_echoes > 0:
                    for ench in card_enchs:
                        if ench != "echo" and ench in counts:
                            counts[ench] += card_echoes
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
        """Apply siphon heal and hex bleed stacking from enchanted cards in hand."""
        ench = self._count_enchantments(player_cards)
        if ench["echo"] > 0:
            print(f"  {C_GREEN}Echo x{ench['echo']}: duplicating enchantments{C_RESET}")
        if ench["siphon"] > 0:
            heal = int(self._ench_total(self.config.enchantment.siphon_heal, ench["siphon"]))
            self.player.heal(heal)
            print(f"  {C_GREEN}Siphon x{ench['siphon']}: heal {heal}!{C_RESET} ({self.player.hp}/{self.player.max_hp})")
        if ench["hex"] > 0:
            added = ench["hex"] * self.config.enchantment.hex_bleed_per_play
            self._hex_bleed_counter += added
            print(f"  {C_RED}Hex x{ench['hex']}: +{added} bleed (total: {self._hex_bleed_counter}){C_RESET}")

    def base_damage(self, winner_val, loser_val):
        cfg = self.config.damage
        if cfg.model == "differential":
            return max(winner_val - loser_val, cfg.damage_floor)
        return max(winner_val - cfg.damage_subtract, 1)

    # --- Decision HUD helpers ---

    def _estimate_damage(self, p_val, player_cards, enemy):
        """Approximate win/loss damage for the HUD preview. Returns (est_win, est_loss)."""
        cfg = self.config.damage
        e_est = enemy.hit_threshold  # best available estimate of enemy final value

        # Win estimate
        if cfg.model == "differential":
            win_base = float(max(p_val - e_est, cfg.damage_floor))
        else:
            win_base = float(max(p_val - cfg.damage_subtract, 1))
        win_dmg = win_base
        imp_mult = None if self._silenced else self.player.get_companion_effect("damage_multiplier", player_cards)
        if imp_mult:
            win_dmg *= imp_mult
        # Shell absorption
        if enemy.damage_absorption > 0:
            win_dmg = max(0, win_dmg - enemy.damage_absorption)

        # Loss estimate
        if cfg.model == "differential":
            loss_base = float(max(e_est - p_val, cfg.damage_floor))
        else:
            loss_base = float(max(e_est - cfg.damage_subtract, 1))
        loss_dmg = loss_base
        reduction_pct = None if self._silenced else self.player.get_companion_effect("damage_reduction_pct", player_cards)
        if reduction_pct:
            loss_dmg = max(0, loss_dmg - loss_dmg * reduction_pct)
        if enemy.bonus_damage > 0:
            loss_dmg += enemy.bonus_damage

        return int(win_dmg), int(loss_dmg)

    def _companion_status_brief(self, player_cards):
        """Brief companion activation status for card-composition companions only."""
        parts = []
        for c in self.player.companions:
            if c.activation not in ("two_red", "two_black"):
                continue
            active = check_activation(player_cards, c.activation)
            hint = colorize_hint(c.activation)
            if active:
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                parts.append(f"{hint} {shade_c}\u2713 {c.name}{C_RESET}")
            else:
                raw_hint = activation_hint(c.activation)
                parts.append(f"{C_DIM}{raw_hint} {c.name}{C_RESET}")
        return "  ".join(parts)

    def _enemy_threat_brief(self, enemy):
        """Compact enemy threat string for the HUD."""
        parts = [f"{enemy.hp}/{enemy.max_hp} Chips"]
        if enemy.bonus_damage > 0:
            if enemy.rage_per_hand:
                parts.append(f"tilt +{enemy.bonus_damage}")
            else:
                parts.append(f"+{enemy.bonus_damage} dmg")
        if enemy.poison_per_hand:
            parts.append(f"bleed {enemy.poison_per_hand}/hand")
        if enemy.drain:
            parts.append("siphon")
        if enemy.damage_absorption:
            parts.append(f"edge {enemy.damage_absorption}")
        if enemy.reckless_extra:
            parts.append(f"wild {enemy.reckless_extra}")
        if enemy.forced_extra_hits:
            parts.append(f"rigged {enemy.forced_extra_hits}")
        if enemy.crit_chance > 0:
            parts.append(f"sharp {enemy.crit_chance:.0%}")
        if enemy.backstab_on_21:
            parts.append("dead hand")
        if enemy.silence_shades:
            parts.append("shroud")
        if enemy.reap_shade_on_21:
            parts.append("reaper")
        return "  ".join(parts)

    def _recruit_block_reason(self, enemy):
        """Return why this enemy is not currently recruitable, else None."""
        if enemy.tier != "normal":
            return "Dealers and Pit Bosses cannot be bound"
        if not enemy.companion_type:
            return "No recruitable Shade data"
        if enemy.companion_type not in COMPANION_TEMPLATES:
            return "Missing recruit template"
        return None

    def _print_decision_hud(self, p_val, player_cards, enemy, bust_pct, deck_ct):
        """Print 2-line decision HUD with damage estimates, risk, enemy threat, companions."""
        est_win, est_loss = self._estimate_damage(p_val, player_cards, enemy)

        # Bust color
        if bust_pct > 70:
            bust_color = C_RED
        elif bust_pct >= 20:
            bust_color = C_AMBER
        else:
            bust_color = C_GREEN

        line1 = f"  Win ~{est_win}  Lose ~{est_loss}   {bust_color}bust: {bust_pct:.0f}%{C_RESET}  deck: {deck_ct}"
        print(line1)

        threat = self._enemy_threat_brief(enemy)
        companion = self._companion_status_brief(player_cards)
        line2_parts = [f"  {C_DIM}{threat}{C_RESET}"]
        if companion:
            line2_parts.append(f"    {companion}")
        print("".join(line2_parts))
        if hasattr(self, '_current_act_map') and hasattr(self, '_current_node'):
            print(f"  {self._journey_map(self._current_act_map, self._current_node)}")

    # --- Encounter generation ---

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
        capture_roll = 1.0
        capture_power_mult = 1.0
        deck_removed = enemy_deck_removed_ranks(rarity)
        deck_quality = enemy_deck_quality_label(rarity)
        deck_size = 52 - len(deck_removed)
        if t.get("companion_type"):
            capture_roll = capture_roll_for_rarity(self.config, rarity)
            capture_power_mult = companion_power_multiplier_for_rarity(
                self.config, rarity, capture_roll
            )
            diff_mult = 1.0 + max(0.0, capture_roll - 1.0) * 0.45
            scaled_hp = max(1, int(scaled_hp * diff_mult))
            if capture_roll >= 1.12:
                threshold = min(19, threshold + 1)

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
            crit_chance=t.get("crit_chance", 0.0),
            backstab_on_21=t.get("backstab_on_21", False),
            capture_roll=capture_roll,
            capture_power_mult=capture_power_mult,
            deck_quality=deck_quality,
            deck_removed_ranks=deck_removed,
            deck_size=deck_size,
        )

    # --- Display helpers ---

    def show_status(self):
        bar = hp_bar(self.player.hp, self.player.max_hp)
        reserve_count = len(self.player.reserve_companions)
        print(
            f"  You  {bar} {self.player.hp}/{self.player.max_hp}     "
            f"Folds: {self.player.folds}  Shades: {len(self.player.companions)}/{self.player.max_companion_slots} (+{reserve_count} reserve)"
        )
        if self.player.companions:
            for c in self.player.companions:
                hint_c = colorize_hint(c.activation)
                suffix = f" [{hint_c}]" if hint_c else ""
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                print(f"  {shade_c}{c.name}{C_RESET} Lv{c.level}{suffix}")

    def _maybe_final_wager(self):
        """Trigger Final Wager on lethal HP if requirements are met."""
        if self.player.hp > 0 or not self.player.can_final_wager():
            return False
        sacrificed = self.player.total_companions()
        self.player.trigger_final_wager()
        print()
        flash_text(f"{C_BRED}  FINAL WAGER!{C_RESET}")
        typewrite(
            f"  {C_AMBER}You burn {sacrificed} shades to stay in the game.{C_RESET}",
            delay=0.025,
        )
        typewrite(f"  {C_GREEN}HP restored to 1.{C_RESET}", delay=0.02)
        return True

    # --- Damage application ---

    def hurt_enemy(self, enemy, raw_dmg, show=True):
        if enemy.damage_absorption > 0 and raw_dmg > 0:
            absorbed = min(raw_dmg, enemy.damage_absorption)
            raw_dmg = max(0, raw_dmg - enemy.damage_absorption)
            if show:
                print(f"  {C_AMBER}-{absorbed:.0f} house edge -> {raw_dmg:.0f}{C_RESET}")
        actual = int(raw_dmg)
        old_hp = enemy.hp
        enemy.hp = max(0, enemy.hp - actual)
        if show:
            print(f"  {C_GREEN}>> {actual} to {enemy_display_name(enemy)}{C_RESET}")
            animate_hp_change(old_hp, enemy.hp, enemy.max_hp, width=10)

    def hurt_player(self, dmg, show=True):
        actual = int(dmg)
        old_hp = self.player.hp
        self.player.take_damage(actual)
        used_wager = self._maybe_final_wager()
        if show:
            text = f"{C_RED}<< Take {actual}{C_RESET}"
            if actual >= 8:
                shake_line(text, intensity=3, count=4)
            else:
                print(f"  {text}")
            animate_hp_change(old_hp, self.player.hp, self.player.max_hp)
            if used_wager:
                print(f"  {C_DIM}All shades sacrificed. No second wager this run.{C_RESET}")

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
            abilities.append(f"  Wild Card: hits {enemy.reckless_extra} extra")
        if enemy.damage_absorption:
            abilities.append(f"  House Edge: absorbs {enemy.damage_absorption} dmg/hand")
        if enemy.nine_lives_chance > 0:
            abilities.append(f"  Last Breath: {enemy.nine_lives_chance:.0%} survive death")
        elif getattr(enemy, '_nine_lives_spent', False):
            abilities.append(f"  Last Breath: spent")
        if enemy.rage_per_hand:
            abilities.append(f"  Tilt: +{enemy.rage_per_hand}/hand (now +{enemy.bonus_damage})")
        if enemy.poison_per_hand:
            abilities.append(f"  Bleed: {enemy.poison_per_hand} dmg/hand")
        if enemy.drain:
            abilities.append(f"  Siphon: heals on hit")
        if enemy.forced_extra_hits:
            abilities.append(f"  Rigged: forces {enemy.forced_extra_hits} extra hit(s)")
        if enemy.crit_chance > 0:
            abilities.append(f"  Sharp: {enemy.crit_chance:.0%} chance for {enemy.crit_multiplier:.1f}x damage")
        if enemy.backstab_on_21:
            abilities.append(f"  Dead Hand: guaranteed crit on 21")
        if enemy.silence_shades:
            abilities.append(f"  Shroud: your Shades are silenced")
        if enemy.reap_shade_on_21:
            abilities.append(f"  Reaper: claims one of your Shades on 21")
        if enemy.bonus_damage and not enemy.rage_per_hand:
            abilities.append(f"  Bonus damage: +{enemy.bonus_damage}")

        if abilities:
            add("")
            for a in abilities:
                add(f"{C_AMBER}{a}{C_RESET}")
        else:
            add("")
            add(f"  {C_DIM}No special abilities.{C_RESET}")

        # Spirit deck intel
        removed = list(enemy.deck_removed_ranks or [])
        add("")
        add(
            f"  {C_BWHITE}Spirit Deck:{C_RESET} {enemy.deck_size} cards  "
            f"{C_DIM}({enemy.deck_quality}){C_RESET}"
        )
        if removed:
            counts = Counter(removed)
            detail = ", ".join(f"{r}x{n}" for r, n in sorted(counts.items(), key=lambda kv: RANKS.index(kv[0])))
            add(f"  {C_DIM}Trimmed ranks: {detail}{C_RESET}")
        else:
            add(f"  {C_DIM}No trims (full house stock deck).{C_RESET}")

        # --- Companions section ---
        divider()
        if self.player.companions:
            reserve_count = len(self.player.reserve_companions)
            add(
                f"  {C_BWHITE}SHADES{C_RESET} "
                f"{C_DIM}(active {len(self.player.companions)}/{self.player.max_companion_slots}, reserve {reserve_count}){C_RESET}"
            )

            for c in self.player.companions:
                effect_label = describe_companion_effect(c.effect_type, short=True)

                val_str = format_effect_value(c.effect_type, c.effect_value)

                # Check activation against current hand
                if c.activation in ("two_red", "two_black"):
                    active = check_activation(player_cards, c.activation)
                else:
                    active = None  # contextual, not card-composition

                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                line = f"  {shade_c}{c.name}{C_RESET} Lv{c.level}"
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
            if self.player.reserve_companions:
                shown = ", ".join(c.name for c in self.player.reserve_companions[:4])
                extra = len(self.player.reserve_companions) - 4
                if extra > 0:
                    shown += f", +{extra} more"
                add(f"  {C_DIM}Reserve: {shown}{C_RESET}")
        else:
            slots = self.player.max_companion_slots
            reserve_count = len(self.player.reserve_companions)
            add(f"  {C_DIM}No active Shades (0/{slots}), reserve {reserve_count}{C_RESET}")

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
            ench_counts = {"fury": 0, "siphon": 0, "ward": 0, "echo": 0, "gambit": 0, "hex": 0}
            for _card, enchs in ench_summary:
                for e in enchs:
                    if e in ench_counts:
                        ench_counts[e] += 1
            parts = [f"{ct}\u00d7 {n.capitalize()}" for n, ct in ench_counts.items() if ct > 0]
            if parts:
                add(f"  {C_GREEN}Enchanted: {', '.join(parts)}{C_RESET}")

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
        enemy_cards = [self.enemy_deck.draw(), self.enemy_deck.draw()]
        has_peek = (not self._silenced and
                    self.player.get_companion_effect("peek_enemy", player_cards) is not None)

        hand_label = f"── Hand {hand_num} "
        print(f"\n  {C_DIM}{hand_label}{'─' * (45 - len(hand_label))}{C_RESET}")

        # --- Naturals ---
        p_nat = is_natural_21(player_cards)
        e_nat = is_natural_21(enemy_cards)

        if p_nat or e_nat:
            print_cards("You    ", player_cards, p_val_str(player_cards))
            beat(0.15)
            print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards))
            beat(0.5)
            if p_nat and e_nat:
                print(f"  {C_AMBER}Both natural 21! Push.{C_RESET}")
                self._apply_siphon(player_cards)
                return {"action": "natural_push", "p_val": 21, "e_val": 21,
                        "won": False, "lost": False, "dmg_dealt": 0, "dmg_taken": 0,
                        "enemy_busted": False}
            if p_nat:
                flash_text(f"  {C_BGREEN}NATURAL 21!{C_RESET}")
                beat(0.5)
                ehp_b = enemy.hp
                dmg = self._calc_win_damage(21, hand_value(enemy_cards), is_natural=True, player_cards=player_cards)
                self.hurt_enemy(enemy, dmg)
                self._apply_siphon(player_cards)
                return {"action": "natural", "p_val": 21, "e_val": hand_value(enemy_cards),
                        "won": True, "lost": False, "dmg_dealt": max(0, ehp_b - enemy.hp),
                        "dmg_taken": 0, "enemy_busted": False}
            typewrite(f"  {C_BRED}Spirit natural 21!{C_RESET}", delay=0.03)
            beat(0.4)
            self._try_reap_shade(enemy, 21)
            php_b = self.player.hp
            dmg = self._calc_loss_damage(21, hand_value(player_cards), enemy, is_natural=True,
                                         player_cards=player_cards)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            self._apply_siphon(player_cards)
            return {"action": "natural_loss", "p_val": hand_value(player_cards), "e_val": 21,
                    "won": False, "lost": True, "dmg_dealt": 0,
                    "dmg_taken": max(0, php_b - self.player.hp), "enemy_busted": False}

        # --- Show starting hands (animated deal) ---
        # Deal player cards: show first, beat, then reveal both
        print_cards("You    ", [player_cards[0]], p_val_str([player_cards[0]]))
        beat(0.15)
        erase_lines(3)
        print_cards("You    ", player_cards, p_val_str(player_cards))
        beat(0.12)
        threshold_str = f"stands at {enemy.hit_threshold}"
        if has_peek:
            hole_card = enemy_cards[1]
            hole_str = f"{hole_card.rank}{SUIT_SYM[hole_card.suit]}"
            print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards),
                        suffix=f"{SHADE_COLORS['dutch']}[Dutch]{C_RESET}")
            self._shade_proc("Dutch", "Peek", f"Hole card: {hole_str}")
            self._whisper("dutch", card=hole_str)
        else:
            print_cards("Dead   ", enemy_cards, hidden_indices={1},
                        suffix=f"{C_DIM}{threshold_str}{C_RESET}")

        # --- Split detection ---
        can_split = (len(player_cards) == 2
                     and player_cards[0].rank == player_cards[1].rank)

        hit_from_split_prompt = False
        split_need_reprint = False
        while can_split:
            # Offer split as first-decision option
            bust_pct = self.deck.bust_probability(player_cards) * 100
            deck_ct = len(self.deck.cards)

            arrow_labels = {"right": "HIT", "left": "STAND", "down": "FOLD", "up": "INFO", "r": "RULES", "s": "SPLIT"}

            if split_need_reprint:
                print()
                print_cards("You    ", player_cards, p_val_str(player_cards))
                threshold_str = f"stands at {enemy.hit_threshold}"
                if has_peek:
                    print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards),
                                suffix=f"{SHADE_COLORS['dutch']}[Dutch]{C_RESET}")
                else:
                    print_cards("Dead   ", enemy_cards, hidden_indices={1},
                                suffix=f"{C_DIM}{threshold_str}{C_RESET}")
            split_need_reprint = True

            p_val = hand_value(player_cards)
            print()
            self._print_decision_hud(p_val, player_cards, enemy, bust_pct, deck_ct)

            has_folds = self.player.folds > 0

            print(f"\n  \u2192 Hit   \u2190 Stand")
            valid_keys = ["right", "left", "up", "r", "s"]
            if has_folds:
                fold_str = f"\u2193 Fold ({self.player.folds})"
                valid_keys.append("down")
                choice = prompt_choice(
                    f"{fold_str}  \u2191 Info  r Rules  s Split",
                    valid_keys,
                    arrow_labels,
                )
            else:
                choice = prompt_choice(
                    f"{C_DIM}\u2193 Fold (0){C_RESET}  \u2191 Info  r Rules  s Split",
                    valid_keys,
                    arrow_labels,
                )

            if choice == "up":
                self.inspect_panel(enemy, player_cards)
                continue
            elif choice == "r":
                self.show_rules()
                continue
            elif choice == "down":
                self.player.folds -= 1
                fold_dmg = self.config.damage.fold_damage
                print(f"  Folded. Take {fold_dmg} chip damage. ({self.player.folds} folds left)")
                self.hurt_player(fold_dmg)
                return {"action": "folded", "p_val": hand_value(player_cards),
                        "e_val": hand_value(enemy_cards), "won": False, "lost": True,
                        "dmg_dealt": 0, "dmg_taken": fold_dmg, "enemy_busted": False}
            elif choice == "s":
                # --- Split flow ---
                card_a, card_b = player_cards
                hand_a = [card_a, self.deck.draw()]
                hand_b = [card_b, self.deck.draw()]

                print(f"\n  {C_AMBER}Split!{C_RESET}")
                beat(0.3)

                # Hand 1a
                label_a = f"\u2500\u2500 Hand {hand_num}a \u2500\u2500"
                print(f"\n  {C_DIM}{label_a}{C_RESET}")
                print_cards("You    ", hand_a, p_val_str(hand_a))
                threshold_str = f"stands at {enemy.hit_threshold}"
                if has_peek:
                    print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards),
                                suffix=f"{SHADE_COLORS['dutch']}[Dutch]{C_RESET}")
                else:
                    print_cards("Dead   ", enemy_cards, hidden_indices={1},
                                suffix=f"{C_DIM}{threshold_str}{C_RESET}")

                hand_a, busted_a, _ = self._player_turn(
                    hand_a, enemy, enemy_cards, has_peek,
                    allow_fold=False, label=f"\u2500\u2500 Hand {hand_num}a \u2500\u2500")

                # Hand 1b
                label_b = f"\u2500\u2500 Hand {hand_num}b \u2500\u2500"
                print(f"\n  {C_DIM}{label_b}{C_RESET}")
                print_cards("You    ", hand_b, p_val_str(hand_b))
                if has_peek:
                    print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards),
                                suffix=f"{SHADE_COLORS['dutch']}[Dutch]{C_RESET}")
                else:
                    print_cards("Dead   ", enemy_cards, hidden_indices={1},
                                suffix=f"{C_DIM}{threshold_str}{C_RESET}")

                hand_b, busted_b, _ = self._player_turn(
                    hand_b, enemy, enemy_cards, has_peek,
                    allow_fold=False, label=f"\u2500\u2500 Hand {hand_num}b \u2500\u2500")

                # Enemy turn (once) -- aware enemies target the best non-busted hand
                best_p = max(
                    (hand_value(h) for h, b in [(hand_a, busted_a), (hand_b, busted_b)] if not b),
                    default=0)
                enemy_cards, enemy_busted, e_val = self._enemy_turn(enemy, enemy_cards, p_val=best_p)
                self._try_reap_shade(enemy, e_val)

                # Resolve each hand
                print()
                p_val_a = hand_value(hand_a)
                p_val_b = hand_value(hand_b)

                won_a, lost_a = self._resolve_hand(
                    p_val_a, e_val, busted_a, enemy_busted, hand_a, enemy,
                    label=f"Hand {hand_num}a:")
                self._apply_siphon(hand_a)

                won_b, lost_b = self._resolve_hand(
                    p_val_b, e_val, busted_b, enemy_busted, hand_b, enemy,
                    label=f"Hand {hand_num}b:")
                self._apply_siphon(hand_b)

                # Callouts for each hand
                for tag, cards, won, lost, busted, p_v in [
                    (f"Hand {hand_num}a", hand_a, won_a, lost_a, busted_a, p_val_a),
                    (f"Hand {hand_num}b", hand_b, won_b, lost_b, busted_b, p_val_b),
                ]:
                    if p_v == 22 and busted:
                        beat(0.3)
                        print(f"  {C_DIM}{tag}: Just one over...{C_RESET}")
                    if len(cards) >= 5 and not busted:
                        beat(0.2)
                        print(f"  {C_BWHITE}{tag}: Five cards!{C_RESET}")
                    if won and not enemy_busted and p_v - e_val == 1:
                        beat(0.3)
                        print(f"  {C_GREEN}{tag}: By a hair!{C_RESET}")
                    if lost and not busted and e_val - p_v == 1:
                        beat(0.3)
                        print(f"  {C_RED}{tag}: So close...{C_RESET}")
                if (won_a or won_b) and self.player.hp <= self.player.max_hp * 0.2:
                    beat(0.4)
                    typewrite(f"  {C_BGREEN}Clutch!{C_RESET}", delay=0.05)
                return {"action": "split", "p_val": 0, "e_val": e_val,
                        "won": won_a or won_b, "lost": lost_a or lost_b,
                        "dmg_dealt": 0, "dmg_taken": 0, "enemy_busted": enemy_busted}
            else:
                # Hit or stand chosen on the split prompt -- fall through to normal play
                # Put the choice back by handling it inline
                if choice == "left":
                    self._last_bust_prob = bust_pct / 100.0
                    print(f"  Stand at {C_BGREEN}{hand_value(player_cards)}{C_RESET}.")
                    # Skip player turn, go straight to enemy
                    player_busted = False
                    p_val = hand_value(player_cards)

                    ehp_before = enemy.hp
                    php_before = self.player.hp
                    enemy_cards, enemy_busted, e_val = self._enemy_turn(enemy, enemy_cards, p_val=p_val)
                    self._try_reap_shade(enemy, e_val)
                    print()
                    beat(0.3)
                    won, lost = self._resolve_hand(p_val, e_val, False, enemy_busted, player_cards, enemy)
                    self._apply_siphon(player_cards)
                    self._hand_callouts(player_cards, won, lost, False, p_val, e_val, enemy_busted)
                    return {"action": "stood", "p_val": p_val, "e_val": e_val,
                            "won": won, "lost": lost,
                            "dmg_dealt": max(0, ehp_before - enemy.hp),
                            "dmg_taken": max(0, php_before - self.player.hp),
                            "enemy_busted": enemy_busted}
                elif choice == "right":
                    card = self.deck.draw()
                    player_cards.append(card)
                    print(f"  Drew {show_card(card)}  = {p_val_str(player_cards)}")
                    hit_from_split_prompt = True
                    break

        # --- Normal (non-split) flow ---
        player_cards, player_busted, folded = self._player_turn(
            player_cards, enemy, enemy_cards, has_peek,
            allow_fold=(not hit_from_split_prompt),
            first_decision_consumed=hit_from_split_prompt,
        )
        if folded:
            fold_dmg = self.config.damage.fold_damage
            return {"action": "folded", "p_val": hand_value(player_cards),
                    "e_val": hand_value(enemy_cards), "won": False, "lost": True,
                    "dmg_dealt": 0, "dmg_taken": fold_dmg, "enemy_busted": False}

        p_val = hand_value(player_cards)

        # Player busted: reveal enemy and resolve
        if player_busted:
            beat(0.5)
            e_val = hand_value(enemy_cards)
            print_cards("Dead   ", enemy_cards, f"{C_AMBER}{e_val}{C_RESET}")
            beat(0.3)
            ehp_before = enemy.hp
            php_before = self.player.hp
            won, lost = self._resolve_hand(p_val, e_val, True, False, player_cards, enemy)
            self._apply_siphon(player_cards)
            self._hand_callouts(player_cards, won, lost, True, p_val, e_val, False)
            return {"action": "busted", "p_val": p_val, "e_val": e_val,
                    "won": won, "lost": lost,
                    "dmg_dealt": max(0, ehp_before - enemy.hp),
                    "dmg_taken": max(0, php_before - self.player.hp),
                    "enemy_busted": False}

        # Enemy turn
        ehp_before = enemy.hp
        php_before = self.player.hp
        enemy_cards, enemy_busted, e_val = self._enemy_turn(enemy, enemy_cards, p_val=p_val)
        self._try_reap_shade(enemy, e_val)

        # Resolve
        print()
        beat(0.3)
        won, lost = self._resolve_hand(p_val, e_val, False, enemy_busted, player_cards, enemy)
        self._apply_siphon(player_cards)

        # Highlight callouts
        self._hand_callouts(player_cards, won, lost, player_busted, p_val, e_val, enemy_busted)

        return {"action": "stood", "p_val": p_val, "e_val": e_val,
                "won": won, "lost": lost,
                "dmg_dealt": max(0, ehp_before - enemy.hp),
                "dmg_taken": max(0, php_before - self.player.hp),
                "enemy_busted": enemy_busted}

    def _hand_callouts(self, player_cards, won, lost, player_busted, p_val, e_val, enemy_busted):
        """Show flavor text after a hand resolves."""
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
            typewrite(f"  {C_BGREEN}Clutch!{C_RESET}", delay=0.05)

    def _player_turn(self, player_cards, enemy, enemy_cards, has_peek, allow_fold=True, label=None, first_decision_consumed=False):
        """Run player hit/stand loop. Returns (cards, busted, folded)."""
        first_decision = not first_decision_consumed
        need_reprint = first_decision_consumed
        forced = enemy.forced_extra_hits
        player_busted = False

        while True:
            p_val = hand_value(player_cards)

            if p_val > 21:
                unbust = None if self._silenced else self.player.get_companion_effect("unbust_chance", player_cards)
                if unbust and random.random() < unbust:
                    removed = player_cards.pop()
                    self._shade_proc("Nines", "Second Chance", f"Tossed {show_card(removed)} to prevent bust")
                    self._whisper("nines")
                    print_cards("You    ", player_cards, p_val_str(player_cards))
                    continue
                player_busted = True
                beat(0.4)
                flash_text(f"  {C_BRED}BUST! ({p_val}){C_RESET}")
                break

            if p_val == 21:
                print(f"  {C_GREEN}21!{C_RESET}")
                break

            if forced > 0:
                print(f"  {C_AMBER}Rigged! Forced to hit!{C_RESET}")
                forced -= 1
                card = self.deck.draw()
                player_cards.append(card)
                print(f"  Drew {show_card(card)}  = {p_val_str(player_cards)}")
                need_reprint = True
                first_decision = False
                continue

            bust_pct = self.deck.bust_probability(player_cards) * 100
            deck_ct = len(self.deck.cards)

            arrow_labels = {"right": "HIT", "left": "STAND", "down": "FOLD", "up": "INFO", "r": "RULES"}

            # Reprint hands so they're always visible at the prompt
            if need_reprint:
                print()
                if label:
                    print(f"  {C_DIM}{label}{C_RESET}")
                print_cards("You    ", player_cards, f"{C_BGREEN}{p_val}{C_RESET}")
                threshold_str = f"stands at {enemy.hit_threshold}"
                if has_peek:
                    print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards),
                                suffix=f"{SHADE_COLORS['dutch']}[Dutch]{C_RESET}")
                else:
                    print_cards("Dead   ", enemy_cards, hidden_indices={1},
                                suffix=f"{C_DIM}{threshold_str}{C_RESET}")
            need_reprint = True

            print()
            self._print_decision_hud(p_val, player_cards, enemy, bust_pct, deck_ct)

            can_fold = allow_fold and first_decision and self.player.folds > 0

            print(f"\n  \u2192 Hit   \u2190 Stand")
            if can_fold:
                fold_str = f"\u2193 Fold ({self.player.folds})"
                choice = prompt_choice(
                    f"{fold_str}  \u2191 Info  r Rules",
                    ["right", "left", "down", "up", "r"],
                    arrow_labels,
                )
            elif allow_fold and first_decision:
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
                return player_cards, False, True

            if choice == "left":
                self._last_bust_prob = bust_pct / 100.0
                print(f"  Stand at {C_BGREEN}{p_val}{C_RESET}.")
                break

            card = self.deck.draw()
            player_cards.append(card)
            print(f"  Drew {show_card(card)}  = {p_val_str(player_cards)}")

        # Auto-stand at 21 means max bust risk
        if not player_busted and hand_value(player_cards) == 21:
            self._last_bust_prob = 1.0

        return player_cards, player_busted, False

    def _enemy_turn(self, enemy, enemy_cards, p_val=None):
        """Run enemy draws. Returns (cards, busted, e_val).

        p_val: player's final hand value. Elite/boss enemies use this
        to stop drawing once they're ahead.
        """
        aware = enemy.tier in ("elite", "boss")
        beat(0.5)
        print(f"\n  {C_AMBER}The dead reveal...{C_RESET}")
        beat(0.3)
        print_cards("Dead   ", enemy_cards, e_val_str(enemy_cards))

        while hand_value(enemy_cards) <= enemy.hit_threshold:
            if aware and p_val and hand_value(enemy_cards) > p_val:
                break
            beat(0.3)
            card = self.enemy_deck.draw()
            enemy_cards.append(card)
            print(f"  Spirit draws  {show_card(card)}  -> {e_val_str(enemy_cards)}")

        for _ in range(enemy.reckless_extra):
            if hand_value(enemy_cards) < 21:
                if aware and p_val and hand_value(enemy_cards) > p_val:
                    break
                beat(0.3)
                card = self.enemy_deck.draw()
                enemy_cards.append(card)
                print(f"  {C_AMBER}Wild Card!{C_RESET}  Spirit draws {show_card(card)}  -> {e_val_str(enemy_cards)}")

        e_val = hand_value(enemy_cards)
        enemy_busted = e_val > 21

        if enemy_busted:
            beat(0.4)
            flash_text(f"  {C_BGREEN}SPIRIT BUSTS! ({e_val}){C_RESET}")

        return enemy_cards, enemy_busted, e_val

    def _resolve_hand(self, p_val, e_val, player_busted, enemy_busted, player_cards, enemy, label=None):
        """Resolve one hand vs enemy. Returns (won, lost)."""
        prefix = f"{label} " if label else ""
        won = False
        lost = False

        if player_busted:
            if label:
                beat(0.3)
                print(f"  {C_RED}{prefix}Bust!{C_RESET} ({p_val})")
            dmg = self._calc_loss_damage(e_val, p_val, enemy, is_bust=True,
                                         player_cards=player_cards)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            lost = True
        elif enemy_busted:
            if label:
                print(f"  {C_GREEN}{prefix}You win!{C_RESET} {C_BGREEN}{p_val}{C_RESET} vs {C_AMBER}{e_val}{C_RESET} (bust)")
            beat(0.3)
            dmg = self._calc_win_damage(p_val, e_val, player_cards=player_cards)
            self.hurt_enemy(enemy, dmg)
            won = True
        elif p_val > e_val:
            print(f"  {C_GREEN}{prefix}You win!{C_RESET} {C_BGREEN}{p_val}{C_RESET} vs {C_AMBER}{e_val}{C_RESET}")
            beat(0.15)
            dmg = self._calc_win_damage(p_val, e_val, player_cards=player_cards)
            self.hurt_enemy(enemy, dmg)
            won = True
        elif e_val > p_val:
            print(f"  {C_RED}{prefix}You lose.{C_RESET} {C_BGREEN}{p_val}{C_RESET} vs {C_AMBER}{e_val}{C_RESET}")
            beat(0.15)
            dmg = self._calc_loss_damage(e_val, p_val, enemy, player_cards=player_cards)
            self.hurt_player(dmg)
            if enemy.drain:
                self._apply_drain(enemy, dmg)
            lost = True
        else:
            print(f"  {C_AMBER}{prefix}Push.{C_RESET} Both {C_BGREEN}{p_val}{C_RESET}.")

        return won, lost

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
            cat_mult = None if self._silenced else self.player.get_companion_effect("natural_21_multiplier", player_cards)
            if cat_mult:
                dmg *= cat_mult
                self._shade_proc("Sable", "Ace High", f"x{cat_mult:.2f} natural-21 damage -> {dmg:.0f}")
                self._whisper("sable")
            else:
                dmg *= cfg.natural_21_multiplier
                print(f"  {C_DIM}x{cfg.natural_21_multiplier:.1f} natural -> {dmg:.0f}{C_RESET}")
        else:
            margin = p_val - e_val
            if margin >= cfg.margin_bonus_threshold:
                dmg *= cfg.margin_bonus_multiplier
                print(f"  {C_DIM}x{cfg.margin_bonus_multiplier:.1f} margin ({margin}pt) -> {dmg:.0f}{C_RESET}")
        imp_mult = None if self._silenced else self.player.get_companion_effect("damage_multiplier", player_cards)
        if imp_mult:
            dmg *= imp_mult
            self._shade_proc("Maggie", "Burn", f"x{imp_mult:.2f} win damage -> {dmg:.0f}")
            self._whisper("maggie")
        if player_cards:
            ench = self._count_enchantments(player_cards)
            if ench["echo"] > 0:
                print(f"  {C_GREEN}Echo x{ench['echo']}: duplicating enchantments{C_RESET}")
            if ench["fury"] > 0:
                fury_bonus = self._ench_total(self.config.enchantment.fury_damage, ench["fury"])
                dmg += fury_bonus
                print(f"  {C_GREEN}+{fury_bonus:.0f} Fury x{ench['fury']} -> {dmg:.0f}{C_RESET}")
            if ench["gambit"] > 0:
                ecfg = self.config.enchantment
                gambit_bonus = ench["gambit"] * (ecfg.gambit_base_damage + ecfg.gambit_bust_scaling * self._last_bust_prob)
                dmg += gambit_bonus
                print(f"  {C_GREEN}+{gambit_bonus:.1f} Gambit x{ench['gambit']} ({self._last_bust_prob*100:.0f}% bust risk) -> {dmg:.0f}{C_RESET}")
        # Player crit
        if random.random() < self.config.damage.player_crit_chance:
            dmg *= self.config.damage.crit_multiplier
            flash_text(f"  {C_BGREEN}CRIT! x{self.config.damage.crit_multiplier:.1f} -> {dmg:.0f}{C_RESET}")
        return dmg

    def _calc_loss_damage(self, e_val, p_val, enemy, is_natural=False, is_bust=False,
                          player_cards=None):
        cfg = self.config.damage
        if cfg.model == "differential":
            base = float(max(e_val - p_val, cfg.damage_floor))
            print(f"  {C_DIM}{e_val} - {p_val} = {base:.0f}{C_RESET}")
        else:
            base = float(max(e_val - cfg.damage_subtract, 1))
            print(f"  {C_DIM}{e_val} - {cfg.damage_subtract} = {base:.0f}{C_RESET}")
        dmg = base
        # Enemy crit / backstab
        if enemy.backstab_on_21 and e_val == 21:
            dmg *= enemy.crit_multiplier
            flash_text(f"  {C_BRED}DEAD HAND! x{enemy.crit_multiplier:.1f} -> {dmg:.0f}{C_RESET}")
        elif enemy.crit_chance > 0 and random.random() < enemy.crit_chance:
            dmg *= enemy.crit_multiplier
            flash_text(f"  {C_RED}CRIT! x{enemy.crit_multiplier:.1f} -> {dmg:.0f}{C_RESET}")
        if is_bust:
            dmg *= cfg.bust_penalty_multiplier
            print(f"  {C_DIM}x{cfg.bust_penalty_multiplier:.1f} bust -> {dmg:.0f}{C_RESET}")
        if is_natural:
            dmg *= cfg.natural_21_multiplier
            print(f"  {C_DIM}x{cfg.natural_21_multiplier:.1f} natural -> {dmg:.0f}{C_RESET}")
        reduction_pct = None if self._silenced else self.player.get_companion_effect("damage_reduction_pct", player_cards)
        if reduction_pct:
            reduced = dmg * reduction_pct
            dmg = max(0, dmg - reduced)
            self._shade_proc("Priest", "Shield", f"-{reduction_pct*100:.0f}% incoming damage -> {dmg:.0f}")
            self._whisper("priest")
        if player_cards:
            ench = self._count_enchantments(player_cards)
            if ench["ward"] > 0:
                ward_red = self._ench_total(self.config.enchantment.ward_reduction, ench["ward"])
                dmg = max(0, dmg - ward_red)
                print(f"  {C_GREEN}-{ward_red:.0f} Ward x{ench['ward']} -> {dmg:.0f}{C_RESET}")
        if enemy.bonus_damage > 0:
            dmg += enemy.bonus_damage
            print(f"  {C_DIM}+{enemy.bonus_damage} tilt -> {dmg:.0f}{C_RESET}")
        return dmg

    def _apply_drain(self, enemy, dmg):
        heal = max(1, int(dmg))
        enemy.hp = min(enemy.max_hp, enemy.hp + heal)
        print(f"  {C_RED}{enemy.name} siphons {heal} chips!{C_RESET} ({enemy.hp}/{enemy.max_hp})")

    def _try_reap_shade(self, enemy, e_val):
        """If enemy has reap_shade_on_21 and hit exactly 21, kill a random shade."""
        if not enemy.reap_shade_on_21 or e_val != 21:
            return
        companions = self.player.companions
        if not companions:
            return
        victim = random.choice(companions)
        shade_c = SHADE_COLORS.get(victim.companion_type, C_GREEN)
        beat(0.5)
        flash_text(f"  {C_BRED}REAPED!{C_RESET}")
        beat(0.3)
        typewrite(f"  {C_RED}{enemy.name} claims {shade_c}{victim.name}{C_RED}. Gone.{C_RESET}", delay=0.03)
        self.player.companions.remove(victim)
        beat(0.5)

    # --- Map display ---

    NODE_SYMBOLS = {
        NodeType.GRAVE: ("\u25cf", "\u25cb"),       # filled/hollow circle
        NodeType.MAUSOLEUM: ("\u25c6", "\u25c7"),   # filled/hollow diamond
        NodeType.BOSS: ("\u2605", "\u2606"),         # filled/hollow star
        NodeType.BARROW: ("+", "+"),
        NodeType.VIGIL: ("~", "~"),
        NodeType.CROSSROADS: ("?", "?"),
    }

    NODE_LABELS = {
        NodeType.GRAVE: "Grave",
        NodeType.MAUSOLEUM: "Mausoleum",
        NodeType.BOSS: "Boss",
        NodeType.BARROW: "Barrow",
        NodeType.VIGIL: "Vigil",
        NodeType.CROSSROADS: "Crossroads",
    }

    def show_act_overview(self, act_map):
        """Show the full act map at the start of each act."""
        clear()
        print()

        act_name = ACT_NAMES[act_map.act_num] if act_map.act_num < len(ACT_NAMES) else ""
        title = f"ACT {act_map.act_num + 1}"
        if act_name:
            title += f" \u00b7 {act_name.upper()}"

        # Collect content lines: (raw_text, ansi_text)
        content = []
        layer_map = act_map.layers()
        sorted_layers = sorted(layer_map.keys())

        for li, layer_num in enumerate(sorted_layers):
            layer_nodes = layer_map[layer_num]

            if len(layer_nodes) == 1:
                node = layer_nodes[0]
                sym_done, sym_todo = self.NODE_SYMBOLS.get(node.node_type, ("\u25cf", "\u25cb"))
                if node.node_type in (NodeType.GRAVE, NodeType.MAUSOLEUM, NodeType.BOSS):
                    label = node.enemy_name if node.enemy_name else self.NODE_LABELS.get(node.node_type, "?")
                else:
                    label = self.NODE_LABELS.get(node.node_type, "?")
                if node.visited:
                    sa, sr = f"{C_GREEN}{sym_done}{C_RESET}", sym_done
                elif node.node_type == NodeType.BOSS:
                    sa, sr = f"{C_RED}{sym_todo}{C_RESET}", sym_todo
                else:
                    sa, sr = f"{C_DIM}{sym_todo}{C_RESET}", sym_todo
                content.append((f" {sr}  {label}", f" {sa}  {label}"))
            else:
                for bi, node in enumerate(layer_nodes):
                    sym_done, sym_todo = self.NODE_SYMBOLS.get(node.node_type, ("+", "+"))
                    label = self.NODE_LABELS.get(node.node_type, "?")
                    if node.visited:
                        sa, sr = f"{C_GREEN}{sym_done}{C_RESET}", sym_done
                    else:
                        sa, sr = f"{C_DIM}{sym_todo}{C_RESET}", sym_todo
                    branch = "\u2514\u2500\u2500" if bi == len(layer_nodes) - 1 else "\u251c\u2500\u2500"
                    content.append(
                        (f" {branch} {sr} {label}",
                         f" {C_DIM}{branch}{C_RESET} {sa} {label}"))

            if li < len(sorted_layers) - 1:
                content.append((" \u2502", f" {C_DIM}\u2502{C_RESET}"))

        leg1 = " \u25cb grave  \u25c7 dealer  \u2606 pit boss"
        leg2 = " + barrow  ~ vigil  ? crossroads"

        all_raw = [title] + [r for r, _ in content] + [leg1, leg2]
        inner_w = max(len(s) for s in all_raw) + 4
        h = "\u2500" * inner_w
        d, rs = C_DIM, C_RESET

        print(f"  {d}\u250c{h}\u2510{rs}")
        pad_t = " " * (inner_w - len(title))
        typewrite(f"  {d}\u2502{rs} {C_BWHITE}{title}{pad_t}{C_RESET}{d}\u2502{rs}", delay=0.02)
        print(f"  {d}\u251c{h}\u2524{rs}")
        print(f"  {d}\u2502{rs}{' ' * inner_w}{d}\u2502{rs}")

        for raw, ansi in content:
            pad = " " * (inner_w - len(raw))
            print(f"  {d}\u2502{rs}{ansi}{pad}{d}\u2502{rs}")

        print(f"  {d}\u2502{rs}{' ' * inner_w}{d}\u2502{rs}")
        for leg in (leg1, leg2):
            pad = " " * (inner_w - len(leg))
            print(f"  {d}\u2502{rs}{d}{leg}{rs}{pad}{d}\u2502{rs}")
        print(f"  {d}\u2514{h}\u2518{rs}")

        print()
        pause()
    def fork_selection(self, children):
        """Arrow-key selection screen for branch nodes. Returns chosen MapNode."""
        selected = 0
        descriptions = {
            NodeType.BARROW: "Work the dead earth. Bury or exhume cards.",
            NodeType.VIGIL: "Rest among candles. Heal, commune, or offer.",
            NodeType.CROSSROADS: "A stranger waits. Risk and reward.",
        }

        def draw():
            lines = []
            lines.append(f"  {C_BWHITE}THE PATH FORKS{C_RESET}")
            lines.append("")
            for i, node in enumerate(children):
                label = self.NODE_LABELS.get(node.node_type, "?")
                desc = descriptions.get(node.node_type, "")
                if i == selected:
                    lines.append(f"  {C_BGREEN}> {label:<12}{C_RESET} {desc}")
                else:
                    lines.append(f"  {C_DIM}  {label:<12}{C_RESET} {C_DIM}{desc}{C_RESET}")
            lines.append("")
            lines.append(f"  {C_DIM}\u2191\u2193 choose   \u2192 confirm{C_RESET}")
            return lines

        # Initial draw
        print()
        lines = draw()
        for line in lines:
            print(line)

        while True:
            key = read_key()
            if key == '\x03':
                print("\n\n  Goodbye!")
                sys.exit(0)
            if key == "up":
                selected = (selected - 1) % len(children)
            elif key == "down":
                selected = (selected + 1) % len(children)
            elif key == "right":
                # Confirm selection
                erase_lines(len(lines))
                chosen = children[selected]
                label = self.NODE_LABELS.get(chosen.node_type, "?")
                print(f"  {C_GREEN}Chose: {label}{C_RESET}")
                print()
                return chosen

            # Redraw
            erase_lines(len(lines))
            lines = draw()
            for line in lines:
                print(line)

    def _journey_map(self, act_map, current_node):
        """Render a compact progress line for the current act."""
        layer_map = act_map.layers()
        sorted_layers = sorted(layer_map.keys())
        parts = []

        for layer_num in sorted_layers:
            layer_nodes = layer_map[layer_num]
            # For branch layers, show the one that was visited (or first if none)
            if len(layer_nodes) == 1:
                node = layer_nodes[0]
            else:
                visited = [n for n in layer_nodes if n.visited]
                node = visited[0] if visited else layer_nodes[0]

            sym_done, sym_todo = self.NODE_SYMBOLS.get(node.node_type, ("\u25cf", "\u25cb"))

            if node.visited:
                parts.append(f"{C_GREEN}{sym_done}{C_RESET}")
            elif current_node and node.node_id == current_node.node_id:
                parts.append(f"{C_BGREEN}{sym_done}{C_RESET}")
            else:
                parts.append(f"{C_DIM}{sym_todo}{C_RESET}")

        dash = f"{C_DIM}\u2500{C_RESET}"
        return dash.join(parts)

    # --- Non-combat node screens ---

    def barrow_screen(self):
        """Barrow node: bury (remove), exhume (gain grave card), or enchant."""
        clear()
        print()
        typewrite(f"  {C_BWHITE}THE BARROW{C_RESET}", delay=0.03)
        print(f"  {C_DIM}Cold earth and older bones.{C_RESET}")
        print()
        self.show_status()
        print()

        removable = self.deck.removable_ranks(self.config.reward.min_deck_size)
        can_bury = bool(removable)
        ecfg = self.config.enchantment
        enchantable = self.deck.enchantable_cards(1, ecfg.max_per_card)

        options = []
        arrows = ["left", "right", "down"]
        arrow_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}

        if can_bury:
            options.append(("left", "Bury a card", "bury"))
        options.append(("right", "Exhume a grave card", "exhume"))
        if enchantable:
            options.append(("down", "Engrave a card", "enchant"))

        for key, label, _ in options:
            print(f"    {arrow_syms[key]} {label}")

        valid_keys = [o[0] for o in options]
        labels = {o[0]: o[1].upper() for o in options}
        choice = prompt_choice("  >", valid_keys, labels)
        action = next(o[2] for o in options if o[0] == choice)

        if action == "bury":
            self._card_removal_ui()
        elif action == "exhume":
            self._exhume_ui()
        elif action == "enchant":
            self._enchantment_ui()

        pause()

    def _exhume_ui(self):
        """Show 2-3 random grave cards for the player to pick one."""
        keys = list(GRAVE_CARDS.keys())
        random.shuffle(keys)
        offered = keys[:random.randint(2, 3)]

        print(f"\n  {C_AMBER}Bones shift in the dirt...{C_RESET}")
        print()

        arrows = ["left", "right", "down"]
        arrow_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}
        valid_keys = []
        card_labels = {}
        card_map = {}

        for i, gkey in enumerate(offered):
            gc = GRAVE_CARDS[gkey]
            key = arrows[i]
            valid_keys.append(key)
            card = Card(gc["rank"], gc["suit"])
            card_labels[key] = gc["name"]
            card_map[key] = (gc, card, gkey)
            ench_tag = gc["enchantment"].capitalize()
            print(f"    {arrow_syms[key]} {show_card(card)} {C_BWHITE}{gc['name']}{C_RESET}")
            print(f"      {C_DIM}{gc['desc']}{C_RESET}  [{ench_tag}]")

        choice = prompt_choice("  >", valid_keys, card_labels)
        gc, card, gkey = card_map[choice]

        # Add card to deck template and enchant it
        new_card = Card(gc["rank"], gc["suit"])
        self.deck._template.append(new_card)
        self.deck.enchant_card(new_card, gc["enchantment"], self.config.enchantment.max_per_card)

        ench_tag = gc["enchantment"].capitalize()
        print(f"\n  {C_BGREEN}{gc['name']} rises from the earth.{C_RESET}")
        print(f"  Added to deck with {ench_tag} enchantment. ({self.deck.template_size} cards)")

    def vigil_screen(self):
        """Vigil node: rest (heal), commune (companion XP), or burn offering (HP for folds)."""
        clear()
        print()
        typewrite(f"  {C_BWHITE}THE VIGIL{C_RESET}", delay=0.03)
        print(f"  {C_DIM}Candles flicker. The dead remember.{C_RESET}")
        print()
        self.show_status()
        print()

        mcfg = self.config.map
        options = []
        arrow_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}

        # Rest: heal
        heal_amt = int(self.player.max_hp * mcfg.vigil_heal_pct)
        if self.player.hp < self.player.max_hp:
            options.append(("left", f"Rest (heal {heal_amt} chips)", "rest"))

        # Commune: companion XP
        if self.player.companions:
            options.append(("right", f"Commune (+{mcfg.vigil_commune_xp} XP to shades)", "commune"))

        # Burn offering: HP for folds
        can_offer = self.player.hp > mcfg.vigil_offering_hp_cost + 1
        if can_offer:
            options.append(("down", f"Burn offering (-{mcfg.vigil_offering_hp_cost} chips, +{mcfg.vigil_offering_folds} folds)", "offer"))

        if not options:
            print(f"  {C_DIM}Nothing to do here. The candles dim.{C_RESET}")
            pause()
            return

        for key, label, _ in options:
            print(f"    {arrow_syms[key]} {label}")

        valid_keys = [o[0] for o in options]
        labels = {o[0]: o[1].upper() for o in options}
        choice = prompt_choice("  >", valid_keys, labels)
        action = next(o[2] for o in options if o[0] == choice)

        if action == "rest":
            old_hp = self.player.hp
            self.player.heal(heal_amt)
            healed = self.player.hp - old_hp
            print(f"  {C_GREEN}+{healed} chips{C_RESET} ({old_hp} \u2192 {self.player.hp})")
            animate_hp_change(old_hp, self.player.hp, self.player.max_hp)
        elif action == "commune":
            xp_per = self.config.companion.xp_per_level
            max_lvl = self.config.companion.max_level
            prev_levels = {c.name: c.level for c in self.player.companions}
            for c in self.player.companions:
                c.gain_xp(mcfg.vigil_commune_xp, xp_per, max_lvl)
            print(f"  {C_GREEN}Shades commune with the flame.{C_RESET}")
            for c in self.player.companions:
                old_lvl = prev_levels.get(c.name, 0)
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                if c.level > old_lvl:
                    flash_text(f"  {shade_c}{c.name} \u2192 LEVEL {c.level}!{C_RESET}")
                else:
                    xp_display = xp_bar(c.xp, xp_per, 12)
                    print(f"  {shade_c}{c.name}{C_RESET} +{mcfg.vigil_commune_xp} XP  {xp_display} {c.xp}/{xp_per}  Lv{c.level}")
        elif action == "offer":
            old_hp = self.player.hp
            self.player.take_damage(mcfg.vigil_offering_hp_cost)
            self.player.folds += mcfg.vigil_offering_folds
            print(f"  {C_RED}-{mcfg.vigil_offering_hp_cost} chips{C_RESET} ({old_hp} \u2192 {self.player.hp})")
            print(f"  {C_GREEN}+{mcfg.vigil_offering_folds} folds{C_RESET} ({self.player.folds} total)")
            animate_hp_change(old_hp, self.player.hp, self.player.max_hp)

        print()
        pause()

    def crossroads_screen(self):
        """Crossroads node: random event. Player can accept or decline."""
        clear()
        print()
        typewrite(f"  {C_BWHITE}THE CROSSROADS{C_RESET}", delay=0.03)
        print(f"  {C_DIM}A figure stands where the paths meet.{C_RESET}")
        print()
        self.show_status()
        print()

        mcfg = self.config.map
        event = random.choice(["dead_hand", "whisper", "wager"])

        if event == "dead_hand":
            print(f"  {C_AMBER}Dead Man's Hand{C_RESET}")
            print(f"  {C_DIM}Play a single hand against a phantom.{C_RESET}")
            print(f"  {C_DIM}Win: heal {mcfg.crossroads_win_heal}. Lose: take {mcfg.crossroads_loss_damage}.{C_RESET}")
            print()
            print(f"    {C_GREEN}\u2192{C_RESET} Accept    {C_DIM}\u2190{C_RESET} Walk away")
            choice = prompt_choice("  >", ["right", "left"], {"right": "ACCEPT", "left": "WALK AWAY"})
            if choice == "right":
                self._crossroads_dead_hand(mcfg)
            else:
                print(f"  {C_DIM}You pass by in silence.{C_RESET}")

        elif event == "whisper":
            print(f"  {C_AMBER}The Whisper{C_RESET}")
            print(f"  {C_DIM}Pay 1 fold to learn the act boss's abilities.{C_RESET}")
            print()
            if self.player.folds > 0:
                print(f"    {C_GREEN}\u2192{C_RESET} Pay 1 fold    {C_DIM}\u2190{C_RESET} Walk away")
                choice = prompt_choice("  >", ["right", "left"], {"right": "PAY", "left": "WALK AWAY"})
                if choice == "right":
                    self.player.folds -= 1
                    if hasattr(self, '_current_act_map'):
                        self._current_act_map.boss_revealed = True
                    # Find the boss node and show its info
                    if hasattr(self, '_current_act_map'):
                        for node in self._current_act_map.nodes:
                            if node.node_type == NodeType.BOSS and node.enemy_key:
                                tmpl = ENEMY_TEMPLATES[node.enemy_key]
                                print(f"\n  {C_BWHITE}The boss is {tmpl['name']}.{C_RESET}")
                                abilities = describe_abilities(Enemy(
                                    name=tmpl["name"], hp=1, max_hp=1,
                                    hit_threshold=tmpl["hit_threshold"],
                                    tier="boss",
                                    reckless_extra=tmpl.get("reckless_extra", 0),
                                    damage_absorption=tmpl.get("damage_absorption", 0),
                                    nine_lives_chance=tmpl.get("nine_lives_chance", 0.0),
                                    rage_per_hand=tmpl.get("rage_per_hand", 0),
                                    poison_per_hand=tmpl.get("poison_per_hand", 0),
                                    drain=tmpl.get("drain", False),
                                    crit_chance=tmpl.get("crit_chance", 0.0),
                                    backstab_on_21=tmpl.get("backstab_on_21", False),
                                    silence_shades=tmpl.get("silence_shades", False),
                                    reap_shade_on_21=tmpl.get("reap_shade_on_21", False),
                                ))
                                for a in abilities:
                                    print(f"  {C_AMBER}{a}{C_RESET}")
                                break
                    print(f"  {C_DIM}(-1 fold, {self.player.folds} remaining){C_RESET}")
                else:
                    print(f"  {C_DIM}You pass by in silence.{C_RESET}")
            else:
                print(f"  {C_DIM}No folds to pay. You walk on.{C_RESET}")

        elif event == "wager":
            print(f"  {C_AMBER}Buried Wager{C_RESET}")
            print(f"  {C_DIM}Pay 3 chips. 50% chance to gain a grave card.{C_RESET}")
            print()
            if self.player.hp > 3:
                print(f"    {C_GREEN}\u2192{C_RESET} Gamble    {C_DIM}\u2190{C_RESET} Walk away")
                choice = prompt_choice("  >", ["right", "left"], {"right": "GAMBLE", "left": "WALK AWAY"})
                if choice == "right":
                    old_hp = self.player.hp
                    self.player.take_damage(3)
                    print(f"  {C_RED}-3 chips{C_RESET} ({old_hp} \u2192 {self.player.hp})")
                    if random.random() < 0.5:
                        gkey = random.choice(list(GRAVE_CARDS.keys()))
                        gc = GRAVE_CARDS[gkey]
                        new_card = Card(gc["rank"], gc["suit"])
                        self.deck._template.append(new_card)
                        self.deck.enchant_card(new_card, gc["enchantment"], self.config.enchantment.max_per_card)
                        print(f"  {C_BGREEN}{gc['name']} claws up from the dirt!{C_RESET}")
                        print(f"  Added to deck with {gc['enchantment'].capitalize()}. ({self.deck.template_size} cards)")
                    else:
                        print(f"  {C_DIM}Nothing stirs. The earth keeps its secrets.{C_RESET}")
                else:
                    print(f"  {C_DIM}You pass by in silence.{C_RESET}")
            else:
                print(f"  {C_DIM}Too wounded to gamble. You walk on.{C_RESET}")

        print()
        pause()

    def _crossroads_dead_hand(self, mcfg):
        """Play a single blackjack hand against a phantom for the crossroads event."""
        # Create a simple phantom enemy
        phantom = Enemy(
            name="Phantom", hp=1, max_hp=1,
            hit_threshold=16, tier="normal", rarity="common",
        )
        self.enemy_deck = build_enemy_deck_from_removed_ranks([])

        # Deal
        player_cards = [self.deck.draw(), self.deck.draw()]
        enemy_cards = [self.enemy_deck.draw(), self.enemy_deck.draw()]
        print()
        print_cards("  You: ", player_cards, p_val_str(player_cards))

        # Simple hit/stand loop
        while hand_value(player_cards) < 21:
            bust_prob = self.deck.bust_probability(player_cards)
            print(f"  {C_DIM}Bust risk: {bust_prob*100:.0f}%{C_RESET}")
            print(f"  {C_GREEN}\u2192{C_RESET} hit  {C_GREEN}\u2190{C_RESET} stand")
            key = prompt_choice("  >", ["right", "left"], {"right": "HIT", "left": "STAND"})
            if key == "left":
                break
            player_cards.append(self.deck.draw())
            print_cards("  You: ", player_cards, p_val_str(player_cards))

        p_val = hand_value(player_cards)

        # Enemy turn
        while hand_value(enemy_cards) <= 16:
            enemy_cards.append(self.enemy_deck.draw())
        e_val = hand_value(enemy_cards)

        print_cards("  Phantom: ", enemy_cards, e_val_str(enemy_cards))

        if p_val > 21:
            print(f"  {C_RED}Bust! You take {mcfg.crossroads_loss_damage} damage.{C_RESET}")
            self.player.take_damage(mcfg.crossroads_loss_damage)
        elif e_val > 21 or p_val > e_val:
            print(f"  {C_GREEN}You win! +{mcfg.crossroads_win_heal} chips.{C_RESET}")
            self.player.heal(mcfg.crossroads_win_heal)
        elif e_val > p_val:
            print(f"  {C_RED}You lose. -{mcfg.crossroads_loss_damage} chips.{C_RESET}")
            self.player.take_damage(mcfg.crossroads_loss_damage)
        else:
            print(f"  {C_AMBER}Push. Nothing gained, nothing lost.{C_RESET}")

    # --- Fight loop ---

    def show_enemy_status(self, enemy):
        ebar = hp_bar(enemy.hp, enemy.max_hp)
        name = enemy_display_name(enemy)
        tier = TIER_LABELS.get(enemy.tier, "")
        print(f"  {name}{tier}  {ebar} {enemy.hp}/{enemy.max_hp}")

    def play_fight(self, enemy, fight_num, total, act_num):
        self._fight_num = fight_num
        self._silenced = enemy.silence_shades
        self.enemy_deck = build_enemy_deck_from_removed_ranks(enemy.deck_removed_ranks)
        clear()
        w = 47
        DIV = self._DIVIDER
        lines = []

        act_label = f"ACT {act_num}"
        fight_label = f"Séance {fight_num} of {total}"
        pad = w - 2 - len(act_label) - len(fight_label)
        lines.append(f"  {C_BWHITE}{act_label}{' ' * pad}{fight_label}{C_RESET}")
        lines.append(DIV)

        name = enemy_display_name(enemy)
        ebar = hp_bar(enemy.hp, enemy.max_hp, 10)
        tier = TIER_LABELS.get(enemy.tier, "")
        lines.append(f"  {name}{tier}  {ebar} {enemy.hp}/{enemy.max_hp}")
        recruit_block = self._recruit_block_reason(enemy)
        if recruit_block:
            lines.append(f"  {C_DIM}Recruit: No ({recruit_block}){C_RESET}")
        else:
            reserve_count = len(self.player.reserve_companions)
            lines.append(
                f"  {C_GREEN}Recruit: Yes{C_RESET} "
                f"{C_DIM}(active {len(self.player.companions)}/{self.player.max_companion_slots}, reserve {reserve_count}){C_RESET}"
            )

        abilities = describe_abilities(enemy)
        if abilities:
            for a in abilities:
                lines.append(f"  {C_AMBER}{a}{C_RESET}")
        lines.append(DIV)

        bar = hp_bar(self.player.hp, self.player.max_hp)
        lines.append(f"  You  {bar} {self.player.hp}/{self.player.max_hp}     Folds: {self.player.folds}")
        if self.player.companions:
            for c in self.player.companions:
                hint_c = colorize_hint(c.activation)
                suffix = f" [{hint_c}]" if hint_c else ""
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                if self._silenced:
                    lines.append(f"  {C_DIM}{c.name} Lv{c.level}{suffix} [silenced]{C_RESET}")
                else:
                    lines.append(f"  {shade_c}{c.name}{C_RESET} Lv{c.level}{suffix}")

        max_width = max((plain_len(l) for l in lines if l is not DIV), default=w)
        max_width = max(max_width + 2, w)

        # Frame style by tier: boss=double, elite=heavy, normal=thin
        if enemy.tier == "boss":
            tl, tr, bl, br = "\u2554", "\u2557", "\u255a", "\u255d"
            h, v, lj, rj = "\u2550", "\u2551", "\u2560", "\u2563"
            frame_color = C_RED
        elif enemy.tier == "elite":
            tl, tr, bl, br = "\u250f", "\u2513", "\u2517", "\u251b"
            h, v, lj, rj = "\u2501", "\u2503", "\u2523", "\u252b"
            frame_color = C_AMBER
        else:
            tl, tr, bl, br = "\u250c", "\u2510", "\u2514", "\u2518"
            h, v, lj, rj = "\u2500", "\u2502", "\u251c", "\u2524"
            frame_color = C_DIM

        print()
        print(f"  {frame_color}{tl}{h * max_width}{tr}{C_RESET}")
        for line in lines:
            if line is DIV:
                print(f"  {frame_color}{lj}{h * max_width}{rj}{C_RESET}")
            else:
                padding = max_width - plain_len(line)
                print(f"  {frame_color}{v}{C_RESET}{line}{' ' * padding}{frame_color}{v}{C_RESET}")
        print(f"  {frame_color}{bl}{h * max_width}{br}{C_RESET}")
        self._shade_chatter("fight_start", chance=0.45)

        hand_num = 0
        total_dealt = 0
        total_taken = 0
        self._hex_bleed_counter = 0
        prev_levels = {c.name: c.level for c in self.player.companions}
        had_natural = False
        had_bust = False
        had_fold = False
        high_total_finish = False

        while self.player.alive and enemy.alive:
            hand_num += 1
            ehp_before, php_before = enemy.hp, self.player.hp
            result = self.play_hand(enemy, hand_num)
            action = result.get("action", "")
            if action in ("natural", "natural_push"):
                had_natural = True
            if action == "busted":
                had_bust = True
            if action == "folded":
                had_fold = True
            if result.get("won") and result.get("p_val", 0) >= 20:
                high_total_finish = True
            total_dealt += max(0, ehp_before - enemy.hp)
            total_taken += max(0, php_before - self.player.hp)

            summary = format_hand_summary(result)
            if summary:
                print(f"\n  {summary}")

            # Shade ambient chatter based on what just happened
            if result.get("won"):
                if result.get("enemy_busted"):
                    self._shade_chatter("enemy_bust", chance=0.40)
                else:
                    self._shade_chatter("win", chance=0.25)
            elif result.get("lost"):
                self._shade_chatter("loss", chance=0.25)
            if self.player.alive and self.player.hp <= self.player.max_hp * 0.25:
                self._shade_chatter("low_hp", chance=0.30)

            # Show both HP bars after each hand
            if self.player.alive and enemy.alive:
                print()
                self.show_enemy_status(enemy)
                self.show_status()
                print(f"  {C_DIM}{'─ ' * 20}{C_RESET}")

            # Hex bleed tick (end of round)
            if self._hex_bleed_counter > 0 and enemy.alive:
                beat(0.2)
                enemy.hp = max(0, enemy.hp - self._hex_bleed_counter)
                total_dealt += self._hex_bleed_counter
                print(f"  {C_RED}Hex bleed: -{self._hex_bleed_counter} chips!{C_RESET} ({enemy.hp}/{enemy.max_hp})")
                if not enemy.alive:
                    beat(0.4)
                    typewrite(f"  {C_BGREEN}The curse consumes them!{C_RESET}", delay=0.03)

            # Poison (every hand)
            if enemy.poison_per_hand and enemy.alive and self.player.alive:
                beat(0.2)
                self.hurt_player(enemy.poison_per_hand, show=False)
                print(f"  {C_RED}Bleed! -{enemy.poison_per_hand} chips{C_RESET} ({self.player.hp}/{self.player.max_hp})")

            # Nine lives
            if not enemy.alive and enemy.nine_lives_chance > 0:
                if random.random() < enemy.nine_lives_chance:
                    beat(0.5)
                    enemy.hp = 1
                    enemy.nine_lives_chance = 0.0
                    enemy._nine_lives_spent = True
                    typewrite(f"  {C_AMBER}LAST BREATH!{C_RESET} {enemy_display_name(enemy)} clings on with 1 chip!", delay=0.03)
                    beat(0.3)

            # Rage escalation
            if enemy.rage_per_hand and enemy.alive:
                enemy.bonus_damage += enemy.rage_per_hand
                beat(0.3)
                print(f"  {C_AMBER}{enemy_display_name(enemy)} is tilting! (+{enemy.bonus_damage} dmg){C_RESET}")

        # Companion XP (end of fight)
        for c in self.player.companions:
            c.gain_xp(
                self.config.companion.xp_per_fight,
                self.config.companion.xp_per_level,
                self.config.companion.max_level,
            )

        won = not enemy.alive
        self._last_capture_bonus, self._last_capture_bonus_reasons = self._capture_bonus_from_flags(
            hand_num, had_natural, had_bust, had_fold, high_total_finish
        )
        if won:
            print()
            typewrite(f"  {enemy_display_name(enemy)} defeated!", delay=0.03)
            print(f"  {C_DIM}{hand_num} hands | {total_dealt} dealt | {total_taken} taken{C_RESET}")
            if hasattr(self, '_current_act_map') and hasattr(self, '_current_node'):
                print(f"  {self._journey_map(self._current_act_map, self._current_node)}")

        # Companion XP and level-up display
        xp_per = self.config.companion.xp_per_level
        xp_gain = self.config.companion.xp_per_fight
        max_lvl = self.config.companion.max_level
        if self.player.companions:
            print()
        for c in self.player.companions:
            old_lvl = prev_levels.get(c.name, 0)
            if c.level > old_lvl:
                # --- Level-up celebration ---
                beat(0.3)
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                flash_text(f"  {shade_c}{c.name} \u2192 LEVEL {c.level}!{C_RESET}")
                beat(0.2)
                # Show what improved
                effect_short = describe_companion_effect(c.effect_type, short=True)
                val_str = format_effect_value(c.effect_type, c.effect_value)
                if val_str:
                    print(f"  {C_GREEN}  {effect_short}: {val_str}{C_RESET}")
                if c.level >= max_lvl:
                    typewrite(f"  {C_AMBER}  MAX LEVEL{C_RESET}", delay=0.04)
                else:
                    xp_display = xp_bar(c.xp, xp_per, 12)
                    print(f"  {C_DIM}  {xp_display} {c.xp}/{xp_per} XP{C_RESET}")
            elif c.level < max_lvl:
                # Show XP gain and progress bar
                xp_display = xp_bar(c.xp, xp_per, 12)
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                print(f"  {shade_c}{c.name}{C_RESET} +{xp_gain} XP  {xp_display} {c.xp}/{xp_per}  Lv{c.level}")
            else:
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                print(f"  {shade_c}{c.name}{C_RESET} Lv{c.level} {C_AMBER}MAX{C_RESET}")

        return won

    # --- Recruitment screen ---

    def recruitment_screen(self, enemy):
        """Show recruitment splash after defeating a normal Shade."""
        block_reason = self._recruit_block_reason(enemy)
        if block_reason:
            print(f"  {C_DIM}No recruitment: {block_reason}.{C_RESET}")
            return

        template = COMPANION_TEMPLATES.get(enemy.companion_type)
        if not template:
            return

        shade_key = enemy.companion_type
        sig = SHADE_SIGNATURES.get(shade_key, "")
        quote = SHADE_QUOTES.get(shade_key, "")
        ability_info = SHADE_ABILITY_DESC.get(template["effect_type"], ("", "", ""))
        ability_name, ability_desc, activation_label = ability_info
        capture_bonus = getattr(self, "_last_capture_bonus", 0.0)
        capture_bonus_reasons = getattr(self, "_last_capture_bonus_reasons", [])
        capture_chance = min(
            0.95,
            capture_chance_for_rarity(self.config, enemy.rarity, enemy.capture_roll) + capture_bonus,
        )
        power_mult = enemy.capture_power_mult

        # Dramatic reveal before the splash
        beat(0.3)
        typewrite(f"  {C_PHANTOM}A spirit lingers at the table...{C_RESET}", delay=0.03)
        beat(0.3)

        # Build framed splash
        lines = [
            "",
            f"  {C_BGREEN}SPIRIT UNBOUND{C_RESET}",
            "",
            f"  {C_BWHITE}{template['name']}{C_RESET} [{sig}]",
            f"  {C_PHANTOM}\"{quote}\"{C_RESET}",
            "",
            f"  {ability_name}: {ability_desc}",
            f"  Activation: {activation_label}",
            f"  Capture chance: {capture_chance*100:.0f}% ({enemy.rarity})",
            f"  Effect power: x{power_mult:.2f}",
            f"  Shade roll: x{enemy.capture_roll:.2f}",
            "",
        ]
        if capture_bonus_reasons:
            lines.append("  Bonus chance:")
            for reason in capture_bonus_reasons:
                lines.append(f"    + {reason}")
            lines.append("")

        max_width = max((plain_len(l) for l in lines), default=30) + 2
        max_width = max(max_width, 47)

        print()
        print(f"  {C_DIM}\u250c{'─' * max_width}\u2510{C_RESET}")
        for line in lines:
            padding = max_width - plain_len(line)
            print(f"  {C_DIM}\u2502{C_RESET}{line}{' ' * padding}{C_DIM}\u2502{C_RESET}")
        choice_line = f"  [R]ecruit    [F]ree"
        padding = max_width - plain_len(choice_line)
        print(f"  {C_DIM}\u2502{C_RESET}{choice_line}{' ' * padding}{C_DIM}\u2502{C_RESET}")
        print(f"  {C_DIM}\u2502{' ' * max_width}\u2502{C_RESET}")
        print(f"  {C_DIM}\u2514{'─' * max_width}\u2518{C_RESET}")
        print()

        choice = prompt_choice("", ["r", "f"], {"r": "RECRUIT", "f": "FREE"})

        if choice == "r":
            if random.random() < capture_chance:
                act_key = template.get("activation", "always")
                comp = Companion(
                    name=template["name"],
                    companion_type=enemy.companion_type,
                    effect_type=template["effect_type"],
                    base_value=template["base_value"],
                    per_level=template["per_level"],
                    activation=act_key,
                    source_rarity=enemy.rarity,
                    power_multiplier=power_mult,
                )
                placement = self.player.add_captured_companion(comp)
                desc = activation_desc(act_key)
                if placement == "active":
                    placement_msg = f"joins active Shades ({len(self.player.companions)}/{self.player.max_companion_slots})"
                elif placement == "replaced":
                    placement_msg = "takes an active slot (prior Shade moved to reserve)"
                else:
                    placement_msg = f"added to reserve ({len(self.player.reserve_companions)} stored)"
                print(f"  {C_BGREEN}{comp.name} {placement_msg}.{C_RESET}")
                print(f"  {C_GREEN}Activation: {desc} | {enemy.rarity} x{power_mult:.2f}{C_RESET}")
            else:
                print(f"  {C_RED}{template['name']} slips away...{C_RESET}")
        else:
            heal = self.config.reward.heal_amount
            old_hp = self.player.hp
            self.player.heal(heal)
            print(f"  {C_GREEN}{template['name']} fades into the dark.{C_RESET}")
            print(f"  {C_GREEN}+{self.player.hp - old_hp} chips{C_RESET} ({old_hp} -> {self.player.hp})")

        pause()

    # --- Post-fight reward ---

    def post_fight_reward(
        self,
        enemy,
        title="REWARD",
        allow_heal=True,
        allow_remove=True,
        allow_enchant=True,
        allow_fold=True,
    ):
        print()
        self.show_status()
        print(f"\n  {C_AMBER}--- {title} ---{C_RESET}")

        # Build options mapped to arrow directions
        arrows = ["left", "right", "down"]
        arrow_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}
        options = []       # (label, action_id)

        # Option: Remove a card
        removable = self.deck.removable_ranks(self.config.reward.min_deck_size)
        if allow_remove and removable:
            options.append(("Remove a card", "remove"))

        # Option: Heal
        heal_amount = (
            self.config.reward.heal_amount_elite
            if enemy.tier in ("elite", "boss")
            else self.config.reward.heal_amount
        )
        if allow_heal and self.player.hp < self.player.max_hp:
            options.append((f"Heal {heal_amount} chips", "heal"))

        # Option: Enchant a card
        ecfg = self.config.enchantment
        enchantable = self.deck.enchantable_cards(1, ecfg.max_per_card)
        if allow_enchant and enchantable:
            options.append(("Enchant a card", "enchant"))

        # Option: Gain folds
        fold_amt = self.config.fold.fold_reward_amount
        if allow_fold:
            options.append((f"Gain {fold_amt} folds", "fold_reward"))

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
            print(f"  {C_GREEN}Healed {self.player.hp - old_hp} chips{C_RESET} ({old_hp} -> {self.player.hp})")
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

        card_arrows = ["left", "right", "down"]
        card_syms = {"left": "\u2190", "right": "\u2192", "down": "\u2193"}
        card_keys = []
        card_labels = {}
        card_map = {}

        print(f"\n  Pick a card to enchant:")
        for i, card in enumerate(cards):
            key = card_arrows[i]
            card_keys.append(key)
            card_labels[key] = show_card(card)
            card_map[key] = card
            ench = self.deck.get_enchantments(card)
            ench_str = ""
            if ench:
                tags = ", ".join(e.capitalize() for e in ench)
                ench_str = f"  ({tags})"
            print(f"    {card_syms[key]} {show_card(card)}{ench_str}")

        choice = prompt_choice("  >", card_keys, card_labels)
        chosen_card = card_map[choice]

        # Offer enchantment types
        from .engine import ENCHANTMENT_TYPES
        offered = random.sample(ENCHANTMENT_TYPES, min(ecfg.types_offered, len(ENCHANTMENT_TYPES)))

        type_labels = {
            "fury": f"Fury (+{ecfg.fury_damage} dmg on wins)",
            "siphon": f"Siphon (heal {ecfg.siphon_heal} any hand)",
            "ward": f"Ward (-{ecfg.ward_reduction} dmg on losses)",
            "echo": "Echo (duplicates other enchantments on same card)",
            "gambit": f"Gambit (+dmg scaling with bust risk when you stand)",
            "hex": f"Hex (+{ecfg.hex_bleed_per_play} bleed per round, stacks all fight)",
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
        static_burst(width=49, height=3, duration=0.12)
        crt_wipe()
        print()
        beat(0.3)
        typewrite(f"  {C_BWHITE}ACT {act_num}{C_RESET}", delay=0.05)
        print()
        print(f"  {C_DIM}The candles gutter. Silence returns.{C_RESET}")
        beat(0.4)
        print()
        healed = self.player.hp - old_hp
        print(f"  {C_GREEN}+{healed} chips{C_RESET}  ({old_hp} \u2192 {self.player.hp})")
        animate_hp_change(old_hp, self.player.hp, self.player.max_hp)
        print()
        if self.player.companions:
            for c in self.player.companions:
                hint_c = colorize_hint(c.activation)
                suffix = f" [{hint_c}]" if hint_c else ""
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                print(f"  {shade_c}{c.name}{C_RESET} Lv{c.level}{suffix}")
            print()
        crt_wipe()
        pause()

    # --- Main loop ---

    def run(self):
        clear()
        print()
        crt_wipe()
        print()
        # Dead man's hand: A♠ 8♣ A♣ 8♠
        print(f"        {C_DIM}┌───┐ ┌───┐ ┌───┐ ┌───┐{C_RESET}")
        beat(0.1)
        print(f"        {C_DIM}│{C_RESET}{C_BWHITE} A\u2660{C_RESET}{C_DIM}│{C_RESET} {C_DIM}│{C_RESET}{C_BWHITE} 8\u2663{C_RESET}{C_DIM}│{C_RESET} {C_DIM}│{C_RESET}{C_BWHITE} A\u2663{C_RESET}{C_DIM}│{C_RESET} {C_DIM}│{C_RESET}{C_BWHITE} 8\u2660{C_RESET}{C_DIM}│{C_RESET}")
        beat(0.1)
        print(f"        {C_DIM}└───┘ └───┘ └───┘ └───┘{C_RESET}")
        print()
        typewrite(f"  {C_BGREEN}BUST: THE DEAD MAN'S HAND{C_RESET}", delay=0.04)
        print()
        crt_wipe()
        print()
        beat(0.3)
        print(f"  {C_GREEN}Summon the dead. Beat them at cards.{C_RESET}")
        beat(0.1)
        print(f"  {C_GREEN}Closer to 21 wins. Go over and you bust.{C_RESET}")
        beat(0.1)
        print(f"  {C_GREEN}Bind the Shades you defeat. They'll play for you.{C_RESET}")
        print()
        beat(0.1)
        print(f"  {C_GREEN}Survive 3 acts and walk free.{C_RESET}")
        print()
        print(f"  {C_DIM}\u2192 hit  \u2190 stand  \u2193 fold  \u2191 info  r rules{C_RESET}")
        print()
        pause()

        act_maps = [generate_act_map(a, self.config) for a in range(self.config.run.acts)]
        fight_num = 0
        total_fights = sum(
            1 for am in act_maps for n in am.nodes
            if n.node_type in COMBAT_NODE_TYPES
        )

        for act_idx, act_map in enumerate(act_maps):
            if act_idx > 0:
                self.between_acts(act_idx + 1)

            self._current_act_map = act_map
            self.show_act_overview(act_map)
            current = act_map.start_node()

            while current:
                current.visited = True
                self._current_node = current

                if current.node_type in COMBAT_NODE_TYPES:
                    fight_num += 1
                    enemy = self.create_enemy(current.enemy_key, act_idx)
                    won = self.play_fight(enemy, fight_num, total_fights, act_idx + 1)

                    if not self.player.alive:
                        print()
                        beat(0.5)
                        static_burst(width=49, height=4, duration=0.2)
                        print()
                        shake_line(f"{C_BRED}B U R I E D{C_RESET}", intensity=3, count=5, delay=0.05)
                        print()
                        beat(0.3)
                        typewrite(f"  {C_DIM}Claimed at séance {fight_num} of {total_fights}.{C_RESET}", delay=0.03)
                        beat(0.2)
                        typewrite(f"  {C_DIM}Taken by: {enemy.name}{C_RESET}", delay=0.03)
                        print()
                        crt_wipe()
                        self.show_final()
                        return

                    if won:
                        self.recruitment_screen(enemy)
                        if current.node_type == NodeType.BOSS:
                            self.post_fight_reward(enemy, title="BOSS REWARD")

                elif current.node_type == NodeType.BARROW:
                    self.barrow_screen()
                elif current.node_type == NodeType.VIGIL:
                    self.vigil_screen()
                elif current.node_type == NodeType.CROSSROADS:
                    self.crossroads_screen()

                # Advance to next node
                children = act_map.get_children(current.node_id)
                if not children:
                    break
                elif len(children) == 1:
                    current = children[0]
                else:
                    current = self.fork_selection(children)

        # Victory
        clear()
        print()
        crt_wipe()
        print()
        typewrite(f"  {C_BGREEN}F R E E D O M{C_RESET}", delay=0.06)
        print()
        beat(0.4)
        print(f"  {C_GREEN}Survived all {total_fights} séances.{C_RESET}")
        beat(0.2)
        typewrite(f"  {C_GREEN}The dead have no claim on you.{C_RESET}", delay=0.03)
        print()
        color = hp_color(self.player.hp, self.player.max_hp)
        print(f"  Final Chips: {color}{self.player.hp}/{self.player.max_hp}{C_RESET}")
        print()
        crt_wipe()
        self.show_final()

    def show_final(self):
        if self.player.companions:
            print(f"\n  Active Shades:")
            for c in self.player.companions:
                effect = describe_companion_effect(c.effect_type)
                hint_c = colorize_hint(c.activation)
                suffix = f" [{hint_c}]" if hint_c else ""
                shade_c = SHADE_COLORS.get(c.companion_type, C_GREEN)
                print(f"    {shade_c}{c.name}{C_RESET} Lv{c.level} -- {effect}: {c.effect_value:.1f}{suffix}")
        if self.player.reserve_companions:
            print(f"\n  Reserve Shades:")
            for c in self.player.reserve_companions:
                effect = describe_companion_effect(c.effect_type)
                print(f"    {C_DIM}{c.name}{C_RESET} Lv{c.level} -- {effect}: {c.effect_value:.1f}")
        print()


def main():
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
