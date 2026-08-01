# Fantasy Football Decision Engine — Product & Data Requirements

## 1. Core Strategic Features

### 1.1 Drafting Assistant
| Feature | Description | Priority |
|---|---|---|
| Value-Based Drafting (VBD) engine | Rank players by value over replacement (VORP), value over baseline (VOLS), and value over next available (VONA) — recalculated live as picks come off the board | P0 |
| Dynamic tier lists | Cluster players into tiers per position using statistical breakpoints (k-means or std-dev gaps on projection), not fixed rank cutoffs | P0 |
| Positional scarcity tracker | Live "cliff" indicator showing how many players remain in a tier vs. picks until your next turn | P0 |
| Auto-adjusting ADP vs. Value delta | Flag players falling below their projected value ("value" pick) or being reached for | P1 |
| Roster construction simulator | Projects your remaining roster needs based on league settings (starting lineup, bench, flex/superflex) | P1 |
| Best Player Available (BPA) vs. Need toggle | Switch between pure value and positional-need-weighted recommendations | P1 |
| Bye week / stacking conflict warnings | Flags QB-WR stacks (good) or bye-week clustering (bad) in real time | P1 |
| Mock draft simulator w/ AI opponents | Practice against bots trained on historical ADP behavior | P2 |
| Keeper/Dynasty value adjustments | Age curve, contract year, draft capital pedigree factored into rookie/dynasty rankings | P2 |

### 1.2 Start/Sit Optimizer
| Feature | Description | Priority |
|---|---|---|
| Matchup grade (opponent defense) | Position-specific defensive rank (vs. QB, vs. RB, vs. slot WR, etc.) using EPA/play allowed, not just total yards allowed | P0 |
| Projected volume model | Snap share, target share, carry share projections adjusted for game script | P0 |
| Game script / Vegas-implied pace | Combines implied team total + spread to project positive/negative script and pass/run lean | P0 |
| Weather impact flag | Wind speed/precip alerts specifically for outdoor games affecting passing volume & kicker accuracy | P1 |
| Floor/Ceiling/Median projection bands | Show a distribution, not a single number, with boom/bust probability | P0 |
| Head-to-head "swap" comparator | Side-by-side two-player comparison with win-probability of the swap | P0 |
| Injury/practice designation tracker | Auto-pulls Wed/Thu/Fri practice reports and game status designations | P0 |
| Correlation/stack warnings for DFS or same-game | Alerts if starting two players cannibalizes target/carry share | P2 |

### 1.3 Waiver Wire / Pickup Finder
| Feature | Description | Priority |
|---|---|---|
| Opportunity/usage trend detector | Flags players with rising snap%, route participation, or red-zone touches over trailing 3 weeks | P0 |
| Depth chart vacancy scanner | Auto-detects injuries/suspensions/trades that open opportunity ahead of the news cycle | P0 |
| "Efficiency vs. Opportunity" breakout score | Separates players outperforming volume (regression risk) from players under-produced relative to volume (buy signal) | P0 |
| FAAB bid optimizer | Recommends bid % of remaining budget based on league size, scarcity, and projected rest-of-season value | P1 |
| Rest-of-season (ROS) schedule strength | Overlays upcoming matchup difficulty on the pickup recommendation | P1 |
| Drop candidate suggester | Identifies your worst bench asset to cut, factoring bye weeks and playoff schedule | P1 |
| Trending-add velocity | % of leagues adding the player in the last 24/48h as a herd-momentum signal | P2 |

---

## 2. Quantitative KPIs & Metrics Database

### 2.1 Quarterbacks
- **Efficiency:** EPA/play, EPA/dropback, CPOE (completion % over expected), success rate, ANY/A
- **Volume:** Dropbacks/game, designed rush attempts, red-zone pass attempts, play-action rate
- **Pressure context:** Pressure-to-sack rate, time to throw, pressure rate allowed by O-line
- **Explosiveness:** Air yards/attempt, deep ball attempt rate (20+ yds), aDOT
- **Situational:** 3rd-down conversion rate, red-zone TD rate, 2-minute drill usage

