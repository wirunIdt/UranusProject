"""
Volume Control — Fixed (no more AudioDevice Activate error)
Uses PowerShell COM object on Windows (no pycaw needed)
macOS: osascript | Linux: pactl/amixer
"""
import subprocess, platform, shutil, re

SYSTEM = platform.system()


class VolumeController:
    def __init__(self):
        self._cache = 70
        self._muted = False
        self._backend = self._detect()
        print(f"[VOL] backend: {self._backend}")

    def _detect(self) -> str:
        if SYSTEM == "Windows":
            # Try pycaw first but with correct API
            try:
                import ctypes
                from ctypes import cast, POINTER, c_float, HRESULT
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                # Test the correct activation pattern
                speakers = AudioUtilities.GetSpeakers()
                iid = IAudioEndpointVolume._iid_
                iface = speakers.Activate(iid, CLSCTX_ALL, None)
                vol = cast(iface, POINTER(IAudioEndpointVolume))
                _ = vol.GetMasterVolumeLevelScalar()
                return "pycaw"
            except Exception as e:
                print(f"[VOL] pycaw unavailable: {e} → using PowerShell")
            return "powershell"
        elif SYSTEM == "Darwin":
            return "osascript"
        else:
            if shutil.which("pactl"):  return "pactl"
            if shutil.which("amixer"): return "amixer"
            return "none"

    # ── Internal: get pycaw volume object ────────────────────────────────────
    def _pycaw_vol(self):
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        speakers = AudioUtilities.GetSpeakers()
        iid   = IAudioEndpointVolume._iid_
        iface = speakers.Activate(iid, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))

    # ── PowerShell COM (no pycaw) ─────────────────────────────────────────────
    def _ps_set(self, level: int):
        """Set Windows volume via PowerShell WScript.Shell audio keys."""
        # Use nircmd if available (most reliable)
        if shutil.which("nircmd"):
            subprocess.run(["nircmd", "setsysvolume", str(int(level / 100 * 65535))],
                           capture_output=True)
            return
        # Fallback: PowerShell audio endpoint COM
        script = f"""
$vol = {level / 100:.4f}
$wshell = New-Object -ComObject WScript.Shell
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {{
    void p1();void p2();void p3();void p4();
    int SetMasterVolumeLevelScalar(float f, System.Guid g);
}}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {{ int Activate(ref System.Guid g,uint c,System.IntPtr p,out object o); }}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {{ int e(int f,uint m,out object c); int GetDefaultAudioEndpoint(int f,int r,out IMMDevice d); }}
[ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorClass{{}}
public class WinVol {{
    public static void Set(float v){{
        var en=(IMMDeviceEnumerator)new MMDeviceEnumeratorClass();
        IMMDevice d; en.GetDefaultAudioEndpoint(0,1,out d);
        var iid=typeof(IAudioEndpointVolume).GUID;
        object o; d.Activate(ref iid,23,System.IntPtr.Zero,out o);
        ((IAudioEndpointVolume)o).SetMasterVolumeLevelScalar(v,System.Guid.Empty);
    }}
}}
'@ -Language CSharp
[WinVol]::Set({level / 100:.4f})
"""
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-c", script],
                           capture_output=True, timeout=5)
        except Exception as e:
            print(f"[VOL] PS set error: {e}")

    def _ps_get(self) -> int:
        script = """
try {
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume { void p1();void p2();int GetMasterVolumeLevelScalar(out float f); }
[Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref System.Guid g,uint c,System.IntPtr p,out object o); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int e(int f,uint m,out object c); int GetDefaultAudioEndpoint(int f,int r,out IMMDevice d); }
[ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorClass{}
public class WinVolGet {
    public static float Get(){
        var en=(IMMDeviceEnumerator)new MMDeviceEnumeratorClass();
        IMMDevice d; en.GetDefaultAudioEndpoint(0,1,out d);
        var iid=typeof(IAudioEndpointVolume).GUID;
        object o; d.Activate(ref iid,23,System.IntPtr.Zero,out o);
        float v; ((IAudioEndpointVolume)o).GetMasterVolumeLevelScalar(out v); return v;
    }
}
'@ -Language CSharp
[Math]::Round([WinVolGet]::Get()*100)
} catch { 70 }
"""
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-c", script],
                               capture_output=True, text=True, timeout=4)
            val = r.stdout.strip()
            return int(val) if val.isdigit() else self._cache
        except Exception:
            return self._cache

    def _ps_mute(self, mute: bool):
        # SendKeys: 173 = mute toggle
        subprocess.run(["powershell", "-NoProfile", "-c",
                        "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],
                       capture_output=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_volume(self) -> int:
        try:
            if self._backend == "pycaw":
                return int(round(self._pycaw_vol().GetMasterVolumeLevelScalar() * 100))
            elif self._backend == "powershell":
                return self._ps_get()
            elif self._backend == "osascript":
                r = subprocess.run(
                    ["osascript", "-e", "output volume of (get volume settings)"],
                    capture_output=True, text=True, timeout=3)
                val = r.stdout.strip()
                return int(val) if val.isdigit() else self._cache
            elif self._backend == "pactl":
                r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                                   capture_output=True, text=True, timeout=3)
                m = re.search(r'(\d+)%', r.stdout)
                return int(m.group(1)) if m else self._cache
            elif self._backend == "amixer":
                r = subprocess.run(["amixer", "-D", "pulse", "sget", "Master"],
                                   capture_output=True, text=True, timeout=3)
                m = re.search(r'\[(\d+)%\]', r.stdout)
                return int(m.group(1)) if m else self._cache
        except Exception as e:
            print(f"[VOL] get error: {e}")
        return self._cache

    def is_muted(self) -> bool:
        return self._muted

    def set_volume(self, level: int) -> str:
        level = max(0, min(100, level))
        self._muted = False
        try:
            if self._backend == "pycaw":
                self._pycaw_vol().SetMasterVolumeLevelScalar(level / 100.0, None)
            elif self._backend == "powershell":
                self._ps_set(level)
            elif self._backend == "osascript":
                subprocess.run(["osascript", "-e", f"set volume output volume {level}"],
                               capture_output=True)
            elif self._backend == "pactl":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                               capture_output=True)
            elif self._backend == "amixer":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{level}%"],
                               capture_output=True)
            self._cache = level
        except Exception as e:
            print(f"[VOL] set error: {e}")
        icon = "🔇" if level == 0 else ("🔉" if level < 50 else "🔊")
        return f"{icon} Volume: {level}%"

    def step(self, delta: int) -> str:
        return self.set_volume(self.get_volume() + delta)

    def mute(self) -> str:
        self._muted = True
        try:
            if self._backend == "pycaw":
                self._pycaw_vol().SetMute(1, None)
            elif self._backend == "powershell":
                self._ps_mute(True)
            elif self._backend == "osascript":
                subprocess.run(["osascript", "-e", "set volume with output muted"], capture_output=True)
            elif self._backend == "pactl":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], capture_output=True)
            elif self._backend == "amixer":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "mute"], capture_output=True)
        except Exception as e:
            print(f"[VOL] mute error: {e}")
        return "🔇 Muted"

    def unmute(self) -> str:
        self._muted = False
        try:
            if self._backend == "pycaw":
                self._pycaw_vol().SetMute(0, None)
            elif self._backend == "powershell":
                self._ps_mute(False)
            elif self._backend == "osascript":
                subprocess.run(["osascript", "-e", "set volume without output muted"], capture_output=True)
            elif self._backend == "pactl":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True)
            elif self._backend == "amixer":
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "unmute"], capture_output=True)
        except Exception as e:
            print(f"[VOL] unmute error: {e}")
        return f"🔊 Unmuted ({self._cache}%)"

    def toggle_mute(self) -> str:
        return self.unmute() if self._muted else self.mute()
