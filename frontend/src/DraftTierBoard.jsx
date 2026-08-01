import React, { useState } from "react";
import { ChevronRight, AlertTriangle, TrendingDown, TrendingUp, Minus } from "lucide-react";

// ---- Design tokens (shared with player-card-wireframe for consistency) ----
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

const POSITIONS = ["QB", "RB", "WR", "TE"];

const TIER_DATA = {
  WR: {
    picksUntilTurn: 4,
    tiers: [
      {
        tier: 1,
        label: "Elite WR1",
        players: [
          { name: "J. CHASE", team: "CIN", adp: 4.2, vbd: 142.6, flag: "FAIR" },
          { name: "CEEDEE LAMB", team: "DAL", adp: 5.1, vbd: 138.9, flag: "FAIR" },
        ],
      },
      {
        tier: 2,
        label: "Strong WR1 / WR2",
        players: [
          { name: "A. BROWN", team: "PHI", adp: 11.8, vbd: 118.3, flag: "REACH" },
          { name: "G. WILSON", team: "NYJ", adp: 14.1, vbd: 109.7, flag: "VALUE" },
          { name: "D. MOORE", team: "CHI", adp: 15.4, vbd: 106.2, flag: "FAIR" },
        ],
      },
      {
        tier: 3,
        label: "WR2 Floor",
        players: [
          { name: "T. HIGGINS", team: "CIN", adp: 22.9, vbd: 84.1, flag: "VALUE" },
          { name: "D. LONDON", team: "ATL", adp: 24.6, vbd: 80.7, flag: "FAIR" },
        ],
      },
    ],
  },
  RB: {
    picksUntilTurn: 4,
    tiers: [
      {
        tier: 1,
        label: "Bell-Cow RB1",
        players: [{ name: "B. ROBINSON", team: "ATL", adp: 6.3, vbd: 151.2, flag: "FAIR" }],
      },
      {
        tier: 2,
        label: "RB1 / High-Floor RB2",
        players: [
          { name: "J. GIBBS", team: "DET", adp: 9.7, vbd: 129.4, flag: "REACH" },
          { name: "K. WALKER", team: "SEA", adp: 13.2, vbd: 112.8, flag: "VALUE" },
        ],
      },
    ],
  },
  QB: { picksUntilTurn: 4, tiers: [{ tier: 1, label: "Elite QB1", players: [{ name: "J. ALLEN", team: "BUF", adp: 28.1, vbd: 61.4, flag: "FAIR" }] }] },
  TE: { picksUntilTurn: 4, tiers: [{ tier: 1, label: "Elite TE", players: [{ name: "S. LAPORTA", team: "DET", adp: 18.9, vbd: 58.2, flag: "FAIR" }] }] },
};

function flagColor(flag) {
  if (flag === "VALUE") return tokens.green;
  if (flag === "REACH") return tokens.red;
  return tokens.textMuted;
}

function ScarcityMeter({ playersLeft, picksUntilTurn }) {
  const critical = playersLeft <= picksUntilTurn;
  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1 rounded"
      style={{ backgroundColor: critical ? `${tokens.red}22` : tokens.panel2, border: `1px solid ${critical ? tokens.red : tokens.line}` }}
    >
      {critical && <AlertTriangle size={11} color={tokens.red} />}
      <span className="text-[10px] font-mono font-semibold" style={{ color: critical ? tokens.red : tokens.textMuted }}>
        {playersLeft} LEFT · {picksUntilTurn} PICKS TO YOU
      </span>
    </div>
  );
}

