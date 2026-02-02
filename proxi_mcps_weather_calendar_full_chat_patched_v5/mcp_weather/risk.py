
from __future__ import annotations
from typing import Dict, Any
from datetime import datetime

def _parse(dt: str) -> datetime:
    s = (dt or "").strip()
    if "T" in s:
        s = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s).replace(tzinfo=None)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.min

def risk_at(hourly: Dict[str, Any], iso_datetime: str, activity: str = "outdoor") -> Dict[str, Any]:
    activity = (activity or "outdoor").lower().strip()
    times = hourly.get("time", []) or []
    target = _parse(iso_datetime)
    idx = 0
    best = 10**18
    for i, t in enumerate(times):
        dt = _parse(t)
        d = abs((dt - target).total_seconds())
        if d < best:
            best = d
            idx = i

    def at(key: str, default: float = 0.0) -> float:
        arr = hourly.get(key, [])
        if isinstance(arr, list) and 0 <= idx < len(arr):
            try:
                return float(arr[idx])
            except Exception:
                return default
        return default

    snowfall = at("snowfall", 0.0)
    precipitation = at("precipitation", 0.0)
    gusts = at("wind_gusts_10m", 0.0)
    visibility = at("visibility", 10000.0)

    score = 0.0
    reasons = []
    if snowfall >= 1.0:
        score += min(3.0, snowfall); reasons.append(f"snowfall={snowfall}")
    if precipitation >= 2.0:
        score += 1.5; reasons.append(f"precip={precipitation}mm")
    if gusts >= 35:
        score += 1.5; reasons.append(f"gusts={gusts}km/h")
    if visibility <= 1000:
        score += 2.0; reasons.append(f"visibility={visibility}m")

    if activity == "driving": score *= 1.2
    elif activity == "flight": score *= 1.1

    if score >= 5:
        risk, rec, conf = "high", "avoid or delay; add buffer", 0.8
    elif score >= 3:
        risk, rec, conf = "medium", "consider adjusting schedule; monitor", 0.7
    else:
        risk, rec, conf = "low", "conditions acceptable", 0.65

    return {"time_slot": times[idx] if times else iso_datetime, "activity": activity, "risk": risk, "score": round(score,2), "confidence": conf,
            "reasons": reasons or ["no major hazards detected"], "recommendation": rec}

def best_time_in_window(hourly: Dict[str, Any], start_dt: str, end_dt: str, activity: str = "driving", step_minutes: int = 60) -> Dict[str, Any]:
    times = hourly.get("time", []) or []
    if not times:
        return {"ok": False, "error": "no hourly data"}
    start = _parse(start_dt); end = _parse(end_dt)
    step_minutes = max(15, min(int(step_minutes), 180))

    candidates = []
    for t in times:
        dt = _parse(t)
        if start <= dt <= end:
            candidates.append(t)

    chosen = []
    last = None
    for t in candidates:
        dt = _parse(t)
        if last is None or (dt - last).total_seconds() >= step_minutes*60:
            chosen.append(t); last = dt

    best = None
    for t in chosen:
        r = risk_at(hourly, t, activity)
        if best is None or (r["score"], -r["confidence"]) < (best["score"], -best["confidence"]):
            best = r
    return {"ok": True, "best": best, "window": {"start": start_dt, "end": end_dt, "step_minutes": step_minutes}}