### 2.2 Running Backs
- **Opportunity:** Snap share, carry share, target share, weighted opportunity score (touches weighted for scoring value: goal-line carries + receptions weighted higher)
- **Efficiency:** Yards after contact/attempt, missed tackles forced/attempt, success rate, RYOE (rush yards over expected), yards/route run
- **Receiving:** Route participation %, target share out of backfield, catch rate, receiving-game "passing down" usage
- **Red zone:** Inside-the-5 carry share, goal-line back designation
- **O-line context:** Team run-blocking grade / adjusted line yards

### 2.3 Pass Catchers (WR/TE)
- **Volume:** Target share, air yards share, WOPR (weighted opportunity rating), routes run, route participation %
- **Efficiency:** Yards/route run (YPRR), catch rate over expected, target separation, contested-catch rate
- **Role quality:** aDOT (depth of target), slot vs. wide alignment rate, red-zone target share, end-zone target share
- **Explosiveness:** Yards after catch/reception, breakaway run rate
- **Team context:** QB play quality (EPA/dropback of the team's passer), pass-block win rate affecting dropback volume

### 2.4 Cross-Position / System-Wide
- Injury history & recovery timeline database (per body part, per position, historical return-to-form curves)
- Strength-of-schedule index (per position, defense-adjusted)
- Age/experience curve modifiers (breakout ages by position)
- Coaching scheme tags (zone vs. gap run scheme, RPO rate, pace of play)

---

## 3. External Data & Predictive Signals

| Source Type | Specific Signal | Why It Matters |
|---|---|---|
| Vegas sportsbook feeds | Player props (rush yds, rec yds, TDs, longest reception) | Market-priced probability, often sharper than raw stats |
| Vegas sportsbook feeds | Team implied totals & spreads | Drives game-script and volume projections |
| Vegas sportsbook feeds | Live in-week line movement | Detects sharp money / injury-driven shifts before news breaks |
| Next Gen Stats / player tracking | Separation, closest defender distance, RYOE, CPOE | Skill-isolated metrics independent of scheme/teammates |
| PFF or equivalent grading | Pass-block win rate, coverage grades, run-block grades | O-line/defense context that shapes opportunity |
| Beat writer / practice report aggregation | Practice participation, coach quotes, snap-count trends | Early-warning signal ahead of consensus rankings |
| Weather APIs | Wind, precipitation, temperature by stadium | Passing volume & kicker suppression |
| Officiating crew tendencies | Penalty rate, pace impact | Second-order pace/scoring environment signal |
| Social/news NLP scraper | Beat reporter sentiment, depth chart language changes | Speed advantage on breaking news |
| Historical outcome database | Full play-by-play back to prior seasons | Model training/backtesting |

---

## 4. User Interaction / UI Requirements

### Design Principles
- **Progressive disclosure:** Headline recommendation first ("Start," "Sit," "Add — Bid 12% FAAB"), advanced metrics available on tap/expand — never all at once.
- **Single confidence score:** Roll up underlying KPIs into one 0–100 confidence/grade badge (color-coded) so users get a fast read; raw metrics live one layer deeper.
- **Visual over numeric:** Use tier-grouped cards, matchup heat-maps (red/green defensive grids), and range bars (floor–median–ceiling) instead of dense tables as the primary view.
- **Comparison-first for Start/Sit:** Default to a side-by-side two-card comparator with a single highlighted "Edge" verdict, not a full stat sheet.
- **Trend sparklines:** Small inline trend lines (snap %, target share) next to a player's name instead of separate charts.
- **Plain-language "why":** Every recommendation includes a 1-sentence natural-language rationale (e.g., "Target share up 8% over 3 weeks, plays a bottom-5 pass defense") generated from the underlying KPIs.
- **Filter/sort, not scroll walls:** Waiver wire view defaults to a ranked list filterable by position/FAAB budget/need, with advanced columns toggle-able for power users.
- **Alerts, not dashboards, for time-sensitive data:** Push notifications for injury/inactive news rather than requiring the user to monitor a live feed.

### Recommended Screen Hierarchy
1. **Dashboard:** This week's Start/Sit alerts + top 3 waiver targets + any lineup risk flags
2. **Draft Room:** Tier board (primary) → player detail drawer (secondary) → VBD/scarcity panel (tertiary)
3. **Player Card (shared across modules):** Confidence badge → floor/ceiling bar → matchup grade → 3-line trend → expandable full KPI table

