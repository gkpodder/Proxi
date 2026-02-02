
from __future__ import annotations
from typing import Dict, Any
from shared.utils import run_osascript, esc_applescript

def open_weather_app() -> Dict[str, Any]:
    rc, out, err = run_osascript('tell application "Weather" to activate\nreturn "ok"')
    return {"ok": rc == 0, "stdout": out, "stderr": err}

def show_location(city: str) -> Dict[str, Any]:
    city = (city or "").strip()
    if not city:
        return {"ok": False, "error": "city required"}
    c = esc_applescript(city)
    script = f'''
    tell application "Weather" to activate
    delay 0.5
    tell application "System Events"
      if not (UI elements enabled) then return "ERROR: Accessibility UI scripting not enabled"
      keystroke "f" using command down
      delay 0.2
      keystroke "{c}"
      delay 0.2
      key code 36
    end tell
    return "ok"
    '''
    rc, out, err = run_osascript(script, timeout_s=25)
    if out.startswith("ERROR:"):
        return {"ok": False, "error": out, "stderr": err}
    return {"ok": rc == 0, "stdout": out, "stderr": err, "note": "Best-effort UI navigation."}

def add_city_ui(city: str) -> Dict[str, Any]:
    city = (city or "").strip()
    if not city:
        return {"ok": False, "error": "city required"}
    c = esc_applescript(city)
    script = f'''
    tell application "Weather" to activate
    delay 0.5
    tell application "System Events"
      if not (UI elements enabled) then return "ERROR: Accessibility UI scripting not enabled"
      keystroke "f" using command down
      delay 0.2
      keystroke "{c}"
      delay 0.2
      key code 36
      delay 0.8
      keystroke "+" using command down
      delay 0.2
    end tell
    return "ok"
    '''
    rc, out, err = run_osascript(script, timeout_s=25)
    if out.startswith("ERROR:"):
        return {"ok": False, "error": out, "stderr": err}
    return {"ok": rc == 0, "stdout": out, "stderr": err, "note": "UI add is best-effort; backend state is always updated."}

def remove_city_ui(city: str) -> Dict[str, Any]:
    city = (city or "").strip()
    if not city:
        return {"ok": False, "error": "city required"}
    c = esc_applescript(city)
    script = f'''
    tell application "Weather" to activate
    delay 0.5
    tell application "System Events"
      if not (UI elements enabled) then return "ERROR: Accessibility UI scripting not enabled"
      keystroke "f" using command down
      delay 0.2
      keystroke "{c}"
      delay 0.2
      key code 36
      delay 0.8
      key code 51
      delay 0.2
      keystroke (ASCII character 8)
      delay 0.2
    end tell
    return "ok"
    '''
    rc, out, err = run_osascript(script, timeout_s=25)
    if out.startswith("ERROR:"):
        return {"ok": False, "error": out, "stderr": err}
    return {"ok": rc == 0, "stdout": out, "stderr": err, "note": "UI removal is best-effort; backend state is always updated."}
