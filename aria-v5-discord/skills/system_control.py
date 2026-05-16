"""
System Control Skills v2
- Open / close applications
- Open URLs / websites in browser
- Volume control (Windows / macOS / Linux)
- Command parsing from natural language (EN + TH)
"""
import subprocess, platform, webbrowser, shutil, re, os

SYSTEM = platform.system()

APP_MAP_WIN = {
    "notepad":"notepad.exe","calculator":"calc.exe","calc":"calc.exe",
    "paint":"mspaint.exe","chrome":"chrome","google chrome":"chrome",
    "firefox":"firefox","edge":"msedge","microsoft edge":"msedge",
    "explorer":"explorer.exe","file explorer":"explorer.exe",
    "cmd":"cmd.exe","command prompt":"cmd.exe","terminal":"wt.exe",
    "powershell":"powershell.exe","vscode":"code","vs code":"code",
    "discord":"discord","telegram":"telegram","spotify":"spotify",
    "word":"winword","excel":"excel","powerpoint":"powerpnt",
    "task manager":"taskmgr.exe","taskmgr":"taskmgr.exe",
    "settings":"ms-settings:","control panel":"control","vlc":"vlc","obs":"obs64",
    "โน้ตแพด":"notepad.exe","เครื่องคิดเลข":"calc.exe","เพนต์":"mspaint.exe",
    "ครอม":"chrome","เบราว์เซอร์":"chrome","เอดจ์":"msedge",
    "เทอร์มินัล":"wt.exe","เวิร์ด":"winword","เอกซ์เซล":"excel",
    "ดิสคอร์ด":"discord","เทเลแกรม":"telegram","สปอติฟาย":"spotify",
    "ตัวจัดการงาน":"taskmgr.exe",
}
APP_MAP_MAC = {
    "chrome":"Google Chrome","google chrome":"Google Chrome",
    "firefox":"Firefox","safari":"Safari","terminal":"Terminal",
    "calculator":"Calculator","notes":"Notes","finder":"Finder",
    "vscode":"Visual Studio Code","vs code":"Visual Studio Code",
    "discord":"Discord","telegram":"Telegram","spotify":"Spotify",
    "word":"Microsoft Word","excel":"Microsoft Excel","vlc":"VLC",
    "ครอม":"Google Chrome","เครื่องคิดเลข":"Calculator",
    "เทอร์มินัล":"Terminal","ดิสคอร์ด":"Discord","เทเลแกรม":"Telegram",
}

WEB_MAP = {
    "youtube":"https://youtube.com","ยูทูป":"https://youtube.com",
    "google":"https://google.com","กูเกิล":"https://google.com",
    "facebook":"https://facebook.com","เฟซบุ๊ก":"https://facebook.com",
    "instagram":"https://instagram.com","อินสตาแกรม":"https://instagram.com",
    "github":"https://github.com","twitter":"https://twitter.com","x":"https://x.com",
    "reddit":"https://reddit.com","wikipedia":"https://wikipedia.org",
    "วิกิพีเดีย":"https://wikipedia.org","gmail":"https://mail.google.com",
    "เมล":"https://mail.google.com","maps":"https://maps.google.com",
    "แผนที่":"https://maps.google.com","chatgpt":"https://chat.openai.com",
    "claude":"https://claude.ai","gemini":"https://gemini.google.com",
    "lazada":"https://lazada.co.th","shopee":"https://shopee.co.th",
    "netflix":"https://netflix.com","pantip":"https://pantip.com",
    "sanook":"https://sanook.com","kapook":"https://kapook.com",
}

URL_RE = re.compile(r'^(https?://|www\.)?[\w\-]+\.[\w\.\-/\?=&#%]{2,}$')

def open_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return f"✅ เปิด {url} แล้ว"
    except Exception as e:
        return f"❌ เปิด URL ไม่ได้: {e}"

def open_app(app_name: str) -> str:
    n = app_name.lower().strip()
    if n in WEB_MAP:
        return open_url(WEB_MAP[n])
    if URL_RE.match(n):
        return open_url(n)
    if SYSTEM == "Windows":
        exe = APP_MAP_WIN.get(n, app_name)
        try:
            if exe.endswith(":"): os.startfile(exe)
            elif exe.endswith(".exe"): subprocess.Popen([exe])
            else: subprocess.Popen(f'start "" "{exe}"', shell=True)
            return f"✅ เปิด {app_name} แล้ว"
        except Exception as e:
            return f"❌ เปิด '{app_name}' ไม่ได้: {e}"
    elif SYSTEM == "Darwin":
        app = APP_MAP_MAC.get(n, app_name)
        try:
            subprocess.Popen(["open","-a",app])
            return f"✅ เปิด {app} แล้ว"
        except Exception as e:
            return f"❌ เปิด '{app}' ไม่ได้: {e}"
    else:
        try:
            subprocess.Popen([n])
            return f"✅ เปิด {app_name} แล้ว"
        except Exception as e:
            return f"❌ เปิด '{app_name}' ไม่ได้: {e}"

