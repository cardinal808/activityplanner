"""Garmin Connect Personal API: token ophalen en per dag slaap, activiteiten,
Body Battery en hartslag samenvatten tot het half-uurrooster van het formulier.

Endpoints volgens Garmins Personal API-documentatie (Swagger, versie 1.0.0).
"""
import json
import os
import time
from datetime import date as Date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from . import store

BASE = os.environ.get("GARMIN_BASE", "https://personal.connectapi.garmin.com")
TOKEN_URL = BASE + "/personalapitoken-service/personal-api/personal-api-key/token"
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam"))
TOKEN_FILE = store.DATA_DIR / "garmin-token.json"
SLOT0, SLOT_MIN, N = 390, 30, store.N_SLOTS  # 06:30, 30 min, 34 vakjes


class GarminError(Exception):
    pass


def _api_key():
    k = os.environ.get("GARMIN_API_KEY", "").strip()
    if not k:
        raise GarminError("GARMIN_API_KEY ontbreekt in /etc/activiteiten.env")
    return k


def _token(force=False):
    if not force and TOKEN_FILE.exists():
        try:
            t = json.loads(TOKEN_FILE.read_text())
            if t.get("exp", 0) > time.time() + 300:
                return t["token"]
        except (ValueError, KeyError):
            pass
    r = httpx.post(TOKEN_URL, headers={"Authorization": "ApiKey " + _api_key()}, timeout=30)
    if r.status_code >= 400:
        raise GarminError(f"Token ophalen mislukt (HTTP {r.status_code}). Klopt de sleutel en is hij niet verlopen?")
    tok, ttl = None, 23 * 3600
    try:
        j = r.json()
        if isinstance(j, dict):
            tok = j.get("access_token") or j.get("accessToken") or j.get("token")
            ttl = int(j.get("expires_in") or j.get("expiresIn") or ttl)
        elif isinstance(j, str):
            tok = j
    except ValueError:
        tok = r.text.strip()
    if not tok:
        raise GarminError("Onbekend antwoord van de token-service (geen token gevonden)")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"token": tok, "exp": time.time() + min(ttl, 23 * 3600)}))
    os.chmod(TOKEN_FILE, 0o600)
    return tok


def get(path, params=None):
    for attempt in (0, 1):
        r = httpx.get(BASE + path, params=params,
                      headers={"Authorization": "Bearer " + _token(force=attempt == 1), "Accept": "application/json"},
                      timeout=45)
        if r.status_code == 401 and attempt == 0:
            continue
        if r.status_code == 204 or not r.content:
            return None
        if r.status_code >= 400:
            raise GarminError(f"{path}: HTTP {r.status_code}")
        return r.json()


# ---------- tijd ----------
def to_local(v, naive_is_utc=True):
    """Garmin geeft tijden als epoch-ms, ISO-tekst of {date, localDate}."""
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("date") or v.get("localDate")
        if v is None:
            return None
    if isinstance(v, (int, float)):
        sec = v / 1000 if v > 1e11 else v
        return datetime.fromtimestamp(sec, timezone.utc).astimezone(TZ)
    s = str(v).strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc if naive_is_utc else TZ)
    return d.astimezone(TZ)


def _mins(dt, day):
    """Minuten vanaf middernacht van `day` (lokaal), begrensd tot de dag."""
    start = datetime.combine(day, datetime.min.time(), TZ)
    m = (dt - start).total_seconds() / 60
    return max(0, min(1440, round(m)))


def _interval(a, b, day, label):
    if not a or not b or b <= a:
        return None
    s, e = _mins(a, day), _mins(b, day)
    if e - s < 5:
        return None
    return {"s": s, "e": e, "label": label, "van": a.strftime("%H:%M"), "tot": b.strftime("%H:%M")}


def _slot_means(rows, day):
    """rows: [(datetime, waarde)] → gemiddelde per half-uurvak (afgerond) of None."""
    acc = [[] for _ in range(N)]
    for dt, val in rows:
        if dt is None or val is None or dt.date() != day:
            continue
        m = dt.hour * 60 + dt.minute
        i = (m - SLOT0) // SLOT_MIN
        if 0 <= i < N:
            acc[i].append(val)
    return [round(sum(a) / len(a)) if a else None for a in acc]


