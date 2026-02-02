
from __future__ import annotations
import json, os
from typing import Any, Dict

STATE_PATH = os.path.expanduser("~/.proxi_weather_state.json")

DEFAULT_STATE: Dict[str, Any] = {
    "units": "C",
    "home_location": None,
    "saved_locations": [],
}

def load_state(path: str = STATE_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s, dict):
            out = {**DEFAULT_STATE, **s}
            out["saved_locations"] = [str(x) for x in out.get("saved_locations", []) if str(x).strip()]
            u = str(out.get("units", "C")).upper()
            out["units"] = "F" if u == "F" else "C"
            return out
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return DEFAULT_STATE.copy()

def save_state(state: Dict[str, Any], path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def add_location(name: str) -> Dict[str, Any]:
    st = load_state()
    n = (name or "").strip()
    if n and all(x.lower() != n.lower() for x in st["saved_locations"]):
        st["saved_locations"].append(n)
        save_state(st)
    return st

def remove_location(name: str) -> Dict[str, Any]:
    st = load_state()
    n = (name or "").strip().lower()
    st["saved_locations"] = [x for x in st["saved_locations"] if x.lower() != n]
    if st.get("home_location") and st["home_location"].strip().lower() == n:
        st["home_location"] = None
    save_state(st)
    return st

def set_home(name: str) -> Dict[str, Any]:
    st = load_state()
    n = (name or "").strip()
    if n:
        st["home_location"] = n
        if all(x.lower() != n.lower() for x in st["saved_locations"]):
            st["saved_locations"].append(n)
        save_state(st)
    return st

def set_units(units: str) -> Dict[str, Any]:
    st = load_state()
    u = (units or "").strip().upper()
    st["units"] = "F" if u == "F" else "C"
    save_state(st)
    return st
