import React, { useEffect, useState } from "react";
import {
  Flame, ChevronDown, Wind, TrendingUp, TrendingDown,
  ShieldAlert, AlertTriangle, LayoutGrid, Users, Repeat, Home, ListChecks, Send, Sparkles,
} from "lucide-react";
import { POSITION_LIMITS, ROUND_GUIDE, STRATEGY_NOTES, LEAGUE_CONTEXT } from "./draftStrategy";

// ---- Shared design tokens ----
const T = {
  ink: "#0B1220",
  panel: "#121A2C",
  panel2: "#16213A",
  line: "#243252",
  gold: "#F2B705",
  green: "#3ED07C",
  red: "#FF5C5C",
  text: "#EDEFF4",
  muted: "#8A96AC",
};

const API_BASE = "http://localhost:8000";

// The 2025 season is the most recent one nflverse has published complete
// weekly stats for as of this build (see ingestion/README.md -- nflverse
// renamed the release nfl_data_py's wrapper points at, which is why this
// was stuck on 2024 before; fixed in nflverse_ingest.py). Real, current
// data, not a placeholder. Once 2026 games are played and re-ingested,
// bump these and every screen below updates with no code change.
const SEASON = 2025;
const WEEK = 18;

// Your actual roster, synced from ESPN league 1859403384 ("Edgar's Crown
// Jewel") via espn_ingest.py. Travis Etienne is who you currently have
// starting at FLEX; Jordan Addison is on your bench -- a real lineup
// decision from your real roster, not a scripted demo pairing. (With real
// 2025 data the numbers actually favor Etienne now -- a genuinely
// different answer than the 2024 snapshot gave, which is the point.)
// A future backend endpoint reading your synced roster_slots directly would
// pick this automatically each week instead of it being hardcoded here.
const COMPARE_IDS = ["00-0036973", "00-0038994"]; // Travis Etienne (your FLEX), Jordan Addison (your bench)

// Your real synced ESPN league (see ingestion/espn_ingest.py). Used to scope
// waivers/draft-tiers to this league's actual roster settings and free
// agent pool instead of a generic assumption.
const LEAGUE_ID = 1859403384;
const TEAM_NAME = "Crown Jewel";

function recColor(rec) {
  const r = (rec || "").toLowerCase();
  if (r === "start") return T.green;
  if (r === "sit") return T.red;
  return T.gold;
}

// Distinct from recColor's green/red (which mean start/sit elsewhere) --
// these screens don't show recommendations, so the palette is free to
// encode position instead.
const POSITION_COLORS = { QB: T.gold, RB: T.green, WR: "#4FA8E8", TE: "#B98AF2", K: "#F2955C", DST: T.red };

function PositionBadge({ position }) {
  const color = POSITION_COLORS[position] || T.muted;
  return (
    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0"
      style={{ color, backgroundColor: `${color}22`, border: `1px solid ${color}55` }}>
      {position}
    </span>
  );
}

// Real primary team colors; the handful of teams whose primary is near-black
// (CHI, JAX, LV/OAK) use their brighter secondary instead so the dot is
// actually visible against this dark theme.
const TEAM_COLORS = {
  ARI: "#97233F", ATL: "#A71930", BAL: "#241773", BUF: "#00338D", CAR: "#0085CA",
  CHI: "#C83803", CIN: "#FB4F14", CLE: "#FF3C00", DAL: "#869397", DEN: "#FB4F14",
  DET: "#0076B6", GB: "#FFB612", HOU: "#A71930", IND: "#002C5F", JAX: "#D7A22A",
  KC: "#E31837", LAC: "#0080C6", LAR: "#003594", LA: "#003594", LV: "#A5ACAF",
  MIA: "#008E97", MIN: "#4F2683", NE: "#002244", NO: "#D3BC8D", NYG: "#0B2265",
  NYJ: "#125740", OAK: "#A5ACAF", PHI: "#004C54", PIT: "#FFB612", SD: "#0080C6",
  SEA: "#69BE28", SF: "#AA0000", STL: "#003594", TB: "#D50A0A", TEN: "#4B92DB",
  WAS: "#5A1414",
};

function TeamDot({ team }) {
  return <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: TEAM_COLORS[team] || T.muted }} />;
}

function EnvPill({ rank }) {
  if (rank == null) return null;
  const color = rank <= 10 ? T.green : rank >= 23 ? T.red : T.muted;
  return (
    <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded shrink-0" style={{ color, backgroundColor: `${color}22` }}>
      env #{rank}
    </span>
  );
}

