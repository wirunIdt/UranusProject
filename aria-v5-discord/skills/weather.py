"""
Weather Skill v1
- ใช้ Open-Meteo API (ฟรี 100%, ไม่ต้อง API key)
- Geocoding ด้วย Open-Meteo Geocoding API
- รองรับภาษาไทย + อังกฤษ
- ข้อมูล: อุณหภูมิ, ความชื้น, ลม, UV, ฝน, พยากรณ์ 7 วัน
"""
import requests
from datetime import datetime, timedelta

BASE_GEO     = "https://geocoding-api.open-meteo.com/v1/search"
BASE_WEATHER = "https://api.open-meteo.com/v1/forecast"

WMO_CODES = {
    0: ("Clear sky",           "แดดจัด",           "☀️"),
    1: ("Mainly clear",        "แจ่มใส",            "🌤️"),
    2: ("Partly cloudy",       "มีเมฆบางส่วน",      "⛅"),
    3: ("Overcast",            "เมฆมาก",            "☁️"),
    45:("Foggy",               "หมอก",              "🌫️"),
    48:("Icy fog",             "หมอกน้ำแข็ง",       "🌫️"),
    51:("Light drizzle",       "ฝนปรอยๆ",           "🌦️"),
    53:("Moderate drizzle",    "ฝนปรอย",            "🌦️"),
    55:("Dense drizzle",       "ฝนปรอยหนัก",        "🌧️"),
    61:("Slight rain",         "ฝนเบา",             "🌧️"),
    63:("Moderate rain",       "ฝนปานกลาง",         "🌧️"),
    65:("Heavy rain",          "ฝนหนัก",            "🌧️"),
    71:("Slight snow",         "หิมะเบา",           "🌨️"),
    73:("Moderate snow",       "หิมะปานกลาง",        "❄️"),
    75:("Heavy snow",          "หิมะหนัก",          "❄️"),
    77:("Snow grains",         "เม็ดหิมะ",          "🌨️"),
    80:("Slight showers",      "ฝนสั้นๆ",           "🌦️"),
    81:("Moderate showers",    "ฝนฟ้าคะนอง",        "⛈️"),
    82:("Violent showers",     "พายุฝน",            "⛈️"),
    85:("Snow showers",        "พายุหิมะ",          "🌨️"),
    95:("Thunderstorm",        "พายุฝนฟ้าคะนอง",    "⛈️"),
    96:("Thunderstorm+hail",   "พายุลูกเห็บ",       "⛈️"),
    99:("Thunderstorm+hail",   "พายุลูกเห็บหนัก",   "⛈️"),
}

UV_LABELS = {
    "th": ["ต่ำมาก","ต่ำ","ปานกลาง","สูง","สูงมาก","อันตราย"],
    "en": ["Very Low","Low","Moderate","High","Very High","Extreme"],
}

WIND_DIRS = {
    "th": ["เหนือ","ตะวันออกเฉียงเหนือ","ตะวันออก","ตะวันออกเฉียงใต้",
           "ใต้","ตะวันตกเฉียงใต้","ตะวันตก","ตะวันตกเฉียงเหนือ","เหนือ"],
    "en": ["N","NE","E","SE","S","SW","W","NW","N"],
}

DAYS_TH = ["จันทร์","อังคาร","พุธ","พฤหัส","ศุกร์","เสาร์","อาทิตย์"]
DAYS_EN = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]


def _wmo(code: int, lang: str = "th") -> tuple:
    data = WMO_CODES.get(code, ("Unknown","ไม่ทราบ","❓"))
    return (data[1] if lang == "th" else data[0], data[2])


def geocode(city: str) -> dict | None:
    """Get lat/lon from city name."""
    try:
        r = requests.get(BASE_GEO, params={"name": city, "count": 1,
                                            "language": "th", "format": "json"},
                          timeout=8)
        results = r.json().get("results", [])
        if results:
            loc = results[0]
            return {
                "name":    loc.get("name", city),
                "country": loc.get("country", ""),
                "lat":     loc.get("latitude"),
                "lon":     loc.get("longitude"),
                "tz":      loc.get("timezone", "Asia/Bangkok"),
            }
    except Exception as e:
        print(f"[GEO] {e}")
    return None


