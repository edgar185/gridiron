# Projection Model Spec — From Raw KPIs to Floor / Median / Ceiling / Confidence

Closes the loop: this defines exactly how the numbers in `projections` (and therefore the Player Card and Tier Board) get computed from `player_game_stats`, `vegas_lines`, `player_props`, and `defense_matchup_grades`.

---

## 1. Architecture — Three-Stage Ensemble

```
 Stage A: Usage Model        Stage B: Efficiency/Matchup      Stage C: Market Blend
 (how many opportunities)  →  Adjustment (pts per opportunity) →  (reconcile vs. Vegas props)
        ↓                            ↓                                  ↓
   projected_touches           expected_pts_per_touch              final median_pts
        └──────────────┬──────────────┘                                ↓
                   raw_median_pts  ───────────────────────────►  blended with market
                        ↓
            Quantile heads (p10 / p50 / p90)  →  floor / median / ceiling
                        ↓
         Confidence sub-model (model agreement + data quality + volatility)
                        ↓
              recommendation + rationale (NLG template)
```

Each stage is a separate, independently-testable model so a bad matchup grade doesn't corrupt the usage projection, and vice versa.

---

## 2. Stage A — Usage Model (Opportunity Projection)

**Goal:** predict `projected_touches` (targets, carries, dropbacks) for the week, independent of efficiency.

**Model type:** Gradient-boosted trees (LightGBM/XGBoost) — handles nonlinear usage patterns (e.g., injury-driven role changes) better than linear regression.

**Inputs by position** (all sourced from `player_game_stats` rolling windows + `depth_charts` + `injuries`):

| Position | Key Features |
|---|---|
| QB | `dropbacks` trail3/trail5, team implied total (from `vegas_lines`), opponent pace, `designed_rush_attempts` trend |
| RB | `carries` + `targets` trail3, `snap_pct` trail3, `depth_charts.depth_rank`, goal-line role (`goal_line_carries` share), teammate injury status |
| WR/TE | `route_participation_pct` trail3, `target_share` trail3, `slot_snap_pct`, `depth_charts.depth_rank`, teammate target-competition changes (from `news_events` category = `depth_chart`) |

**Output:** `projected_touches` with an implicit variance band (from quantile loss — see §4).

---

## 3. Stage B — Efficiency & Matchup Adjustment

**Goal:** convert `projected_touches` → `raw_median_pts` by applying an opponent- and context-adjusted points-per-touch rate.

**Base rate:** player's own trailing efficiency (`yprr`, `ryoe`, `epa_per_dropback`, catch rate) — trail5, regressed toward position-level mean using a shrinkage factor proportional to sample size (small-sample players get pulled harder toward the mean; this is what prevents a 1-game outlier from swinging a projection).

```
adjusted_efficiency = (n / (n + k)) * player_trail5_efficiency
                     + (k / (n + k)) * position_league_avg_efficiency
```
where `k` is a position-specific shrinkage constant (e.g., k=4 games for WR yprr) and `n` = games of trailing data available.

**Matchup multiplier:** derived from `defense_matchup_grades.epa_allowed_per_play` (or `yprr_allowed` for pass catchers) for the opponent at the relevant `vs_position`, normalized to a multiplier centered at 1.0 (league-avg defense = 1.0x, toughest = ~0.85x, easiest = ~1.15x).

**Environment multiplier:** from `weather` (wind >15mph applies a passing-volume/accuracy penalty) and `vegas_lines` implied total (higher implied team total → positive multiplier on scoring-dependent stats like TDs/red-zone touches).

```
raw_median_pts = projected_touches × adjusted_efficiency × matchup_multiplier × environment_multiplier
```

---

## 4. Quantile Heads — Floor / Ceiling

Rather than modeling variance analytically, train **three separate quantile regression heads** (p10, p50, p90) on the same feature set as Stages A+B, using pinball loss. This directly produces:

- `floor_pts` = p10 output
- `median_pts` = p50 output (should closely track `raw_median_pts` from §3 — large divergence is a model-disagreement flag, see §6)
- `ceiling_pts` = p90 output

**Why quantile regression over a symmetric std-dev band:** fantasy scoring is right-skewed (a big TD reception inflates upside far more than a bad game deflates floor), so a single mean ± std-dev band understates ceiling and overstates floor. Quantile heads capture that asymmetry natively.

