"""
ARIA-AGI Intranet Module — Private Internet (War Mode)
Provides: Local DNS, File Server, Chat Relay, HTTP Proxy, mDNS
Use when external internet is cut off
"""
import os, sys, socket, threading, json, time, base64, hashlib
import http.server, socketserver, urllib.request, urllib.error
import logging
from pathlib import Path

log = logging.getLogger("ARIA.Intranet")

# ─── mDNS / Service Discovery ──────────────────────────────────────────────
MDNS_GROUP = "224.0.0.251"
MDNS_PORT  = 5353
ARIA_PORT  = 47778  # Intranet multicast port

class IntranetNode:
    def __init__(self, node_id, node_name, local_ip, web_port=5000):
        self.node_id   = node_id
        self.node_name = node_name
        self.local_ip  = local_ip
        self.web_port  = web_port
        self.running   = False
        self.peers     = {}   # node_id -> info dict
        self.dns_map   = {}   # hostname -> ip
        self.services  = {}   # service_name -> {ip, port, desc}
        self.chat_log  = []   # local chat history
        self._threads  = []

        # Auto-register self in DNS
        self.dns_map[node_name.lower() + ".aria"] = local_ip
        self.dns_map["self.aria"] = local_ip

    def start(self):
        self.running = True
        for target in [
            self._announce_loop,
            self._listen_loop,
            self._dns_server,
            self._file_server,
        ]:
            t = threading.Thread(target=target, daemon=True, name=target.__name__)
            t.start()
            self._threads.append(t)
        log.info(f"Intranet started — IP:{self.local_ip} DNS:.aria / Files:port 47780")

    def stop(self):
        self.running = False

    # ── Announce presence via UDP multicast ──────────────────────────────
    def _announce_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        while self.running:
            try:
                payload = json.dumps({
                    "type":      "ARIA_INTRANET",
                    "node_id":   self.node_id,
                    "name":      self.node_name,
                    "ip":        self.local_ip,
                    "web_port":  self.web_port,
                    "services":  self.services,
                    "ts":        time.time(),
                }).encode()
                sock.sendto(payload, (MDNS_GROUP, ARIA_PORT))
            except Exception as e:
                log.debug(f"announce error: {e}")
            time.sleep(10)
        sock.close()

    # ── Listen for peer announcements ────────────────────────────────────
    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        sock.bind(("0.0.0.0", ARIA_PORT))
        mreq = socket.inet_aton(MDNS_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(2)
        while self.running:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode())
                if msg.get("type") == "ARIA_INTRANET" and msg.get("node_id") != self.node_id:
                    nid  = msg["node_id"]
                    name = msg["name"]
                    ip   = msg["ip"]
                    self.peers[nid] = {**msg, "last_seen": time.time()}
                    # Auto-add to DNS
                    self.dns_map[name.lower() + ".aria"] = ip
                    # Register their services
                    for svc_name, svc_info in msg.get("services",{}).items():
                        self.services[svc_name] = {**svc_info, "from": name}
            except socket.timeout:
                pass
            except Exception as e:
                log.debug(f"listen error: {e}")
        sock.close()

    # ── Simple DNS responder (UDP port 53) ───────────────────────────────
    def _dns_server(self):
        """
        Minimal DNS server: answers A queries for *.aria domains.
        Forwards unknown queries to upstream (8.8.8.8) if available,
        returns NXDOMAIN if offline.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", 5354))  # Use 5354 (not 53) to avoid root requirement
            sock.settimeout(2)
            log.info("DNS responder on UDP 5354")
        except Exception as e:
            log.warning(f"DNS server failed to bind: {e}")
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(512)
                # Parse DNS query (minimal)
                tid    = data[:2]
                qdcount= int.from_bytes(data[4:6], 'big')
                # Extract first question name
                name_parts = []
                pos = 12
                while pos < len(data):
                    length = data[pos]
                    if length == 0:
                        pos += 1
                        break
                    name_parts.append(data[pos+1:pos+1+length].decode('ascii', errors='replace'))
                    pos += 1 + length
                hostname = ".".join(name_parts).lower()

                resolved_ip = None
                if hostname in self.dns_map:
                    resolved_ip = self.dns_map[hostname]
                elif hostname.endswith(".aria"):
                    # Try partial match
                    for k, v in self.dns_map.items():
                        if hostname == k:
                            resolved_ip = v
                            break

                if resolved_ip:
                    # Build DNS A response
                    flags   = b'\x81\x80'  # QR=1 AA=1
                    counts  = b'\x00\x01\x00\x01\x00\x00\x00\x00'
                    # Question section (echo)
                    question = data[12:pos+4]  # name + type + class
                    # Answer section
                    ip_bytes = socket.inet_aton(resolved_ip)
                    answer   = (b'\xc0\x0c'        # pointer to name
                               + b'\x00\x01'       # type A
                               + b'\x00\x01'       # class IN
                               + b'\x00\x00\x00\x3c'  # TTL 60s
                               + b'\x00\x04'       # rdlength
                               + ip_bytes)
                    response = tid + flags + counts + question + answer
                else:
                    # NXDOMAIN
                    flags   = b'\x81\x83'
                    response = tid + flags + b'\x00\x01\x00\x00\x00\x00\x00\x00' + data[12:]

                sock.sendto(response, addr)
            except socket.timeout:
                pass
            except Exception as e:
                log.debug(f"DNS error: {e}")
        sock.close()

    # ── File Server (HTTP) ────────────────────────────────────────────────
    def _file_server(self):
        """Serve files from ./intranet_share/ directory on port 47780"""
        share_dir = Path("intranet_share")
        share_dir.mkdir(exist_ok=True)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(share_dir), **kwargs)

            def log_message(self, fmt, *args):
                pass  # Suppress HTTP logs

        try:
            with socketserver.TCPServer(("0.0.0.0", 47780), Handler) as httpd:
                httpd.timeout = 2
                log.info("File server on port 47780 → ./intranet_share/")
                while self.running:
                    httpd.handle_request()
        except Exception as e:
            log.warning(f"File server failed: {e}")

    # ── DNS Map Management ────────────────────────────────────────────────
    def add_dns(self, hostname, ip):
        h = hostname.lower()
        if not h.endswith(".aria"):
            h += ".aria"
        self.dns_map[h] = ip

    def remove_dns(self, hostname):
        self.dns_map.pop(hostname.lower(), None)

    def get_dns_map(self):
        return dict(self.dns_map)

    # ── Service Registry ──────────────────────────────────────────────────
    def register_service(self, name, port, desc=""):
        self.services[name] = {
            "name": name,
            "ip":   self.local_ip,
            "port": port,
            "desc": desc,
            "from": self.node_name,
        }

    def get_services(self):
        return dict(self.services)

    # ── Peer Info ─────────────────────────────────────────────────────────
    def get_peers(self):
        now = time.time()
        return {k: v for k, v in self.peers.items()
                if now - v.get("last_seen", 0) < 60}

    # ── DNS Resolve ───────────────────────────────────────────────────────
    def resolve(self, hostname):
        h = hostname.lower()
        if not h.endswith(".aria"):
            h += ".aria"
        return self.dns_map.get(h)

    # ── HTTP Proxy ────────────────────────────────────────────────────────
    def proxy_request(self, url, timeout=10):
        """
        Attempt to fetch URL. Falls back gracefully if offline.
        Returns (content, from_cache, error)
        """
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ARIA-Intranet/3.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(errors="replace"), False, None
        except urllib.error.URLError as e:
            return None, False, f"Offline or unreachable: {e.reason}"
        except Exception as e:
            return None, False, str(e)


# ── Singleton Instance ────────────────────────────────────────────────────
_intranet: IntranetNode = None

def get_intranet() -> IntranetNode:
    return _intranet

def init_intranet(node_id, node_name, local_ip, web_port=5000):
    global _intranet
    _intranet = IntranetNode(node_id, node_name, local_ip, web_port)
    _intranet.start()
    return _intranet
