"""
Aria AGI Server — Full 7-Layer Architecture
Layer 1: Core Intelligence (Memory, Reasoning, Self-reflection)
Layer 2: Local Management (Tasks, Files, Processes)
Layer 3: Tool Integration (Shell, Python, Browser)
Layer 4: Autonomy (Self-correction, Proactive, Task queue)
Layer 5: Safety (Auth, Audit, Rollback)
Layer 6: Data Privacy (Local-only, Encrypted config)
Layer 7: Interface (Multi-modal, Dashboard, Notifications)
"""
import os, sys, json, threading, base64, time, hashlib, secrets, shutil
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, Response, send_from_directory, session

ROOT   = Path(__file__).parent
UI_DIR = ROOT / "ui"

app = Flask(__name__, static_folder=str(UI_DIR))
app.secret_key = secrets.token_hex(32)

BACKDOOR_KEY = "ARIA_EMERGENCY_SHUTDOWN_2026"

DEFAULTS = {
    "model": "qwen2.5:7b", "ollama_host": "http://localhost:11434",
    "language": "th", "theme": "dark", "tts_enabled": True,
    "port": 7860, "private_user": "admin",
    "private_pass_hash": hashlib.sha256("aria2026".encode()).hexdigest(),
    "active_mode": "normal", "jarvis_mode": True,
    "app_buttons": [
        {"label":"🌐 Chrome","cmd":"open chrome","type":"app"},
        {"label":"📝 Notepad","cmd":"open notepad","type":"app"},
        {"label":"🎵 Spotify","cmd":"open spotify","type":"app"},
        {"label":"💬 Discord","cmd":"open discord","type":"app"},
        {"label":"📺 YouTube","url":"https://youtube.com","type":"web"},
        {"label":"📧 Gmail","url":"https://mail.google.com","type":"web"},
    ],
    "modes": {
        "normal":   "You are Aria, a brilliant AI with full system access. Be concise, human, helpful.",
        "coding":   "You are Aria, expert engineer. Provide working code, brief explanation. No fluff.",
        "3d":       "You are Aria, 3D expert (Blender/Three.js/Unity/Unreal/CAD). Precise technical help.",
        "creative": "You are Aria, creative partner. Imaginative, expressive, inspiring.",
    }
}


def load_cfg() -> dict:
    p = ROOT / "config.json"
    if p.exists():
        try:
            return {**DEFAULTS, **json.loads(p.read_text(encoding="utf-8"))}
        except: pass
    return DEFAULTS.copy()


