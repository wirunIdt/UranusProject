"""modules/iot.py — IoT Device Control: ESP32/MQTT/HTTP/Sensor"""
import os, json, time, threading, socket, logging
import requests

log = logging.getLogger("ARIA.IoT")

# ── Device Registry ───────────────────────────────────────────────────────
_devices: dict = {}   # id → device config
_LOCK = threading.Lock()
_sensor_history: dict = {}  # id → list of readings

MQTT_BROKER = os.environ.get("MQTT_BROKER", "")
MQTT_PORT   = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USER   = os.environ.get("MQTT_USER", "")
MQTT_PASS   = os.environ.get("MQTT_PASS", "")

# Try MQTT
_mqtt_client = None
try:
    import paho.mqtt.client as mqtt
    _HAS_MQTT = True
except ImportError:
    _HAS_MQTT = False

def _init_mqtt():
    global _mqtt_client
    if not _HAS_MQTT or not MQTT_BROKER:
        return
    try:
        _mqtt_client = mqtt.Client(client_id=f"aria-iot-{os.getpid()}")
        if MQTT_USER:
            _mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
        _mqtt_client.on_message = _on_mqtt_message
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        _mqtt_client.loop_start()
        log.info(f"MQTT connected: {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        log.warning(f"MQTT connect failed: {e}")

def _on_mqtt_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode())
    except:
        payload = msg.payload.decode()
    # Find device by topic
    with _LOCK:
        for dev_id, dev in _devices.items():
            if dev.get("mqtt_topic_sub") == topic:
                if dev_id not in _sensor_history:
                    _sensor_history[dev_id] = []
                _sensor_history[dev_id].append({"ts": time.time(), "data": payload})
                _sensor_history[dev_id] = _sensor_history[dev_id][-100:]
                dev["last_seen"] = time.time()
                dev["last_data"] = payload

# ── Device Management ──────────────────────────────────────────────────────
def register_device(dev_id: str, name: str, ip: str = "", port: int = 80,
                    dev_type: str = "esp32", protocol: str = "http",
                    mqtt_topic: str = "", capabilities: list = None) -> dict:
    with _LOCK:
        _devices[dev_id] = {
            "id": dev_id, "name": name, "ip": ip, "port": port,
            "type": dev_type, "protocol": protocol,
            "mqtt_topic_pub": mqtt_topic or f"aria/{dev_id}/cmd",
            "mqtt_topic_sub": f"aria/{dev_id}/data",
            "capabilities": capabilities or ["on_off"],
            "status": "unknown", "last_seen": 0, "last_data": None,
            "registered": time.time(),
        }
    # Subscribe to sensor topic
    if _mqtt_client and mqtt_topic:
        _mqtt_client.subscribe(f"aria/{dev_id}/data")
    log.info(f"Device registered: {dev_id} ({name}) @ {ip}:{port}")
    return _devices[dev_id]

def list_devices() -> list:
    with _LOCK:
        return list(_devices.values())

def get_device(dev_id: str) -> dict:
    with _LOCK:
        return _devices.get(dev_id)

def remove_device(dev_id: str):
    with _LOCK:
        _devices.pop(dev_id, None)

# ── Commands ───────────────────────────────────────────────────────────────
def send_command(dev_id: str, command: str, params: dict = None) -> dict:
    dev = get_device(dev_id)
    if not dev:
        return {"ok": False, "error": f"Device {dev_id} not found"}
    proto = dev.get("protocol", "http")
    if proto == "mqtt":
        return _mqtt_cmd(dev, command, params or {})
    else:
        return _http_cmd(dev, command, params or {})

