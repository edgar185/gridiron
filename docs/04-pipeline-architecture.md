# Model Pipeline — Job Architecture

Orchestrator: **Airflow** (or Prefect/Dagster — same shape). Chosen over cron/APScheduler because several jobs are dependent (a failed upstream job must block downstream retrains) and need retries + alerting, not just time-triggering.

---

## Weekly DAG — `fantasy_weekly_retrain`

**Schedule:** Tuesdays 06:00 ET (after MNF final stats land), before Wednesday waiver processing.

```
refresh_player_game_stats
        │
        ▼
refresh_trailing_form_view   (player_trailing_form materialized view)
        │
        ├─────────────┐
        ▼             ▼
 train_stage_a    refresh_matchup_grades   (defense_matchup_grades)
 (usage model)          │
        └──────┬────────┘
               ▼
        train_stage_b   (efficiency + matchup adjustment)
               ▼
        train_quantile_heads   (p10/p50/p90)
               ▼
        backtest_quantile_coverage   ──── FAIL → alert + block publish
               │ pass
               ▼
        blend_market_signals   (Stage C, pulls fresh player_props)
               ▼
        compute_confidence_scores
               ▼
        generate_rationale_text
               ▼
        publish_projections   (writes to `projections` table)
```

**Retry policy:** 3 retries, exponential backoff, per task. `backtest_quantile_coverage` failure does **not** retry — it's a gate, not a transient error; it halts the DAG and pages the on-call so a stale (last week's) projection stays live rather than a miscalibrated one publishing.

**SLA:** full DAG must complete by Wed 08:00 ET — waiver recommendations depend on `publish_projections` completing first.

---

## Monthly DAG — `fantasy_monthly_recalibration`

**Schedule:** 1st of each month, 03:00 ET.

```
refresh_archetype_accuracy_tables   (rolling 3-season backtest by usage-profile bucket)
        ▼
recalibrate_market_blend_weights    (per-position `w` in Stage C, tuned on trailing accuracy)
        ▼
recalibrate_shrinkage_constants     (k in efficiency shrinkage — preseason + monthly touch-up)
        ▼
publish_model_config                (versioned config row consumed by weekly DAG)
```

This DAG doesn't publish projections directly — it updates the **config** the weekly DAG reads (`model_version` in `projections`), so a bad monthly recalibration can't corrupt live data mid-week; it only takes effect at the next weekly run.

---

## Event-Driven Jobs (not calendar-scheduled)

| Trigger | Job | Notes |
|---|---|---|
| New row in `injuries` (status = Out/Doubtful) | `recompute_affected_projections` | Targeted re-run for just the affected player + any teammate whose usage share shifts (e.g., backup RB) |
| New row in `news_events` (category = depth_chart) | `flag_stale_usage_features` | Marks player for priority refresh next scheduled run rather than a full re-train |
| `vegas_lines` line move >2 points | `refresh_market_blend_single_game` | Cheap partial re-run of Stage C only, no re-train |

These run via a lightweight listener (DB trigger → queue → worker), not the DAG scheduler — they're too frequent/urgent to wait for Tuesday.

---

## Monitoring & Alerting

| Metric | Alert condition |
|---|---|
| Quantile coverage (p10/p90) | Drift >3pp from target → page on-call, block publish |
| DAG SLA miss | Weekly DAG not complete by Wed 08:00 ET → page |
| Model-vs-market divergence rate | >X% of players with >15% divergence → Slack warning (informational, non-blocking) |
| `confidence_score` calibration (Brier score) | Degrades >10% month-over-month → flags for the next monthly DAG's review, not auto-blocking |
