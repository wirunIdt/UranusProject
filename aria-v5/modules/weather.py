"""modules/weather.py — Realtime weather via wttr.in (free, no API key)"""
import os, time, threading
import requests

OWM_KEY  = os.environ.get("OWM_API_KEY", "")
_cache   = {}
_LOCK    = threading.Lock()
_CACHE_S = 300

WI_ICONS = {
    "113":"☀","116":"⛅","119":"☁","122":"☁","143":"🌫","176":"🌦",
    "179":"🌨","182":"🌧","185":"🌧","200":"⛈","227":"🌨","230":"❄",
    "248":"🌫","263":"🌦","266":"🌦","281":"🌧","293":"🌦","296":"🌦",
    "299":"🌧","302":"🌧","305":"🌧","308":"🌧","317":"🌧","320":"🌨",
    "323":"🌨","326":"❄","329":"❄","332":"❄","335":"❄","338":"❄",
    "353":"🌦","356":"🌧","359":"🌧","362":"🌧","365":"🌧","368":"🌨",
    "371":"❄","374":"🌧","377":"🌧","386":"⛈","389":"⛈","392":"⛈","395":"❄",
}

def _n(v, d=0):
    try: return int(float(str(v))) if v not in (None,"","N/A") else d
    except: return d
def _f(v, d=0.0):
    try: return float(str(v)) if v not in (None,"","N/A") else d
    except: return d

def _from_wttr(city):
    url = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
    r = requests.get(url, timeout=12, headers={"User-Agent":"ARIA-Weather/5"})
    r.raise_for_status()
    d = r.json()
    cw   = d["current_condition"][0]
    days = d["weather"][:6]
    area = d["nearest_area"][0]
    code = str(cw.get("weatherCode","113"))

    hourly = []
    for h in days[0].get("hourly",[]):
        t = _n(h.get("time",0)) // 100
        hourly.append({
            "hour": f"{t:02d}:00",
            "temp": _n(h.get("tempC",0)), "feels": _n(h.get("FeelsLikeC",0)),
            "rain": round(_f(h.get("precipMM",0)),1), "wind": _n(h.get("windspeedKmph",0)),
            "humidity": _n(h.get("humidity",0)),
            "desc": h.get("weatherDesc",[{}])[0].get("value",""),
            "icon": WI_ICONS.get(str(h.get("weatherCode","113")),"🌡"),
        })

    forecast = []
    for w in days:
        mid = w.get("hourly",[])[4] if len(w.get("hourly",[]))>4 else {}
        forecast.append({
            "date": w.get("date",""), "max": _n(w.get("maxtempC",0)), "min": _n(w.get("mintempC",0)),
            "desc": mid.get("weatherDesc",[{}])[0].get("value",""),
            "icon": WI_ICONS.get(str(mid.get("weatherCode","113")),"🌡"),
            "rain_mm": round(sum(_f(h.get("precipMM",0)) for h in w.get("hourly",[])),1),
            "sun_h": round(_f(w.get("sunHour",0)),1), "uv": _n(w.get("uvIndex",0)),
        })

    return {
        "source": "wttr.in",
        "city": area.get("areaName",[{}])[0].get("value",city),
        "country": area.get("country",[{}])[0].get("value",""),
        "lat": _f(area.get("latitude",0)), "lon": _f(area.get("longitude",0)),
        "temp": _n(cw.get("temp_C",0)), "feels": _n(cw.get("FeelsLikeC",0)),
        "humidity": _n(cw.get("humidity",0)), "wind_kph": _n(cw.get("windspeedKmph",0)),
        "wind_dir": cw.get("winddir16Point",""), "wind_deg": _n(cw.get("winddirDegree",0)),
        "pressure": _n(cw.get("pressure",0)), "visibility": _n(cw.get("visibility",0)),
        "uv_index": _n(cw.get("uvIndex",0)), "cloud_cover": _n(cw.get("cloudcover",0)),
        "desc": cw.get("weatherDesc",[{}])[0].get("value",""),
        "icon": WI_ICONS.get(code,"🌡"),
        "forecast": forecast, "hourly": hourly,
        "api_key": bool(OWM_KEY), "ts": time.time(),
    }

def get_weather(city="Bangkok", units="metric"):
    key = f"{city}_{units}"
    with _LOCK:
        c = _cache.get(key)
        if c and not c.get("error") and time.time()-c.get("ts",0) < _CACHE_S:
            return c
    try:
        data = _from_wttr(city)
        with _LOCK: _cache[key] = data
        return data
    except Exception as e:
        with _LOCK:
            if key in _cache: _cache[key]["stale"]=True; return _cache[key]
        return {"error":str(e),"city":city,"temp":0,"desc":"unavailable",
                "icon":"🌡","humidity":0,"wind_kph":0,"forecast":[],"hourly":[]}

def invalidate(city=None):
    with _LOCK:
        if city: _cache.pop(f"{city}_metric",None)
        else: _cache.clear()