function PlayerRow({ player, isBest }) {
  return (
    <div
      className="flex items-center justify-between px-3 py-2.5 rounded-md mb-1.5"
      style={{
        backgroundColor: isBest ? `${tokens.gold}15` : tokens.panel2,
        border: `1px solid ${isBest ? tokens.gold : tokens.line}`,
      }}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        {isBest && (
          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded uppercase shrink-0" style={{ backgroundColor: tokens.gold, color: tokens.ink }}>
            BPA
          </span>
        )}
        <div className="min-w-0">
          <div className="text-sm font-bold truncate" style={{ color: tokens.textPrimary }}>
            {player.name}
          </div>
          <div className="text-[10px]" style={{ color: tokens.textMuted }}>
            {player.team} · ADP {player.adp}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <div className="text-right">
          <div className="text-xs font-mono font-bold" style={{ color: tokens.textPrimary }}>
            {player.vbd}
          </div>
          <div className="text-[9px] uppercase tracking-wide" style={{ color: tokens.textMuted }}>
            VBD
          </div>
        </div>
        <span
          className="text-[9px] font-bold px-1.5 py-1 rounded uppercase w-14 text-center"
          style={{ color: flagColor(player.flag), border: `1px solid ${flagColor(player.flag)}55` }}
        >
          {player.flag}
        </span>
      </div>
    </div>
  );
}

function TierBlock({ tier, picksUntilTurn }) {
  const playersLeft = tier.players.length;
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-2 px-1">
        <div className="flex items-center gap-2">
          <span
            className="w-6 h-6 flex items-center justify-center rounded-full text-xs font-mono font-bold"
            style={{ backgroundColor: tokens.panel2, color: tokens.gold, border: `1px solid ${tokens.line}` }}
          >
            {tier.tier}
          </span>
          <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: tokens.textPrimary }}>
            {tier.label}
          </span>
        </div>
        <ScarcityMeter playersLeft={playersLeft} picksUntilTurn={picksUntilTurn} />
      </div>
      {tier.players.map((p, i) => (
        <PlayerRow key={p.name} player={p} isBest={tier.tier === 1 && i === 0} />
      ))}
      <div className="h-px w-full mt-3" style={{ backgroundColor: tokens.line }} />
    </div>
  );
}

export default function DraftTierBoard() {
  const [position, setPosition] = useState("WR");
  const data = TIER_DATA[position];

  return (
    <div className="min-h-screen w-full flex flex-col items-center py-8 px-4" style={{ backgroundColor: tokens.ink }}>
      <div className="w-full max-w-md mb-5">
        <h1 className="text-sm font-bold uppercase tracking-[0.2em] mb-1" style={{ color: tokens.textMuted }}>
          Draft Room — Tier Board
        </h1>
        <p className="text-xs" style={{ color: tokens.textMuted }}>
          Round 3, Pick 4 · Snake draft · 12-team PPR
        </p>
      </div>

      {/* Position tabs */}
      <div className="w-full max-w-md flex gap-1.5 mb-4">
        {POSITIONS.map((pos) => (
          <button
            key={pos}
            onClick={() => setPosition(pos)}
            className="flex-1 py-2 rounded-md text-xs font-bold tracking-wide"
            style={{
              backgroundColor: position === pos ? tokens.gold : tokens.panel,
              color: position === pos ? tokens.ink : tokens.textMuted,
              border: `1px solid ${position === pos ? tokens.gold : tokens.line}`,
            }}
          >
            {pos}
          </button>
        ))}
      </div>

      {/* Board */}
      <div className="w-full max-w-md rounded-lg border p-4" style={{ backgroundColor: tokens.panel, borderColor: tokens.line }}>
        {data.tiers.map((tier) => (
          <TierBlock key={tier.tier} tier={tier} picksUntilTurn={data.picksUntilTurn} />
        ))}

        <button
          className="w-full flex items-center justify-center gap-1 py-2.5 rounded-md text-xs font-semibold uppercase tracking-widest"
          style={{ backgroundColor: tokens.panel2, color: tokens.gold, border: `1px solid ${tokens.line}` }}
        >
          View Remaining {position}s
          <ChevronRight size={13} />
        </button>
      </div>

      {/* Roster need strip */}
      <div className="w-full max-w-md mt-4 rounded-lg border p-3 flex items-center gap-2" style={{ backgroundColor: tokens.panel, borderColor: tokens.line }}>
        <Minus size={13} color={tokens.textMuted} className="rotate-90" />
        <span className="text-[11px]" style={{ color: tokens.textMuted }}>
          Your roster: <span style={{ color: tokens.textPrimary, fontWeight: 600 }}>1 QB · 2 RB · 1 WR · 1 TE</span> filled — WR is your deepest remaining need
        </span>
      </div>
    </div>
  );
}