def close_app(app_name: str) -> str:
    n = app_name.lower().strip()
    if SYSTEM == "Windows":
        exe = APP_MAP_WIN.get(n, app_name)
        if not exe.endswith(".exe"): exe += ".exe"
        r = subprocess.run(["taskkill","/F","/IM",exe], capture_output=True, text=True)
        return f"✅ ปิด {app_name} แล้ว" if r.returncode==0 else f"❌ ปิด '{app_name}' ไม่ได้"
    elif SYSTEM == "Darwin":
        app = APP_MAP_MAC.get(n, app_name)
        r = subprocess.run(["pkill","-f",app], capture_output=True)
        return f"✅ ปิด {app} แล้ว" if r.returncode==0 else f"❌ ไม่พบ '{app}'"
    else:
        r = subprocess.run(["pkill","-f",n], capture_output=True)
        return f"✅ ปิด {app_name} แล้ว" if r.returncode==0 else f"❌ ไม่พบ '{app_name}'"

def _vol_win(action):
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        d = AudioUtilities.GetSpeakers()
        iface = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        v = cast(iface, POINTER(IAudioEndpointVolume))
        cur = v.GetMasterVolumeLevelScalar()
        if action=="up":   new=min(1.0,cur+0.10); v.SetMasterVolumeLevelScalar(new,None); return f"🔊 {int(new*100)}%"
        if action=="down": new=max(0.0,cur-0.10); v.SetMasterVolumeLevelScalar(new,None); return f"🔉 {int(new*100)}%"
        if action=="mute":   v.SetMute(1,None); return "🔇 Muted"
        if action=="unmute": v.SetMute(0,None); return f"🔊 Unmuted ({int(cur*100)}%)"
    except ImportError: pass
    km={"up":175,"down":174,"mute":173}
    k=km.get(action)
    if k:
        subprocess.run(["powershell","-c",f"(New-Object -comObject WScript.Shell).SendKeys([char]{k})"],capture_output=True)
        return {"up":"🔊 Volume Up","down":"🔉 Volume Down","mute":"🔇 Mute toggled"}.get(action,"Done")
    return "❓ Unknown"

def _vol_mac(action):
    cmds={"up":"set volume output volume (output volume of (get volume settings) + 10)",
          "down":"set volume output volume (output volume of (get volume settings) - 10)",
          "mute":"set volume with output muted","unmute":"set volume without output muted"}
    if action in cmds:
        subprocess.run(["osascript","-e",cmds[action]])
        return {"up":"🔊 Up","down":"🔉 Down","mute":"🔇 Muted","unmute":"🔊 Unmuted"}.get(action,"Done")
    return "❓ Unknown"

def _vol_linux(action):
    cmds={"up":["amixer","-D","pulse","sset","Master","10%+"],
          "down":["amixer","-D","pulse","sset","Master","10%-"],
          "mute":["amixer","-D","pulse","sset","Master","mute"],
          "unmute":["amixer","-D","pulse","sset","Master","unmute"]}
    cmd=cmds.get(action)
    if cmd and shutil.which("amixer"):
        subprocess.run(cmd,capture_output=True)
        return {"up":"🔊 Up","down":"🔉 Down","mute":"🔇 Muted","unmute":"🔊 Unmuted"}.get(action,"Done")
    return "❓ amixer not found"

def set_volume(action: str) -> str:
    a=action.lower().strip()
    if SYSTEM=="Windows": return _vol_win(a)
    if SYSTEM=="Darwin":  return _vol_mac(a)
    return _vol_linux(a)

OPEN_PAT  = [r"open\s+(.+)",r"launch\s+(.+)",r"start\s+(.+)",r"go to\s+(.+)",
             r"browse\s+(.+)",r"visit\s+(.+)",r"เปิด\s+(.+)",r"เปิดเว็บ\s+(.+)",
             r"ไปที่\s+(.+)",r"เข้า\s+(.+)"]
CLOSE_PAT = [r"close\s+(.+)",r"kill\s+(.+)",r"quit\s+(.+)",r"ปิด\s+(.+)"]
VOL_TRIG  = {
    "up":     ["volume up","louder","vol up","เพิ่มเสียง","เสียงดัง"],
    "down":   ["volume down","quieter","vol down","ลดเสียง","เสียงเบา"],
    "mute":   ["mute","silent","ปิดเสียง","ไม่มีเสียง","เงียบ"],
    "unmute": ["unmute","sound on","เปิดเสียง"],
}

def parse_command(text: str) -> dict | None:
    tl = text.lower().strip()
    for action, triggers in VOL_TRIG.items():
        if any(tr in tl for tr in triggers):
            return {"action":"volume","target":action}
    for p in OPEN_PAT:
        m = re.search(p, tl)
        if m: return {"action":"open","target":m.group(1).strip().rstrip(".")}
    for p in CLOSE_PAT:
        m = re.search(p, tl)
        if m: return {"action":"close","target":m.group(1).strip().rstrip(".")}
    return None

def execute_command(cmd: dict) -> str:
    a, t = cmd.get("action"), cmd.get("target","")
    if a=="open":   return open_app(t)
    if a=="close":  return close_app(t)
    if a=="volume": return set_volume(t)
    if a=="url":    return open_url(t)
    return f"❓ Unknown: {a}"
