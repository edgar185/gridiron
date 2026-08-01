"""
GridironIQ backend — starter implementation.

Currently implements one endpoint from docs/02-api-contracts.md end to end
to prove the Docker -> Postgres -> FastAPI chain works. Add /compare,
/draft/tiers, and /waivers/candidates following the same pattern —
see docs/02-api-contracts.md for the full response shapes.
"""

import os
from fastapi import FastAPI
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="GridironIQ API")
DB_URL = os.environ["DATABASE_URL"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/players/{player_id}/card")
def player_card(player_id: str, week: int, scoring: str = "ppr"):
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT p.player_id, p.full_name AS name, p.position, t.team_id AS team,
                   pr.floor_pts, pr.median_pts, pr.ceiling_pts, pr.confidence_score,
                   pr.recommendation, pr.rationale_text
            FROM players p
            JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN projections pr
              ON pr.player_id = p.player_id AND pr.week = %s
            WHERE p.player_id = %s
            """,
            (week, player_id),
        ).fetchone()
    return row or {"error": {"code": "PLAYER_NOT_FOUND"}}
