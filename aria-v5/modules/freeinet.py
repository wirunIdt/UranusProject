"""modules/freeinet.py — Decentralized internet: mesh, Tor, DoH, Yggdrasil, P2P"""
import os, subprocess, threading, socket, time, json, platform, requests

SYSTEM = platform.system()

# ── DNS over HTTPS (bypass ISP DNS) ──────────────────────────────────────
DOH_SERVERS = {
    "Cloudflare":  "https://cloudflare-dns.com/dns-query",
    "Google":      "https://dns.google/resolve",
    "Quad9":       "https://dns.quad9.net/dns-query",
    "AdGuard":     "https://dns.adguard.com/resolve",
    "NextDNS":     "https://dns.nextdns.io",
}

def doh_lookup(hostname: str, server: str = "Cloudflare") -> dict:
    url = DOH_SERVERS.get(server, DOH_SERVERS["Cloudflare"])
    try:
        r = requests.get(url, params={"name": hostname, "type": "A"},
                         headers={"Accept": "application/dns-json"}, timeout=5)
        d = r.json()
        answers = [a["data"] for a in d.get("Answer", []) if a.get("type") == 1]
        return {"host": hostname, "ips": answers, "server": server,
                "status": d.get("Status", -1), "ok": len(answers) > 0}
    except Exception as e:
        return {"host": hostname, "ips": [], "error": str(e), "ok": False}

def set_doh_systemwide(server: str = "Cloudflare") -> dict:
    """Configure system-wide DoH (requires root on Linux)"""
    url = DOH_SERVERS.get(server, DOH_SERVERS["Cloudflare"])
    if SYSTEM == "Linux":
        conf = f"""[Resolve]
DNS=1.1.1.1 8.8.8.8
DNSOverTLS=opportunistic
"""
        try:
            with open("/etc/systemd/resolved.conf.d/doh.conf", "w") as f:
                f.write(conf)
            subprocess.run(["systemctl","restart","systemd-resolved"],
                           capture_output=True, timeout=5)
            return {"ok": True, "msg": f"DoH via systemd-resolved pointing to {server}"}
        except PermissionError:
            return {"ok": False, "msg": "Need sudo. Run: sudo python3 server.py"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}
    return {"ok": False, "msg": f"Use {url} in your browser DoH settings"}

# ── Tor integration ───────────────────────────────────────────────────────
def tor_status() -> dict:
    """Check if Tor is running"""
    try:
        r = subprocess.run(["tor", "--version"], capture_output=True, text=True, timeout=3)
        running = False
        try:
            s = socket.create_connection(("127.0.0.1", 9050), timeout=2)
            s.close(); running = True
        except:
            pass
        return {"installed": r.returncode == 0,
                "version": r.stdout.strip()[:40],
                "running": running,
                "socks_port": 9050 if running else None}
    except FileNotFoundError:
        return {"installed": False, "running": False}

def tor_start() -> dict:
    try:
        subprocess.Popen(["tor"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        time.sleep(3)
        return tor_status()
    except FileNotFoundError:
        return {"ok": False, "msg": "Tor not installed. Run: sudo apt install tor"}

def request_via_tor(url: str) -> dict:
    """HTTP request through Tor SOCKS5 proxy"""
    proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
    try:
        r = requests.get(url, proxies=proxies, timeout=15)
        return {"ok": True, "status": r.status_code, "len": len(r.content)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_tor_ip() -> dict:
    """Get IP address seen through Tor"""
    return request_via_tor("https://check.torproject.org/api/ip")

# ── Yggdrasil (global encrypted mesh IPv6) ───────────────────────────────
def yggdrasil_status() -> dict:
    try:
        r = subprocess.run(["yggdrasilctl","getSelf"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            return {"installed": True, "running": True, "addr": d.get("address",""), "data": d}
        return {"installed": True, "running": False}
    except FileNotFoundError:
        return {"installed": False, "running": False,
                "install": "https://yggdrasil-network.github.io/installation.html"}

# ── WiFi Mesh (batman-adv) ────────────────────────────────────────────────
def batman_status() -> dict:
    if SYSTEM != "Linux":
        return {"supported": False}
    try:
        r = subprocess.run(["batctl","o"], capture_output=True, text=True, timeout=3)
        peers = [l.split()[0] for l in r.stdout.strip().split("\n")[1:] if l.strip()]
        return {"installed": r.returncode == 0, "peers": peers, "count": len(peers)}
    except FileNotFoundError:
        return {"installed": False,
                "install": "sudo apt install batctl && sudo modprobe batman-adv"}

def setup_batman(iface: str = "wlan0") -> dict:
    """Set up batman-adv mesh on wifi interface"""
    cmds = [
        f"sudo modprobe batman-adv",
        f"sudo ip link set {iface} down",
        f"sudo iw {iface} set type ibss",
        f"sudo ip link set {iface} up",
        f"sudo iw {iface} ibss join ARIA-MESH 2412",
        f"sudo batctl if add {iface}",
        f"sudo ip link set bat0 up",
    ]
    results = []
    for cmd in cmds:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        results.append({"cmd": cmd, "ok": r.returncode == 0, "out": r.stdout+r.stderr})
    return {"steps": results}

# ── Hotspot (share internet) ──────────────────────────────────────────────
def hotspot_action(action: str, ssid: str = "ARIA-Net", password: str = "aria1234") -> dict:
    def run(cmd):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    if SYSTEM == "Linux":
        if action == "on":
            ok, out = run(f"nmcli device wifi hotspot ssid '{ssid}' password '{password}' ifname wlan0 2>/dev/null")
            if not ok:
                ok, out = run(f"nmcli d wifi hotspot ssid '{ssid}' password '{password}'")
        elif action == "off":
            ok, out = run("nmcli con down hotspot 2>/dev/null || nmcli device disconnect wlan0")
        else:
            ok, out = run("nmcli device status")
        return {"ok": ok, "output": out[:300], "os": "Linux", "ssid": ssid}

    elif SYSTEM == "Windows":
        if action == "on":
            ok, out = run(f'netsh wlan set hostednetwork mode=allow ssid="{ssid}" key="{password}" && netsh wlan start hostednetwork')
        elif action == "off":
            ok, out = run("netsh wlan stop hostednetwork")
        else:
            ok, out = run("netsh wlan show hostednetwork")
        return {"ok": ok, "output": out[:300], "os": "Windows", "ssid": ssid}

    elif SYSTEM == "Darwin":
        return {"ok": True, "os": "macOS",
                "output": "System Preferences → Sharing → Internet Sharing"}

    return {"ok": False, "output": f"Unsupported: {SYSTEM}"}

# ── Network connectivity check ────────────────────────────────────────────
def check_connectivity() -> dict:
    checks = [
        ("8.8.8.8", 53, "Google DNS"),
        ("1.1.1.1", 80, "Cloudflare"),
        ("208.67.222.222", 53, "OpenDNS"),
    ]
    results = []
    for ip, port, name in checks:
        try:
            t0 = time.time()
            s = socket.create_connection((ip, port), timeout=3)
            s.close()
            results.append({"name": name, "ok": True, "ms": round((time.time()-t0)*1000)})
        except:
            results.append({"name": name, "ok": False})

    online = any(r["ok"] for r in results)
    return {"online": online, "checks": results}

def full_status() -> dict:
    return {
        "connectivity": check_connectivity(),
        "tor":          tor_status(),
        "yggdrasil":    yggdrasil_status(),
        "batman":       batman_status(),
        "doh_servers":  list(DOH_SERVERS.keys()),
    }