def get_weather(city: str = "Bangkok", lang: str = "th") -> dict:
    """
    Fetch current weather + 7-day forecast.
    Returns structured dict with formatted strings.
    """
    loc = geocode(city)
    if not loc:
        return {"ok": False, "error": f"ไม่พบเมือง '{city}'"}

    try:
        params = {
            "latitude":   loc["lat"],
            "longitude":  loc["lon"],
            "timezone":   loc["tz"],
            "current": ",".join([
                "temperature_2m","relative_humidity_2m",
                "apparent_temperature","is_day",
                "precipitation","weather_code",
                "wind_speed_10m","wind_direction_10m",
                "uv_index","surface_pressure",
            ]),
            "daily": ",".join([
                "weather_code","temperature_2m_max","temperature_2m_min",
                "precipitation_sum","precipitation_probability_max",
                "uv_index_max","wind_speed_10m_max",
            ]),
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "forecast_days": 7,
        }
        r = requests.get(BASE_WEATHER, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"ok": False, "error": f"ดึงข้อมูลไม่ได้: {e}"}

    cur   = data.get("current", {})
    daily = data.get("daily", {})

    # Current
    code   = cur.get("weather_code", 0)
    desc, icon = _wmo(code, lang)
    temp   = cur.get("temperature_2m", "--")
    feels  = cur.get("apparent_temperature", "--")
    humid  = cur.get("relative_humidity_2m", "--")
    wind_s = cur.get("wind_speed_10m", "--")
    wind_d = cur.get("wind_direction_10m", 0)
    uv     = cur.get("uv_index", 0)
    rain   = cur.get("precipitation", 0)
    press  = cur.get("surface_pressure", "--")
    is_day = cur.get("is_day", 1)

    # Wind direction
    wind_idx = round(wind_d / 45) % 8
    wind_dir = WIND_DIRS[lang][wind_idx]

    # UV label
    uv_idx = min(int(uv // 3), 5)
    uv_lbl = UV_LABELS[lang][uv_idx]

    # 7-day forecast
    forecast = []
    dates  = daily.get("time", [])
    codes  = daily.get("weather_code", [])
    maxts  = daily.get("temperature_2m_max", [])
    mints  = daily.get("temperature_2m_min", [])
    rains  = daily.get("precipitation_sum", [])
    rain_p = daily.get("precipitation_probability_max", [])
    uvs    = daily.get("uv_index_max", [])

    for i, date_str in enumerate(dates):
        d     = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = (DAYS_TH if lang == "th" else DAYS_EN)[d.weekday()]
        fdesc, ficon = _wmo(codes[i] if i < len(codes) else 0, lang)
        forecast.append({
            "date":    date_str,
            "day":     day_name,
            "icon":    ficon,
            "desc":    fdesc,
            "max":     maxts[i] if i < len(maxts) else "--",
            "min":     mints[i] if i < len(mints) else "--",
            "rain_mm": rains[i] if i < len(rains) else 0,
            "rain_p":  rain_p[i] if i < len(rain_p) else 0,
            "uv":      uvs[i] if i < len(uvs) else 0,
        })

    # Format summary text
    if lang == "th":
        summary = (
            f"🌍 {loc['name']}, {loc['country']}\n"
            f"{icon} {desc}\n"
            f"🌡️ {temp}°C (รู้สึกเหมือน {feels}°C)\n"
            f"💧 ความชื้น {humid}%\n"
            f"💨 ลม {wind_s} km/h ทิศ{wind_dir}\n"
            f"☔ ฝน {rain} มม.\n"
            f"🌞 UV Index {uv} ({uv_lbl})\n"
            f"🔵 ความกดอากาศ {press} hPa"
        )
    else:
        summary = (
            f"🌍 {loc['name']}, {loc['country']}\n"
            f"{icon} {desc}\n"
            f"🌡️ {temp}°C (feels like {feels}°C)\n"
            f"💧 Humidity {humid}%\n"
            f"💨 Wind {wind_s} km/h {wind_dir}\n"
            f"☔ Rain {rain} mm\n"
            f"🌞 UV {uv} ({uv_lbl})\n"
            f"🔵 Pressure {press} hPa"
        )

    return {
        "ok":       True,
        "location": loc,
        "current": {
            "temp": temp, "feels": feels, "humid": humid,
            "wind_speed": wind_s, "wind_dir": wind_dir,
            "uv": uv, "uv_label": uv_lbl,
            "rain": rain, "pressure": press,
            "icon": icon, "desc": desc,
            "is_day": is_day,
        },
        "forecast": forecast,
        "summary":  summary,
    }


def parse_weather_query(text: str) -> str | None:
    """Extract city from weather query. Returns city or None."""
    import re
    text_lower = text.lower()

    # Thai patterns
    th_patterns = [
        r"อากาศ(?:ที่|ใน|วัน[นี้]*)?\s*(.+)",
        r"พยากรณ์(?:อากาศ)?(?:ที่|ใน)?\s*(.+)",
        r"ฝน(?:ตก)?(?:ที่|ใน)?\s*(.+)",
        r"อุณหภูมิ(?:ที่|ใน)?\s*(.+)",
        r"สภาพอากาศ(?:ที่|ใน)?\s*(.+)",
    ]
    # English patterns
    en_patterns = [
        r"weather\s+(?:in|at|for)?\s*(.+)",
        r"forecast\s+(?:for|in)?\s*(.+)",
        r"temperature\s+(?:in|at)?\s*(.+)",
        r"(?:is it|will it)\s+rain(?:ing)?\s+in\s*(.+)",
        r"how(?:'s| is) the weather\s+(?:in|at)?\s*(.+)",
    ]

    for p in th_patterns + en_patterns:
        m = re.search(p, text_lower)
        if m:
            city = m.group(1).strip().rstrip("?").rstrip("ครับ").rstrip("ค่ะ").strip()
            if city and len(city) >= 2:
                return city

    # Keywords without city → default Bangkok
    weather_kws = ["อากาศ","พยากรณ์","ฝน","หิมะ","ร้อน","หนาว","weather","forecast","rain"]
    if any(k in text_lower for k in weather_kws):
        return "Bangkok"

    return None


def format_forecast_short(forecast: list, lang: str = "th") -> str:
    """Format 3-day short forecast string."""
    lines = []
    for day in forecast[:3]:
        if lang == "th":
            lines.append(f"{day['icon']} {day['day']}: {day['min']}°–{day['max']}° | ฝน {day['rain_p']}%")
        else:
            lines.append(f"{day['icon']} {day['day']}: {day['min']}°–{day['max']}° | Rain {day['rain_p']}%")
    return "\n".join(lines)
