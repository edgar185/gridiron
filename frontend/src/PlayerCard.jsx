import React, { useState } from "react";
import { ChevronDown, Wind, TrendingUp, TrendingDown, ShieldAlert, Flame } from "lucide-react";

// ---- Design tokens (broadcast scoreboard / telestrator direction) ----
const tokens = {
  ink: "#0B1220",
  panel: "#121A2C",
  panel2: "#16213A",
  line: "#243252",
  gold: "#F2B705",
  green: "#3ED07C",
  red: "#FF5C5C",
  textPrimary: "#EDEFF4",
  textMuted: "#8A96AC",
};

const PLAYERS = [
  {
    id: "p1",
    name: "J. CHASE",
    pos: "WR",
    team: "CIN",
    num: 1,
    opp: "vs PIT",
    rec: "START",
    confidence: 88,
    floor: 11.2,
    median: 18.4,
    ceiling: 27.1,
    matchupRank: 27, // defense rank vs position, 32 = easiest
    matchupNote: "PIT ranks 27th vs WR (EPA/target)",
    weather: null,
    rationale:
      "Target share up to 31% over the last 3 weeks and PIT's slot coverage has allowed the 5th-most YPRR to WRs.",
    trend: [0.21, 0.24, 0.26, 0.29, 0.31],
    trendLabel: "Target Share (L5)",
    kpis: {
      snapPct: 91,
      routePct: 94,
      targets: 9.4,
      targetShare: 31,
      yprr: 2.61,
      adot: 12.8,
      wopr: 0.71,
      rzTargets: 2.1,
    },
  },
  {
    id: "p2",
    name: "T. LOCKETT",
    pos: "WR",
    team: "SEA",
    num: 16,
    opp: "@ SF",
    rec: "SIT",
    confidence: 34,
    floor: 3.8,
    median: 8.1,
    ceiling: 15.9,
    matchupRank: 3,
    matchupNote: "SF ranks 3rd vs WR (EPA/target)",
    weather: { wind: 18, note: "18mph wind, outdoor" },
    rationale:
      "Route participation down to 68% over the last 3 weeks behind two rookies, and SF's secondary allows the 3rd-fewest fantasy points to WRs.",
    trend: [0.81, 0.76, 0.7, 0.69, 0.68],
    trendLabel: "Route Participation (L5)",
    kpis: {
      snapPct: 72,
      routePct: 68,
      targets: 4.9,
      targetShare: 14,
      yprr: 1.42,
      adot: 9.1,
      wopr: 0.31,
      rzTargets: 0.4,
    },
  },
];

function recColor(rec) {
  if (rec === "START") return tokens.green;
  if (rec === "SIT") return tokens.red;
  return tokens.gold;
}

function ConfidenceGauge({ value, color }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const filled = (value / 100) * c;
  return (
    <div className="relative w-28 h-28 flex items-center justify-center shrink-0">
      <svg width="112" height="112" viewBox="0 0 112 112" className="-rotate-90">
        <circle cx="56" cy="56" r={r} fill="none" stroke={tokens.line} strokeWidth="8" />
        <circle
          cx="56"
          cy="56"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${c - filled}`}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="font-mono text-2xl font-bold" style={{ color: tokens.textPrimary }}>
          {value}
        </span>
        <span className="text-[9px] tracking-widest uppercase" style={{ color: tokens.textMuted }}>
          Confidence
        </span>
      </div>
    </div>
  );
}

function RangeBar({ floor, median, ceiling }) {
  const max = ceiling * 1.15;
  const pct = (v) => (v / max) * 100;
  return (
    <div className="w-full">
      <div className="flex justify-between text-[10px] font-mono mb-1" style={{ color: tokens.textMuted }}>
        <span>FLOOR {floor}</span>
        <span style={{ color: tokens.gold }}>MEDIAN {median}</span>
        <span>CEIL {ceiling}</span>
      </div>
      <div className="relative h-2 rounded-full" style={{ backgroundColor: tokens.line }}>
        <div
          className="absolute h-2 rounded-full"
          style={{
            left: `${pct(floor)}%`,
            width: `${pct(ceiling) - pct(floor)}%`,
            backgroundColor: tokens.panel2,
            border: `1px solid ${tokens.gold}55`,
          }}
        />
        <div
          className="absolute top-1/2 -translate-y-1/2 w-1 h-4 rounded-sm"
          style={{ left: `${pct(median)}%`, backgroundColor: tokens.gold }}
        />
      </div>
    </div>
  );
}

function Sparkline({ points, color }) {
  const w = 88;
  const h = 28;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const norm = (v) => h - ((v - min) / (max - min || 1)) * h;
  const step = w / (points.length - 1);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${i * step} ${norm(p)}`).join(" ");
  return (
    <svg width={w} height={h}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={(points.length - 1) * step} cy={norm(points[points.length - 1])} r="2.5" fill={color} />
    </svg>
  );
}

function KPIRow({ label, value }) {
  return (
    <div className="flex justify-between py-1.5 border-b" style={{ borderColor: tokens.line }}>
      <span className="text-xs" style={{ color: tokens.textMuted }}>
        {label}
      </span>
      <span className="text-xs font-mono font-semibold" style={{ color: tokens.textPrimary }}>
        {value}
      </span>
    </div>
  );
}