function useApi(path) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  useEffect(() => {
    let cancelled = false;
    setState({ data: null, loading: true, error: null });
    fetch(`${API_BASE}${path}`)
      .then((r) => r.json())
      .then((json) => {
        if (cancelled) return;
        if (json?.error) setState({ data: null, loading: false, error: json.error.message || json.error.code });
        else setState({ data: json, loading: false, error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ data: null, loading: false, error: err.message });
      });
    return () => { cancelled = true; };
  }, [path]);
  return state;
}

function StatusPanel({ error }) {
  return (
    <div className="rounded-lg border p-3 text-[11px]" style={{ backgroundColor: T.panel, borderColor: T.red, color: T.red }}>
      Couldn't reach the backend at {API_BASE} ({error}). Is `docker compose up -d db backend` running?
    </div>
  );
}

function Sparkline({ points, color }) {
  const w = 72, h = 24;
  const min = Math.min(...points), max = Math.max(...points);
  const norm = (v) => h - ((v - min) / (max - min || 1)) * h;
  const step = w / (points.length - 1 || 1);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${i * step} ${norm(p)}`).join(" ");
  return (
    <svg width={w} height={h}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={(points.length - 1) * step} cy={norm(points[points.length - 1])} r="2.2" fill={color} />
    </svg>
  );
}

function ConfidenceGauge({ value, color, size = 88 }) {
  const r = 34, c = 2 * Math.PI * r, filled = (value / 100) * c;
  return (
    <div className="relative flex items-center justify-center shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 88 88" className="-rotate-90">
        <circle cx="44" cy="44" r={r} fill="none" stroke={T.line} strokeWidth="7" />
        <circle cx="44" cy="44" r={r} fill="none" stroke={color} strokeWidth="7" strokeLinecap="round"
          strokeDasharray={`${filled} ${c - filled}`} />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="font-mono text-lg font-bold" style={{ color: T.text }}>{value}</span>
        <span className="text-[8px] tracking-widest uppercase" style={{ color: T.muted }}>Conf</span>
      </div>
    </div>
  );
}

function RangeBar({ floor, median, ceiling }) {
  const max = ceiling * 1.15 || 1;
  const pct = (v) => (v / max) * 100;
  return (
    <div className="w-full">
      <div className="flex justify-between text-[9px] font-mono mb-1" style={{ color: T.muted }}>
        <span>FLOOR {floor}</span><span style={{ color: T.gold }}>MED {median}</span><span>CEIL {ceiling}</span>
      </div>
      <div className="relative h-1.5 rounded-full" style={{ backgroundColor: T.line }}>
        <div className="absolute h-1.5 rounded-full" style={{ left: `${pct(floor)}%`, width: `${pct(ceiling) - pct(floor)}%`, backgroundColor: T.panel2, border: `1px solid ${T.gold}55` }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-1 h-3 rounded-sm" style={{ left: `${pct(median)}%`, backgroundColor: T.gold }} />
      </div>
    </div>
  );
}

// ---------------- Screen: Dashboard ----------------
function DashboardScreen() {
  const compare = useApi(`/v1/compare?playerIds=${COMPARE_IDS.join(",")}&week=${WEEK}&season=${SEASON}`);
  const waivers = useApi(`/v1/waivers/candidates?season=${SEASON}&week=${WEEK}&position=RB&leagueId=${LEAGUE_ID}`);
  const roster = useApi(`/v1/roster?leagueId=${LEAGUE_ID}&teamName=${encodeURIComponent(TEAM_NAME)}&season=${SEASON}&week=${WEEK}`);

  const sitPlayer = compare.data?.players.find((p) => p.recommendation === "sit");
  const topWaiver = waivers.data?.candidates?.[0];
  const starters = roster.data?.players?.filter((p) => p.slotType && p.slotType !== "BENCH") || [];

  return (
    <div className="px-4 pt-4 pb-2">
      <p className="text-xs mb-3" style={{ color: T.muted }}>Season {SEASON} · Week {WEEK}</p>

      {compare.error && <StatusPanel error={compare.error} />}

      {sitPlayer && (
        <div className="rounded-lg border p-3 mb-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
          <div className="flex items-center gap-1.5 mb-1">
            <AlertTriangle size={12} color={T.red} />
            <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.red }}>Sit Alert</span>
          </div>
          <p className="text-xs" style={{ color: T.text }}>{sitPlayer.rationale}</p>
        </div>
      )}

      {topWaiver && (
        <div className="rounded-lg border p-3 mb-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp size={12} color={T.green} />
            <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.green }}>Top Waiver Target</span>
          </div>
          <p className="text-xs" style={{ color: T.text }}>
            {topWaiver.name} ({topWaiver.team} {topWaiver.position}) — {topWaiver.breakoutScore} breakout score, recommend {topWaiver.recommendedFaabPct}% FAAB.
          </p>
        </div>
      )}

      <div className="rounded-lg border p-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.muted }}>Your Starting Lineup</span>
        {roster.error && <p className="text-xs mt-2" style={{ color: T.red }}>{roster.error}</p>}
        {starters.length === 0 && !roster.error && <p className="text-xs mt-2" style={{ color: T.muted }}>Loading...</p>}
        <div className="mt-2 flex flex-col gap-1.5">
          {starters.map((p) => (
            <div key={p.playerId} className="flex items-center gap-1.5">
              <PositionBadge position={p.position} />
              <TeamDot team={p.team} />
              <span className="text-xs flex-1 truncate" style={{ color: T.text }}>{p.slotType} · {p.name}</span>
              {p.confidence != null ? (
                <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded"
                  style={{ color: T.ink, backgroundColor: recColor(p.recommendation) }}>{p.confidence}</span>
              ) : (
                <span className="text-[9px]" style={{ color: T.muted }}>no proj.</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Real LLM call (Claude via the backend's /v1/ask, see backend/main.py) --
// grounded in the same real projection data shown above it, not a canned
// template. Needs ANTHROPIC_API_KEY set on the backend; shows a clear error
// if it's missing rather than failing silently.
function AskBox({ playerIds }) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState({ answer: null, loading: false, error: null });

  const ask = async () => {
    if (!question.trim()) return;
    setState({ answer: null, loading: true, error: null });
    try {
      const res = await fetch(`${API_BASE}/v1/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, playerIds, season: SEASON, week: WEEK }),
      });
      const json = await res.json();
      if (json.error) setState({ answer: null, loading: false, error: json.error.message || json.error.code });
      else setState({ answer: json.answer, loading: false, error: null });
    } catch (err) {
      setState({ answer: null, loading: false, error: err.message });
    }
  };

  return (
    <div className="mt-3 rounded-lg border p-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
      <div className="flex items-center gap-1.5 mb-2">
        <Sparkles size={12} color={T.gold} />
        <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.gold }}>Ask about this matchup</span>
      </div>
      <div className="flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="e.g. what if scoring were standard, not PPR?"
          className="flex-1 text-xs rounded-md px-2 py-1.5 outline-none"
          style={{ backgroundColor: T.panel2, color: T.text, border: `1px solid ${T.line}` }}
        />
        <button onClick={ask} disabled={state.loading}
          className="px-2.5 rounded-md flex items-center justify-center"
          style={{ backgroundColor: T.gold, opacity: state.loading ? 0.6 : 1 }}>
          <Send size={14} color={T.ink} />
        </button>
      </div>
      {state.loading && <p className="text-[10px] mt-2" style={{ color: T.muted }}>Thinking...</p>}
      {state.error && <p className="text-[10px] mt-2" style={{ color: T.red }}>{state.error}</p>}
      {state.answer && <p className="text-[11px] mt-2 leading-snug" style={{ color: T.text }}>{state.answer}</p>}
    </div>
  );
}

