"""modules/scanner.py — Network Security Scanner"""
import os, socket, subprocess, threading, time, json, platform
import ipaddress
import logging

log = logging.getLogger("ARIA.Scanner")
SYSTEM = platform.system()

# ── Port Scanner ──────────────────────────────────────────────────────────
COMMON_PORTS = {
    21:"FTP",22:"SSH",23:"Telnet",25:"SMTP",53:"DNS",
    80:"HTTP",110:"POP3",143:"IMAP",443:"HTTPS",
    445:"SMB",3306:"MySQL",3389:"RDP",5432:"PostgreSQL",
    5900:"VNC",6379:"Redis",8080:"HTTP-Alt",8443:"HTTPS-Alt",
    27017:"MongoDB",47777:"ARIA-Mesh",47780:"ARIA-Files",
    5000:"ARIA-Web",11434:"Ollama",
}

def scan_port(host: str, port: int, timeout: float = 0.5) -> dict:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        open_ = result == 0
        # Try banner grab
        banner = ""
        if open_ and port not in (443, 8443):
            try:
                s2 = socket.socket()
                s2.settimeout(1)
                s2.connect((host, port))
                s2.send(b"HEAD / HTTP/1.0\r\n\r\n")
                banner = s2.recv(256).decode("utf-8", errors="ignore").split("\n")[0][:80]
                s2.close()
            except:
                pass
        return {"port": port, "open": open_, "service": COMMON_PORTS.get(port, "unknown"),
                "banner": banner.strip()}
    except Exception as e:
        return {"port": port, "open": False, "error": str(e)}

def scan_host(host: str, ports: list = None, timeout: float = 0.5) -> dict:
    """Scan a single host — returns open ports and basic info"""
    if ports is None:
        ports = list(COMMON_PORTS.keys())
    # Ping test
    alive = _ping(host)
    if not alive:
        return {"host": host, "alive": False, "open_ports": [], "ts": time.time()}
    # Hostname
    try:
        hostname = socket.gethostbyaddr(host)[0]
    except:
        hostname = ""
    # Port scan (threaded)
    results = []
    lock = threading.Lock()
    def _scan(p):
        r = scan_port(host, p, timeout)
        if r["open"]:
            with lock: results.append(r)
    threads = [threading.Thread(target=_scan, args=(p,), daemon=True) for p in ports]
    for t in threads: t.start()
    for t in threads: t.join(timeout=3)
    results.sort(key=lambda x: x["port"])
    # Risk assessment
    risks = []
    for r in results:
        if r["port"] == 23:  risks.append({"port":23, "sev":"HIGH",   "msg":"Telnet open — unencrypted"})
        if r["port"] == 21:  risks.append({"port":21, "sev":"MEDIUM", "msg":"FTP open — consider SFTP"})
        if r["port"] == 3389:risks.append({"port":3389,"sev":"HIGH",  "msg":"RDP exposed"})
        if r["port"] == 6379:risks.append({"port":6379,"sev":"CRITICAL","msg":"Redis open — often no auth"})
        if r["port"] == 27017:risks.append({"port":27017,"sev":"CRITICAL","msg":"MongoDB open — often no auth"})
        if r["port"] == 5900:risks.append({"port":5900,"sev":"MEDIUM", "msg":"VNC open"})
    return {"host": host, "alive": True, "hostname": hostname,
            "open_ports": results, "risks": risks, "ts": time.time()}

def _ping(host: str) -> bool:
    try:
        param = "-n" if SYSTEM == "Windows" else "-c"
        r = subprocess.run(["ping", param, "1", "-W", "1", host],
                           capture_output=True, timeout=3)
        return r.returncode == 0
    except:
        try:
            s = socket.create_connection((host, 80), timeout=1); s.close(); return True
        except:
            pass
        try:
            s = socket.create_connection((host, 22), timeout=1); s.close(); return True
        except:
            return False

