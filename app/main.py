"""Activiteitenformulier: kleine webapp voor het dagelijkse Meander-formulier."""
import base64
import csv
import io
import os
import re
import secrets
from datetime import date as Date, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import garmin, store

HERE = os.path.dirname(__file__)
USER = os.environ.get("APP_USER", "bjorn")
PASSWORD = os.environ.get("APP_PASSWORD", "")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PN = {"L": "Liggen", "Z": "Zitten", "S": "Staan/lopen"}

store.init()
app = FastAPI(title="Activiteitenformulier", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if PASSWORD:
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(u, USER) and secrets.compare_digest(p, PASSWORD)
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Activiteiten"'})
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _date(d):
    if not DATE_RE.match(d):
        raise HTTPException(400, "Ongeldige datum")
    return d


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/day/{d}")
def day(d: str):
    out = store.get_day(_date(d))
    out["garmin"] = store.get_garmin(d)
    return out


@app.put("/api/day/{d}")
async def put_day(d: str, request: Request):
    body = await request.json()
    return {"date": d, "slots": store.put_day(_date(d), body.get("slots"))}


@app.get("/api/settings")
def settings():
    return store.get_settings()


@app.put("/api/settings")
async def put_settings(request: Request):
    return store.put_settings(await request.json())


@app.get("/api/garmin/status")
def garmin_status():
    return {"configured": bool(os.environ.get("GARMIN_API_KEY", "").strip())}


@app.post("/api/garmin/sync/{d}")
async def garmin_sync(d: str):
    _date(d)
    try:
        await run_in_threadpool(garmin.sync, 1, Date.fromisoformat(d))
    except garmin.GarminError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"garmin": store.get_garmin(d)}


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


@app.get("/api/trend")
def trend(days: int = 30, end: str | None = None):
    days = max(7, min(366, days))
    e = Date.fromisoformat(_date(end)) if end else Date.today()
    s = e - timedelta(days=days - 1)
    dd = dict(store.all_days(s.isoformat(), e.isoformat()))
    gg = store.garmin_range(s.isoformat(), e.isoformat())
    rows = []
    for k in range(days):
        ds = (s + timedelta(days=k)).isoformat()
        sl, g = dd.get(ds) or [], gg.get(ds) or {}
        rows.append({
            "date": ds,
            "moeheid": _avg([v["m"] for v in sl if v]),
            "pijn": _avg([v["s"] for v in sl if v]),
            "liggen": sum(1 for v in sl if v and v["p"] == "L") / 2 if sl else None,
            "bb_min": g.get("bb_min"), "bb_max": g.get("bb_max"),
            "slaap": g.get("sleep_hours"), "rhr": g.get("rhr"),
            "hrv": (g.get("hrv") or {}).get("night"), "hrv_low": (g.get("hrv") or {}).get("low"),
            "hrv_high": (g.get("hrv") or {}).get("high"), "stappen": g.get("steps"), "stress": g.get("stress"),
        })
    return {"rows": rows}


@app.get("/api/export.csv")
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["datum", "tijd", "activiteit", "houding", "moeheid", "pijn", "opmerking"])
    for d, slots in store.all_days():
        for i, v in enumerate(slots):
            if v:
                m = 390 + 30 * i
                w.writerow([d, f"{m // 60:02d}:{m % 60:02d}", v["a"], PN.get(v["p"], ""),
                            "" if v["m"] is None else v["m"], "" if v["s"] is None else v["s"], v["n"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="activiteiten-alle-dagen.csv"'})


@app.post("/api/import")
async def import_csv(request: Request):
    """Importeert de CSV-export van de eerdere claude.ai-versie (of van deze app)."""
    text = (await request.body()).decode("utf-8-sig", errors="replace")
    rev = {v.lower(): k for k, v in PN.items()}
    per_day = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        d, t = (row.get("datum") or "").strip(), (row.get("tijd") or "").strip()
        if not DATE_RE.match(d) or not re.match(r"^\d{2}:\d{2}$", t):
            continue
        i = (int(t[:2]) * 60 + int(t[3:]) - 390) // 30
        if not 0 <= i < store.N_SLOTS:
            continue
        per_day.setdefault(d, [None] * store.N_SLOTS)[i] = {
            "a": row.get("activiteit", ""), "p": rev.get((row.get("houding") or "").strip().lower(), ""),
            "m": row.get("moeheid") or None, "s": row.get("pijn") or None, "n": row.get("opmerking", ""),
        }
    for d, slots in per_day.items():
        existing = store.get_day(d)["slots"]
        store.put_day(d, [e or n for e, n in zip(existing, slots)])
    return {"dagen": len(per_day)}


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