// ---------------- Screen: Start/Sit ----------------
function StartSitScreen() {
  const [expandedIdx, setExpandedIdx] = useState(null);
  const { data, loading, error } = useApi(`/v1/compare?playerIds=${COMPARE_IDS.join(",")}&week=${WEEK}&season=${SEASON}`);

  if (error) return <div className="px-4 pt-4"><StatusPanel error={error} /></div>;
  if (loading || !data) return <div className="px-4 pt-4 text-xs" style={{ color: T.muted }}>Loading...</div>;

  return (
    <div className="px-4 pt-4 pb-2">
      <p className="text-xs mb-3" style={{ color: T.muted }}>Your FLEX spot vs. your bench — Week {WEEK}</p>
      <div className="flex flex-col gap-3">
        {data.players.map((p, idx) => {
          const color = recColor(p.recommendation);
          return (
            <div key={p.playerId} className="rounded-lg border overflow-hidden" style={{ backgroundColor: T.panel, borderColor: T.line }}>
              <div className="h-1 w-full" style={{ backgroundColor: color }} />
              <div className="p-3 flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-1.5">
                    <PositionBadge position={p.position} />
                    <span className="font-bold text-sm" style={{ color: T.text }}>{p.name}</span>
                  </div>
                  <div className="text-[10px] flex items-center gap-1 mt-0.5" style={{ color: T.muted }}>
                    <TeamDot team={p.team} />
                    {p.team} · vs {p.opponent}
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase"
                  style={{ color: T.ink, backgroundColor: color }}>{p.recommendation}</span>
              </div>
              <div className="px-3 flex gap-2.5 items-center">
                <ConfidenceGauge value={p.confidence} color={color} size={72} />
                <p className="text-[11px] leading-snug" style={{ color: T.text }}>{p.rationale}</p>
              </div>
              <div className="p-3"><RangeBar floor={p.projection.floor} median={p.projection.median} ceiling={p.projection.ceiling} /></div>
              {p.matchup && (
                <div className="px-3 pb-3">
                  <div className="rounded-md p-2" style={{ backgroundColor: T.panel2 }}>
                    <div className="flex items-center gap-1 mb-0.5"><ShieldAlert size={10} color={T.muted} />
                      <span className="text-[8px] uppercase tracking-widest" style={{ color: T.muted }}>Matchup</span></div>
                    <div className="text-xs font-mono font-bold" style={{ color: T.text }}>#{p.matchup.vsPositionRank}/32</div>
                  </div>
                </div>
              )}
              <button onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                className="w-full flex items-center justify-center gap-1 py-2 text-[10px] font-semibold uppercase tracking-widest border-t"
                style={{ borderColor: T.line, color: T.gold }}>
                Rationale
                <ChevronDown size={12} style={{ transform: expandedIdx === idx ? "rotate(180deg)" : "none" }} />
              </button>
              {expandedIdx === idx && (
                <div className="px-3 pb-3 pt-1" style={{ backgroundColor: T.ink }}>
                  <p className="text-[10px] py-1" style={{ color: T.muted }}>{p.rationale}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {data.edge && (
        <div className="mt-3 rounded-lg border p-2.5 flex items-center justify-between" style={{ backgroundColor: T.panel, borderColor: T.line }}>
          <span className="text-[10px]" style={{ color: T.muted }}>Edge:</span>
          <span className="text-xs font-bold" style={{ color: T.green }}>{data.edge.summary}</span>
        </div>
      )}
      <AskBox playerIds={COMPARE_IDS} />
    </div>
  );
}

// ---------------- Screen: Draft ----------------
const DRAFT_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"];

function StrategyPanel({ onPickPosition }) {
  const [round, setRound] = useState(1);
  const roster = useApi(`/v1/roster?leagueId=${LEAGUE_ID}&teamName=${encodeURIComponent(TEAM_NAME)}&season=${SEASON}&week=${WEEK}`);
  const envs = useApi(`/v1/team-environments?season=2026`);
  const counts = roster.data?.positionCounts || {};
  const guide = ROUND_GUIDE[round - 1];
  const topEnvs = envs.data?.teams?.slice(0, 5) || [];
  const bottomEnvs = envs.data?.teams?.slice(-5).reverse() || [];

  return (
    <div className="mb-3">
      <div className="rounded-lg border p-3 mb-2" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.muted }}>
          Your Build vs. Strategy ({LEAGUE_CONTEXT.teams}-team {LEAGUE_CONTEXT.scoring}, pick {LEAGUE_CONTEXT.draftSlot})
        </span>
        <div className="grid grid-cols-3 gap-2 mt-2">
          {POSITION_LIMITS.map((lim) => {
            const have = counts[lim.position] || 0;
            const ok = have >= lim.min && have <= lim.max;
            return (
              <div key={lim.position} className="rounded-md p-1.5 text-center" style={{ backgroundColor: T.panel2 }}>
                <div className="text-[9px]" style={{ color: T.muted }}>{lim.position}</div>
                <div className="text-sm font-mono font-bold" style={{ color: ok ? T.green : T.gold }}>{have}</div>
                <div className="text-[8px]" style={{ color: T.muted }}>of {lim.min}-{lim.max}</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-lg border p-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.muted }}>Round Guide</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setRound((r) => Math.max(1, r - 1))} className="text-[10px] px-1.5 rounded" style={{ color: T.gold, border: `1px solid ${T.line}` }}>-</button>
            <span className="text-xs font-mono w-14 text-center" style={{ color: T.text }}>Rd {round}</span>
            <button onClick={() => setRound((r) => Math.min(16, r + 1))} className="text-[10px] px-1.5 rounded" style={{ color: T.gold, border: `1px solid ${T.line}` }}>+</button>
          </div>
        </div>
        <p className="text-xs font-bold" style={{ color: T.text }}>{guide.preference}</p>
        <p className="text-[10px] mt-1 leading-snug" style={{ color: T.muted }}>{guide.rationale}</p>
        <div className="flex gap-1.5 mt-2">
          {guide.suggest.map((pos) => (
            <button key={pos} onClick={() => onPickPosition(pos)}
              className="text-[9px] font-mono px-2 py-1 rounded uppercase"
              style={{ backgroundColor: T.gold, color: T.ink }}>
              View {pos} tiers
            </button>
          ))}
        </div>
      </div>

      {topEnvs.length > 0 && (
        <div className="rounded-lg border p-3 mt-2" style={{ backgroundColor: T.panel, borderColor: T.line }}>
          <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.muted }}>
            2026 Offensive Environments (real Vegas implied totals)
          </span>
          <div className="grid grid-cols-2 gap-3 mt-2">
            <div>
              <div className="text-[8px] uppercase mb-1" style={{ color: T.green }}>Best</div>
              {topEnvs.map((t) => (
                <div key={t.team} className="flex justify-between text-[10px] font-mono py-0.5">
                  <span style={{ color: T.text }}>{t.team}</span>
                  <span style={{ color: T.green }}>{t.avgImplied}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="text-[8px] uppercase mb-1" style={{ color: T.red }}>Worst</div>
              {bottomEnvs.map((t) => (
                <div key={t.team} className="flex justify-between text-[10px] font-mono py-0.5">
                  <span style={{ color: T.text }}>{t.team}</span>
                  <span style={{ color: T.red }}>{t.avgImplied}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DraftScreen() {
  const [position, setPosition] = useState("WR");
  const [showStrategy, setShowStrategy] = useState(true);
  const { data, loading, error } = useApi(`/v1/draft/tiers?position=${position}&season=${SEASON}&week=${WEEK}&leagueId=${LEAGUE_ID}`);

  return (
    <div className="px-4 pt-4 pb-2">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs" style={{ color: T.muted }}>Season {SEASON}, Week {WEEK} tiers</p>
        <button onClick={() => setShowStrategy((s) => !s)}
          className="flex items-center gap-1 text-[9px] font-mono px-2 py-1 rounded uppercase"
          style={{ backgroundColor: showStrategy ? T.gold : T.panel2, color: showStrategy ? T.ink : T.muted, border: `1px solid ${T.line}` }}>
          <ListChecks size={10} /> Strategy
        </button>
      </div>

      {showStrategy && <StrategyPanel onPickPosition={setPosition} />}

      <div className="flex gap-1 mb-3">
        {DRAFT_POSITIONS.map((pos) => (
          <button key={pos} onClick={() => setPosition(pos)}
            className="text-[9px] font-mono px-2 py-1 rounded"
            style={{
              backgroundColor: pos === position ? T.gold : T.panel2,
              color: pos === position ? T.ink : T.muted,
              border: `1px solid ${pos === position ? T.gold : T.line}`,
            }}>{pos}</button>
        ))}
      </div>

      {error && <StatusPanel error={error} />}
      {loading && <p className="text-xs" style={{ color: T.muted }}>Loading...</p>}

      {data?.tiers?.map((tier) => (
        <div key={tier.tier} className="mb-3">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="w-5 h-5 flex items-center justify-center rounded-full text-[10px] font-mono font-bold"
              style={{ backgroundColor: T.panel2, color: T.gold, border: `1px solid ${T.line}` }}>{tier.tier}</span>
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: T.text }}>{tier.label}</span>
          </div>
          {tier.players.map((p) => (
            <div key={p.playerId} className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-md mb-1"
              style={{ backgroundColor: T.panel2, border: `1px solid ${T.line}`, borderLeft: `3px solid ${TEAM_COLORS[p.team] || T.line}` }}>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <PositionBadge position={p.position} />
                  <span className="text-xs font-bold truncate" style={{ color: T.text }}>{p.name}</span>
                </div>
                <div className="text-[9px] flex items-center gap-1 mt-0.5" style={{ color: T.muted }}>
                  <TeamDot team={p.team} />
                  {p.team}
                  <EnvPill rank={p.teamImpliedRank} />
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <div className="text-right">
                  <div className="text-[11px] font-mono font-bold" style={{ color: T.text }}>{p.projectedPts}</div>
                  <div className="text-[7px] uppercase" style={{ color: T.muted }}>PROJ PTS</div>
                </div>
                {p.vbd != null && (
                  <div className="text-right">
                    <div className="text-[11px] font-mono font-bold" style={{ color: T.gold }}>{p.vbd}</div>
                    <div className="text-[7px] uppercase" style={{ color: T.muted }}>VBD</div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------- Screen: Waivers ----------------
function WaiversScreen() {
  const { data, loading, error } = useApi(`/v1/waivers/candidates?season=${SEASON}&week=${WEEK}&leagueId=${LEAGUE_ID}`);

  return (
    <div className="px-4 pt-4 pb-2">
      <p className="text-xs mb-3" style={{ color: T.muted }}>Ranked by breakout score · Week {WEEK} · excludes your league's rostered players</p>
      {error && <StatusPanel error={error} />}
      {loading && <p className="text-xs" style={{ color: T.muted }}>Loading...</p>}
      <div className="flex flex-col gap-2">
        {data?.candidates?.map((c) => (
          <div key={c.playerId} className="rounded-lg border p-3" style={{ backgroundColor: T.panel, borderColor: T.line, borderLeft: `3px solid ${TEAM_COLORS[c.team] || T.line}` }}>
            <div className="flex items-start justify-between mb-1.5">
              <div>
                <div className="flex items-center gap-1.5">
                  <PositionBadge position={c.position} />
                  <span className="font-bold text-sm" style={{ color: T.text }}>{c.name}</span>
                </div>
                <div className="text-[10px] flex items-center gap-1 mt-0.5" style={{ color: T.muted }}>
                  <TeamDot team={c.team} />
                  {c.team}{c.rosteredPct != null && ` · ${c.rosteredPct.toFixed(1)}% owned`}
                </div>
              </div>
              <div className="text-right">
                <div className="text-lg font-mono font-bold" style={{ color: c.breakoutScore >= 70 ? T.green : T.gold }}>{c.breakoutScore}</div>
                <div className="text-[8px] uppercase tracking-widest" style={{ color: T.muted }}>Breakout</div>
              </div>
            </div>
            {c.vacancyReason && (
              <div className="flex items-center gap-1.5 mb-1.5 rounded-md p-1.5" style={{ backgroundColor: T.panel2 }}>
                <ShieldAlert size={10} color={T.gold} />
                <span className="text-[10px]" style={{ color: T.text }}>{c.vacancyReason}</span>
              </div>
            )}
            <div className="flex items-center justify-between">
              <Sparkline points={c.trend.points} color={T.green} />
              <span className="text-[10px] font-mono px-2 py-1 rounded" style={{ backgroundColor: T.panel2, color: T.gold, border: `1px solid ${T.line}` }}>
                Bid {c.recommendedFaabPct}% FAAB
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------- App Shell ----------------
const TABS = [
  { id: "dash", label: "Home", icon: Home },
  { id: "draft", label: "Draft", icon: LayoutGrid },
  { id: "startsit", label: "Start/Sit", icon: Repeat },
  { id: "waivers", label: "Waivers", icon: Users },
];

export default function FantasyAppDemo() {
  const [tab, setTab] = useState("startsit");

  return (
    <div className="h-screen w-full flex justify-center" style={{ backgroundColor: "#05070C" }}>
      <div className="w-full max-w-sm h-screen flex flex-col" style={{ backgroundColor: T.ink }}>
        {/* Status/header bar */}
        <div className="flex items-center gap-2 px-4 pt-4 pb-2">
          <Flame size={16} color={T.gold} />
          <span className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: T.text }}>GridironIQ</span>
        </div>

        {/* Screen content */}
        <div className="flex-1 overflow-y-auto pb-2">
          {tab === "dash" && <DashboardScreen />}
          {tab === "draft" && <DraftScreen />}
          {tab === "startsit" && <StartSitScreen />}
          {tab === "waivers" && <WaiversScreen />}
        </div>

        {/* Bottom nav */}
        <div className="flex border-t" style={{ borderColor: T.line, backgroundColor: T.panel }}>
          {TABS.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className="flex-1 flex flex-col items-center gap-1 py-2.5">
              <Icon size={16} color={tab === id ? T.gold : T.muted} />
              <span className="text-[9px] font-semibold" style={{ color: tab === id ? T.gold : T.muted }}>{label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
