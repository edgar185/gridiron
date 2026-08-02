// Your pre-draft strategy for the 2026 season (14-team PPR, pick 5-9).
// Static personal config, not DB-backed -- same pattern as App.jsx's
// COMPARE_IDS/LEAGUE_ID constants. Edit this file directly if the strategy
// changes; there's no admin UI for it since it's a single-user plan.

export const POSITION_LIMITS = [
  { position: "QB", min: 1, max: 2, why: "Streamable position in most formats; one strong starter + a late backup is plenty" },
  { position: "RB", min: 4, max: 7, why: "Thinnest position at 14 teams — you need bodies and handcuffs" },
  { position: "WR", min: 5, max: 8, why: "Deepest position in PPR; load up, especially mid-late rounds" },
  { position: "TE", min: 1, max: 2, why: "Either pay up for an elite one early or punt and stream" },
  { position: "K", min: 1, max: 1, why: "Never draft two, never draft early" },
  { position: "DST", min: 1, max: 1, why: "Stream-able; one is enough, don't reach" },
];

// `suggest` is the position(s) the round guide points to when this tool
// forces a single choice -- your own note was "lean RB rounds 1-2, WR
// rounds 3-5" when the true answer is "true BPA, take what falls."
export const ROUND_GUIDE = [
  { round: 1, suggest: ["RB", "WR"], preference: "RB or WR (Best Available)", rationale: "From 5-9, you'll see a mix of elite RBs (Gibbs, Bijan, CMC) and top WRs (Nacua, Chase) — take the highest-graded one, don't force a position" },
  { round: 2, suggest: ["RB", "WR"], preference: "RB or WR", rationale: "Same logic — balance your build, don't panic into a run" },
  { round: 3, suggest: ["WR", "RB"], preference: "RB or WR", rationale: "This is where your RB2/WR2 anchor comes from" },
  { round: 4, suggest: ["WR", "RB"], preference: "RB or WR", rationale: "Keep building the core; avoid QB/TE unless a top-3 TE inexplicably falls" },
  { round: 5, suggest: ["WR", "RB"], preference: "WR or RB", rationale: "By now you want at least 2 RB + 2 WR rostered" },
  { round: 6, suggest: ["WR", "RB"], preference: "WR or RB", rationale: "Best remaining flex-caliber player" },
  { round: 7, suggest: ["TE"], preference: "Tight End", rationale: "Good window to grab a mid-tier TE if you punted the position early" },
  { round: 8, suggest: ["RB", "WR"], preference: "RB or WR", rationale: "Depth/upside piece — bench flex material" },
  { round: 9, suggest: ["QB"], preference: "Quarterback", rationale: "Solid value window for a QB1 without reaching earlier" },
  { round: 10, suggest: ["RB", "WR"], preference: "RB or WR", rationale: "Keep stacking depth; target players in good offenses" },
  { round: 11, suggest: ["WR", "RB"], preference: "WR or RB", rationale: "Bench depth, lottery-ticket upside players" },
  { round: 12, suggest: ["RB"], preference: "RB", rationale: "Handcuff a stud RB you own, or take an upside backfield piece" },
  { round: 13, suggest: ["WR"], preference: "WR", rationale: "Depth / bye-week fill-in" },
  { round: 14, suggest: ["QB", "TE"], preference: "Quarterback (backup) or TE", rationale: "Only if you don't like your TE1 — otherwise best RB/WR flier" },
  { round: 15, suggest: ["DST"], preference: "Team Defense/Special Teams", rationale: "Never draft D/ST before round 14-15" },
  { round: 16, suggest: ["K"], preference: "Place Kicker", rationale: "Always the last pick — kickers are a coin flip anyway" },
];

export const STRATEGY_NOTES = [
  "True BPA drafting adapts to what actually falls — rounds 1-6 lean RB early (scarcity), WR mid (depth/PPR value), then reassess.",
  "Don't draft a K or DST before round 14 — no meaningful edge, and it costs you a useful bench piece.",
  "If an elite top-3 TE is still on the board in round 2-3, it's fine to jump the queue — TE scarcity can be a bigger edge than a WR3/RB3.",
];

export const LEAGUE_CONTEXT = { teams: 14, scoring: "PPR", draftSlot: "5-9" };