def _cols(descriptors, idx_key, name_key):
    out = {}
    for d in descriptors or []:
        if isinstance(d, dict):
            out[str(d.get(name_key))] = d.get(idx_key)
    return out


SITTING_TYPES = ("cycling", "indoor_cycling", "rowing", "indoor_rowing", "driving", "kayak", "e_bike")


def build_day(day: Date):
    ds, errors = day.isoformat(), []
    out = {"date": ds, "fetched": time.time(), "sleep": [], "naps": [], "activities": [],
           "bb": [None] * N, "hr": [None] * N, "steps": None, "stress": None,
           "bb_min": None, "bb_max": None, "sleep_hours": None, "rhr": None, "hrv": None, "errors": errors}

    # Slaap: de nacht vóór deze dag (record van `day`) en de nacht erna (record van day+1).
    for d in (day, day + timedelta(days=1)):
        try:
            sl = get("/sleep-service/sleep/dailySleep", {"date": d.isoformat()}) or {}
            iv = _interval(to_local(sl.get("sleepStartTimestampGMT")), to_local(sl.get("sleepEndTimestampGMT")), day, "Slapen")
            if iv:
                out["sleep"].append(iv)
            if d == day and sl.get("sleepTimeSeconds"):
                out["sleep_hours"] = round(sl["sleepTimeSeconds"] / 3600, 1)
            for nap in sl.get("dailyNapDTOS") or []:
                iv = _interval(to_local(nap.get("napStartTimestampGMT")), to_local(nap.get("napEndTimestampGMT")), day, "Dutje")
                if iv:
                    out["naps"].append(iv)
        except Exception as e:  # noqa: BLE001
            errors.append(f"slaap {d}: {e}")

    try:
        acts = get("/activitylist-service/activities/search/activities",
                   {"startDate": ds, "endDate": ds, "limit": 50}) or []
        for a in acts:
            st = to_local(a.get("startTimeLocal"), naive_is_utc=False) or to_local(a.get("startTimeGMT"))
            dur = a.get("duration") or a.get("elapsedDuration") or 0
            if not st or not dur:
                continue
            t = a.get("activityType") or {}
            key = (t.get("typeKey") or t.get("key") or "") if isinstance(t, dict) else str(t)
            iv = _interval(st, st + timedelta(seconds=float(dur)), day, a.get("activityName") or key or "Activiteit")
            if iv:
                iv["type"] = key
                iv["p"] = "Z" if any(k in key for k in SITTING_TYPES) else "S"
                out["activities"].append(iv)
    except Exception as e:  # noqa: BLE001
        errors.append(f"activiteiten: {e}")

    try:
        rep = get("/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": ds, "endDate": ds}) or []
        rep = rep[0] if isinstance(rep, list) and rep else (rep if isinstance(rep, dict) else {})
        cols = _cols(rep.get("bodyBatteryValueDescriptorDTOList"), "bodyBatteryValueDescriptorIndex",
                     "bodyBatteryValueDescriptorKey")
        ti, li = cols.get("timestamp", 0), cols.get("bodyBatteryLevel", 1)
        rows = []
        for row in rep.get("bodyBatteryValuesArray") or []:
            if isinstance(row, list) and len(row) > max(ti, li) and isinstance(row[li], (int, float)):
                rows.append((to_local(row[ti]), row[li]))
        out["bb"] = _slot_means(rows, day)
        lv = [v for _, v in rows]
        if lv:
            out["bb_min"], out["bb_max"] = min(lv), max(lv)
    except Exception as e:  # noqa: BLE001
        errors.append(f"Body Battery: {e}")

    try:
        hr = get("/wellness-service/wellness/dailyHeartRate", {"date": ds}) or {}
        cols = _cols(hr.get("heartRateValueDescriptors"), "index", "key")
        ti, vi = cols.get("timestamp", 0), cols.get("heartrate", 1)
        rows = [(to_local(r[ti]), r[vi]) for r in hr.get("heartRateValues") or []
                if isinstance(r, list) and len(r) > max(ti, vi) and isinstance(r[vi], (int, float))]
        out["hr"] = _slot_means(rows, day)
        out["rhr"] = hr.get("restingHeartRate")
    except Exception as e:  # noqa: BLE001
        errors.append(f"hartslag: {e}")

    try:
        hv = get(f"/hrv-service/hrv/{ds}") or {}
        su = hv.get("hrvSummary") or {}
        bl = su.get("baseline") or {}
        if su.get("lastNightAvg") is not None:
            out["hrv"] = {"night": su.get("lastNightAvg"), "week": su.get("weeklyAvg"), "status": su.get("status"),
                          "low": bl.get("balancedLow"), "high": bl.get("balancedUpper")}
    except Exception as e:  # noqa: BLE001
        errors.append(f"HRV: {e}")

    try:
        sm = get("/usersummary-service/v2/dailysummaries", {"startDate": ds, "endDate": ds}) or {}
        d0 = (sm.get("data") or [None])[0] if isinstance(sm, dict) else None
        if d0:
            out["steps"] = ((d0.get("movement") or {}).get("steps") or {}).get("value")
            out["stress"] = (d0.get("stress") or {}).get("avgLevel")
            bb = d0.get("bodyBattery") or {}
            out["bb_min"] = out["bb_min"] if out["bb_min"] is not None else bb.get("minValue")
            out["bb_max"] = out["bb_max"] if out["bb_max"] is not None else bb.get("maxValue")
    except Exception as e:  # noqa: BLE001
        errors.append(f"dagsamenvatting: {e}")

    return out