function PlayerCard({ player, expanded, onToggle }) {
  const color = recColor(player.rec);
  return (
    <div
      className="rounded-lg overflow-hidden border w-full max-w-sm"
      style={{ backgroundColor: tokens.panel, borderColor: tokens.line }}
    >
      {/* Header stripe */}
      <div className="h-1.5 w-full" style={{ backgroundColor: color }} />

      {/* Top row: identity + recommendation badge */}
      <div className="p-4 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-lg tracking-tight" style={{ color: tokens.textPrimary }}>
              {player.name}
            </span>
            <span className="text-xs font-mono" style={{ color: tokens.textMuted }}>
              #{player.num}
            </span>
          </div>
          <div className="text-xs mt-0.5" style={{ color: tokens.textMuted }}>
            {player.pos} · {player.team} · {player.opp}
          </div>
        </div>
        <span
          className="px-2.5 py-1 rounded text-xs font-bold tracking-widest uppercase"
          style={{ color: tokens.ink, backgroundColor: color }}
        >
          {player.rec}
        </span>
      </div>

      {/* Gauge + rationale */}
      <div className="px-4 flex gap-3 items-center">
        <ConfidenceGauge value={player.confidence} color={color} />
        <p className="text-xs leading-relaxed" style={{ color: tokens.textPrimary }}>
          {player.rationale}
        </p>
      </div>

      {/* Range bar */}
      <div className="p-4">
        <RangeBar floor={player.floor} median={player.median} ceiling={player.ceiling} />
      </div>

      {/* Matchup + weather + trend tiles */}
      <div className="px-4 pb-4 grid grid-cols-2 gap-2">
        <div className="rounded-md p-2.5" style={{ backgroundColor: tokens.panel2 }}>
          <div className="flex items-center gap-1.5 mb-1">
            <ShieldAlert size={12} color={tokens.textMuted} />
            <span className="text-[9px] uppercase tracking-widest" style={{ color: tokens.textMuted }}>
              Matchup
            </span>
          </div>
          <div className="text-sm font-mono font-bold" style={{ color: tokens.textPrimary }}>
            #{player.matchupRank}/32
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: tokens.textMuted }}>
            {player.matchupNote}
          </div>
        </div>

        <div className="rounded-md p-2.5" style={{ backgroundColor: tokens.panel2 }}>
          <div className="flex items-center gap-1.5 mb-1">
            {player.trend[player.trend.length - 1] >= player.trend[0] ? (
              <TrendingUp size={12} color={tokens.green} />
            ) : (
              <TrendingDown size={12} color={tokens.red} />
            )}
            <span className="text-[9px] uppercase tracking-widest" style={{ color: tokens.textMuted }}>
              {player.trendLabel}
            </span>
          </div>
          <Sparkline
            points={player.trend}
            color={player.trend[player.trend.length - 1] >= player.trend[0] ? tokens.green : tokens.red}
          />
        </div>

        {player.weather && (
          <div className="col-span-2 rounded-md p-2.5 flex items-center gap-2" style={{ backgroundColor: tokens.panel2 }}>
            <Wind size={14} color={tokens.gold} />
            <span className="text-xs" style={{ color: tokens.textPrimary }}>
              {player.weather.note}
            </span>
          </div>
        )}
      </div>

      {/* Expand toggle */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-center gap-1.5 py-2.5 text-xs font-semibold uppercase tracking-widest border-t"
        style={{ borderColor: tokens.line, color: tokens.gold }}
      >
        Full KPI Breakdown
        <ChevronDown size={14} style={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.2s" }} />
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1" style={{ backgroundColor: tokens.ink }}>
          <KPIRow label="Snap %" value={`${player.kpis.snapPct}%`} />
          <KPIRow label="Route Participation" value={`${player.kpis.routePct}%`} />
          <KPIRow label="Targets / gm" value={player.kpis.targets} />
          <KPIRow label="Target Share" value={`${player.kpis.targetShare}%`} />
          <KPIRow label="Yards / Route Run" value={player.kpis.yprr} />
          <KPIRow label="Avg Depth of Target" value={player.kpis.adot} />
          <KPIRow label="WOPR" value={player.kpis.wopr} />
          <KPIRow label="Red-Zone Targets / gm" value={player.kpis.rzTargets} />
        </div>
      )}
    </div>
  );
}

export default function PlayerCardWireframe() {
  const [expandedId, setExpandedId] = useState(null);
  const [mode, setMode] = useState("compare"); // "compare" | "single"

  return (
    <div className="min-h-screen w-full flex flex-col items-center py-8 px-4" style={{ backgroundColor: tokens.ink }}>
      <div className="w-full max-w-3xl mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Flame size={18} color={tokens.gold} />
          <h1 className="text-sm font-bold uppercase tracking-[0.2em]" style={{ color: tokens.textMuted }}>
            Start / Sit — Player Card
          </h1>
        </div>
        <p className="text-xs" style={{ color: tokens.textMuted }}>
          Week 9 · Confidence-first layout. Tap "Full KPI Breakdown" for raw stats.
        </p>
      </div>

      <div className="w-full max-w-3xl flex flex-col md:flex-row gap-5 items-start justify-center">
        {PLAYERS.map((p) => (
          <PlayerCard key={p.id} player={p} expanded={expandedId === p.id} onToggle={() => setExpandedId(expandedId === p.id ? null : p.id)} />
        ))}
      </div>

      <div className="w-full max-w-3xl mt-5 rounded-lg border p-3 flex items-center justify-between" style={{ backgroundColor: tokens.panel, borderColor: tokens.line }}>
        <span className="text-xs" style={{ color: tokens.textMuted }}>
          Edge:
        </span>
        <span className="text-sm font-bold" style={{ color: tokens.green }}>
          Start J. CHASE over T. LOCKETT — 54 pt confidence gap
        </span>
      </div>
    </div>
  );
}