# ── LAN Discovery ─────────────────────────────────────────────────────────
def discover_lan(subnet: str = None) -> list:
    """Discover live hosts on LAN"""
    if not subnet:
        # Auto-detect local subnet
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            subnet = ".".join(local_ip.split(".")[:3]) + ".0/24"
        except:
            subnet = "192.168.1.0/24"
    try:
        network = ipaddress.IPv4Network(subnet, strict=False)
    except:
        return [{"error": f"Invalid subnet: {subnet}"}]
    hosts_list = list(network.hosts())[:254]
    alive = []
    lock  = threading.Lock()
    def _check(ip):
        if _ping(str(ip)):
            try:
                hostname = socket.gethostbyaddr(str(ip))[0]
            except:
                hostname = ""
            with lock:
                alive.append({"ip": str(ip), "hostname": hostname})
    threads = [threading.Thread(target=_check, args=(ip,), daemon=True) for ip in hosts_list]
    for t in threads: t.start()
    for t in threads: t.join(timeout=5)
    alive.sort(key=lambda x: list(map(int, x["ip"].split("."))))
    return alive

# ── WiFi Networks ──────────────────────────────────────────────────────────
def scan_wifi() -> list:
    """Scan nearby WiFi networks"""
    networks = []
    try:
        if SYSTEM == "Linux":
            r = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,FREQ",
                                "dev", "wifi", "list"], capture_output=True, text=True, timeout=10)
            for line in r.stdout.strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 3:
                    networks.append({
                        "ssid":     parts[0] or "(hidden)",
                        "signal":   parts[1] if len(parts)>1 else "?",
                        "security": parts[2] if len(parts)>2 else "?",
                        "freq":     parts[3] if len(parts)>3 else "?",
                    })
        elif SYSTEM == "Darwin":
            r = subprocess.run(["/System/Library/PrivateFrameworks/Apple80211.framework/"
                                "Versions/Current/Resources/airport", "-s"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if parts:
                    networks.append({"ssid": parts[0], "signal": parts[2] if len(parts)>2 else "?"})
        elif SYSTEM == "Windows":
            r = subprocess.run(["netsh", "wlan", "show", "networks", "mode=bssid"],
                               capture_output=True, text=True, timeout=10)
            current = {}
            for line in r.stdout.split("\n"):
                line = line.strip()
                if line.startswith("SSID"):
                    if current: networks.append(current)
                    current = {"ssid": line.split(":")[-1].strip()}
                elif "Authentication" in line:
                    current["security"] = line.split(":")[-1].strip()
                elif "Signal" in line:
                    current["signal"] = line.split(":")[-1].strip()
            if current: networks.append(current)
    except Exception as e:
        networks.append({"error": str(e)})
    return networks

# ── Nmap wrapper (if installed) ───────────────────────────────────────────
def nmap_scan(target: str, flags: str = "-sV --open -T4") -> dict:
    try:
        r = subprocess.run(["nmap"] + flags.split() + [target],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return {"ok": True, "output": r.stdout[:8000], "target": target}
        return {"ok": False, "error": r.stderr[:500]}
    except FileNotFoundError:
        return {"ok": False, "error": "nmap not installed. Run: sudo apt install nmap"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Vulnerability checks ──────────────────────────────────────────────────
def quick_audit(host: str = "127.0.0.1") -> dict:
    """Quick security audit of a host"""
    result = scan_host(host, list(COMMON_PORTS.keys()))
    score  = 100
    issues = []
    for r in result.get("risks", []):
        if r["sev"] == "CRITICAL": score -= 30; issues.append(r)
        elif r["sev"] == "HIGH":   score -= 20; issues.append(r)
        elif r["sev"] == "MEDIUM": score -= 10; issues.append(r)
    score = max(0, score)
    grade = "A" if score>=90 else "B" if score>=70 else "C" if score>=50 else "F"
    return {**result, "security_score": score, "grade": grade,
            "issues": issues, "recommendation": _rec(grade)}

def _rec(grade: str) -> str:
    recs = {
        "A": "Good security posture. Keep ports minimal.",
        "B": "Minor issues found. Review open ports.",
        "C": "Several issues. Immediate attention needed.",
        "F": "Critical issues! Exposed services need fixing now."
    }
    return recs.get(grade, "")
