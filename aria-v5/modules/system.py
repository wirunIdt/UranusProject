"""modules/system.py — System monitoring: CPU, RAM, GPU, disk, network, processes"""
import os, time, json, subprocess, platform
import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    _NVML = True
except:
    _NVML = False

_NET_LAST = {"t": 0, "s": 0, "r": 0}

def get_cpu():
    pct     = psutil.cpu_percent(interval=0)
    per_core= psutil.cpu_percent(interval=0, percpu=True)
    freq    = psutil.cpu_freq()
    return {
        "percent":   round(pct, 1),
        "count":     psutil.cpu_count(logical=True),
        "physical":  psutil.cpu_count(logical=False),
        "per_core":  [round(c, 1) for c in per_core],
        "freq_mhz":  round(freq.current, 0) if freq else None,
        "freq_max":  round(freq.max, 0) if freq else None,
    }

def get_memory():
    m = psutil.virtual_memory()
    s = psutil.swap_memory()
    return {
        "total":    m.total,
        "used":     m.used,
        "free":     m.available,
        "percent":  round(m.percent, 1),
        "swap_total": s.total,
        "swap_used":  s.used,
        "swap_pct":   round(s.percent, 1),
    }

def get_disk():
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device":     part.device,
                "mountpoint": part.mountpoint,
                "fstype":     part.fstype,
                "total":      u.total,
                "used":       u.used,
                "free":       u.free,
                "percent":    round(u.percent, 1),
            })
        except:
            pass
    # Primary disk
    primary = disks[0] if disks else {}
    return {"primary": primary, "disks": disks}

def get_network():
    global _NET_LAST
    net = psutil.net_io_counters()
    now = time.time()
    dt  = max(now - _NET_LAST["t"], 0.001)
    send_rate = (net.bytes_sent - _NET_LAST["s"]) / dt
    recv_rate = (net.bytes_recv - _NET_LAST["r"]) / dt
    _NET_LAST = {"t": now, "s": net.bytes_sent, "r": net.bytes_recv}

    # Active interfaces
    ifaces = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == 2:  # IPv4
                ifaces.append({"name": name, "ip": a.address})
    local_ip = next((i["ip"] for i in ifaces if not i["ip"].startswith("127.")), "127.0.0.1")

    return {
        "bytes_sent":  net.bytes_sent,
        "bytes_recv":  net.bytes_recv,
        "packets_sent":net.packets_sent,
        "packets_recv":net.packets_recv,
        "send_rate":   round(send_rate),
        "recv_rate":   round(recv_rate),
        "local_ip":    local_ip,
        "interfaces":  ifaces[:8],
    }

def get_gpu():
    if not _NVML:
        # Try AMD via rocm-smi
        try:
            r = subprocess.run(["rocm-smi", "--showuse", "--showmeminfo", "vram", "--json"],
                               capture_output=True, text=True, timeout=3)
            d = json.loads(r.stdout)
            card = list(d.values())[0]
            return {
                "available": True,
                "vendor": "AMD",
                "name": "AMD GPU",
                "util": int(card.get("GPU use (%)", 0)),
                "mem_used": 0,
                "mem_total": 0,
                "temp": 0,
                "driver": "ROCm",
            }
        except:
            return {"available": False}

    try:
        count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes): name = name.decode()
            gpus.append({
                "available": True,
                "vendor": "NVIDIA",
                "name": name,
                "util": util.gpu,
                "mem_used": mem.used // (1024*1024),
                "mem_total": mem.total // (1024*1024),
                "temp": temp,
                "driver": str(pynvml.nvmlSystemGetDriverVersion()),
                "vram_pct": round(mem.used / mem.total * 100, 1),
            })
        return gpus[0] if gpus else {"available": False}
    except:
        return {"available": False}

def get_processes(limit=20):
    procs = []
    for p in psutil.process_iter(["pid","name","cpu_percent","memory_percent","status","create_time","username"]):
        try:
            procs.append({
                "pid":    p.pid,
                "name":   p.name()[:24],
                "cpu_percent": round(p.cpu_percent(), 2),
                "memory_percent": round(p.memory_percent(), 3),
                "status": p.status(),
                "user":   p.username()[:12] if p.username() else "",
            })
        except:
            pass
    procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    return procs[:limit]

def get_uptime():
    boot = psutil.boot_time()
    return {"boot_time": boot, "uptime": time.time() - boot}

def get_full_status(node_id, node_name, local_ip, version, current_model, mesh_peers):
    return {
        "node_id": node_id,
        "node_name": node_name,
        "version": version,
        "model": current_model,
        "mesh_peers": mesh_peers,
        "local_ip": local_ip,
        "cpu": get_cpu(),
        "memory": get_memory(),
        "disk": get_disk()["primary"],
        "network": get_network(),
        "gpu": get_gpu(),
        **get_uptime(),
    }