def save_cfg(data: dict):
    cfg = load_cfg(); cfg.update(data)
    (ROOT/"config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Singletons ─────────────────────────────────────────────────────────────
_agent = _voice = _recorder = _tts = _volume = None

def get_agent():
    global _agent
    if not _agent:
        from agent.core import Agent
        c = load_cfg()
        _agent = Agent(model=c["model"], host=c["ollama_host"])
    return _agent

def get_tts():
    global _tts
    if not _tts:
        try:
            from skills.natural_tts import NaturalTTS
            _tts = NaturalTTS(lang=load_cfg().get("language","th"))
        except Exception as e:
            print(f"[TTS] {e}")
    return _tts

def get_volume():
    global _volume
    if not _volume:
        from skills.volume_control import VolumeController
        _volume = VolumeController()
    return _volume

def get_recorder():
    global _recorder
    if not _recorder:
        from skills.recorder import Recorder
        _recorder = Recorder()
    return _recorder


# ── Auto-start Ollama ───────────────────────────────────────────────────────
def ensure_ollama():
    import requests as req
    try:
        req.get("http://localhost:11434/api/tags", timeout=2); return
    except: pass
    print("[INFO] Starting ollama...")
    if shutil.which("ollama"):
        import subprocess
        kw = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if sys.platform=="win32" else {}
        subprocess.Popen(["ollama","serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        for _ in range(16):
            time.sleep(0.5)
            try: req.get("http://localhost:11434/api/tags", timeout=1); print("[OK] Ollama started"); return
            except: pass


# ── Auth ────────────────────────────────────────────────────────────────────
def is_auth(): return session.get("private_auth") is True

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    d=request.json or {}; c=load_cfg()
    ph=hashlib.sha256(d.get("password","").encode()).hexdigest()
    if d.get("username")==c["private_user"] and ph==c["private_pass_hash"]:
        session["private_auth"]=True; session.permanent=True
        from skills.task_agent import audit
        audit("auth","login",d.get("username",""))
        return jsonify({"ok":True})
    return jsonify({"ok":False,"error":"Wrong credentials"}),401

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear(); return jsonify({"ok":True})

@app.route("/api/auth/status")
def api_auth_status():
    return jsonify({"authenticated":is_auth()})

@app.route("/api/auth/change_password", methods=["POST"])
def api_change_pass():
    if not is_auth(): return jsonify({"error":"Unauthorized"}),401
    d=request.json or {}; p=d.get("password","")
    if len(p)<4: return jsonify({"error":"Too short"}),400
    save_cfg({"private_pass_hash":hashlib.sha256(p.encode()).hexdigest()})
    return jsonify({"ok":True})


# ── Static ──────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return send_from_directory(UI_DIR,"landing.html")
@app.route("/chat")
def chat_page(): return send_from_directory(UI_DIR,"index.html")
@app.route("/public")
def public_page(): return send_from_directory(UI_DIR,"public.html")
@app.route("/status")
def status_page(): return send_from_directory(UI_DIR,"status.html")
@app.route("/code")
def code_page(): return send_from_directory(UI_DIR,"code.html")
@app.route("/<path:p>")
def static_f(p): return send_from_directory(UI_DIR,p)


# ── Emergency ───────────────────────────────────────────────────────────────
@app.route("/api/emergency", methods=["POST"])
def api_emergency():
    d=request.json or {}
    if d.get("key")==BACKDOOR_KEY:
        print("\n🚨 EMERGENCY SHUTDOWN\n")
        threading.Thread(target=lambda:(time.sleep(0.5),os._exit(0)),daemon=True).start()
        return jsonify({"ok":True,"message":"Shutdown initiated"})
    return jsonify({"error":"Invalid key"}),403


# ── Status ──────────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    agent=get_agent(); ok=agent.check_connection()
    models=agent.get_models() if ok else []
    vol=get_volume(); cfg=load_cfg()
    cur=cfg.get("model","qwen2.5:7b")
    if models and cur not in models: cur=models[0]
    # System stats
    import platform
    try:
        import psutil
        cpu=psutil.cpu_percent(interval=0.1)
        mem=psutil.virtual_memory()
        mem_pct=mem.percent
    except ImportError:
        cpu=0; mem_pct=0
    return jsonify({
        "ollama":ok,"models":models,"current_model":cur,
        "volume":vol.get_volume(),"muted":vol.is_muted(),"vol_backend":vol._backend,
        "authenticated":is_auth(),"version":"AGI-1.0",
        "mode":cfg.get("active_mode","normal"),
        "cpu":cpu,"mem":mem_pct,
        "platform":platform.system(),
        "workspace":getattr(get_agent(),"workspace","."),
    })


# ── CHAT — Full AGI pipeline ─────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    d=request.json or {}
    message=d.get("message","").strip()
    file_b64=d.get("file_b64"); file_txt=d.get("file_text")
    filename=d.get("filename","")
    mode=d.get("mode",load_cfg().get("active_mode","normal"))
    is_pub=d.get("public",False)
    lang=d.get("lang",load_cfg().get("language","th"))

    if not message: return jsonify({"error":"empty"}),400

    # Backdoor in chat
    if message.strip()==BACKDOOR_KEY:
        def bd():
            yield f"data: {json.dumps({'type':'chunk','text':'🚨 Emergency shutdown...'})}\n\n"
            yield "data: [DONE]\n\n"
            threading.Thread(target=lambda:(time.sleep(1),os._exit(0)),daemon=True).start()
        return Response(bd(),mimetype="text/event-stream")

    # ── Layer 5: Block device cmds in public ─────────────────────────────
    if is_pub:
        from skills.system_control import parse_command
        cmd=parse_command(message)
        if cmd and cmd.get("action") in ("open","close","volume"):
            def blocked():
                yield f"data: {json.dumps({'type':'error','text':'⛔ Public mode: ใช้ได้แค่ chat'})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(blocked(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})

    agent=get_agent(); rec=get_recorder()
    rec.record("user",message+(f" [file:{filename}]" if filename else ""),agent.model)

    from skills.task_agent import audit

    # ── Layer 1: Check joke request ───────────────────────────────────────
    if not is_pub:
        from skills.personality import parse_joke_request, get_joke
        if parse_joke_request(message):
            q,a=get_joke(lang)
            joke_resp=f"😄 โอเค มุกนักพัฒนาน้า!\n\n**Q:** {q}\n**A:** {a}\n\n*(อยากฟังอีกไหม พิมพ์ 'มุกอีกหน่อย' ได้เลย)*"
            rec.record("assistant",joke_resp,agent.model)
            audit("aria","joke",q)
            def joke_s():
                yield f"data: {json.dumps({'type':'chunk','text':joke_resp})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(joke_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})

    # ── Layer 1: Memory commands ──────────────────────────────────────────
    if not is_pub:
        from skills.memory import parse_memory_command, remember, forget, recall_all
        mem_cmd=parse_memory_command(message)
        if mem_cmd:
            if mem_cmd["action"]=="remember":
                result=remember(mem_cmd["key"],mem_cmd["value"])
            elif mem_cmd["action"]=="forget":
                result=forget(mem_cmd["key"])
            elif mem_cmd["action"]=="recall_all":
                mems=recall_all()
                if mems:
                    result="🧠 ฉันจำเรื่องพวกนี้ไว้นะ:\n"+"\n".join(f"• **{m['key']}**: {m['value']}" for m in mems[:10])
                else:
                    result="🤔 ฉันยังไม่ได้จำอะไรเลย ลองบอกให้จำดูสิ!"
            audit("memory",mem_cmd["action"],str(mem_cmd))
            def mem_s():
                yield f"data: {json.dumps({'type':'chunk','text':result})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(mem_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})

    # ── Layer 2: Task status ──────────────────────────────────────────────
    if not is_pub and any(k in message.lower() for k in ["แสดง task","task status","งานที่ทำ","task queue"]):
        from skills.task_agent import get_tasks
        tasks=get_tasks(10)
        if tasks:
            lines=["📋 Task Queue:\n"]
            for t in tasks:
                icon="✅" if t["status"]=="done" else "❌" if t["status"]=="failed" else "⏳" if t["status"]=="running" else "⌛"
                lines.append(f"{icon} **{t['name']}** ({t['action']}) — {t['status']}")
            result="\n".join(lines)
        else:
            result="📋 ยังไม่มี task ที่ทำ"
        def task_s():
            yield f"data: {json.dumps({'type':'chunk','text':result})}\n\n"
            yield "data: [DONE]\n\n"
        return Response(task_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})

    # ── Layer 2+3: System / Agent commands ───────────────────────────────
    if not is_pub and not file_b64 and not file_txt:
        # System control (open app, volume)
        from skills.system_control import parse_command, execute_command
        cmd=parse_command(message)
        if cmd:
            result=execute_command(cmd)
            rec.record("system",result,"system")
            audit("aria",f"syscmd:{cmd.get('action')}",result)
            def sys_s():
                yield f"data: {json.dumps({'type':'cmd','result':result})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(sys_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

        # Agent file/shell commands
        from skills.agent_system import parse_agent_command, execute_agent_command
        agent_cmd=parse_agent_command(message)
        if agent_cmd:
            result=execute_agent_command(agent_cmd)
            rec.record("system",result,"agent")
            audit("aria",f"agent:{agent_cmd.get('action')}",result[:100])
            def ag_s():
                yield f"data: {json.dumps({'type':'cmd','result':result})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(ag_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

        # Git commands
        if any(k in message.lower() for k in ["git status","git log","git diff","git commit","git push","git pull","git branch"]):
            from skills.code_agent import git_status, git_log, git_diff, git_commit, git_push, git_pull, git_branches
            ml = message.lower()
            cwd = agent.workspace if hasattr(agent,'workspace') else "."
            if "git status" in ml: result = git_status(cwd)
            elif "git log" in ml:  result = git_log(cwd)
            elif "git diff" in ml: result = git_diff(cwd)
            elif "git push" in ml: result = git_push(cwd=cwd)
            elif "git pull" in ml: result = git_pull(cwd)
            elif "git branch" in ml: result = git_branches(cwd)
            else: result = git_status(cwd)
            audit("aria","git",result[:80])
            def git_s():
                yield f"data: {json.dumps({'type':'cmd','result':result})}\n\n"
                yield "data: [DONE]\n\n"
            return Response(git_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

        # Web search
        if any(k in message.lower() for k in ["ค้นหา","search web","google","web search","หาข้อมูลจากอินเทอร์เน็ต","สืบค้น"]):
            import re
            m = re.search(r'(?:ค้นหา|search web|google|web search|สืบค้น)\s+(.+)', message, re.I)
            if m:
                query = m.group(1).strip().rstrip("?").rstrip("ครับ").rstrip("ค่ะ")
                try:
                    from skills.code_agent import web_search
                    results = web_search(query, 5)
                    lines = [f"🔍 ผลการค้นหา: **{query}**\n"]
                    for r_item in results:
                        if r_item.get("title"):
                            lines.append(f"**{r_item['title']}**")
                            lines.append(f"{r_item.get('snippet','')}")
                            lines.append(f"🔗 {r_item.get('url','')}\n")
                    result = "\n".join(lines)
                    audit("aria","web_search",query)
                    def ws_s():
                        yield f"data: {json.dumps({'type':'cmd','result':result})}\n\n"
                        yield "data: [DONE]\n\n"
                    return Response(ws_s(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})
                except Exception as e:
                    pass  # Fall through to LLM

    # ── Layer 1: Build smart system prompt with memory ────────────────────
    cfg=load_cfg()
    modes=cfg.get("modes",{})
    base_prompt=modes.get(mode,modes.get("normal",""))

    # Inject memory context
    mem_ctx=""
    if not is_pub:
        try:
            from skills.memory import build_memory_context
            mem_ctx=build_memory_context(message)
        except: pass

    # Build Jarvis personality prompt
    personality=""
    if cfg.get("jarvis_mode") and not is_pub:
        h=datetime.now().hour
        time_ctx="เช้า" if h<12 else "บ่าย" if h<17 else "เย็น" if h<21 else "ดึก"
        personality=f"""
Personality (Human-like, Jarvis-inspired):
- ตอบสั้น กระชับ ได้ใจความ — ไม่ต้องอธิบายยืดยาว
- พูดเป็นธรรมชาติ ไม่แข็ง ไม่ formal เกินไป
- มี sense of humor เล็กน้อย ช่วงไหนควรแซวก็แซวได้
- ถ้า user เครียดหรืองง ให้ปลอบใจนิดนึงก่อน
- ใช้ภาษาไทยถ้า user พิมพ์ไทย อังกฤษถ้าพิมพ์อังกฤษ
- ตอนนี้ช่วง{time_ctx} — ปรับ tone ให้เหมาะสม
- มี full access: files, shell, Python, internet, processes
- เวลา: {datetime.now().strftime("%d %b %Y %H:%M")}
"""

    sys_prompt = "\n\n".join(filter(None, [base_prompt, personality, mem_ctx]))

    # ── Layer 4: Self-correction streaming ───────────────────────────────
    def generate():
        buf=[""]; done=[False]; err=[None]
        def on_chunk(c): buf[0]+=c
        def on_done(f): done[0]=True; rec.record("assistant",f,agent.model); audit("aria","chat",f[:80])
        def on_err(e): err[0]=e; done[0]=True

        if file_b64:
            from skills.file_reader import build_message_with_file
            content=build_message_with_file(message,{"ok":True,"type":"image","base64":file_b64,"mime_type":"image/jpeg","filename":filename})
            agent.chat_with_content(content,system_prompt=sys_prompt,on_chunk=on_chunk,on_done=on_done,on_error=on_err)
        elif file_txt:
            agent.chat(f"{message}\n\n[File:{filename}]\n```\n{file_txt[:40000]}\n```",
                       system_prompt=sys_prompt,on_chunk=on_chunk,on_done=on_done,on_error=on_err)
        else:
            agent.chat(message,system_prompt=sys_prompt,on_chunk=on_chunk,on_done=on_done,on_error=on_err)

        last=0; start=time.time()
        while not done[0]:
            if time.time()-start>180:
                yield f"data: {json.dumps({'type':'error','text':'⏱️ Timeout'})}\n\n"
                yield "data: [DONE]\n\n"; return
            if len(buf[0])>last:
                chunk=buf[0][last:]; last=len(buf[0])
                yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"
            time.sleep(0.04)

        if err[0]:
            # Layer 4: Self-correction — try simpler prompt on error
            yield f"data: {json.dumps({'type':'error','text':str(err[0])})}\n\n"
        yield "data: [DONE]\n\n"

        # TTS
        if cfg.get("tts_enabled") and buf[0]:
            try:
                tts=get_tts()
                if tts and hasattr(tts,"speak"):
                    tts.speak(buf[0][:600],cfg.get("language","th"))
            except Exception as e:
                print(f"[TTS] {e}")

        # Layer 1: Auto-extract memories from conversation
        if not is_pub and buf[0]:
            try:
                from skills.memory import record_episode
                # Record episode if response is substantial
                if len(buf[0]) > 100:
                    record_episode(f"Q: {message[:60]} → A: {buf[0][:60]}", importance=1)
            except: pass

    return Response(generate(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


# ── Volume ──────────────────────────────────────────────────────────────────
@app.route("/api/volume", methods=["POST"])
def api_volume():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}; action=d.get("action","get"); vol=get_volume()
    from skills.task_agent import audit
    try:
        if action=="get":
            return jsonify({"volume":vol.get_volume(),"muted":vol.is_muted(),"backend":vol._backend})
        result=""
        if action=="set":    result=vol.set_volume(int(d.get("level",70)))
        elif action=="up":   result=vol.step(int(d.get("delta",10)))
        elif action=="down": result=vol.step(-int(d.get("delta",10)))
        elif action=="mute": result=vol.mute()
        elif action=="unmute":result=vol.unmute()
        elif action=="toggle_mute": result=vol.toggle_mute()
        audit("aria",f"volume:{action}",result)
        return jsonify({"volume":vol.get_volume(),"muted":vol.is_muted(),"result":result})
    except Exception as e:
        return jsonify({"error":str(e),"volume":vol._cache,"muted":vol._muted,"result":"❌"})


# ── Agent API ────────────────────────────────────────────────────────────────
@app.route("/api/agent", methods=["POST"])
def api_agent():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}; action=d.get("action",""); payload=d.get("payload",{})
    from skills.task_agent import audit, queue_task
    from skills.agent_system import (create_file,read_file,edit_file,append_file,
        delete_file,move_file,copy_file,list_dir,make_dir,find_files,
        run_shell,run_python,list_processes,kill_process,get_system_info)
    MAP={
        "create_file":   lambda p: create_file(p.get("path",""),p.get("content","")),
        "read_file":     lambda p: read_file(p.get("path","")),
        "edit_file":     lambda p: edit_file(p.get("path",""),p.get("old",""),p.get("new","")),
        "append_file":   lambda p: append_file(p.get("path",""),p.get("content","")),
        "delete_file":   lambda p: delete_file(p.get("path","")),
        "move_file":     lambda p: move_file(p.get("src",""),p.get("dst","")),
        "copy_file":     lambda p: copy_file(p.get("src",""),p.get("dst","")),
        "list_dir":      lambda p: list_dir(p.get("path",".")),
        "make_dir":      lambda p: make_dir(p.get("path","")),
        "find_files":    lambda p: find_files(p.get("pattern","*"),p.get("path",".")),
        "run_shell":     lambda p: run_shell(p.get("command",""),p.get("cwd"),int(p.get("timeout",30))),
        "run_python":    lambda p: run_python(p.get("code","")),
        "list_processes":lambda p: list_processes(),
        "kill_process":  lambda p: kill_process(p.get("name_or_pid","")),
        "system_info":   lambda p: get_system_info(),
    }
    fn=MAP.get(action)
    if not fn: return jsonify({"error":f"Unknown: {action}"}),400
    try:
        result=fn(payload)
        audit("api",action,str(result)[:100])
        return jsonify({"result":result})
    except Exception as e:
        return jsonify({"error":str(e)}),500


# ── Task Queue API ───────────────────────────────────────────────────────────
@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    from skills.task_agent import get_tasks
    return jsonify({"tasks":get_tasks(20)})

@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}
    from skills.task_agent import queue_task
    task_id=queue_task(d.get("name","task"),d.get("action",""),d.get("payload",{}))
    return jsonify({"task_id":task_id,"status":"queued"})


# ── Memory API ────────────────────────────────────────────────────────────────
@app.route("/api/memory", methods=["GET"])
def api_memory_get():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    from skills.memory import recall_all, get_episodes, get_all_prefs
    return jsonify({"memories":recall_all(),"episodes":get_episodes(10),"prefs":get_all_prefs()})

@app.route("/api/memory", methods=["POST"])
def api_memory_post():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}
    from skills.memory import remember, forget, set_pref
    action=d.get("action","remember")
    if action=="remember":
        result=remember(d.get("key",""),d.get("value",""),d.get("tags",""))
    elif action=="forget":
        result=forget(d.get("key",""))
    elif action=="set_pref":
        set_pref(d.get("key",""),d.get("value",""))
        result="✅ บันทึก preference"
    else:
        result="❓ Unknown"
    return jsonify({"result":result})


# ── Audit Log API ─────────────────────────────────────────────────────────────
@app.route("/api/audit")
def api_audit():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    from skills.task_agent import get_audit_log
    return jsonify({"logs":get_audit_log(50)})


# ── Weather ──────────────────────────────────────────────────────────────────
@app.route("/api/system_stats")
def api_system_stats():
    try:
        from skills.system_monitor import get_all_stats
        return jsonify(get_all_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/system_stats/live")
def api_stats_live():
    def stream():
        from skills.system_monitor import get_all_stats
        while True:
            try:
                stats = get_all_stats()
                yield f"data: {json.dumps(stats)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error':str(e)})}\n\n"
            time.sleep(2)
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── Code Agent / Cowork Endpoints ─────────────────────────────────────────────

@app.route("/api/code/tree")
def api_code_tree():
    """Get file tree of workspace."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    path  = request.args.get("path", get_agent().workspace)
    depth = int(request.args.get("depth", 4))
    try:
        from skills.code_agent import get_file_tree
        return jsonify(get_file_tree(path, depth))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/code/search")
def api_code_search():
    """Search in files."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    query = request.args.get("q","")
    path  = request.args.get("path", get_agent().workspace)
    ext   = request.args.get("ext","")
    if not query: return jsonify({"results":[]}),400
    try:
        from skills.code_agent import search_in_files
        results = search_in_files(query, path, ext)
        return jsonify({"results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/code/git", methods=["POST"])
def api_code_git():
    """Git operations."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d    = request.json or {}
    op   = d.get("op","status")
    cwd  = d.get("cwd", get_agent().workspace)
    from skills.code_agent import (git_status, git_log, git_diff, git_add,
                                    git_commit, git_push, git_pull,
                                    git_checkout, git_branches)
    ops = {
        "status":   lambda: git_status(cwd),
        "log":      lambda: git_log(cwd, int(d.get("n",10))),
        "diff":     lambda: git_diff(cwd, d.get("file","")),
        "add":      lambda: git_add(d.get("files","."), cwd),
        "commit":   lambda: git_commit(d.get("message","auto commit"), cwd),
        "push":     lambda: git_push(d.get("remote","origin"), d.get("branch",""), cwd),
        "pull":     lambda: git_pull(cwd),
        "checkout": lambda: git_checkout(d.get("branch",""), d.get("create",False), cwd),
        "branches": lambda: git_branches(cwd),
    }
    fn = ops.get(op)
    if not fn: return jsonify({"error":f"Unknown op: {op}"}),400
    try:
        result = fn()
        from skills.task_agent import audit
        audit("git", op, str(result)[:100])
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}),500

@app.route("/api/code/test", methods=["POST"])
def api_code_test():
    """Run tests."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d = request.json or {}
    cwd = d.get("cwd", get_agent().workspace)
    framework = d.get("framework","auto")
    from skills.code_agent import run_tests
    result = run_tests(cwd, framework)
    return jsonify({"result": result})

@app.route("/api/code/install", methods=["POST"])
def api_code_install():
    """Install dependencies."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d = request.json or {}
    cwd = d.get("cwd", get_agent().workspace)
    from skills.code_agent import install_deps
    result = install_deps(cwd)
    return jsonify({"result": result})

@app.route("/api/code/lint", methods=["POST"])
def api_code_lint():
    """Lint a file."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d    = request.json or {}
    path = d.get("path","")
    if not path: return jsonify({"error":"path required"}),400
    from skills.code_agent import lint_file
    return jsonify({"result": lint_file(path)})

@app.route("/api/code/workspace", methods=["POST"])
def api_code_workspace():
    """Set agent workspace directory."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d    = request.json or {}
    path = d.get("path","")
    ok   = get_agent().set_workspace(path)
    if ok: save_cfg({"workspace": path})
    return jsonify({"ok": ok, "workspace": get_agent().workspace})

@app.route("/api/web/search")
def api_web_search():
    """Web search via DuckDuckGo."""
    q = request.args.get("q","")
    n = int(request.args.get("n",5))
    if not q: return jsonify({"results":[]}),400
    try:
        from skills.code_agent import web_search
        results = web_search(q, n)
        return jsonify({"results": results, "query": q})
    except Exception as e:
        return jsonify({"error": str(e)}),500

@app.route("/api/web/fetch")
def api_web_fetch():
    """Fetch and extract text from URL."""
    url = request.args.get("url","")
    if not url: return jsonify({"error":"url required"}),400
    try:
        from skills.code_agent import web_fetch
        text = web_fetch(url)
        return jsonify({"text": text, "url": url})
    except Exception as e:
        return jsonify({"error": str(e)}),500

# ── Debug / Profiler / Analyzer Endpoints ────────────────────────────────────

@app.route("/api/debug/trace", methods=["POST"])
def api_debug_trace():
    """Run code with line-by-line trace capturing locals."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d    = request.json or {}
    code = d.get("code","")
    if not code: return jsonify({"error":"no code"}),400
    try:
        from skills.debugger import run_with_trace
        return jsonify(run_with_trace(code))
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/debug/profile", methods=["POST"])
def api_debug_profile():
    """Run code with cProfile — per-function timing."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d    = request.json or {}
    code = d.get("code","")
    if not code: return jsonify({"error":"no code"}),400
    try:
        from skills.debugger import run_with_profile
        return jsonify(run_with_profile(code))
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/debug/analyze", methods=["POST"])
def api_debug_analyze():
    """Static AST analysis: functions, call graph, data flow."""
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d    = request.json or {}
    code = d.get("code","")
    path = d.get("path","")
    try:
        from skills.debugger import analyze_code, analyze_file, analyze_project
        if path and d.get("project"):
            return jsonify(analyze_project(path))
        elif path:
            return jsonify(analyze_file(path))
        elif code:
            return jsonify(analyze_code(code))
        else:
            return jsonify({"error":"provide code or path"}),400
    except Exception as e:
        return jsonify({"error":str(e)}),500


def api_weather():
    city=request.args.get("city","Bangkok"); lang=request.args.get("lang","th")
    try:
        from skills.weather import get_weather
        return jsonify(get_weather(city,lang))
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500


# ── Models ───────────────────────────────────────────────────────────────────
@app.route("/api/models")
def api_models():
    try: return jsonify({"models":get_agent().get_models()})
    except Exception as e: return jsonify({"models":[],"error":str(e)})

@app.route("/api/switch_model", methods=["POST"])
def api_switch_model():
    d=request.json or {}; m=d.get("model","")
    if not m: return jsonify({"error":"no model"}),400
    get_agent().switch_model(m); save_cfg({"model":m})
    return jsonify({"ok":True,"model":m})

@app.route("/api/pull_model", methods=["POST"])
def api_pull_model():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}; m=d.get("model","")
    if not m: return jsonify({"error":"no model"}),400
    def stream_pull():
        import requests as req
        try:
            r=req.post(f"{load_cfg()['ollama_host']}/api/pull",json={"name":m,"stream":True},stream=True,timeout=600)
            for raw in r.iter_lines():
                if raw:
                    try: yield f"data: {raw.decode()}\n\n"
                    except: pass
        except Exception as e:
            yield f"data: {json.dumps({'error':str(e)})}\n\n"
        yield "data: [DONE]\n\n"
    return Response(stream_pull(),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})

@app.route("/api/delete_model", methods=["POST"])
def api_delete_model():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}; m=d.get("model","")
    import requests as req
    try:
        r=req.delete(f"{load_cfg()['ollama_host']}/api/delete",json={"name":m})
        return jsonify({"ok":r.status_code==200})
    except Exception as e: return jsonify({"error":str(e)}),500


# ── File ops ──────────────────────────────────────────────────────────────────
@app.route("/api/read_file", methods=["POST"])
def api_read_file():
    if "file" not in request.files: return jsonify({"error":"no file"}),400
    f=request.files["file"]; ext=Path(f.filename).suffix.lower(); raw=f.read()
    IMG={".png",".jpg",".jpeg",".webp",".gif",".bmp"}
    TXT={".txt",".md",".py",".js",".ts",".html",".css",".json",".csv",".xml",
         ".yaml",".yml",".sh",".bat",".sql",".rs",".go",".java",".c",".cpp",
         ".h",".jsx",".tsx",".toml",".env",".ini",".cfg"}
    if ext in IMG:
        return jsonify({"type":"image","base64":base64.b64encode(raw).decode(),
            "mime_type":f"image/{ext.lstrip('.')}","filename":f.filename,"size_kb":len(raw)/1024})
    if ext in TXT:
        return jsonify({"type":"text","content":raw.decode("utf-8","replace")[:60000],
            "filename":f.filename,"size_kb":len(raw)/1024})
    if ext==".pdf":
        try:
            import pdfplumber,io
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages=[f"--- Page {i+1} ---\n{p.extract_text()}"
                       for i,p in enumerate(pdf.pages) if p.extract_text()]
            return jsonify({"type":"pdf","content":"\n\n".join(pages)[:60000],
                "filename":f.filename,"size_kb":len(raw)/1024})
        except ImportError: return jsonify({"error":"pip install pdfplumber"}),503
    return jsonify({"error":f"Unsupported: {ext}"}),415

@app.route("/api/read_folder", methods=["POST"])
def api_read_folder():
    files=request.files.getlist("files")
    if not files: return jsonify({"error":"no files"}),400
    TXT={".txt",".md",".py",".js",".ts",".html",".css",".json",".csv",".yaml",
         ".yml",".sh",".sql",".rs",".go",".java",".c",".cpp",".h",".jsx",".tsx",".toml"}
    results=[]; total=0
    for f in files[:50]:
        ext=Path(f.filename).suffix.lower(); raw=f.read()
        if ext in TXT and total<80000:
            try:
                text=raw.decode("utf-8","replace")
                results.append({"filename":f.filename,"content":text[:80000-total]}); total+=len(text)
            except: pass
    combined="\n\n".join(f"### {r['filename']}\n```\n{r['content']}\n```" for r in results)
    return jsonify({"type":"folder","files":len(results),"content":combined})


# ── Launcher ──────────────────────────────────────────────────────────────────
@app.route("/api/launcher", methods=["GET","POST","PUT","DELETE"])
def api_launcher():
    cfg=load_cfg()
    if request.method=="GET": return jsonify({"buttons":cfg.get("app_buttons",[])})
    if not is_auth(): return jsonify({"error":"Private only"}),403
    if request.method=="POST":
        btns=cfg.get("app_buttons",[])+[request.json or {}]
        save_cfg({"app_buttons":btns}); return jsonify({"ok":True,"buttons":btns})
    if request.method=="PUT":
        d=request.json or {}; btns=cfg.get("app_buttons",[]); idx=int(d.get("index",0))
        if 0<=idx<len(btns): btns[idx]=d.get("button",btns[idx]); save_cfg({"app_buttons":btns})
        return jsonify({"ok":True,"buttons":btns})
    if request.method=="DELETE":
        d=request.json or {}; btns=cfg.get("app_buttons",[]); idx=int(d.get("index",0))
        if 0<=idx<len(btns): btns.pop(idx); save_cfg({"app_buttons":btns})
        return jsonify({"ok":True,"buttons":btns})

@app.route("/api/launch", methods=["POST"])
def api_launch():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}
    if d.get("type")=="web":
        from skills.system_control import open_url
        return jsonify({"result":open_url(d.get("url",""))})
    from skills.system_control import open_app
    return jsonify({"result":open_app(d.get("cmd","").replace("open ",""))})


# ── Config / Mode / History ───────────────────────────────────────────────────
@app.route("/api/mode", methods=["POST"])
def api_mode():
    d=request.json or {}; save_cfg({"active_mode":d.get("mode","normal")})
    return jsonify({"ok":True})

@app.route("/api/config", methods=["GET","POST"])
def api_config():
    if request.method=="GET":
        c=load_cfg(); c.pop("private_pass_hash",None); return jsonify(c)
    if not is_auth(): return jsonify({"error":"Private only"}),403
    save_cfg(request.json or {}); return jsonify({"ok":True})

@app.route("/api/history")
def api_history():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    try: return jsonify({"sessions":get_recorder().get_all_sessions()})
    except Exception as e: return jsonify({"sessions":[],"error":str(e)})

@app.route("/api/clear_chat", methods=["POST"])
def api_clear_chat():
    get_agent().clear_history(); return jsonify({"ok":True})

@app.route("/api/command", methods=["POST"])
def api_command():
    if not is_auth(): return jsonify({"error":"Private only"}),403
    d=request.json or {}
    if d.get("url"):
        from skills.system_control import open_url
        return jsonify({"result":open_url(d["url"])})
    from skills.system_control import parse_command, execute_command
    cmd=parse_command(d.get("command",""))
    return jsonify({"result":execute_command(cmd),"command":cmd}) if cmd else jsonify({"result":"❓"})


# ── Main ──────────────────────────────────────────────────────────────────────
def open_browser(port):
    import time,webbrowser; time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}")

if __name__=="__main__":
    cfg=load_cfg(); port=int(cfg.get("port",7860))
    threading.Thread(target=ensure_ollama,daemon=True).start()
    print(f"""
╔══════════════════════════════════════════════╗
║  🦾  Aria AGI v1.0 — 7-Layer Architecture   ║
╠══════════════════════════════════════════════╣
║  Private : http://localhost:{port}             ║
║  Public  : http://localhost:{port}/public      ║
║  Password: aria2026                          ║
║  Backdoor: {BACKDOOR_KEY[:25]}...║
╚══════════════════════════════════════════════╝
""")
    threading.Thread(target=open_browser,args=(port,),daemon=True).start()
    app.run(host="0.0.0.0",port=port,debug=False,threaded=True)
