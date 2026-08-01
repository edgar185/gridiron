"""
Ingest game-day weather for outdoor stadiums into the `weather` table.

Source: Open-Meteo (https://open-meteo.com) — free, no API key, no rate-limit
issues at this volume (~16 games/week).

Run: python weather_ingest.py --week 9
"""

import argparse
import os
import requests
import psycopg
from psycopg.rows import dict_row

DB_URL = os.environ["DATABASE_URL"]


def get_outdoor_games(conn, week):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT g.game_id, g.kickoff_ts, s.stadium_id
            FROM games g
            JOIN stadiums s ON s.stadium_id = g.stadium_id
            WHERE g.week = %s AND s.is_dome = false
            """,
            (week,),
        )
        return cur.fetchall()


def get_stadium_coords(conn, stadium_id):
    # Requires a lat/lon column pair on stadiums in practice — adding here
    # as the two columns this script needs; not in the original DDL.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT latitude, longitude FROM stadiums WHERE stadium_id = %s", (stadium_id,))
        return cur.fetchone()


def fetch_forecast(lat, lon, date_str):
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation_probability,windspeed_10m",
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "start_date": date_str,
            "end_date": date_str,
        },
    )
    resp.raise_for_status()
    return resp.json()


def store_weather(conn, game_id, forecast, kickoff_hour):
    hourly = forecast["hourly"]
    idx = kickoff_hour  # simplification — match nearest hour index in production
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weather (game_id, temp_f, wind_mph, precip_pct, is_dome)
            VALUES (%s, %s, %s, %s, false)
            ON CONFLICT (game_id) DO UPDATE SET
                temp_f = EXCLUDED.temp_f,
                wind_mph = EXCLUDED.wind_mph,
                precip_pct = EXCLUDED.precip_pct
            """,
            (
                game_id,
                hourly["temperature_2m"][idx],
                hourly["windspeed_10m"][idx],
                hourly["precipitation_probability"][idx],
            ),
        )
    conn.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    with psycopg.connect(DB_URL) as conn:
        games = get_outdoor_games(conn, args.week)
        for g in games:
            coords = get_stadium_coords(conn, g["stadium_id"])
            if not coords:
                continue
            date_str = g["kickoff_ts"].strftime("%Y-%m-%d")
            forecast = fetch_forecast(coords["latitude"], coords["longitude"], date_str)
            store_weather(conn, g["game_id"], forecast, kickoff_hour=g["kickoff_ts"].hour)
        print(f"Weather refreshed for {len(games)} outdoor games, week {args.week}")
