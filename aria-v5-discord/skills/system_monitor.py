"""
System Monitor — Real-time stats
Uses psutil (pip install psutil) with fallback to subprocess
"""
import platform, subprocess, time, os
from pathlib import Path

SYSTEM = platform.system()

def _try_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None

def get_cpu() -> dict:
    ps = _try_psutil()
    if ps:
        try:
            per_core = ps.cpu_percent(interval=0.1, percpu=True)
            freq = ps.cpu_freq()
            return {
                "total":   round(ps.cpu_percent(interval=0), 1),
                "cores":   [round(c, 1) for c in per_core],
                "count":   ps.cpu_count(logical=True),
                "freq_mhz": round(freq.current) if freq else 0,
            }
        except: pass
    return {"total": 0, "cores": [], "count": 0, "freq_mhz": 0}

def get_memory() -> dict:
    ps = _try_psutil()
    if ps:
        try:
            m = ps.virtual_memory()
            s = ps.swap_memory()
            return {
                "total_gb":  round(m.total / 1e9, 1),
                "used_gb":   round(m.used  / 1e9, 1),
                "free_gb":   round(m.available / 1e9, 1),
                "percent":   m.percent,
                "swap_gb":   round(s.used / 1e9, 1),
                "swap_pct":  s.percent,
            }
        except: pass
    return {"total_gb":0,"used_gb":0,"free_gb":0,"percent":0,"swap_gb":0,"swap_pct":0}

def get_disk() -> list[dict]:
    ps = _try_psutil()
    results = []
    if ps:
        try:
            for part in ps.disk_partitions():
                try:
                    u = ps.disk_usage(part.mountpoint)
                    results.append({
                        "device":     part.device,
                        "mount":      part.mountpoint,
                        "fstype":     part.fstype,
                        "total_gb":   round(u.total / 1e9, 1),
                        "used_gb":    round(u.used  / 1e9, 1),
                        "free_gb":    round(u.free  / 1e9, 1),
                        "percent":    u.percent,
                    })
                except: pass
        except: pass
    return results[:4]

def get_network() -> dict:
    ps = _try_psutil()
    if ps:
        try:
            n = ps.net_io_counters()
            # Get per-interface
            ifaces = []
            for name, stats in ps.net_if_stats().items():
                if stats.isup and name not in ("lo","Loopback"):
                    ifaces.append({"name": name, "speed_mb": stats.speed})
            return {
                "sent_mb":   round(n.bytes_sent  / 1e6, 1),
                "recv_mb":   round(n.bytes_recv  / 1e6, 1),
                "packets_sent": n.packets_sent,
                "packets_recv": n.packets_recv,
                "interfaces": ifaces[:4],
            }
        except: pass
    return {"sent_mb":0,"recv_mb":0,"packets_sent":0,"packets_recv":0,"interfaces":[]}

def get_processes(limit: int = 10) -> list[dict]:
    ps = _try_psutil()
    if ps:
        try:
            procs = []
            for p in ps.process_iter(["pid","name","cpu_percent","memory_percent","status"]):
                try:
                    procs.append({
                        "pid":    p.info["pid"],
                        "name":   p.info["name"],
                        "cpu":    round(p.info["cpu_percent"] or 0, 1),
                        "mem":    round(p.info["memory_percent"] or 0, 1),
                        "status": p.info["status"],
                    })
                except: pass
            procs.sort(key=lambda x: x["cpu"], reverse=True)
            return procs[:limit]
        except: pass
    return []

def get_gpu() -> dict:
    """Try to get GPU info via nvidia-smi."""
    try:
        r = subprocess.run(
            ["nvidia-smi","--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            if len(parts) >= 5:
                return {
                    "name":    parts[0],
                    "temp_c":  int(parts[1]),
                    "util_pct":int(parts[2]),
                    "mem_used_mb": int(parts[3]),
                    "mem_total_mb":int(parts[4]),
                    "available": True,
                }
    except: pass
    return {"available": False}

def get_all_stats() -> dict:
    return {
        "cpu":       get_cpu(),
        "memory":    get_memory(),
        "disk":      get_disk(),
        "network":   get_network(),
        "gpu":       get_gpu(),
        "processes": get_processes(10),
        "platform":  platform.platform(),
        "uptime_s":  int(time.time() - _boot_time()),
        "python":    platform.python_version(),
    }

def _boot_time() -> float:
    ps = _try_psutil()
    if ps:
        try: return ps.boot_time()
        except: pass
    return time.time()
