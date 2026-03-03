# Fun Metrics Model

This document defines a practical fun model for this game's intended blend:
- Slay the Spire: run-level adaptation and archetype building
- Balatro: combo cadence and payoff spikes
- Pokemon: companion attachment and identity

The goal is not "maximize win rate". The goal is **meaningful surprise with agency**.

## Principles

1. Every hand should offer interpretable risk.
2. Every act should create at least one new planning problem.
3. Build choices should produce distinct run identities.
4. Companion choices should matter, but not dominate outcomes.
5. Enemy pressure should feel adaptive, not random.

## Metric Groups

## 1) Tactical Fun (hand-level)

- `decision_tension` (%): Non-obvious hit/stand decisions.
  - Why: If too low, autopilot; if too high, coinflip fatigue.
- `split_rate` (%): Hands where splitting is used (secondary guardrail).
  - Why: Useful for monitoring mechanic relevance, but not a primary fun driver for this game blend.
- `counterplay_success_rate` (%): In enemy chase scenarios, player avoids a loss.
  - Why: Measures if reacting to pressure is rewarded.
- `high_total_loss_rate` (%): Non-bust player 19+ hands that still lose.
  - Why: Fairness guardrail for "I had a good hand and still got crushed" moments.

## 2) Buildcraft Fun (run-level)

- `reward_variety_rate` (% normalized): Average diversity of reward types chosen per run.
  - Why: Detects stale runs where one reward dominates every game.
- `build_pivot_rate` (%): Runs where dominant reward priority changes mid-run.
  - Why: Captures strategic adaptation rather than fixed scripts.
- `synergy_online_rate` (%): Hands with 2+ simultaneous effects.
  - Why: Proxy for combo "engine online" moments.

## 3) Arc & Pacing Fun

- `early_spike_rate` (%): Runs that achieve an act-1 fast kill spike (win in <=3 hands and >=8 total damage in a fight).
  - Why: Early momentum matters for engagement.
- `midrun_novelty_rate` (%): Act 2+ fights that introduce enemies not seen earlier in the run.
  - Why: Prevents act-2/3 repetition drag.
- `power_curve_ratio` (x): Late-act win power relative to early act.
  - Why: Ensures progression without runaway snowball.

## 4) Companion Fun

- `companion_attachment_rate` (%): Runs where a companion reaches level 3+.
  - Why: Indicates pet relationship persistence through the run.
- `companion_meaningfulness` (pp): Survival delta between runs with >=2 captures vs <=1 capture.
  - Why: Measures if companions matter in outcomes.
- `companion_impact` (%): Damage increase with companions vs no companions.
  - Why: Companion system should affect combat, but not fully decide it.

## 5) Enemy Dynamics & Readability

- `enemy_hit_rate` (%), `enemy_chase_hit_rate` (% of hits), `enemy_risk_hit_rate` (% of hits), `enemy_safe_stand_rate` (% of stands)
- Tier checks: `elite_chase_hit_rate`, `boss_chase_hit_rate`
  - Why: Quantifies whether enemies are adaptive vs deterministic.

## How to Use This in Tuning

1. Start with 2k-5k run seeded sims after any combat/AI/reward change.
2. Look for clusters of failed targets, not one metric in isolation.
3. Validate with short human playtests after sim passes:
   - Could players predict enemy pressure?
   - Did reacting correctly feel rewarding?
   - Did runs produce distinct identities?
4. Only tighten target ranges after 2-3 stable iterations.

## Important Caveat

These are proxies for feel, not feel itself. The model is designed to reduce blind tuning, then direct focused playtest rounds.
