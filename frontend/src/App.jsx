import React, { useState } from "react";
import {
  Flame, ChevronDown, ChevronRight, Wind, TrendingUp, TrendingDown,
  ShieldAlert, AlertTriangle, LayoutGrid, Users, Repeat, Home,
} from "lucide-react";

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

// ---- Mock data ----
const CARD_PLAYERS = [
  {
    name: "J. CHASE", pos: "WR", team: "CIN", num: 1, opp: "vs PIT", rec: "START",
    confidence: 88, floor: 11.2, median: 18.4, ceiling: 27.1, matchupRank: 27,
    matchupNote: "PIT ranks 27th vs WR", weather: null,
    rationale: "Target share up to 31% over the last 3 weeks and PIT's slot coverage has allowed the 5th-most YPRR to WRs.",
    trend: [0.21, 0.24, 0.26, 0.29, 0.31], trendLabel: "Target Share (L5)",
  },
  {
    name: "T. LOCKETT", pos: "WR", team: "SEA", num: 16, opp: "@ SF", rec: "SIT",
    confidence: 34, floor: 3.8, median: 8.1, ceiling: 15.9, matchupRank: 3,
    matchupNote: "SF ranks 3rd vs WR", weather: { note: "18mph wind, outdoor" },
    rationale: "Route participation down to 68% over the last 3 weeks, and SF allows the 3rd-fewest fantasy points to WRs.",
    trend: [0.81, 0.76, 0.7, 0.69, 0.68], trendLabel: "Route Participation (L5)",
  },
];

const TIERS_WR = [
  { tier: 1, label: "Elite WR1", players: [
    { name: "J. CHASE", team: "CIN", adp: 4.2, vbd: 142.6, flag: "FAIR" },
    { name: "CEEDEE LAMB", team: "DAL", adp: 5.1, vbd: 138.9, flag: "FAIR" },
  ]},
  { tier: 2, label: "Strong WR1 / WR2", players: [
    { name: "A. BROWN", team: "PHI", adp: 11.8, vbd: 118.3, flag: "REACH" },
    { name: "G. WILSON", team: "NYJ", adp: 14.1, vbd: 109.7, flag: "VALUE" },
  ]},
];

const WAIVER_CANDIDATES = [
  { name: "R. WHITE", pos: "RB", team: "TB", rostered: 41.2, breakout: 82, faab: 18,
    reason: "Starting RB placed on IR (ankle) — Wk8", trend: [0.22, 0.31, 0.44, 0.58, 0.63] },
  { name: "J. FLOWERS", pos: "WR", team: "BAL", rostered: 19.5, breakout: 71, faab: 9,
    reason: "Route participation up 3 straight weeks behind an injured starter", trend: [0.4, 0.48, 0.55, 0.6, 0.66] },
  { name: "T. HOCKENSON", pos: "TE", team: "MIN", rostered: 88.0, breakout: 55, faab: 4,
    reason: "Target share steady, favorable next-3 matchups vs bottom-10 TE defenses", trend: [0.18, 0.2, 0.19, 0.22, 0.23] },
];

function recColor(rec) {
  if (rec === "START") return T.green;
  if (rec === "SIT") return T.red;
  return T.gold;
}
function flagColor(flag) {
  if (flag === "VALUE") return T.green;
  if (flag === "REACH") return T.red;
  return T.muted;
}