**Backtesting requirement:** quantile calibration must be checked every retrain — e.g., the true outcome should fall below `floor_pts` (p10) roughly 10% of the time across the historical validation set. Log actual coverage and flag if a position's coverage drifts >3pp from target.

---

## 5. Stage C — Market Blend (Vegas Reconciliation)

The model's own `median_pts` is blended with an implied projection derived from `player_props` (e.g., a rec-yards prop line + rec prop + TD prop converted to expected fantasy points via scoring settings).

```
final_median_pts = (1 − w) × model_median_pts + w × market_implied_pts
```

- `w` (market weight) is tuned per position — typically higher for QB passing props (deep, efficient market) and lower for niche RB/WR props (thinner market, wider vig).
- Large disagreement between model and market (>15%) does **not** auto-override the model — it lowers `confidence_score` (see §6) and surfaces in the rationale ("model is off-market here") rather than silently forcing convergence.

---

## 6. Confidence Score (0–100)

Confidence is **not** the inverse of the floor-ceiling spread — a volatile-but-well-understood player (e.g., a boom/bust WR3) can still get a high confidence score if the model is consistently right about *that* volatility. Confidence measures **how much to trust the projection itself**, built from four weighted sub-signals:

| Sub-signal | Weight | Description |
|---|---|---|
| Data sufficiency | 25% | Games of trailing data available (rookie/new-role players score lower) |
| Model agreement | 30% | Inverse of divergence between Stage A+B output and Stage C market-implied value (§5) |
| Injury/practice stability | 25% | Penalized for `Questionable`/`Limited` designations in `injuries`; zeroed out logic if `Out`/`Doubtful` |
| Historical accuracy for this archetype | 20% | Backtested MAE of the model specifically for similar usage-profile players (e.g., "slot WRs with <10 games") |

```
confidence_score = round(
    25 × data_sufficiency_norm +
    30 × model_agreement_norm +
    25 × injury_stability_norm +
    20 × archetype_accuracy_norm
)
```

Each sub-signal is normalized to 0–1 before weighting. This is the number that drives the Player Card's gauge and the `START`/`SIT`/`FLEX` recommendation thresholds below.

---

## 7. Recommendation Logic

Recommendation is derived from `median_pts` relative to the **replacement-level baseline for the user's actual lineup** (not a generic threshold) plus the confidence score:

```
replacement_baseline = median_pts of the worst starter-caliber player at that position
                        in the user's league (position rank = num_teams × starters_per_team)

edge = median_pts - replacement_baseline

if edge > threshold_high AND confidence >= 60:  → START
elif edge < threshold_low OR confidence < 35:    → SIT
else:                                             → FLEX (borderline)
```

`threshold_high` / `threshold_low` are league-scoring-aware (PPR vs. std shifts the bar for pass-catching RBs, for example).

---

## 8. Rationale Text (NLG)

Generated from the **top 2 feature contributions** to the projection, ranked by SHAP-style attribution against the model's baseline prediction. Template:

```
"{top_positive_feature_phrase}, and {top_context_feature_phrase}."
```

Example (matches the Player Card mock): *"Target share up to 31% over the last 3 weeks and PIT's slot coverage has allowed the 5th-most YPRR to WRs."* — first clause from the Stage A usage trend feature, second from the Stage B matchup multiplier feature. Feature → phrase mapping is a maintained lookup table per feature, not free-generated text, so rationale stays accurate and auditable.

---

## 9. Retraining & Monitoring Cadence

| Task | Cadence |
|---|---|
| Full model retrain (Stages A, B, quantile heads) | Weekly, Tuesday after MNF, before waiver processing |
| Market-blend weight (`w`) recalibration | Monthly, per position |
| Quantile coverage backtest | Every retrain — auto-alert if coverage drifts >3pp |
| Archetype accuracy tables (confidence sub-signal) | Rolling 3-season window, refreshed monthly |
| Shrinkage constant (`k`) tuning | Preseason, per position |

**Key evaluation metrics:** MAE and RMSE on `median_pts` vs. actual; pinball loss on quantile heads; quantile coverage rate; Brier score on the binary "was START recommendation correct" outcome (calibration check for `confidence_score` itself — a 90-confidence START should be right far more often than a 60-confidence one, and this is what verifies that).