def _http_cmd(dev: dict, command: str, params: dict) -> dict:
    """Send HTTP command to ESP32 or similar"""
    ip, port = dev["ip"], dev.get("port", 80)
    if not ip:
        return {"ok": False, "error": "Device has no IP"}
    # Standard REST endpoints for ESP32
    endpoints = {
        "on":      f"http://{ip}:{port}/on",
        "off":     f"http://{ip}:{port}/off",
        "toggle":  f"http://{ip}:{port}/toggle",
        "status":  f"http://{ip}:{port}/status",
        "read":    f"http://{ip}:{port}/sensor",
        "set":     f"http://{ip}:{port}/set",
        "custom":  f"http://{ip}:{port}/{params.get('path','cmd')}",
    }
    url = endpoints.get(command, f"http://{ip}:{port}/{command}")
    try:
        if params and command not in ("on","off","toggle","status","read"):
            r = requests.post(url, json=params, timeout=5)
        else:
            r = requests.get(url, params=params, timeout=5)
        try:
            data = r.json()
        except:
            data = {"raw": r.text[:200]}
        dev["last_seen"] = time.time()
        dev["status"] = "online"
        return {"ok": True, "device": dev_id, "command": command,
                "response": data, "status_code": r.status_code}
    except requests.exceptions.ConnectTimeout:
        dev["status"] = "timeout"
        return {"ok": False, "error": "Device timeout", "device": dev_id}
    except requests.exceptions.ConnectionError:
        dev["status"] = "offline"
        return {"ok": False, "error": "Device offline", "device": dev_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _mqtt_cmd(dev: dict, command: str, params: dict) -> dict:
    if not _mqtt_client:
        return {"ok": False, "error": "MQTT not connected"}
    topic = dev.get("mqtt_topic_pub", f"aria/{dev['id']}/cmd")
    payload = json.dumps({"cmd": command, **params})
    try:
        result = _mqtt_client.publish(topic, payload, qos=1)
        return {"ok": True, "device": dev["id"], "command": command,
                "topic": topic, "mid": result.mid}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ping_device(dev_id: str) -> dict:
    dev = get_device(dev_id)
    if not dev: return {"ok": False, "error": "Not found"}
    if dev.get("protocol") == "mqtt":
        elapsed = time.time() - dev.get("last_seen", 0)
        alive = elapsed < 60
        return {"ok": alive, "device": dev_id, "last_seen_s": round(elapsed)}
    # HTTP ping
    ip = dev.get("ip")
    if not ip: return {"ok": False, "error": "No IP"}
    try:
        t0 = time.time()
        r = requests.get(f"http://{ip}:{dev.get('port',80)}/status", timeout=3)
        ms = round((time.time()-t0)*1000)
        dev["status"] = "online"; dev["last_seen"] = time.time()
        return {"ok": True, "device": dev_id, "ms": ms, "status": r.status_code}
    except:
        dev["status"] = "offline"
        return {"ok": False, "device": dev_id, "status": "offline"}

def read_sensor(dev_id: str) -> dict:
    return send_command(dev_id, "read")

def get_sensor_history(dev_id: str, limit: int = 50) -> list:
    with _LOCK:
        return _sensor_history.get(dev_id, [])[-limit:]

def broadcast_command(command: str, device_type: str = None) -> list:
    """Send command to all devices (optionally filtered by type)"""
    results = []
    devs = list_devices()
    if device_type:
        devs = [d for d in devs if d.get("type") == device_type]
    for dev in devs:
        r = send_command(dev["id"], command)
        results.append(r)
    return results

# ── ESP32 Template Code ────────────────────────────────────────────────────
ESP32_TEMPLATE = '''
// ESP32 Arduino template for ARIA integration
// Flash this to your ESP32

#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>

const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASS";
const char* aria_ip = "YOUR_ARIA_IP";  // e.g. 192.168.1.100
const int aria_port = 5000;
const char* device_id = "esp32_1";
const char* device_name = "My ESP32";

WebServer server(80);

// Register with ARIA on boot
void registerWithARIA() {
  HTTPClient http;
  String url = "http://" + String(aria_ip) + ":" + String(aria_port) + "/api/iot/register";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  String body = "{\\"id\\":\\"" + String(device_id) + "\\",\\"name\\":\\"" + 
                String(device_name) + "\\",\\"ip\\":\\"" + WiFi.localIP().toString() + 
                "\\",\\"type\\":\\"esp32\\",\\"capabilities\\":[\\"on_off\\",\\"sensor\\"]}";
  int code = http.POST(body);
  http.end();
}

// Route handlers
void handleOn()     { digitalWrite(LED_BUILTIN, HIGH); server.send(200, "application/json", "{\\"ok\\":true,\\"state\\":\\"on\\"}"); }
void handleOff()    { digitalWrite(LED_BUILTIN, LOW);  server.send(200, "application/json", "{\\"ok\\":true,\\"state\\":\\"off\\"}"); }
void handleStatus() { 
  int state = digitalRead(LED_BUILTIN);
  String json = "{\\"ok\\":true,\\"state\\":\\"" + String(state?"on":"off") + "\\",\\"uptime\\":" + String(millis()) + "}";
  server.send(200, "application/json", json);
}
void handleSensor() {
  float temp = 25.0; // Replace with actual sensor read
  String json = "{\\"ok\\":true,\\"temp\\":" + String(temp) + ",\\"ts\\":" + String(millis()) + "}";
  server.send(200, "application/json", json);
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  WiFi.begin(ssid, password);
  while(WiFi.status() != WL_CONNECTED) delay(500);
  server.on("/on",     handleOn);
  server.on("/off",    handleOff);
  server.on("/status", handleStatus);
  server.on("/sensor", handleSensor);
  server.begin();
  registerWithARIA();
}

void loop() { server.handleClient(); }
'''

def get_esp32_template() -> str:
    return ESP32_TEMPLATE

_init_mqtt()