function Sparkline({ points, color }) {
  const w = 72, h = 24;
  const min = Math.min(...points), max = Math.max(...points);
  const norm = (v) => h - ((v - min) / (max - min || 1)) * h;
  const step = w / (points.length - 1);
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
  const max = ceiling * 1.15;
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
  return (
    <div className="px-4 pt-4 pb-2">
      <p className="text-xs mb-3" style={{ color: T.muted }}>Week 9 · Sunday 8:15 AM</p>

      <div className="rounded-lg border p-3 mb-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <div className="flex items-center gap-1.5 mb-1">
          <AlertTriangle size={12} color={T.red} />
          <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.red }}>Lineup Alert</span>
        </div>
        <p className="text-xs" style={{ color: T.text }}>T. Lockett flagged SIT (18mph wind + 68% route rate) — you have him starting.</p>
      </div>

      <div className="rounded-lg border p-3 mb-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <div className="flex items-center gap-1.5 mb-1">
          <TrendingUp size={12} color={T.green} />
          <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.green }}>Top Waiver Target</span>
        </div>
        <p className="text-xs" style={{ color: T.text }}>R. White (TB RB) — 82 breakout score, recommend 18% FAAB.</p>
      </div>

      <div className="rounded-lg border p-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: T.muted }}>This Week's Confidence</span>
        <div className="flex justify-between mt-2">
          {["QB", "RB1", "RB2", "WR1", "WR2", "TE"].map((slot, i) => (
            <div key={slot} className="flex flex-col items-center gap-1">
              <div className="w-7 h-7 rounded-full flex items-center justify-center text-[9px] font-mono font-bold"
                style={{ backgroundColor: T.panel2, color: [T.green, T.green, T.gold, T.green, T.red, T.gold][i], border: `1px solid ${T.line}` }}>
                {[91, 84, 58, 88, 34, 62][i]}
              </div>
              <span className="text-[8px]" style={{ color: T.muted }}>{slot}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------- Screen: Start/Sit ----------------
function StartSitScreen() {
  const [expandedIdx, setExpandedIdx] = useState(null);
  return (
    <div className="px-4 pt-4 pb-2">
      <p className="text-xs mb-3" style={{ color: T.muted }}>Comparing your WR2 options — Week 9</p>
      <div className="flex flex-col gap-3">
        {CARD_PLAYERS.map((p, idx) => {
          const color = recColor(p.rec);
          return (
            <div key={p.name} className="rounded-lg border overflow-hidden" style={{ backgroundColor: T.panel, borderColor: T.line }}>
              <div className="h-1 w-full" style={{ backgroundColor: color }} />
              <div className="p-3 flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm" style={{ color: T.text }}>{p.name}</span>
                    <span className="text-[10px] font-mono" style={{ color: T.muted }}>#{p.num}</span>
                  </div>
                  <div className="text-[10px] mt-0.5" style={{ color: T.muted }}>{p.pos} · {p.team} · {p.opp}</div>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase"
                  style={{ color: T.ink, backgroundColor: color }}>{p.rec}</span>
              </div>
              <div className="px-3 flex gap-2.5 items-center">
                <ConfidenceGauge value={p.confidence} color={color} size={72} />
                <p className="text-[11px] leading-snug" style={{ color: T.text }}>{p.rationale}</p>
              </div>
              <div className="p-3"><RangeBar floor={p.floor} median={p.median} ceiling={p.ceiling} /></div>
              <div className="px-3 pb-3 grid grid-cols-2 gap-2">
                <div className="rounded-md p-2" style={{ backgroundColor: T.panel2 }}>
                  <div className="flex items-center gap-1 mb-0.5"><ShieldAlert size={10} color={T.muted} />
                    <span className="text-[8px] uppercase tracking-widest" style={{ color: T.muted }}>Matchup</span></div>
                  <div className="text-xs font-mono font-bold" style={{ color: T.text }}>#{p.matchupRank}/32</div>
                </div>
                <div className="rounded-md p-2" style={{ backgroundColor: T.panel2 }}>
                  <div className="flex items-center gap-1 mb-0.5">
                    {p.trend.at(-1) >= p.trend[0] ? <TrendingUp size={10} color={T.green} /> : <TrendingDown size={10} color={T.red} />}
                    <span className="text-[8px] uppercase tracking-widest" style={{ color: T.muted }}>{p.trendLabel}</span></div>
                  <Sparkline points={p.trend} color={p.trend.at(-1) >= p.trend[0] ? T.green : T.red} />
                </div>
                {p.weather && (
                  <div className="col-span-2 rounded-md p-2 flex items-center gap-1.5" style={{ backgroundColor: T.panel2 }}>
                    <Wind size={12} color={T.gold} /><span className="text-[10px]" style={{ color: T.text }}>{p.weather.note}</span>
                  </div>
                )}
              </div>
              <button onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                className="w-full flex items-center justify-center gap-1 py-2 text-[10px] font-semibold uppercase tracking-widest border-t"
                style={{ borderColor: T.line, color: T.gold }}>
                Full KPI Breakdown
                <ChevronDown size={12} style={{ transform: expandedIdx === idx ? "rotate(180deg)" : "none" }} />
              </button>
              {expandedIdx === idx && (
                <div className="px-3 pb-3 pt-1" style={{ backgroundColor: T.ink }}>
                  {["Snap % · 91%", "Route Participation · 94%", "Target Share · 31%", "Yards/Route Run · 2.61"].map((row) => (
                    <div key={row} className="flex justify-between py-1 border-b text-[10px]" style={{ borderColor: T.line }}>
                      <span style={{ color: T.muted }}>{row.split(" · ")[0]}</span>
                      <span className="font-mono font-semibold" style={{ color: T.text }}>{row.split(" · ")[1]}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 rounded-lg border p-2.5 flex items-center justify-between" style={{ backgroundColor: T.panel, borderColor: T.line }}>
        <span className="text-[10px]" style={{ color: T.muted }}>Edge:</span>
        <span className="text-xs font-bold" style={{ color: T.green }}>Start CHASE — 54 pt confidence gap</span>
      </div>
    </div>
  );
}

// ---------------- Screen: Draft ----------------
function DraftScreen() {
  return (
    <div className="px-4 pt-4 pb-2">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs" style={{ color: T.muted }}>Round 3, Pick 4 · WR</p>
        <span className="text-[9px] font-mono px-2 py-1 rounded" style={{ backgroundColor: `${T.red}22`, color: T.red, border: `1px solid ${T.red}` }}>4 PICKS TO YOU</span>
      </div>
      {TIERS_WR.map((tier) => (
        <div key={tier.tier} className="mb-3">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="w-5 h-5 flex items-center justify-center rounded-full text-[10px] font-mono font-bold"
              style={{ backgroundColor: T.panel2, color: T.gold, border: `1px solid ${T.line}` }}>{tier.tier}</span>
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: T.text }}>{tier.label}</span>
          </div>
          {tier.players.map((p, i) => (
            <div key={p.name} className="flex items-center justify-between px-2.5 py-2 rounded-md mb-1"
              style={{ backgroundColor: tier.tier === 1 && i === 0 ? `${T.gold}15` : T.panel2, border: `1px solid ${tier.tier === 1 && i === 0 ? T.gold : T.line}` }}>
              <div className="flex items-center gap-2">
                {tier.tier === 1 && i === 0 && <span className="text-[8px] font-bold px-1 py-0.5 rounded uppercase" style={{ backgroundColor: T.gold, color: T.ink }}>BPA</span>}
                <div>
                  <div className="text-xs font-bold" style={{ color: T.text }}>{p.name}</div>
                  <div className="text-[9px]" style={{ color: T.muted }}>{p.team} · ADP {p.adp}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="text-right">
                  <div className="text-[11px] font-mono font-bold" style={{ color: T.text }}>{p.vbd}</div>
                  <div className="text-[7px] uppercase" style={{ color: T.muted }}>VBD</div>
                </div>
                <span className="text-[8px] font-bold px-1 py-0.5 rounded uppercase" style={{ color: flagColor(p.flag), border: `1px solid ${flagColor(p.flag)}55` }}>{p.flag}</span>
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
  return (
    <div className="px-4 pt-4 pb-2">
      <p className="text-xs mb-3" style={{ color: T.muted }}>Ranked by breakout score · Week 9</p>
      <div className="flex flex-col gap-2">
        {WAIVER_CANDIDATES.map((c) => (
          <div key={c.name} className="rounded-lg border p-3" style={{ backgroundColor: T.panel, borderColor: T.line }}>
            <div className="flex items-start justify-between mb-1.5">
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="font-bold text-sm" style={{ color: T.text }}>{c.name}</span>
                  <span className="text-[9px] px-1 rounded" style={{ color: T.muted, border: `1px solid ${T.line}` }}>{c.pos}</span>
                </div>
                <div className="text-[10px] mt-0.5" style={{ color: T.muted }}>{c.team} · {c.rostered}% rostered</div>
              </div>
              <div className="text-right">
                <div className="text-lg font-mono font-bold" style={{ color: c.breakout >= 70 ? T.green : T.gold }}>{c.breakout}</div>
                <div className="text-[8px] uppercase tracking-widest" style={{ color: T.muted }}>Breakout</div>
              </div>
            </div>
            <p className="text-[10px] mb-2" style={{ color: T.text }}>{c.reason}</p>
            <div className="flex items-center justify-between">
              <Sparkline points={c.trend} color={T.green} />
              <span className="text-[10px] font-mono px-2 py-1 rounded" style={{ backgroundColor: T.panel2, color: T.gold, border: `1px solid ${T.line}` }}>
                Bid {c.faab}% FAAB
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
    <div className="min-h-screen w-full flex justify-center" style={{ backgroundColor: "#05070C" }}>
      <div className="w-full max-w-sm min-h-screen flex flex-col" style={{ backgroundColor: T.ink }}>
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
