"""
Metrics computation, experience quality evaluation, and reporting.
"""
from collections import Counter
from typing import List, Dict
from .config import GameConfig, ExperienceTarget
from .engine import RunResult, REWARD_TYPES


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_metrics(results: List[RunResult], config: GameConfig) -> Dict:
    total_runs = len(results)
    if total_runs == 0:
        return {}

    survived = sum(1 for r in results if r.survived)

    all_hands = []
    all_fights = []
    all_decisions = []
    act_damages: Dict[int, List[float]] = {}
    enemy_ai_totals = Counter()
    enemy_ai_by_tier: Dict[str, Counter] = {}
    split_hands = 0
    synergy_hands = 0
    counterplay_cases = 0
    counterplay_successes = 0
    high_total_cases = 0
    high_total_losses = 0
    reward_variety_samples: List[float] = []
    pivot_eligible_runs = 0
    pivot_success_runs = 0
    early_spike_runs = 0
    midrun_novelty_total = 0
    midrun_novelty_new = 0
    companion_attachment_runs = 0
    high_comp_total = high_comp_survived = 0
    low_comp_total = low_comp_survived = 0

    fights_per_act = config.run.fights_per_act + config.run.elites_per_act + 1

    for run in results:
        seen_enemies = set()
        run_early_spike = False
        rewards = [r for r in run.rewards_chosen if r]
        if rewards:
            reward_variety_samples.append(len(set(rewards)) / len(REWARD_TYPES))
        else:
            reward_variety_samples.append(0.0)

        if len(rewards) >= 4:
            pivot_eligible_runs += 1
            split_at = len(rewards) // 2
            left = rewards[:split_at]
            right = rewards[split_at:]
            if left and right:
                left_dom = Counter(left).most_common(1)[0][0]
                right_dom = Counter(right).most_common(1)[0][0]
                if left_dom != right_dom and len(set(rewards)) >= 2:
                    pivot_success_runs += 1

        if any(level >= 3 for level in run.companion_levels.values()):
            companion_attachment_runs += 1

        comp_count = len(run.companions_captured)
        if comp_count >= 2:
            high_comp_total += 1
            high_comp_survived += 1 if run.survived else 0
        elif comp_count <= 1:
            low_comp_total += 1
            low_comp_survived += 1 if run.survived else 0

        for i, fight in enumerate(run.fights):
            all_fights.append(fight)
            act = min(i // fights_per_act, config.run.acts - 1)
            act_damages.setdefault(act, []).append(fight.total_damage_dealt)
            if (
                act == 0
                and fight.player_won
                and len(fight.hands) <= 3
                and fight.total_damage_dealt >= 8
            ):
                run_early_spike = True
            if act >= 1:
                midrun_novelty_total += 1
                if fight.enemy_name not in seen_enemies:
                    midrun_novelty_new += 1
            seen_enemies.add(fight.enemy_name)

            for hand in fight.hands:
                all_hands.append(hand)
                all_decisions.extend(hand.decision_points)
                if hand.was_split:
                    split_hands += 1
                if len(hand.companion_effects) >= 2:
                    synergy_hands += 1
                if (not hand.player_busted and hand.outcome != "fold" and hand.player_value >= 19):
                    high_total_cases += 1
                    if hand.outcome == "lose":
                        high_total_losses += 1
                ai = getattr(hand, "enemy_ai", {}) or {}
                if ai:
                    enemy_ai_totals.update(ai)
                    tier_ctr = enemy_ai_by_tier.setdefault(fight.enemy_tier, Counter())
                    tier_ctr.update(ai)
                    if ai.get("chase_hits", 0) > 0 and not hand.player_busted and hand.outcome != "fold":
                        counterplay_cases += 1
                        if hand.outcome in ("win", "push"):
                            counterplay_successes += 1

        if run_early_spike:
            early_spike_runs += 1

    total_hands = len(all_hands)
    total_fights = len(all_fights)

    # Decision tension
    tense = sum(1 for d in all_decisions if d.is_tense)
    decision_tension = tense / len(all_decisions) if all_decisions else 0

    # Fight length
    fight_lengths = [len(f.hands) for f in all_fights]
    avg_fight_length = sum(fight_lengths) / len(fight_lengths) if fight_lengths else 0

    # Bust rates
    p_busts = sum(1 for h in all_hands if h.player_busted)
    e_busts = sum(1 for h in all_hands if h.enemy_busted)

    # Natural 21 rate
    nat21s = sum(1 for h in all_hands if h.player_natural)

    # Outcomes
    wins = sum(1 for h in all_hands if h.outcome == "win")
    losses = sum(1 for h in all_hands if h.outcome == "lose")
    pushes = sum(1 for h in all_hands if h.outcome == "push")
    folds = sum(1 for h in all_hands if h.outcome == "fold")

    # Close calls (within 2, not a push, neither busted)
    close = sum(
        1 for h in all_hands
        if not h.player_busted and not h.enemy_busted
        and abs(h.player_value - h.enemy_value) <= 2
        and h.outcome != "push"
    )

    # Damage
    avg_dmg_dealt = sum(h.damage_dealt for h in all_hands) / total_hands if total_hands else 0
    avg_dmg_taken = sum(h.damage_taken for h in all_hands) / total_hands if total_hands else 0

    # Companions
    total_captured = sum(len(r.companions_captured) for r in results)
    companion_hands = sum(1 for h in all_hands if h.companion_effects)

    # Snowball ratio
    last_act = config.run.acts - 1
    if act_damages.get(0) and act_damages.get(last_act):
        avg_a1 = sum(act_damages[0]) / len(act_damages[0])
        avg_a3 = sum(act_damages[last_act]) / len(act_damages[last_act])
        snowball = avg_a3 / avg_a1 if avg_a1 > 0 else 1.0
    else:
        snowball = 1.0

    # Fold rate
    fold_rate = folds / total_hands if total_hands else 0

    # Deck trim (avg cards removed per run)
    avg_cards_removed = sum(r.cards_removed for r in results) / total_runs

    # Enchantments
    avg_enchantments = sum(r.enchantments_applied for r in results) / total_runs

    # Power curve ratio: win rate in last act vs first act
    # This captures deck manipulation + companion growth together
    act_wins: Dict[int, List[int]] = {}
    for run in results:
        for i, fight in enumerate(run.fights):
            act = min(i // fights_per_act, config.run.acts - 1)
            for hand in fight.hands:
                if hand.outcome != "fold":
                    act_wins.setdefault(act, []).append(1 if hand.outcome == "win" else 0)

    last_act = config.run.acts - 1
    if act_wins.get(0) and act_wins.get(last_act):
        wr_a1 = sum(act_wins[0]) / len(act_wins[0])
        wr_a3 = sum(act_wins[last_act]) / len(act_wins[last_act])
        power_curve_ratio = wr_a3 / wr_a1 if wr_a1 > 0 else 1.0
    else:
        power_curve_ratio = 1.0

    # --- Highlights ---
    # Memorable moments (rare, unexpected, tell-your-friend worthy)
    MEMORABLE = {
        "natural_21", "enemy_natural_21",
        "close_win", "close_loss",
        "cruel_bust", "five_card",
        "companion_save", "clutch_win",
        "nine_lives",
    }
    # Routine ability events (happen every hand against that enemy type)
    # Tracked for info but don't count toward highlight rate.

    all_highlights = []
    for h in all_hands:
        all_highlights.extend(h.highlights)
    highlight_counts = Counter(all_highlights)

    # Only count memorable moments for the highlight rate
    memorable_hands = sum(
        1 for h in all_hands
        if any(hl in MEMORABLE for hl in h.highlights)
    )
    highlight_rate = memorable_hands / total_hands if total_hands else 0

    ai_hits = enemy_ai_totals.get("hits", 0)
    ai_stands = enemy_ai_totals.get("stands", 0)
    ai_total_decisions = ai_hits + ai_stands

    enemy_ai_metrics = {
        "hit_rate": ai_hits / ai_total_decisions if ai_total_decisions else 0,
        "chase_hit_rate": enemy_ai_totals.get("chase_hits", 0) / ai_hits if ai_hits else 0,
        "risk_hit_rate": enemy_ai_totals.get("risk_hits", 0) / ai_hits if ai_hits else 0,
        "reckless_hit_rate": enemy_ai_totals.get("reckless_hits", 0) / ai_hits if ai_hits else 0,
        "safe_stand_rate": enemy_ai_totals.get("safe_stands", 0) / ai_stands if ai_stands else 0,
    }

    enemy_ai_tier_metrics = {}
    for tier, ctr in enemy_ai_by_tier.items():
        th = ctr.get("hits", 0)
        ts = ctr.get("stands", 0)
        td = th + ts
        enemy_ai_tier_metrics[tier] = {
            "hit_rate": th / td if td else 0,
            "chase_hit_rate": ctr.get("chase_hits", 0) / th if th else 0,
            "risk_hit_rate": ctr.get("risk_hits", 0) / th if th else 0,
            "safe_stand_rate": ctr.get("safe_stands", 0) / ts if ts else 0,
        }

    elite_ai = enemy_ai_tier_metrics.get("elite", {})
    boss_ai = enemy_ai_tier_metrics.get("boss", {})
    if high_comp_total > 0 and low_comp_total > 0:
        companion_meaningfulness = (
            (high_comp_survived / high_comp_total) - (low_comp_survived / low_comp_total)
        ) * 100
    else:
        companion_meaningfulness = 0.0

    return {
        "total_runs": total_runs,
        "total_hands": total_hands,
        "total_fights": total_fights,
        "survival_rate": survived / total_runs,
        "decision_tension": decision_tension,
        "avg_fight_length": avg_fight_length,
        "player_bust_rate": p_busts / total_hands if total_hands else 0,
        "enemy_bust_rate": e_busts / total_hands if total_hands else 0,
        "natural_21_rate": nat21s / total_hands if total_hands else 0,
        "win_rate": wins / total_hands if total_hands else 0,
        "loss_rate": losses / total_hands if total_hands else 0,
        "push_rate": pushes / total_hands if total_hands else 0,
        "fold_rate": fold_rate,
        "close_call_rate": close / total_hands if total_hands else 0,
        "avg_damage_dealt": avg_dmg_dealt,
        "avg_damage_taken": avg_dmg_taken,
        "avg_companions_captured": total_captured / total_runs,
        "companion_effect_rate": companion_hands / total_hands if total_hands else 0,
        "snowball_ratio": snowball,
        "avg_encounters_completed": sum(r.encounters_completed for r in results) / total_runs,
        "avg_cards_removed": avg_cards_removed,
        "avg_enchantments": avg_enchantments,
        "power_curve_ratio": power_curve_ratio,
        # Fun model metrics
        "split_rate": split_hands / total_hands if total_hands else 0,
        "counterplay_success_rate": (
            counterplay_successes / counterplay_cases if counterplay_cases else 0
        ),
        "reward_variety_rate": (
            sum(reward_variety_samples) / len(reward_variety_samples)
            if reward_variety_samples else 0
        ),
        "build_pivot_rate": (
            pivot_success_runs / pivot_eligible_runs if pivot_eligible_runs else 0
        ),
        "synergy_online_rate": synergy_hands / total_hands if total_hands else 0,
        "early_spike_rate": early_spike_runs / total_runs if total_runs else 0,
        "midrun_novelty_rate": (
            midrun_novelty_new / midrun_novelty_total if midrun_novelty_total else 0
        ),
        "companion_attachment_rate": companion_attachment_runs / total_runs if total_runs else 0,
        "companion_meaningfulness": companion_meaningfulness,
        "high_total_loss_rate": (
            high_total_losses / high_total_cases if high_total_cases else 0
        ),
        # Flattened AI metrics for target evaluation
        "enemy_hit_rate": enemy_ai_metrics["hit_rate"],
        "enemy_chase_hit_rate": enemy_ai_metrics["chase_hit_rate"],
        "enemy_risk_hit_rate": enemy_ai_metrics["risk_hit_rate"],
        "enemy_safe_stand_rate": enemy_ai_metrics["safe_stand_rate"],
        "elite_chase_hit_rate": elite_ai.get("chase_hit_rate", 0),
        "boss_chase_hit_rate": boss_ai.get("chase_hit_rate", 0),
        # Highlights
        "highlight_rate": highlight_rate,
        "highlight_counts": dict(highlight_counts),
        "highlight_total": len(all_highlights),
        # Enemy AI telemetry
        "enemy_ai_counts": dict(enemy_ai_totals),
        "enemy_ai_metrics": enemy_ai_metrics,
        "enemy_ai_tier_metrics": enemy_ai_tier_metrics,
    }


# ---------------------------------------------------------------------------
# Experience quality evaluation
# ---------------------------------------------------------------------------
METRIC_MAP = {
    "decision_tension": "decision_tension",
    "highlight_rate": "highlight_rate",
    "survival_rate": "survival_rate",
    "avg_fight_length": "avg_fight_length",
    "snowball_ratio": "snowball_ratio",
    "fold_rate": "fold_rate",
    "deck_trim": "avg_cards_removed",
    "power_curve_ratio": "power_curve_ratio",
    "enemy_hit_rate": "enemy_hit_rate",
    "enemy_chase_hit_rate": "enemy_chase_hit_rate",
    "enemy_risk_hit_rate": "enemy_risk_hit_rate",
    "enemy_safe_stand_rate": "enemy_safe_stand_rate",
    "elite_chase_hit_rate": "elite_chase_hit_rate",
    "boss_chase_hit_rate": "boss_chase_hit_rate",
    "split_rate": "split_rate",
    "counterplay_success_rate": "counterplay_success_rate",
    "reward_variety_rate": "reward_variety_rate",
    "build_pivot_rate": "build_pivot_rate",
    "synergy_online_rate": "synergy_online_rate",
    "early_spike_rate": "early_spike_rate",
    "midrun_novelty_rate": "midrun_novelty_rate",
    "companion_attachment_rate": "companion_attachment_rate",
    "companion_meaningfulness": "companion_meaningfulness",
    "high_total_loss_rate": "high_total_loss_rate",
}


def evaluate_targets(metrics: Dict, targets: List[ExperienceTarget]) -> Dict:
    results = {}
    for t in targets:
        key = METRIC_MAP.get(t.name)
        if not key or key not in metrics:
            continue
        raw = metrics[key]
        display = raw * 100 if t.unit == "%" else raw
        results[t.name] = {
            "target": t,
            "value": display,
            "in_range": t.target_min <= display <= t.target_max,
        }
    return results


# ---------------------------------------------------------------------------
# Recommendations engine
# ---------------------------------------------------------------------------
def generate_recommendations(metrics: Dict, target_results: Dict, config: GameConfig) -> List[str]:
    recs = []

    for name, result in target_results.items():
        if result["in_range"]:
            continue

        t = result["target"]
        v = result["value"]
        low = v < t.target_min

        if name == "survival_rate":
            if low:
                recs.append(f"Survival rate too low ({v:.1f}%). Consider:")
                recs.append(f"  - Increase player.starting_hp (now {config.player.starting_hp})")
                recs.append(f"  - Increase run.heal_between_acts_pct (now {config.run.heal_between_acts_pct})")
                recs.append(f"  - Decrease enemy HP values in ENEMY_TEMPLATES")
            else:
                recs.append(f"Survival rate too high ({v:.1f}%). Consider:")
                recs.append(f"  - Decrease player.starting_hp (now {config.player.starting_hp})")
                recs.append(f"  - Increase enemy HP values")

        elif name == "decision_tension":
            if low:
                recs.append(f"Decision tension too low ({v:.1f}%). Too many auto-pilot decisions. Consider:")
                recs.append(f"  - Enemy hit_thresholds may be too extreme (all 13 or all 18)")
                recs.append(f"  - Deck composition might make hits always safe or always deadly")
            else:
                recs.append(f"Decision tension very high ({v:.1f}%). Every hand is a coinflip. Consider:")
                recs.append(f"  - This might be fine (lots of interesting decisions)")
                recs.append(f"  - If it feels random, add more info sources (peek companions)")

        elif name == "highlight_rate":
            if low:
                recs.append(f"Highlight rate too low ({v:.1f}%). Not enough memorable moments. Consider:")
                recs.append(f"  - Add more enemy abilities that create visible events")
                recs.append(f"  - Increase companion effect magnitudes (more saves)")
                recs.append(f"  - Add more enemies with extreme thresholds for bust drama")
            else:
                recs.append(f"Highlight rate too high ({v:.1f}%). If everything is special, nothing is. Consider:")
                recs.append(f"  - Reduce enemy ability trigger rates")
                recs.append(f"  - Make highlights rarer but more impactful")

        elif name == "avg_fight_length":
            if low:
                recs.append(f"Fights too short ({v:.1f} hands). Consider:")
                recs.append(f"  - Increase enemy HP values")
            else:
                recs.append(f"Fights too long ({v:.1f} hands). Consider:")
                recs.append(f"  - Decrease enemy HP values")

        elif name == "snowball_ratio":
            if low:
                recs.append(f"No power growth ({v:.2f}x). Companions don't scale. Consider:")
                recs.append(f"  - Increase companion base_value / per_level")
                recs.append(f"  - Increase capture_chance (now {config.companion.capture_chance})")
            else:
                recs.append(f"Too much snowball ({v:.2f}x). Player becomes unstoppable. Consider:")
                recs.append(f"  - Decrease companion effect values")
                recs.append(f"  - Increase companion.xp_per_level (now {config.companion.xp_per_level})")

        elif name == "companion_impact":
            if low:
                recs.append(f"Companion impact too low ({v:.1f}%). Consider:")
                recs.append(f"  - Increase companion effect magnitudes in COMPANION_TEMPLATES")
                recs.append(f"  - Increase capture_chance (now {config.companion.capture_chance})")
            else:
                recs.append(f"Companion impact too high ({v:.1f}%). Consider:")
                recs.append(f"  - Decrease companion effect magnitudes")

        elif name == "strategy_skill_gap":
            if low:
                recs.append(f"Skill gap too small ({v:.1f}pp). Game feels random. Consider:")
                recs.append(f"  - Add more decision-relevant mechanics (peek, information)")
                recs.append(f"  - Make bust penalties harsher so mistakes cost more")
            else:
                recs.append(f"Skill gap too large ({v:.1f}pp). Might feel too solvable. Consider:")
                recs.append(f"  - Add more variance (random enemy abilities, events)")

        elif name == "fold_rate":
            if low:
                recs.append(f"Fold rate too low ({v:.1f}%). Players never fold. Consider:")
                recs.append(f"  - Increase fold_damage penalty or make raging enemies scarier")
            else:
                recs.append(f"Fold rate too high ({v:.1f}%). Players fold too much. Consider:")
                recs.append(f"  - Reduce fold_damage or increase fold risk")

        elif name == "deck_trim":
            if low:
                recs.append(f"Deck trim too low ({v:.1f} cards). Power curve is flat. Consider:")
                recs.append(f"  - Reward strategy may prefer healing too much")
                recs.append(f"  - Increase reward frequency or reduce min_deck_size")
            else:
                recs.append(f"Deck trim too high ({v:.1f} cards). Deck gets too small. Consider:")
                recs.append(f"  - Increase min_deck_size (now {config.reward.min_deck_size})")

        elif name == "power_curve_ratio":
            if low:
                recs.append(f"Power curve too flat ({v:.2f}x). Hands don't improve. Consider:")
                recs.append(f"  - Reward strategy not removing enough low cards")
                recs.append(f"  - Deck manipulation may need tuning")
            else:
                recs.append(f"Power curve too steep ({v:.2f}x). Late game too easy. Consider:")
                recs.append(f"  - Increase act_hp_multipliers to compensate")

        elif name == "enemy_hit_rate":
            if low:
                recs.append(f"Enemy hit rate too low ({v:.1f}%). AI may feel passive. Consider:")
                recs.append(f"  - Increase enemy target pressure when behind")
                recs.append(f"  - Raise elite/boss bust tolerance slightly")
            else:
                recs.append(f"Enemy hit rate too high ({v:.1f}%). AI may feel reckless. Consider:")
                recs.append(f"  - Lower bust-risk tolerance in enemy policy")
                recs.append(f"  - Increase stand bias for attrition enemies")

        elif name == "enemy_chase_hit_rate":
            if low:
                recs.append(f"Enemy chase-hit rate too low ({v:.1f}%). AI may miss comeback pressure. Consider:")
                recs.append(f"  - Increase chase branch weight when enemy trails player hand")
            else:
                recs.append(f"Enemy chase-hit rate too high ({v:.1f}%). AI may overforce races. Consider:")
                recs.append(f"  - Require lower bust odds before chase hits")

        elif name == "enemy_risk_hit_rate":
            if low:
                recs.append(f"Enemy high-risk hit rate too low ({v:.1f}%). Behavior may feel too safe. Consider:")
                recs.append(f"  - Increase risk appetite for volatile enemies (reckless/nine lives)")
            else:
                recs.append(f"Enemy high-risk hit rate too high ({v:.1f}%). AI may feel random. Consider:")
                recs.append(f"  - Tighten bust thresholds on borderline hit decisions")

        elif name == "enemy_safe_stand_rate":
            if low:
                recs.append(f"Enemy safe-stand rate too low ({v:.1f}%). AI may throw winning positions. Consider:")
                recs.append(f"  - Increase stand preference when already ahead")
            else:
                recs.append(f"Enemy safe-stand rate too high ({v:.1f}%). AI may feel over-scripted. Consider:")
                recs.append(f"  - Add selective chase hits from advantaged states")

        elif name == "elite_chase_hit_rate":
            if low:
                recs.append(f"Elite chase-hit rate too low ({v:.1f}%). Elites may not pressure enough. Consider:")
                recs.append(f"  - Raise elite chase aggression when behind strong player totals")
            else:
                recs.append(f"Elite chase-hit rate too high ({v:.1f}%). Elites may overcommit. Consider:")
                recs.append(f"  - Decrease elite chase chance on high bust odds")

        elif name == "boss_chase_hit_rate":
            if low:
                recs.append(f"Boss chase-hit rate too low ({v:.1f}%). Bosses may feel too tame. Consider:")
                recs.append(f"  - Increase boss endgame pressure when trailing")
            else:
                recs.append(f"Boss chase-hit rate too high ({v:.1f}%). Bosses may feel all-in every hand. Consider:")
                recs.append(f"  - Require stricter odds before boss chase hits")

        elif name == "split_rate":
            if low:
                recs.append(f"Split rate too low ({v:.1f}%). Splitting may not feel meaningful. Consider:")
                recs.append(f"  - Improve split heuristics for basic/smart strategies")
                recs.append(f"  - Increase split payoff on strong pair breakouts")
            else:
                recs.append(f"Split rate too high ({v:.1f}%). Splitting may be over-centralizing. Consider:")
                recs.append(f"  - Narrow split conditions for medium-value pairs")

        elif name == "counterplay_success_rate":
            if low:
                recs.append(f"Counterplay success too low ({v:.1f}%). Enemy pressure may feel unfair. Consider:")
                recs.append(f"  - Add clearer intent windows before chase-heavy enemy lines")
            else:
                recs.append(f"Counterplay success too high ({v:.1f}%). Enemy threats may feel toothless. Consider:")
                recs.append(f"  - Raise chase pressure when player shows high totals")

        elif name == "reward_variety_rate":
            if low:
                recs.append(f"Reward variety too low ({v:.1f}%). Runs may feel samey. Consider:")
                recs.append(f"  - Increase value of non-heal options in reward strategy")
            else:
                recs.append(f"Reward variety too high ({v:.1f}%). Build identity may get diluted. Consider:")
                recs.append(f"  - Strengthen specialization incentives for chosen archetypes")

        elif name == "build_pivot_rate":
            if low:
                recs.append(f"Build pivot rate too low ({v:.1f}%). Mid-run adaptation is weak. Consider:")
                recs.append(f"  - Add more conditional rewards that unlock late pivots")
            else:
                recs.append(f"Build pivot rate too high ({v:.1f}%). Runs may lack commitment. Consider:")
                recs.append(f"  - Increase payoff for sticking with established build lines")

        elif name == "synergy_online_rate":
            if low:
                recs.append(f"Synergy online rate too low ({v:.1f}%). Combo moments are too rare. Consider:")
                recs.append(f"  - Increase opportunities to stack enchantment + companion effects")
            else:
                recs.append(f"Synergy online rate too high ({v:.1f}%). Power spikes may be too frequent. Consider:")
                recs.append(f"  - Add diminishing returns for overlapping proc effects")

        elif name == "early_spike_rate":
            if low:
                recs.append(f"Early spike rate too low ({v:.1f}%). Early game may feel flat. Consider:")
                recs.append(f"  - Add stronger act-1 reward moments or earlier payoff events")
            else:
                recs.append(f"Early spike rate too high ({v:.1f}%). Early game may be too swingy. Consider:")
                recs.append(f"  - Smooth opening damage/reward variance")

        elif name == "midrun_novelty_rate":
            if low:
                recs.append(f"Mid-run novelty too low ({v:.1f}%). Act 2+ may feel repetitive. Consider:")
                recs.append(f"  - Increase encounter pattern variety after act 1")
            else:
                recs.append(f"Mid-run novelty too high ({v:.1f}%). Run identity may feel random. Consider:")
                recs.append(f"  - Reinforce recurring enemy themes across acts")

        elif name == "companion_attachment_rate":
            if low:
                recs.append(f"Companion attachment too low ({v:.1f}%). Pets may feel disposable. Consider:")
                recs.append(f"  - Increase companion leveling visibility and per-level impact")
            else:
                recs.append(f"Companion attachment too high ({v:.1f}%). Companion choices may become autopicks. Consider:")
                recs.append(f"  - Add more tradeoffs between companion scaling paths")

        elif name == "companion_meaningfulness":
            if low:
                recs.append(f"Companion meaningfulness too low ({v:.1f}pp). Captures may not matter enough. Consider:")
                recs.append(f"  - Increase companion effect magnitude or activation reliability")
            else:
                recs.append(f"Companion meaningfulness too high ({v:.1f}pp). Companions may dominate outcomes. Consider:")
                recs.append(f"  - Reduce companion scaling or make counters more available")

        elif name == "high_total_loss_rate":
            if low:
                recs.append(f"High-total loss rate too low ({v:.1f}%). End-of-hand drama may be muted. Consider:")
                recs.append(f"  - Let select enemies challenge 19-20 with situational aggression")
            else:
                recs.append(f"High-total loss rate too high ({v:.1f}%). Losses may feel unfair at strong totals. Consider:")
                recs.append(f"  - Reduce enemy over-chasing once player reaches 19+")

    return recs


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------
def print_report(
    metrics: Dict,
    target_results: Dict,
    strategy_comparison: Dict = None,
    recommendations: List[str] = None,
):
    print()
    print("=" * 62)
    print("  BLACKJACK ROGUELITE -- SIMULATION REPORT")
    print("=" * 62)

    print(f"\n  Runs: {metrics['total_runs']}  |  "
          f"Hands: {metrics['total_hands']}  |  "
          f"Fights: {metrics['total_fights']}")

    # --- Core stats ---
    print(f"\n--- CORE STATS ---")
    print(f"  Survival Rate:            {metrics['survival_rate']*100:.1f}%")
    print(f"  Avg Encounters Completed: {metrics['avg_encounters_completed']:.1f} / "
          f"{3 * (3 + 1 + 1)}")
    print(f"  Avg Fight Length:         {metrics['avg_fight_length']:.1f} hands")

    # --- Hand outcomes ---
    print(f"\n--- HAND OUTCOMES ---")
    print(f"  Win:       {metrics['win_rate']*100:.1f}%")
    print(f"  Lose:      {metrics['loss_rate']*100:.1f}%")
    print(f"  Push:      {metrics['push_rate']*100:.1f}%")
    print(f"  Fold:      {metrics['fold_rate']*100:.1f}%")
    print(f"  Player Bust Rate:  {metrics['player_bust_rate']*100:.1f}%")
    print(f"  Enemy Bust Rate:   {metrics['enemy_bust_rate']*100:.1f}%")
    print(f"  Natural 21 Rate:   {metrics['natural_21_rate']*100:.1f}%")
    print(f"  Close Calls:       {metrics['close_call_rate']*100:.1f}%")

    # --- Damage ---
    print(f"\n--- DAMAGE ---")
    print(f"  Avg Dealt / Hand:  {metrics['avg_damage_dealt']:.1f}")
    print(f"  Avg Taken / Hand:  {metrics['avg_damage_taken']:.1f}")

    # --- Companions ---
    print(f"\n--- COMPANIONS ---")
    print(f"  Avg Captured / Run:    {metrics['avg_companions_captured']:.2f}")
    print(f"  Effect Trigger Rate:   {metrics['companion_effect_rate']*100:.1f}%")
    print(f"  Snowball (Act 3/Act 1): {metrics['snowball_ratio']:.2f}x")

    # --- Power Curve ---
    print(f"\n--- POWER CURVE ---")
    print(f"  Avg Cards Removed / Run:    {metrics['avg_cards_removed']:.1f}")
    print(f"  Avg Enchantments / Run:     {metrics['avg_enchantments']:.1f}")
    print(f"  Power Curve Ratio:          {metrics['power_curve_ratio']:.3f}x")

    # --- Fun loop metrics ---
    print(f"\n--- FUN LOOP METRICS ---")
    print(f"  Split Rate:                 {metrics['split_rate']*100:.1f}%")
    print(f"  Counterplay Success:        {metrics['counterplay_success_rate']*100:.1f}%")
    print(f"  Reward Variety:             {metrics['reward_variety_rate']*100:.1f}%")
    print(f"  Build Pivot Rate:           {metrics['build_pivot_rate']*100:.1f}%")
    print(f"  Synergy Online Rate:        {metrics['synergy_online_rate']*100:.1f}%")
    print(f"  Early Spike Rate:           {metrics['early_spike_rate']*100:.1f}%")
    print(f"  Mid-run Novelty Rate:       {metrics['midrun_novelty_rate']*100:.1f}%")
    print(f"  Companion Attachment:       {metrics['companion_attachment_rate']*100:.1f}%")
    print(f"  Companion Meaningfulness:   {metrics['companion_meaningfulness']:.1f}pp")
    print(f"  High-total Loss Rate (19+): {metrics['high_total_loss_rate']*100:.1f}%")

    # --- Highlights ---
    print(f"\n--- MEMORABLE MOMENTS ---")
    hc = metrics.get("highlight_counts", {})
    ht = metrics["total_hands"]
    print(f"  Highlight Rate:    {metrics['highlight_rate']*100:.1f}% of hands  (memorable only)")
    memorable_types = [
        ("natural_21", "Natural 21 (player)"),
        ("enemy_natural_21", "Natural 21 (enemy)"),
        ("close_win", "Win by 1"),
        ("close_loss", "Lose by 1"),
        ("cruel_bust", "Bust on 22"),
        ("five_card", "5+ card hand"),
        ("companion_save", "Companion save (unbust)"),
        ("clutch_win", "Clutch win (<20% HP)"),
        ("nine_lives", "Nine Lives triggered"),
    ]
    for key, label in memorable_types:
        count = hc.get(key, 0)
        if count > 0:
            pct = count / ht * 100
            print(f"    {label:28s}  {count:>6}  ({pct:.1f}%)")

    # --- Ability events (routine, not counted as highlights) ---
    ability_types = [
        ("shell_block", "Shell absorbed damage"),
        ("rage_stack", "Rage escalation"),
        ("poison_tick", "Poison tick"),
        ("drain_heal", "Lich drain heal"),
    ]
    has_abilities = any(hc.get(k, 0) > 0 for k, _ in ability_types)
    if has_abilities:
        print(f"\n  Ability Events (routine):")
        for key, label in ability_types:
            count = hc.get(key, 0)
            if count > 0:
                pct = count / ht * 100
                print(f"    {label:28s}  {count:>6}  ({pct:.1f}%)")

    # --- Experience qualities ---
    print(f"\n--- EXPERIENCE QUALITIES ---")
    for name, result in target_results.items():
        t = result["target"]
        v = result["value"]
        ok = result["in_range"]
        marker = "OK" if ok else "!!"

        if t.unit == "%":
            line = f"  {marker}  {t.description}: {v:.1f}%  [{t.target_min:.0f}-{t.target_max:.0f}%]"
        elif t.unit == "hands":
            line = f"  {marker}  {t.description}: {v:.1f}  [{t.target_min:.0f}-{t.target_max:.0f}]"
        elif t.unit == "cards":
            line = f"  {marker}  {t.description}: {v:.1f}  [{t.target_min:.0f}-{t.target_max:.0f}]"
        elif t.unit == "x":
            line = f"  {marker}  {t.description}: {v:.2f}x  [{t.target_min:.1f}-{t.target_max:.1f}x]"
        elif t.unit == "pp":
            line = f"  {marker}  {t.description}: {v:.1f}pp  [{t.target_min:.0f}-{t.target_max:.0f}pp]"
        else:
            line = f"  {marker}  {t.description}: {v:.1f}  [{t.target_min:.0f}-{t.target_max:.0f}]"
        print(line)

    # --- Enemy AI telemetry ---
    ai = metrics.get("enemy_ai_counts", {})
    ai_m = metrics.get("enemy_ai_metrics", {})
    if ai and (ai.get("hits", 0) + ai.get("stands", 0) > 0):
        print(f"\n--- ENEMY AI TELEMETRY ---")
        print(f"  Decisions:                {ai.get('hits', 0) + ai.get('stands', 0)}")
        print(f"  Hit rate:                 {ai_m.get('hit_rate', 0)*100:.1f}%")
        print(f"  Chase hit rate:           {ai_m.get('chase_hit_rate', 0)*100:.1f}% of hits")
        print(f"  High-risk hit rate:       {ai_m.get('risk_hit_rate', 0)*100:.1f}% of hits")
        print(f"  Reckless extra-hit rate:  {ai_m.get('reckless_hit_rate', 0)*100:.1f}% of hits")
        print(f"  Safe stand rate:          {ai_m.get('safe_stand_rate', 0)*100:.1f}% of stands")

        tier_m = metrics.get("enemy_ai_tier_metrics", {})
        for tier in ("normal", "elite", "boss"):
            if tier not in tier_m:
                continue
            tm = tier_m[tier]
            print(
                f"  {tier.capitalize():<9} hit {tm['hit_rate']*100:>5.1f}%  "
                f"chase {tm['chase_hit_rate']*100:>5.1f}%  "
                f"risk {tm['risk_hit_rate']*100:>5.1f}%  "
                f"safe-stand {tm['safe_stand_rate']*100:>5.1f}%"
            )

    # --- Strategy comparison ---
    if strategy_comparison:
        print(f"\n--- STRATEGY COMPARISON ---")
        for strat_name, survival in sorted(strategy_comparison.items(), key=lambda x: x[1]):
            bar = "#" * int(survival * 50)
            print(f"  {strat_name:15s}  {survival*100:5.1f}%  {bar}")

        basic = strategy_comparison.get("basic", 0)
        rand = strategy_comparison.get("random", 0)
        if basic and rand:
            gap = (basic - rand) * 100
            print(f"  Skill Gap (Basic vs Random): {gap:.1f}pp")

    # --- Recommendations ---
    if recommendations:
        print(f"\n--- RECOMMENDATIONS ---")
        for rec in recommendations:
            print(f"  {rec}")

    print()
    print("=" * 62)