def sync(days=2, end=None):
    """Haal `days` dagen op t/m `end` (standaard vandaag) en sla ze op."""
    end = end or datetime.now(TZ).date()
    _token()  # faalt vroeg met een duidelijke melding
    done = []
    for k in range(days):
        d = end - timedelta(days=k)
        data = build_day(d)
        store.put_garmin(d.isoformat(), data)
        done.append((d.isoformat(), data["errors"]))
    return done


# ---------- test: alleen de vorm van de antwoorden, geen waarden ----------
def _shape(v, depth=0):
    if depth > 2:
        return [type(v).__name__]
    if isinstance(v, dict):
        out = []
        for k, x in list(v.items())[:40]:
            sub = _shape(x, depth + 1)
            out.append(f"{k}" + (f" {{{', '.join(sub)}}}" if isinstance(x, (dict, list)) and sub else f": {type(x).__name__}"))
        return out
    if isinstance(v, list):
        return [f"lijst[{len(v)}]"] + (_shape(v[0], depth + 1) if v else [])
    return [type(v).__name__]


def test():
    y = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
    _token(force=True)
    print("Token: OK\n")
    for path, params in [
        ("/sleep-service/sleep/dailySleep", {"date": y}),
        ("/activitylist-service/activities/search/activities", {"startDate": y, "endDate": y, "limit": 5}),
        ("/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": y, "endDate": y}),
        ("/wellness-service/wellness/dailyHeartRate", {"date": y}),
        (f"/hrv-service/hrv/{y}", None),
        ("/usersummary-service/v2/dailysummaries", {"startDate": y, "endDate": y}),
    ]:
        try:
            v = get(path, params)
            print(f"{path}\n  " + "\n  ".join(_shape(v)[:40]) + "\n")
        except Exception as e:  # noqa: BLE001
            print(f"{path}\n  FOUT: {e}\n")
    d = build_day(datetime.now(TZ).date() - timedelta(days=1))
    print("Samenvatting gisteren (zonder gezondheidswaarden):")
    print(f"  slaapblokken: {len(d['sleep'])}, dutjes: {len(d['naps'])}, activiteiten: {len(d['activities'])}")
    print(f"  vakjes met Body Battery: {sum(v is not None for v in d['bb'])}/34, met hartslag: {sum(v is not None for v in d['hr'])}/34")
    print(f"  rusthartslag aanwezig: {d['rhr'] is not None}, HRV aanwezig: {d['hrv'] is not None}")
    print(f"  fouten: {d['errors'] or 'geen'}")
