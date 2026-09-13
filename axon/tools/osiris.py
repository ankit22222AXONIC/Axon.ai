"""OSIRIS (Know the World) Integration Tools.

Allows AXON AI to query real-time global intelligence (conflicts, news, earthquakes,
satellites, maritime, cyber threats, CCTV) from the OSIRIS 3D visualization engine,
and interactively open or command the 3D globe.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional


OSIRIS_BASE_URL = "http://127.0.0.1:3001"

LAYER_ROUTES = {
    "news": "/api/live-news",
    "live-news": "/api/live-news",
    "conflicts": "/api/conflicts",
    "frontlines": "/api/frontlines",
    "country-risk": "/api/country-risk",
    "earthquakes": "/api/earthquakes",
    "fires": "/api/fires",
    "weather": "/api/weather",
    "space-weather": "/api/space-weather",
    "satellites": "/api/satellites",
    "flights": "/api/aircraft",
    "aircraft": "/api/aircraft",
    "maritime": "/api/maritime",
    "cyber": "/api/malware",
    "malware": "/api/malware",
    "cyber-attacks": "/api/cyber-attacks",
    "cctv": "/api/cctv",
    "cameras": "/api/cctv",
    "gdelt": "/api/gdelt-events",
}


def _fetch_osiris_json(endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Dict[str, Any]:
    """Fetch and decode JSON from the local OSIRIS instance."""
    url = f"{OSIRIS_BASE_URL}{endpoint}"
    if params:
        query_string = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if query_string:
            url = f"{url}?{query_string}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AXON-Core/1.0 (OSIRIS-Bridge)",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {"status": "success", "data": data, "endpoint": endpoint}
    except urllib.error.URLError as e:
        return {
            "status": "offline",
            "endpoint": endpoint,
            "error": f"OSIRIS server unreachable at {url}: {e.reason}",
            "hint": "Ensure the OSIRIS Next.js frontend is running on port 3001 ('py -m axon web' or 'npm run dev' inside osiris/).",
        }
    except Exception as e:
        return {
            "status": "error",
            "endpoint": endpoint,
            "error": str(e),
        }


def osiris_status() -> Dict[str, Any]:
    """Check health and connectivity of the OSIRIS (Know the World) 3D intelligence subsystem."""
    res = _fetch_osiris_json("/api/health", timeout=2.5)
    if res["status"] == "success":
        return {
            "status": "online",
            "url": OSIRIS_BASE_URL,
            "available_layers": list(LAYER_ROUTES.keys()),
            "message": "OSIRIS (Know the World) 3D intelligence engine is online on port 3001.",
        }
    # Fallback ping on root
    root_res = _fetch_osiris_json("/", timeout=2.0)
    is_live = root_res["status"] in ("success", "error")  # HTML 200 or parse error still means port is open
    return {
        "status": "online" if is_live else "offline",
        "url": OSIRIS_BASE_URL,
        "available_layers": list(LAYER_ROUTES.keys()),
        "message": "OSIRIS 3D intelligence engine is active." if is_live else "OSIRIS is currently starting or offline.",
    }


def osiris_briefing(region: Optional[str] = None) -> Dict[str, Any]:
    """Generate a global situation intelligence briefing across multiple OSIRIS layers.
    
    Collects live news, active conflict updates, significant seismic events,
    and cyber threat telemetry.
    """
    briefing: Dict[str, Any] = {
        "status": "success",
        "scope": region or "Global",
        "timestamp": None,
        "news": [],
        "conflicts": [],
        "earthquakes": [],
        "cyber_threats": [],
        "summary": "",
    }

    # 1. News
    news_res = _fetch_osiris_json("/api/live-news")
    if news_res["status"] == "success":
        raw_news = news_res["data"]
        items = raw_news if isinstance(raw_news, list) else raw_news.get("items", raw_news.get("feeds", []))
        briefing["news"] = items[:8] if isinstance(items, list) else []

    # 2. Conflicts
    conflicts_res = _fetch_osiris_json("/api/conflicts")
    if conflicts_res["status"] == "success":
        raw_conflicts = conflicts_res["data"]
        c_items = raw_conflicts if isinstance(raw_conflicts, list) else raw_conflicts.get("zones", raw_conflicts.get("events", []))
        briefing["conflicts"] = c_items[:6] if isinstance(c_items, list) else []

    # 3. Earthquakes / Disasters
    eq_res = _fetch_osiris_json("/api/earthquakes")
    if eq_res["status"] == "success":
        raw_eq = eq_res["data"]
        eq_items = raw_eq if isinstance(raw_eq, list) else raw_eq.get("features", raw_eq.get("items", []))
        briefing["earthquakes"] = eq_items[:5] if isinstance(eq_items, list) else []

    # 4. Cyber threats
    cyber_res = _fetch_osiris_json("/api/malware")
    if cyber_res["status"] == "success":
        raw_cyber = cyber_res["data"]
        cy_items = raw_cyber if isinstance(raw_cyber, list) else raw_cyber.get("threats", raw_cyber.get("items", []))
        briefing["cyber_threats"] = cy_items[:5] if isinstance(cy_items, list) else []

    total_events = (
        len(briefing["news"])
        + len(briefing["conflicts"])
        + len(briefing["earthquakes"])
        + len(briefing["cyber_threats"])
    )

    if total_events == 0:
        briefing["status"] = "offline"
        briefing["summary"] = "OSIRIS local intelligence stream not reached. Start via 'py -m axon web'."
    else:
        briefing["summary"] = (
            f"OSIRIS World Briefing: {len(briefing['news'])} active news streams, "
            f"{len(briefing['conflicts'])} conflict hotspots, "
            f"{len(briefing['earthquakes'])} seismic alerts, "
            f"{len(briefing['cyber_threats'])} live cyber threats tracked."
        )

    return briefing


def osiris_get_layer(layer: str = "news", limit: int = 15) -> Dict[str, Any]:
    """Retrieve raw real-time data from a specific OSIRIS intelligence layer.
    
    Supported layers:
      - 'news' / 'live-news': Live international broadcast and news feeds
      - 'conflicts': Active armed conflict zones and geopolitical hotspots
      - 'frontlines': Frontline military reports
      - 'earthquakes': Recent global earthquakes and seismic telemetry
      - 'fires': Satellite active fire detections
      - 'weather' / 'space-weather': Severe terrestrial and solar weather
      - 'satellites': Active orbital satellites and positions
      - 'flights' / 'aircraft': Global air traffic and tracked aircraft
      - 'maritime': Tracked vessels and marine traffic
      - 'cyber' / 'malware': Live cyber threats, malware URLs, and indicators
      - 'cctv' / 'cameras': Live public webcams worldwide
    """
    key = layer.strip().lower()
    endpoint = LAYER_ROUTES.get(key)
    if not endpoint:
        return {
            "status": "error",
            "error": f"Unknown OSIRIS layer '{layer}'. Available: {', '.join(sorted(set(LAYER_ROUTES.keys())))}",
        }

    res = _fetch_osiris_json(endpoint)
    if res["status"] != "success":
        return res

    data = res["data"]
    items: List[Any] = []
    if isinstance(data, list):
        items = data[:limit]
    elif isinstance(data, dict):
        for k in ("items", "zones", "events", "features", "threats", "cameras", "satellites", "feeds"):
            if k in data and isinstance(data[k], list):
                items = data[k][:limit]
                break
        if not items:
            items = [data]

    return {
        "status": "success",
        "layer": key,
        "endpoint": endpoint,
        "count": len(items),
        "data": items,
    }


def osiris_search_region(region: str) -> Dict[str, Any]:
    """Search OSIRIS intelligence dossiers and risks for a specific country or region."""
    clean_region = region.strip()
    if not clean_region:
        return {"status": "error", "error": "Region name cannot be empty."}

    # Query region dossier
    res = _fetch_osiris_json("/api/region-dossier", params={"region": clean_region})
    if res["status"] == "success":
        return {
            "status": "success",
            "region": clean_region,
            "dossier": res["data"],
        }

    # Fallback to country risk
    risk_res = _fetch_osiris_json("/api/country-risk", params={"country": clean_region})
    if risk_res["status"] == "success":
        return {
            "status": "success",
            "region": clean_region,
            "risk_profile": risk_res["data"],
        }

    return {
        "status": "not_found",
        "region": clean_region,
        "message": f"No dedicated dossier found for '{clean_region}'. Try querying the 'conflicts' or 'news' layers.",
    }


def osiris_open_globe(target: Optional[str] = None, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    """Open the OSIRIS 3D interactive globe in the user's browser, optionally centered on coordinates.
    
    Args:
        target: Optional city, region, or layer name to display.
        lat: Optional latitude (-90 to 90).
        lng: Optional longitude (-180 to 180).
    """
    url = OSIRIS_BASE_URL
    params = {}
    if lat is not None and lng is not None:
        params["lat"] = f"{lat:.4f}"
        params["lng"] = f"{lng:.4f}"
    if target:
        params["target"] = target

    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    try:
        webbrowser.open(url)
        return {
            "status": "success",
            "url": url,
            "message": f"Opened OSIRIS 3D Globe at {url}",
        }
    except Exception as e:
        return {
            "status": "error",
            "url": url,
            "error": f"Failed to open browser: {e}",
        }
