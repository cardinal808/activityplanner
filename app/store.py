"""SQLite opslag: dagen, instellingen en Garmin-gegevens per dag."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/var/lib/activiteiten"))
DB_PATH = DATA_DIR / "activiteiten.db"
N_SLOTS = 34  # 06:30 t/m 23:00, per half uur

_lock = threading.Lock()


def _conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS days(date TEXT PRIMARY KEY, slots TEXT NOT NULL, updated REAL);
            CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS garmin(date TEXT PRIMARY KEY, data TEXT NOT NULL, fetched REAL);
            """
        )


def clean_slots(slots):
    out = [None] * N_SLOTS
    if isinstance(slots, list):
        for i, v in enumerate(slots[:N_SLOTS]):
            if isinstance(v, dict) and str(v.get("a", "")).strip():
                p = v.get("p") if v.get("p") in ("L", "Z", "S") else ""
                def score(x):
                    try:
                        x = int(x)
                        return x if 0 <= x <= 10 else None
                    except (TypeError, ValueError):
                        return None
                out[i] = {
                    "a": str(v["a"]).strip()[:80],
                    "p": p,
                    "m": score(v.get("m")),
                    "s": score(v.get("s")),
                    "n": str(v.get("n") or "").strip()[:40],
                }
    return out


def get_day(date):
    with _conn() as c:
        r = c.execute("SELECT slots, updated FROM days WHERE date=?", (date,)).fetchone()
    return {"date": date, "slots": clean_slots(json.loads(r["slots"])) if r else [None] * N_SLOTS,
            "updated": r["updated"] if r else None}


def put_day(date, slots):
    slots = clean_slots(slots)
    with _lock, _conn() as c:
        if any(slots):
            c.execute("INSERT INTO days(date,slots,updated) VALUES(?,?,?) "
                      "ON CONFLICT(date) DO UPDATE SET slots=excluded.slots, updated=excluded.updated",
                      (date, json.dumps(slots), time.time()))
        else:
            c.execute("DELETE FROM days WHERE date=?", (date,))
    return slots


def all_days(start=None, end=None):
    q, a = "SELECT date, slots FROM days", []
    if start and end:
        q += " WHERE date BETWEEN ? AND ?"
        a = [start, end]
    with _conn() as c:
        rows = c.execute(q + " ORDER BY date", a).fetchall()
    return [(r["date"], clean_slots(json.loads(r["slots"]))) for r in rows]


DEFAULT_SETTINGS = {
    "naam": "",
    "favs": [
        {"a": "Slapen", "p": "L"}, {"a": "Rusten", "p": "L"}, {"a": "Ontbijt", "p": "Z"},
        {"a": "Douchen/aankleden", "p": "S"}, {"a": "Werken", "p": "Z"}, {"a": "Lunch", "p": "Z"},
        {"a": "Wandelen", "p": "S"}, {"a": "Huishouden", "p": "S"}, {"a": "Koken", "p": "S"},
        {"a": "Avondeten", "p": "Z"}, {"a": "Tv kijken", "p": "Z"}, {"a": "Autorijden", "p": "Z"},
    ],
}


def get_settings():
    with _conn() as c:
        r = c.execute("SELECT v FROM settings WHERE k='main'").fetchone()
    s = dict(DEFAULT_SETTINGS)
    if r:
        s.update(json.loads(r["v"]))
    return s


def put_settings(s):
    favs = []
    for f in s.get("favs", [])[:60]:
        if isinstance(f, dict) and str(f.get("a", "")).strip():
            favs.append({"a": str(f["a"]).strip()[:80], "p": f.get("p") if f.get("p") in ("L", "Z", "S") else "Z"})
    clean = {"naam": str(s.get("naam", "")).strip()[:80], "favs": favs}
    with _lock, _conn() as c:
        c.execute("INSERT INTO settings(k,v) VALUES('main',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  (json.dumps(clean),))
    return clean


def get_garmin(date):
    with _conn() as c:
        r = c.execute("SELECT data FROM garmin WHERE date=?", (date,)).fetchone()
    return json.loads(r["data"]) if r else None


def put_garmin(date, data):
    with _lock, _conn() as c:
        c.execute("INSERT INTO garmin(date,data,fetched) VALUES(?,?,?) "
                  "ON CONFLICT(date) DO UPDATE SET data=excluded.data, fetched=excluded.fetched",
                  (date, json.dumps(data), time.time()))


def garmin_range(start, end):
    with _conn() as c:
        rows = c.execute("SELECT date, data FROM garmin WHERE date BETWEEN ? AND ? ORDER BY date",
                         (start, end)).fetchall()
    return {r["date"]: json.loads(r["data"]) for r in rows}


def get_kv(k):
    with _conn() as c:
        r = c.execute("SELECT v FROM settings WHERE k=?", ("kv:" + k,)).fetchone()
    return json.loads(r["v"]) if r else None


def put_kv(k, v):
    with _lock, _conn() as c:
        c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  ("kv:" + k, json.dumps(v)))
