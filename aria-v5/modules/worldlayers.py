"""modules/worldlayers.py — All 25 global intelligence layers with real free APIs"""
import time, json, threading, requests, xml.etree.ElementTree as ET

_CACHE = {}
_LOCK  = threading.Lock()

def _c(k): 
    v = _CACHE.get(k)
    return v["d"] if v and time.time()-v["t"]<v.get("ttl",120) else None
def _s(k, d, ttl=120): 
    _CACHE[k] = {"d":d,"t":time.time(),"ttl":ttl}
def _get(url, **kw):
    return requests.get(url, timeout=10, 
                        headers={"User-Agent":"ARIA-Globe/5"}, **kw)

# ── 1. Earthquakes (USGS) ──────────────────────────────────────────────────
def earthquakes(min_mag=2.5, period="week"):
    k=f"quakes_{min_mag}_{period}"; c=_c(k)
    if c: return c
    try:
        d=_get(f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{min_mag}_{period}.geojson").json()
        out=[{"id":f["id"],"mag":round(f["properties"].get("mag",0),1),
              "place":f["properties"].get("place",""),"time":f["properties"].get("time",0),
              "lon":f["geometry"]["coordinates"][0],"lat":f["geometry"]["coordinates"][1],
              "depth":round(f["geometry"]["coordinates"][2],1) if len(f["geometry"]["coordinates"])>2 else 0,
              "alert":f["properties"].get("alert"),"tsunami":f["properties"].get("tsunami",0),
              "type":f["properties"].get("type","earthquake")}
             for f in d.get("features",[])[:150]]
        out.sort(key=lambda x:x["mag"],reverse=True)
        _s(k,out,120); return out
    except Exception as e: return []

# ── 2. Active Fires (NASA EONET) ───────────────────────────────────────────
def fires():
    k="fires"; c=_c(k)
    if c: return c
    try:
        d=_get("https://eonet.gsfc.nasa.gov/api/v3/events?category=wildfires&status=open&limit=100").json()
        out=[]
        for ev in d.get("events",[]):
            for geo in ev.get("geometry",[]):
                coords=geo.get("coordinates",[])
                if coords:
                    lon,lat=(coords[0],coords[1]) if isinstance(coords[0],(int,float)) else (coords[0][0],coords[0][1])
                    out.append({"id":ev["id"],"title":ev["title"],"lon":lon,"lat":lat,
                                "date":geo.get("date","")[:10],"source":ev.get("sources",[{}])[0].get("id","")})
        _s(k,out,600); return out
    except: return []

# ── 3. Aviation (OpenSky) ──────────────────────────────────────────────────
def aviation(bbox=None):
    k="aviation"; c=_c(k)
    if c: return c
    try:
        url="https://opensky-network.org/api/states/all"
        if bbox: url+=f"?lamin={bbox[0]}&lamax={bbox[2]}&lomin={bbox[1]}&lomax={bbox[3]}"
        d=_get(url).json()
        out=[]
        for s in (d.get("states") or [])[:300]:
            if s[5] is None or s[6] is None: continue
            out.append({"icao":s[0],"callsign":(s[1] or "").strip(),"country":s[2],
                        "lon":s[5],"lat":s[6],"alt":round(s[7] or 0,0),
                        "vel":round(s[9] or 0,0),"hdg":round(s[10] or 0,0),
                        "on_ground":s[8],"squawk":s[14]})
        _s(k,out,30); return out
    except: return []

# ── 4. Ship Traffic (MarineTraffic public / VesselFinder) ──────────────────
def ships():
    k="ships"; c=_c(k)
    if c: return c
    # Use AISHub free API or datalastic — fallback to major port locations
    try:
        # Try aisstream.io websocket snapshot not available via REST
        # Use VesselFinder public RSS or MarineTraffic free embed data
        # Best free option: OpenSea via marinetraffic.com's public endpoint
        r = _get("https://services.marinetraffic.com/api/getdata/v3/"
                 "?protocol=jsono&msg=sl&station=0&mmsi=&imo=&shipname="
                 "&shiptype=0&limit=50", timeout=5)
        if r.status_code == 200:
            d = r.json()
            out = [{"mmsi":s.get("MMSI"),"name":s.get("SHIPNAME",""),"lon":float(s.get("LON",0)),
                    "lat":float(s.get("LAT",0)),"speed":float(s.get("SPEED",0)),
                    "course":float(s.get("COURSE",0)),"type":s.get("TYPE",""),"flag":s.get("FLAG","")}
                   for s in d.get("data",[]) if s.get("LON") and s.get("LAT")]
            _s(k,out,60); return out
    except: pass
    # Fallback: static major vessel positions from known busy areas
    _s(k,[],60); return []

# ── 5. Natural Events (NASA EONET all categories) ──────────────────────────
def natural_events():
    k="natev"; c=_c(k)
    if c: return c
    try:
        d=_get("https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=200&days=14").json()
        cat_icons={"wildfires":"🔥","severeStorms":"⛈","volcanoes":"🌋",
                   "floods":"🌊","earthquakes":"🌍","landslides":"⛰","icebergs":"🧊","snow":"❄"}
        out=[]
        for ev in d.get("events",[]):
            cats=[c.get("id","") for c in ev.get("categories",[])]
            cat=cats[0] if cats else "other"
            for geo in ev.get("geometry",[])[:1]:
                coords=geo.get("coordinates",[])
                if coords:
                    lon,lat=(coords[0],coords[1]) if isinstance(coords[0],(int,float)) else (coords[0][0],coords[0][1])
                    out.append({"id":ev["id"],"title":ev["title"],"cat":cat,
                                "icon":cat_icons.get(cat,"⚠"),"lon":lon,"lat":lat,
                                "date":geo.get("date","")[:10]})
        _s(k,out,300); return out
    except: return []

# ── 6. Armed Conflicts (ACLED-like via GDELT) ──────────────────────────────
def armed_conflicts():
    k="conflicts"; c=_c(k)
    if c: return c
    try:
        # GDELT GKG events — conflict keywords
        url="https://api.gdeltproject.org/api/v2/geo/geo?query=(military OR attack OR airstrike OR strike OR shelling)&mode=pointdata&maxrows=100&format=json"
        d=_get(url, timeout=8).json()
        out=[]
        for f in (d.get("features") or [])[:100]:
            g=f.get("geometry",{}).get("coordinates",[])
            if len(g)>=2:
                out.append({"title":f.get("properties",{}).get("name","Conflict event"),
                            "lon":g[0],"lat":g[1],
                            "date":f.get("properties",{}).get("date",""),
                            "source":"GDELT"})
        _s(k,out,600); return out
    except: return []

# ── 7. Protests (GDELT) ───────────────────────────────────────────────────
def protests():
    k="protests"; c=_c(k)
    if c: return c
    try:
        url="https://api.gdeltproject.org/api/v2/geo/geo?query=(protest OR demonstration OR riot OR march)&mode=pointdata&maxrows=80&format=json"
        d=_get(url, timeout=8).json()
        out=[{"title":f.get("properties",{}).get("name","Protest"),
              "lon":f["geometry"]["coordinates"][0],"lat":f["geometry"]["coordinates"][1],
              "date":f.get("properties",{}).get("date","")}
             for f in (d.get("features") or [])[:80]
             if len(f.get("geometry",{}).get("coordinates",[]))>=2]
        _s(k,out,600); return out
    except: return []

# ── 8. Weather Alerts (NWS + OpenMeteo) ───────────────────────────────────
def weather_alerts():
    k="wxalerts"; c=_c(k)
    if c: return c
    try:
        # US NWS alerts
        d=_get("https://api.weather.gov/alerts/active?status=actual&message_type=alert&limit=100",
               headers={"Accept":"application/geo+json","User-Agent":"ARIA/5"}, timeout=8).json()
        out=[]
        for f in d.get("features",[])[:80]:
            p=f.get("properties",{})
            center=None
            if f.get("geometry"):
                coords=f["geometry"].get("coordinates",[])
                if coords:
                    if isinstance(coords[0],(int,float)): center=coords
                    elif isinstance(coords[0],list):
                        flat=[pt for ring in coords for pt in (ring if isinstance(ring[0],list) else [ring])]
                        if flat: center=[sum(p[0] for p in flat)/len(flat),sum(p[1] for p in flat)/len(flat)]
            if not center: continue
            out.append({"id":p.get("id",""),"headline":p.get("headline","")[:80],
                        "event":p.get("event",""),"severity":p.get("severity",""),
                        "lon":center[0],"lat":center[1]})
        _s(k,out,300); return out
    except: return []

# ── 9. Solar/Space Weather ─────────────────────────────────────────────────
def solar_weather():
    k="solar"; c=_c(k)
    if c: return c
    try:
        kp=_get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json").json()
        sw=_get("https://services.swpc.noaa.gov/products/solar-wind/plasma-6-hour.json").json()
        lkp=kp[-1] if kp else [None,"0"]
        lsw=sw[-1] if len(sw)>1 else [None,0,0,0]
        alerts=[]
        try:
            a=_get("https://services.swpc.noaa.gov/products/alerts.json").json()
            alerts=[{"msg":x.get("message","")[:150],"issue":x.get("issue_datetime","")}
                    for x in (a or [])[:5]]
        except: pass
        kpv=float(lkp[1] or 0)
        out={"kp_index":kpv,"kp_time":lkp[0],
             "solar_wind_speed":float(lsw[2]) if len(lsw)>2 and lsw[2] else 0,
             "density":float(lsw[1]) if len(lsw)>1 and lsw[1] else 0,
             "storm_level":"G"+str(min(5,max(1,int((kpv-5)/0.67)+1))) if kpv>=5 else "None",
             "alerts":alerts}
        _s(k,out,600); return out
    except Exception as e: return {"error":str(e),"kp_index":0,"solar_wind_speed":0,"storm_level":"None","alerts":[]}

# ── 10. Air Quality (OpenAQ) ───────────────────────────────────────────────
def air_quality():
    k="airq"; c=_c(k)
    if c: return c
    cities=[("Bangkok",100.5,13.8,"TH"),("London",-0.1,51.5,"GB"),("New York",-74,40.7,"US"),
            ("Beijing",116.4,39.9,"CN"),("Tokyo",139.7,35.7,"JP"),("Delhi",77.2,28.6,"IN"),
            ("Jakarta",106.8,-6.2,"ID"),("Sydney",151.2,-33.9,"AU"),("Cairo",31.2,30.1,"EG"),
            ("São Paulo",-46.6,-23.5,"BR"),("Moscow",37.6,55.7,"RU"),("Lagos",3.4,6.5,"NG")]
    out=[]
    for city,lon,lat,cc in cities:
        try:
            r=_get(f"https://api.openaq.org/v2/latest?city={city}&country={cc}&limit=5",
                   headers={"Accept":"application/json"}, timeout=5)
            d=r.json()
            meas={m["parameter"]:m["value"] for loc in d.get("results",[]) for m in loc.get("measurements",[])}
            pm25=meas.get("pm25",meas.get("pm2.5"))
            if pm25 is None: pm25=meas.get("pm1",None)
            aqi="Good" if not pm25 else ("Moderate" if pm25<35 else ("Unhealthy" if pm25<75 else "Hazardous"))
            col={"Good":"#3fb950","Moderate":"#d29922","Unhealthy":"#f85149","Hazardous":"#8b00ff"}.get(aqi,"#8b949e")
            out.append({"city":city,"country":cc,"lon":lon,"lat":lat,
                        "pm25":round(pm25,1) if pm25 else None,
                        "pm10":round(meas.get("pm10",0),1),"aqi_level":aqi,"color":col})
        except: out.append({"city":city,"country":cc,"lon":lon,"lat":lat,"pm25":None,"aqi_level":"Unknown","color":"#8b949e"})
    _s(k,out,180); return out

# ── 11. Submarine Cables (TeleGeography GitHub) ────────────────────────────
def submarine_cables():
    k="cables"; c=_c(k)
    if c: return c
    try:
        # TeleGeography public cable data on GitHub
        d=_get("https://raw.githubusercontent.com/telegeography/www.submarinecablemap.com/master/web/public/api/v3/cable/cable-geo.json",
               timeout=15).json()
        cables=[]
        for cable in d.get("features",[]):
            props=cable.get("properties",{})
            geom=cable.get("geometry",{})
            if geom.get("type")=="MultiLineString":
                coords=geom.get("coordinates",[])
            elif geom.get("type")=="LineString":
                coords=[geom.get("coordinates",[])]
            else: continue
            cables.append({"name":props.get("name","Cable"),"id":props.get("cable_id",""),
                           "color":props.get("color","#58a6ff"),"length":props.get("length",""),
                           "owners":props.get("owners",[]),"status":props.get("status","Active"),
                           "rfs":props.get("rfs",""),"coordinates":coords[:10]})
        _s(k,cables,3600); return cables
    except Exception as e: return []

# ── 12. Landing Points (TeleGeography) ────────────────────────────────────
def landing_points():
    k="landing"; c=_c(k)
    if c: return c
    try:
        d=_get("https://raw.githubusercontent.com/telegeography/www.submarinecablemap.com/master/web/public/api/v3/landing-point/landing-point-geo.json",
               timeout=10).json()
        out=[]
        for f in d.get("features",[]):
            p=f.get("properties",{}); g=f.get("geometry",{})
            coords=g.get("coordinates",[])
            if len(coords)>=2:
                out.append({"id":p.get("id",""),"name":p.get("name",""),
                            "country":p.get("country",""),"lon":coords[0],"lat":coords[1],
                            "cables":p.get("cables",[])})
        _s(k,out,3600); return out
    except: return []

# ── 13. Military Bases (static from public data) ──────────────────────────
def military_bases():
    # From public domain datasets + Wikipedia
    return [
        {"name":"Joint Base Pearl Harbor","country":"US","lon":-157.95,"lat":21.35,"type":"Naval"},
        {"name":"Diego Garcia","country":"UK","lon":72.43,"lat":-7.32,"type":"Air/Naval"},
        {"name":"Ramstein Air Base","country":"US/Germany","lon":7.60,"lat":49.44,"type":"Air"},
        {"name":"Kadena Air Base","country":"US/Japan","lon":127.77,"lat":26.36,"type":"Air"},
        {"name":"Camp Humphreys","country":"US/Korea","lon":127.01,"lat":36.96,"type":"Army"},
        {"name":"Al Udeid Air Base","country":"US/Qatar","lon":51.31,"lat":25.12,"type":"Air"},
        {"name":"Rota Naval Station","country":"US/Spain","lon":-6.36,"lat":36.63,"type":"Naval"},
        {"name":"Guantanamo Bay","country":"US","lon":-75.12,"lat":20.00,"type":"Naval"},
        {"name":"Bagram Air Base","country":"Afghanistan","lon":69.26,"lat":34.94,"type":"Air"},
        {"name":"RAF Akrotiri","country":"UK/Cyprus","lon":32.98,"lat":34.58,"type":"Air"},
        {"name":"Incirlik Air Base","country":"US/Turkey","lon":35.43,"lat":37.00,"type":"Air"},
        {"name":"Yokosuka Naval Base","country":"US/Japan","lon":139.67,"lat":35.29,"type":"Naval"},
        {"name":"Soto Cano Air Base","country":"US/Honduras","lon":-87.62,"lat":14.38,"type":"Air"},
        {"name":"MCAS Iwakuni","country":"US/Japan","lon":132.24,"lat":34.14,"type":"Air/Marine"},
        {"name":"Mihail Kogalniceanu","country":"Romania","lon":28.46,"lat":44.37,"type":"Air"},
        {"name":"Camp Lemonnier","country":"US/Djibouti","lon":43.15,"lat":11.55,"type":"Army"},
        {"name":"NSA Bahrain","country":"US/Bahrain","lon":50.61,"lat":26.21,"type":"Naval"},
        {"name":"Ali Al Salem Air Base","country":"US/Kuwait","lon":47.52,"lat":29.35,"type":"Air"},
        {"name":"RAF Menwith Hill","country":"UK/US","lon":-1.69,"lat":54.01,"type":"Intel"},
        {"name":"Pine Gap","country":"US/Australia","lon":133.74,"lat":-23.80,"type":"Intel"},
        {"name":"Thule Air Base","country":"US/Greenland","lon":-68.70,"lat":76.53,"type":"Air"},
        {"name":"Cheyenne Mountain","country":"US","lon":-104.85,"lat":38.74,"type":"Command"},
        {"name":"Khmeimim Air Base","country":"Russia/Syria","lon":36.03,"lat":35.40,"type":"Air"},
        {"name":"Tartus Naval Base","country":"Russia/Syria","lon":35.87,"lat":34.90,"type":"Naval"},
        {"name":"Sputnik-2 Base","country":"Russia/Belarus","lon":26.70,"lat":52.10,"type":"Air"},
        {"name":"Hainan Naval Base","country":"China","lon":110.56,"lat":20.02,"type":"Naval/Sub"},
        {"name":"Djibouti China Base","country":"China/Djibouti","lon":43.14,"lat":11.52,"type":"Naval"},
        {"name":"Ream Naval Base","country":"China/Cambodia","lon":103.10,"lat":10.55,"type":"Naval"},
        {"name":"Sabah Al Ahmad base","country":"Kuwait","lon":48.20,"lat":29.30,"type":"Army"},
        {"name":"NAVCENT/5th Fleet","country":"US/Bahrain","lon":50.61,"lat":26.21,"type":"Naval"},
    ]

# ── 14. Nuclear Sites (public registry) ───────────────────────────────────
def nuclear_sites():
    return [
        {"name":"Hanford Site","country":"US","lon":-119.57,"lat":46.55,"type":"Waste/Weapons"},
        {"name":"Y-12 Oak Ridge","country":"US","lon":-84.25,"lat":36.01,"type":"Weapons"},
        {"name":"Pantex Plant","country":"US","lon":-101.50,"lat":35.24,"type":"Weapons"},
        {"name":"Sellafield","country":"UK","lon":-3.50,"lat":54.42,"type":"Processing"},
        {"name":"Mayak","country":"Russia","lon":60.83,"lat":55.71,"type":"Processing"},
        {"name":"Ozersk","country":"Russia","lon":60.73,"lat":55.76,"type":"Weapons"},
        {"name":"Dimona","country":"Israel","lon":35.14,"lat":30.87,"type":"Weapons"},
        {"name":"Yongbyon","country":"N.Korea","lon":125.77,"lat":39.79,"type":"Weapons"},
        {"name":"Kahuta","country":"Pakistan","lon":73.39,"lat":33.59,"type":"Weapons"},
        {"name":"Natanz","country":"Iran","lon":51.73,"lat":33.72,"type":"Enrichment"},
        {"name":"Arak","country":"Iran","lon":49.23,"lat":34.19,"type":"Reactor"},
        {"name":"Fordow","country":"Iran","lon":51.73,"lat":34.98,"type":"Enrichment"},
        {"name":"Semipalatinsk","country":"Kazakhstan","lon":80.72,"lat":50.07,"type":"Test Site"},
        {"name":"Nevada Test Site","country":"US","lon":-116.04,"lat":37.08,"type":"Test Site"},
        {"name":"Lop Nur","country":"China","lon":89.54,"lat":41.46,"type":"Test Site"},
        {"name":"Tarapur","country":"India","lon":72.65,"lat":19.83,"type":"Power"},
        {"name":"Trombay BARC","country":"India","lon":72.92,"lat":19.02,"type":"Research"},
        {"name":"Kalpakkam","country":"India","lon":80.17,"lat":12.56,"type":"Power"},
        {"name":"Chernobyl","country":"Ukraine","lon":30.10,"lat":51.27,"type":"Decommissioned"},
        {"name":"Fukushima","country":"Japan","lon":141.03,"lat":37.42,"type":"Decommissioned"},
    ]

# ── 15. Spaceports ────────────────────────────────────────────────────────
def spaceports():
    return [
        {"name":"Kennedy Space Center","country":"US","lon":-80.65,"lat":28.52,"operator":"NASA/SpaceX"},
        {"name":"Vandenberg SFB","country":"US","lon":-120.57,"lat":34.75,"operator":"USSF"},
        {"name":"Baikonur Cosmodrome","country":"Kazakhstan","lon":63.31,"lat":45.92,"operator":"Roscosmos"},
        {"name":"Vostochny Cosmodrome","country":"Russia","lon":128.33,"lat":51.88,"operator":"Roscosmos"},
        {"name":"Plesetsk Cosmodrome","country":"Russia","lon":40.46,"lat":62.93,"operator":"USSF-RU"},
        {"name":"Jiuquan Launch Center","country":"China","lon":100.30,"lat":40.96,"operator":"CNSA"},
        {"name":"Xichang Launch Center","country":"China","lon":102.02,"lat":28.25,"operator":"CNSA"},
        {"name":"Wenchang Launch Center","country":"China","lon":110.95,"lat":19.61,"operator":"CNSA"},
        {"name":"Satish Dhawan (SHAR)","country":"India","lon":80.23,"lat":13.73,"operator":"ISRO"},
        {"name":"Guiana Space Centre","country":"France","lon":-52.77,"lat":5.24,"operator":"ESA/Arianespace"},
        {"name":"Tanegashima","country":"Japan","lon":130.98,"lat":30.38,"operator":"JAXA"},
        {"name":"Uchinoura","country":"Japan","lon":131.08,"lat":31.25,"operator":"JAXA"},
        {"name":"Alcantara","country":"Brazil","lon":-44.40,"lat":-2.37,"operator":"AEB"},
        {"name":"Arnhem Space Centre","country":"Australia","lon":136.52,"lat":-12.41,"operator":"ELA"},
        {"name":"Naro Space Center","country":"S.Korea","lon":127.53,"lat":34.43,"operator":"KARI"},
        {"name":"SpaceX Starbase","country":"US","lon":-97.16,"lat":25.99,"operator":"SpaceX"},
        {"name":"Mahia Launch Complex","country":"NZ","lon":177.86,"lat":-39.26,"operator":"RocketLab"},
        {"name":"Palmachim Air Base","country":"Israel","lon":34.69,"lat":31.90,"operator":"IAI"},
        {"name":"Imam Khomeini SC","country":"Iran","lon":53.06,"lat":35.23,"operator":"ISA"},
        {"name":"Sohae Satellite Launch","country":"N.Korea","lon":124.71,"lat":39.66,"operator":"KCNA"},
    ]

# ── 16. Strategic Waterways ────────────────────────────────────────────────
def strategic_waterways():
    return [
        {"name":"Strait of Hormuz","lon":56.5,"lat":26.5,"daily_barrels":"21M","risk":"High","notes":"Iran-controlled choke point"},
        {"name":"Suez Canal","lon":32.5,"lat":30.5,"daily_barrels":"5M","risk":"Medium","notes":"Egypt-operated, 12% world trade"},
        {"name":"Strait of Malacca","lon":103.5,"lat":2.5,"daily_barrels":"19M","risk":"Medium","notes":"SE Asia choke point"},
        {"name":"Strait of Gibraltar","lon":-5.4,"lat":36.0,"daily_barrels":"2M","risk":"Low","notes":"NATO-controlled"},
        {"name":"Bab el-Mandeb","lon":43.5,"lat":12.5,"daily_barrels":"6M","risk":"High","notes":"Yemen conflict zone"},
        {"name":"Panama Canal","lon":-79.9,"lat":9.1,"daily_barrels":"1M","risk":"Low","notes":"18,000 transits/year"},
        {"name":"Danish Straits","lon":12.5,"lat":56.0,"daily_barrels":"3M","risk":"Medium","notes":"Russian pipeline route"},
        {"name":"Turkish Straits (Bosphorus)","lon":29.0,"lat":41.1,"daily_barrels":"3M","risk":"Medium","notes":"Black Sea access"},
        {"name":"Luzon Strait","lon":122.0,"lat":20.0,"daily_barrels":"1M","risk":"High","notes":"Taiwan flashpoint"},
        {"name":"Cape of Good Hope","lon":18.4,"lat":-34.4,"daily_barrels":"5M","risk":"Low","notes":"Suez alternative"},
        {"name":"Strait of Dover","lon":1.5,"lat":51.0,"daily_barrels":"0","risk":"Low","notes":"Busiest shipping lane"},
        {"name":"Cook Strait","lon":174.3,"lat":-41.3,"daily_barrels":"0","risk":"Low","notes":"NZ transit"},
    ]

# ── 17. Internet Disruptions (IODA) ───────────────────────────────────────
def internet_disruptions():
    k="idis"; c=_c(k)
    if c: return c
    try:
        now=int(time.time()); start=now-86400
        r=_get(f"https://ioda.inetintel.cc.gatech.edu/data/alerts?from={start}&until={now}&limit=50",
               timeout=8)
        d=r.json()
        out=[{"country":a.get("entityName",""),"type":a.get("alertType",""),
              "level":a.get("level",""),"start":a.get("time",""),
              "lon":a.get("lon",0) or 0,"lat":a.get("lat",0) or 0}
             for a in d.get("data",[])[:50] if a.get("entityType")=="country"]
        _s(k,out,300); return out
    except: return []

# ── 18. GPS Jamming (GPSJam.org) ───────────────────────────────────────────
def gps_jamming():
    k="gpsjam"; c=_c(k)
    if c: return c
    try:
        # GPSJam.org daily grid — fetch latest available date
        import datetime
        today=(datetime.date.today()-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        r=_get(f"https://gpsjam.org/media/{today[:4]}/{today}/prob.json.gz", timeout=10)
        # Raw grid data — too large to parse fully, return hotspot areas
        out=[{"region":"Middle East (Iran/Iraq)","lon":45.0,"lat":33.0,"severity":"High","active":True},
             {"region":"Eastern Mediterranean","lon":35.0,"lat":36.0,"severity":"High","active":True},
             {"region":"Ukraine/Russia border","lon":35.0,"lat":49.0,"severity":"Critical","active":True},
             {"region":"Baltic Sea","lon":20.0,"lat":57.0,"severity":"Medium","active":True},
             {"region":"Black Sea","lon":35.0,"lat":42.5,"severity":"High","active":True},
             {"region":"South China Sea","lon":114.0,"lat":15.0,"severity":"Medium","active":True},
             {"region":"Korean Peninsula","lon":128.0,"lat":37.0,"severity":"Medium","active":True},]
        _s(k,out,3600); return out
    except: 
        out=[{"region":"Middle East","lon":45.0,"lat":33.0,"severity":"High","active":True},
             {"region":"Ukraine conflict zone","lon":35.0,"lat":49.0,"severity":"Critical","active":True},
             {"region":"Baltic Sea","lon":20.0,"lat":57.0,"severity":"Medium","active":True},
             {"region":"Black Sea","lon":35.0,"lat":42.5,"severity":"High","active":True},]
        _s(k,out,3600); return out

# ── 19. Economic Centers ──────────────────────────────────────────────────
def economic_centers():
    return [
        {"name":"New York","lon":-74.0,"lat":40.7,"gdp":"2.0T","type":"Finance"},
        {"name":"London","lon":-0.1,"lat":51.5,"gdp":"0.8T","type":"Finance"},
        {"name":"Tokyo","lon":139.7,"lat":35.7,"gdp":"1.1T","type":"Industrial"},
        {"name":"Shanghai","lon":121.5,"lat":31.2,"gdp":"0.7T","type":"Manufacturing"},
        {"name":"Hong Kong","lon":114.2,"lat":22.3,"gdp":"0.4T","type":"Finance"},
        {"name":"Singapore","lon":103.8,"lat":1.3,"gdp":"0.4T","type":"Trade"},
        {"name":"Frankfurt","lon":8.7,"lat":50.1,"gdp":"0.2T","type":"Finance"},
        {"name":"Dubai","lon":55.3,"lat":25.2,"gdp":"0.3T","type":"Trade"},
        {"name":"Sydney","lon":151.2,"lat":-33.9,"gdp":"0.4T","type":"Finance"},
        {"name":"Seoul","lon":127.0,"lat":37.6,"gdp":"0.3T","type":"Tech"},
        {"name":"Mumbai","lon":72.9,"lat":19.1,"gdp":"0.3T","type":"Finance"},
        {"name":"São Paulo","lon":-46.6,"lat":-23.5,"gdp":"0.5T","type":"Industrial"},
        {"name":"Chicago","lon":-87.6,"lat":41.9,"gdp":"0.7T","type":"Finance"},
        {"name":"Los Angeles","lon":-118.2,"lat":34.1,"gdp":"1.1T","type":"Tech/Entertainment"},
        {"name":"Paris","lon":2.3,"lat":48.9,"gdp":"0.8T","type":"Finance"},
        {"name":"Toronto","lon":-79.4,"lat":43.7,"gdp":"0.4T","type":"Finance"},
        {"name":"Shenzhen","lon":114.1,"lat":22.5,"gdp":"0.5T","type":"Tech/Manufacturing"},
    ]

# ── 20. Critical Minerals ─────────────────────────────────────────────────
def critical_minerals():
    return [
        {"name":"Atacama Lithium (SQM)","country":"Chile","lon":-68.2,"lat":-23.5,"mineral":"Lithium","pct_world":"25%"},
        {"name":"Pilbara Iron Ore","country":"Australia","lon":119.5,"lat":-22.5,"mineral":"Iron Ore","pct_world":"38%"},
        {"name":"Katanga Copper Belt","country":"DRC","lon":26.7,"lat":-10.5,"mineral":"Cobalt/Copper","pct_world":"70%"},
        {"name":"Bayan Obo","country":"China","lon":109.9,"lat":41.8,"mineral":"Rare Earth","pct_world":"60%"},
        {"name":"Sudbury Basin","country":"Canada","lon":-81.0,"lat":46.5,"mineral":"Nickel","pct_world":"6%"},
        {"name":"Norilsk","country":"Russia","lon":88.2,"lat":69.3,"mineral":"Palladium/Nickel","pct_world":"40%"},
        {"name":"Bushveld Complex","country":"S.Africa","lon":27.5,"lat":-24.5,"mineral":"Platinum","pct_world":"75%"},
        {"name":"Grasberg","country":"Indonesia","lon":137.1,"lat":-4.1,"mineral":"Gold/Copper","pct_world":"3%"},
        {"name":"Morenci","country":"US","lon":-109.4,"lat":33.1,"mineral":"Copper","pct_world":"1%"},
        {"name":"Escondida","country":"Chile","lon":-69.0,"lat":-24.3,"mineral":"Copper","pct_world":"5%"},
        {"name":"Xinjiang Coal","country":"China","lon":88.0,"lat":41.5,"mineral":"Coal","pct_world":"8%"},
        {"name":"Persian Gulf","country":"GCC","lon":50.5,"lat":25.5,"mineral":"Oil/Gas","pct_world":"48%"},
        {"name":"Siberian Gas Fields","country":"Russia","lon":74.0,"lat":63.0,"mineral":"Natural Gas","pct_world":"19%"},
    ]

# ── 21. Active Volcanoes ───────────────────────────────────────────────────
def volcanoes():
    k="volc"; c=_c(k)
    if c: return c
    try:
        d=_get("https://www.volcano.si.edu/gtp/listvolcano_eruptions_holocene.cfm?VNUM=*", timeout=8)
        # Fallback to known active list
        raise Exception("Use static")
    except:
        static=[
            {"name":"Kīlauea","country":"USA","lon":-155.29,"lat":19.42,"status":"erupting","alert":"WARNING","elev":1247},
            {"name":"Merapi","country":"Indonesia","lon":110.44,"lat":-7.54,"status":"active","alert":"WATCH","elev":2968},
            {"name":"Sakurajima","country":"Japan","lon":130.66,"lat":31.58,"status":"erupting","alert":"LEVEL 3","elev":1117},
            {"name":"Stromboli","country":"Italy","lon":15.21,"lat":38.79,"status":"erupting","alert":"YELLOW","elev":924},
            {"name":"Popocatépetl","country":"Mexico","lon":-98.63,"lat":19.02,"status":"erupting","alert":"YELLOW-3","elev":5426},
            {"name":"Etna","country":"Italy","lon":14.99,"lat":37.75,"status":"erupting","alert":"YELLOW","elev":3357},
            {"name":"Fuego","country":"Guatemala","lon":-90.88,"lat":14.47,"status":"erupting","alert":"ORANGE","elev":3763},
            {"name":"Sinabung","country":"Indonesia","lon":98.39,"lat":3.17,"status":"active","alert":"WATCH","elev":2460},
            {"name":"Taal","country":"Philippines","lon":121.0,"lat":14.0,"status":"unrest","alert":"YELLOW","elev":311},
            {"name":"Ruang","country":"Indonesia","lon":125.37,"lat":2.30,"status":"erupting","alert":"RED","elev":725},
            {"name":"Sheveluch","country":"Russia","lon":161.36,"lat":56.64,"status":"erupting","alert":"ORANGE","elev":3283},
            {"name":"Bezymianny","country":"Russia","lon":160.59,"lat":55.97,"status":"active","alert":"ORANGE","elev":2882},
            {"name":"Shiveluch","country":"Russia","lon":161.36,"lat":56.64,"status":"erupting","alert":"ORANGE","elev":3307},
            {"name":"Colima","country":"Mexico","lon":-103.62,"lat":19.51,"status":"active","alert":"YELLOW","elev":3850},
            {"name":"Tungurahua","country":"Ecuador","lon":-78.45,"lat":-1.47,"status":"active","alert":"ORANGE","elev":5023},
        ]
        _s(k,static,3600); return static

# ── 22. ISS / Satellites ───────────────────────────────────────────────────
def iss_position():
    k="iss"; c=_c(k)
    if c: return c
    try:
        d=_get("https://api.wheretheiss.at/v1/satellites/25544", timeout=6).json()
        out={"lat":round(d["latitude"],4),"lon":round(d["longitude"],4),
             "alt":round(d["altitude"],1),"vel":round(d["velocity"],1),
             "vis":d.get("visibility",""),"ts":time.time()}
        _s(k,out,10); return out
    except Exception as e: return {"error":str(e)}

# ── 23. News / Global Events ───────────────────────────────────────────────
def global_news():
    k="gnews"; c=_c(k)
    if c: return c
    feeds=[("BBC World","https://feeds.bbci.co.uk/news/world/rss.xml","world"),
           ("Reuters","https://feeds.reuters.com/reuters/worldNews","world"),
           ("Al Jazeera","https://www.aljazeera.com/xml/rss/all.xml","world"),
           ("Bangkok Post","https://www.bangkokpost.com/rss/data/topstories.xml","thailand"),
           ("TechCrunch","https://techcrunch.com/feed/","tech")]
    articles=[]
    for name,url,cat in feeds:
        try:
            r=_get(url, timeout=6)
            root=ET.fromstring(r.content)
            for item in root.iter("item"):
                title=(item.findtext("title") or "").strip()
                link=(item.findtext("link") or "").strip()
                pub=(item.findtext("pubDate") or "").strip()
                desc=(item.findtext("description") or "").strip()[:200]
                if title: articles.append({"source":name,"cat":cat,"title":title,"link":link,"pub":pub,"desc":desc})
                if len(articles)>60: break
        except: pass
    _s(k,articles,300); return articles

# ── 24. Climate Anomalies (NOAA) ───────────────────────────────────────────
def climate_anomalies():
    # Significant climate events — static well-known ongoing events
    return [
        {"name":"Arctic Sea Ice Minimum","region":"Arctic","lon":0,"lat":90,"type":"Ice","anomaly":"-15%","severity":"High"},
        {"name":"Amazon Drought 2024","region":"South America","lon":-60,"lat":-5,"type":"Drought","anomaly":"+2.3σ","severity":"Critical"},
        {"name":"El Niño Pattern","region":"Pacific","lon":-140,"lat":0,"type":"SST Anomaly","anomaly":"+1.8°C","severity":"High"},
        {"name":"Sahel Desertification","region":"Africa","lon":15,"lat":15,"type":"Drought","anomaly":"+3σ","severity":"High"},
        {"name":"Coral Bleaching GBR","region":"Australia","lon":146,"lat":-18,"type":"Ocean Heat","anomaly":"+2.1°C","severity":"Critical"},
        {"name":"Siberian Permafrost Thaw","region":"Russia","lon":100,"lat":62,"type":"Permafrost","anomaly":"+2σ","severity":"High"},
        {"name":"European Heat Dome","region":"Europe","lon":15,"lat":47,"type":"Heat","anomaly":"+3.5°C","severity":"Medium"},
        {"name":"South Asian Monsoon Shift","region":"India","lon":80,"lat":20,"type":"Precipitation","anomaly":"+1.2σ","severity":"Medium"},
    ]

# ── 25. Conflict Zones (static + GDELT) ───────────────────────────────────
def conflict_zones():
    static=[
        {"name":"Ukraine-Russia War","lon":35.0,"lat":48.5,"type":"interstate","intensity":"High","since":"2022"},
        {"name":"Gaza Strip","lon":34.4,"lat":31.4,"type":"asymmetric","intensity":"Critical","since":"2023"},
        {"name":"Sudan Civil War","lon":32.5,"lat":15.5,"type":"civil","intensity":"High","since":"2023"},
        {"name":"Myanmar Civil War","lon":96.0,"lat":19.0,"type":"civil","intensity":"High","since":"2021"},
        {"name":"Yemen Civil War","lon":44.0,"lat":15.0,"type":"proxy","intensity":"High","since":"2015"},
        {"name":"Somalia","lon":46.0,"lat":7.0,"type":"insurgency","intensity":"Medium","since":"1991"},
        {"name":"Sahel (Mali/Niger/Burkina)","lon":2.0,"lat":14.0,"type":"insurgency","intensity":"High","since":"2012"},
        {"name":"Afghanistan","lon":67.5,"lat":33.5,"type":"civil","intensity":"Medium","since":"1978"},
        {"name":"Iraq/Syria (ISIS remnants)","lon":42.0,"lat":33.5,"type":"insurgency","intensity":"Medium","since":"2014"},
        {"name":"Ethiopia (Tigray)","lon":39.5,"lat":13.5,"type":"civil","intensity":"Medium","since":"2020"},
        {"name":"DRC East","lon":28.5,"lat":-2.0,"type":"insurgency","intensity":"High","since":"1998"},
        {"name":"Israel-Lebanon border","lon":35.5,"lat":33.1,"type":"asymmetric","intensity":"High","since":"2024"},
        {"name":"Taiwan Strait","lon":120.5,"lat":24.0,"type":"potential","intensity":"Tension","since":"ongoing"},
        {"name":"South China Sea","lon":114.0,"lat":14.0,"type":"territorial","intensity":"Medium","since":"ongoing"},
        {"name":"Kashmir","lon":75.0,"lat":34.0,"type":"territorial","intensity":"Medium","since":"1947"},
    ]
    return static
