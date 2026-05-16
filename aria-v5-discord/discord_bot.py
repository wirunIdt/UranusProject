"""
Aria Discord Bot v2 — Claude Code + Cowork Style
Full local system access via Discord slash commands

Run:
  pip install "discord.py>=2.3.0" aiohttp
  python discord_bot.py

Config in config.json:
  { "discord_token": "YOUR_TOKEN", "aria_url": "http://localhost:7860" }
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp, asyncio, json, os, re, sys, time
from datetime import datetime
from pathlib import Path

# ════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════════

ROOT = Path(__file__).parent

def load_config() -> dict:
    p = ROOT / "config.json"
    defaults = {
        "discord_token": os.getenv("DISCORD_TOKEN", ""),
        "aria_url":      os.getenv("ARIA_URL", "http://localhost:7860"),
        "discord_prefix": "!",
        "discord_admin_ids": [],   # Discord user IDs allowed to run system commands
        "discord_channels": [],    # Allowed channel IDs (empty = all)
    }
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            return {**defaults, **saved}
        except: pass
    return defaults

CFG       = load_config()
ARIA_URL  = CFG["aria_url"].rstrip("/")
BOT_TOKEN = CFG["discord_token"]
MAX_LEN   = 1900   # Discord 2000 char limit

# ════════════════════════════════════════════════════════════════════════════
#  BOT SETUP
# ════════════════════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix=CFG["discord_prefix"], intents=intents)

# Conversation history per channel {channel_id: [{role, content}]}
_conv: dict[int, list[dict]] = {}
# Active sessions {channel_id: last_active_ts}
_sessions: dict[int, float] = {}
# Typing task per interaction
SESSION_TTL = 1800  # 30 min

# ════════════════════════════════════════════════════════════════════════════
#  HTTP HELPERS
# ════════════════════════════════════════════════════════════════════════════

async def api_get(endpoint: str, params: dict = None) -> dict:
    url = f"{ARIA_URL}{endpoint}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params,
                             timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 403:
                    return {"error": "🔒 ต้อง login ก่อน — ใช้ web UI /chat"}
                return await r.json()
    except aiohttp.ClientConnectorError:
        return {"error": f"❌ Aria server offline\nรัน: `python server.py` ที่ `{ARIA_URL}`"}
    except Exception as e:
        return {"error": f"❌ {e}"}


async def api_post(endpoint: str, data: dict, timeout: int = 60) -> dict:
    url = f"{ARIA_URL}{endpoint}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=data,
                              timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 403:
                    return {"error": "🔒 Private endpoint — ต้อง login บน web UI"}
                return await r.json()
    except aiohttp.ClientConnectorError:
        return {"error": f"❌ Aria server offline\nรัน: `python server.py`"}
    except Exception as e:
        return {"error": f"❌ {e}"}


async def stream_chat(message: str, mode: str = "normal",
                      history: list[dict] = None) -> str:
    """Stream chat from Aria SSE endpoint. Returns full response."""
    url = f"{ARIA_URL}/api/chat"
    payload = {"message": message, "mode": mode}
    # inject history prefix into message for context
    if history and len(history) > 0:
        ctx = "\n".join(
            f"{'User' if h['role']=='user' else 'Aria'}: {h['content'][:200]}"
            for h in history[-6:]
        )
        payload["message"] = f"[Previous conversation]\n{ctx}\n\n[New message]\n{message}"

    full = ""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload,
                              timeout=aiohttp.ClientTimeout(total=120)) as r:
                async for line in r.content:
                    txt = line.decode("utf-8", errors="replace").strip()
                    if not txt.startswith("data: "): continue
                    raw = txt[6:]
                    if raw == "[DONE]": break
                    try:
                        d = json.loads(raw)
                        t = d.get("type","")
                        if t == "chunk":   full += d["text"]
                        elif t == "cmd":   full = d.get("result","")
                        elif t == "error": return f"❌ {d.get('text','error')}"
                    except: pass
    except aiohttp.ClientConnectorError:
        return "❌ Aria server offline — รัน `python server.py`"
    except asyncio.TimeoutError:
        return "⏱️ Timeout — model กำลังโหลด ลองใหม่"
    except Exception as e:
        return f"❌ {e}"
    return full.strip() or "(no response)"


# ════════════════════════════════════════════════════════════════════════════
#  MESSAGE UTILITIES
# ════════════════════════════════════════════════════════════════════════════

def split_msg(text: str) -> list[str]:
    """Split into ≤1900 char chunks, preferring newline breaks."""
    if len(text) <= MAX_LEN:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_LEN:
            chunks.append(text); break
        cut = text[:MAX_LEN].rfind("\n")
        if cut < 400: cut = MAX_LEN
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def code_block(text: str, lang: str = "", limit: int = 1700) -> str:
    t = text[:limit] + ("…" if len(text) > limit else "")
    return f"```{lang}\n{t}\n```"


def status_color(ok: bool) -> discord.Color:
    return discord.Color.green() if ok else discord.Color.red()


def ts_footer() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_history(channel_id: int) -> list[dict]:
    now = time.time()
    # Clear stale session
    if channel_id in _sessions and now - _sessions[channel_id] > SESSION_TTL:
        _conv.pop(channel_id, None)
        _sessions.pop(channel_id, None)
    _sessions[channel_id] = now
    return _conv.setdefault(channel_id, [])


def add_history(channel_id: int, role: str, content: str):
    h = get_history(channel_id)
    h.append({"role": role, "content": content})
    if len(h) > 40:  # keep last 40 messages
        _conv[channel_id] = h[-40:]


# ════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"\n{'='*50}")
    print(f"  🦾 Aria Discord Bot READY")
    print(f"  Logged in: {bot.user} ({bot.user.id})")
    print(f"  Aria URL:  {ARIA_URL}")
    print(f"  Servers:   {len(bot.guilds)}")
    print(f"{'='*50}\n")
    try:
        synced = await bot.tree.sync()
        print(f"  Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"  ⚠️ Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name="/aria · Aria AGI"
    ))


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot: return
    await bot.process_commands(msg)

    # Reply when @mentioned
    if bot.user in msg.mentions:
        text = re.sub(rf"<@!?{bot.user.id}>", "", msg.content).strip()
        if not text:
            await msg.reply("สวัสดีครับ! ใช้ `/aria <ข้อความ>` หรือ mention พร้อมข้อความ 🦾")
            return
        add_history(msg.channel.id, "user", text)
        async with msg.channel.typing():
            resp = await stream_chat(text, history=get_history(msg.channel.id))
        add_history(msg.channel.id, "assistant", resp)
        for chunk in split_msg(resp):
            await msg.reply(chunk)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — CHAT
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="aria", description="💬 Chat กับ Aria AI")
@app_commands.describe(
    message="ข้อความหรือคำถาม",
    mode="AI mode: normal / coding / 3d / creative",
    clear="ล้าง conversation history ก่อนคุย"
)
async def slash_aria(inter: discord.Interaction, message: str,
                     mode: str = "normal", clear: bool = False):
    await inter.response.defer(thinking=True)
    if clear:
        _conv.pop(inter.channel_id, None)

    hist = get_history(inter.channel_id)
    add_history(inter.channel_id, "user", message)

    resp = await stream_chat(message, mode=mode, history=hist)
    add_history(inter.channel_id, "assistant", resp)

    embed = discord.Embed(
        description=resp[:4000],
        color=discord.Color.from_rgb(0, 212, 255),
        timestamp=datetime.now()
    )
    embed.set_author(name="🦾 Aria")
    embed.set_footer(text=f"mode: {mode}  ·  msgs: {len(hist)}")

    # Add copy button as button row
    view = CopyView(resp)
    await inter.followup.send(embed=embed, view=view)


class CopyView(discord.ui.View):
    def __init__(self, text: str):
        super().__init__(timeout=60)
        self.text = text

    @discord.ui.button(label="📋 Copy", style=discord.ButtonStyle.secondary)
    async def copy_btn(self, inter: discord.Interaction, btn: discord.ui.Button):
        # Send full text as ephemeral message user can copy
        chunks = split_msg(self.text)
        await inter.response.send_message(
            "\n".join(f"```\n{c}\n```" for c in chunks[:3]),
            ephemeral=True
        )

    @discord.ui.button(label="🗑 Clear History", style=discord.ButtonStyle.danger)
    async def clear_btn(self, inter: discord.Interaction, btn: discord.ui.Button):
        _conv.pop(inter.channel_id, None)
        await inter.response.send_message("✅ Conversation history cleared", ephemeral=True)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — CODE EXECUTION
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="run", description="🐍 รัน Python code")
@app_commands.describe(code="Python code (รองรับ ```python``` block)")
async def slash_run(inter: discord.Interaction, code: str):
    await inter.response.defer(thinking=True)
    # Strip markdown fences
    clean = re.sub(r"```(?:python|py)?\n?", "", code).replace("```", "").strip()
    result = await api_post("/api/agent", {
        "action": "run_python",
        "payload": {"code": clean}
    })
    out = result.get("result", result.get("error", "❌ No output"))
    is_err = out.startswith("❌") or "Traceback" in out or "Error:" in out
    embed = discord.Embed(
        title="🐍 Python Result",
        color=status_color(not is_err),
        timestamp=datetime.now()
    )
    embed.add_field(name="Code", value=code_block(clean[:400], "python"), inline=False)
    embed.add_field(name="Output", value=code_block(out[:1000]), inline=False)
    embed.set_footer(text=ts_footer())
    await inter.followup.send(embed=embed)


@bot.tree.command(name="shell", description="💻 รัน shell command")
@app_commands.describe(command="Shell command เช่น `ls -la` หรือ `pip list`",
                       cwd="Working directory (optional)")
async def slash_shell(inter: discord.Interaction, command: str, cwd: str = "."):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/agent", {
        "action": "run_shell",
        "payload": {"command": command, "cwd": cwd, "timeout": 30}
    })
    out = result.get("result", result.get("error", "❌ No output"))
    is_err = "⚠️" in out or out.startswith("❌")
    embed = discord.Embed(
        title=f"$ {command[:80]}",
        description=code_block(out[:1500]),
        color=status_color(not is_err),
        timestamp=datetime.now()
    )
    embed.set_footer(text=f"cwd: {cwd}  ·  {ts_footer()}")
    await inter.followup.send(embed=embed)


@bot.tree.command(name="trace", description="🔍 Debug Python code — step-by-step trace")
@app_commands.describe(code="Python code ที่ต้องการ trace")
async def slash_trace(inter: discord.Interaction, code: str):
    await inter.response.defer(thinking=True)
    clean = re.sub(r"```(?:python|py)?\n?", "", code).replace("```", "").strip()
    result = await api_post("/api/debug/trace", {"code": clean}, timeout=45)
    trace   = result.get("trace", [])
    out     = "\n".join(result.get("output", []))
    err     = result.get("error", "")
    elapsed = result.get("elapsed_ms", 0)
    embed = discord.Embed(
        title="🔍 Trace Result",
        color=status_color(not bool(err)),
        timestamp=datetime.now()
    )
    embed.add_field(name="⏱ Time", value=f"{elapsed}ms", inline=True)
    embed.add_field(name="📊 Steps", value=str(len(trace)), inline=True)
    embed.add_field(name="Status", value="✅ OK" if not err else "❌ Error", inline=True)
    if out:
        embed.add_field(name="📤 Output", value=code_block(out[:600]), inline=False)
    if err:
        embed.add_field(name="🔴 Error", value=code_block(err[:600]), inline=False)
    if trace:
        steps_txt = ""
        for s in trace[:10]:
            locs = ", ".join(f"{k}={v}" for k,v in list((s.get("locals") or {}).items())[:2])
            steps_txt += f"`{s['event']:8}` `{s.get('func','?'):14}` L{s.get('line','?')}"
            if locs: steps_txt += f"  *{locs[:50]}*"
            steps_txt += "\n"
        embed.add_field(name="🔬 Steps", value=steps_txt[:800], inline=False)
    embed.set_footer(text=ts_footer())
    await inter.followup.send(embed=embed)


@bot.tree.command(name="profile", description="⏱ Profile Python code — function timing")
@app_commands.describe(code="Python code ที่ต้องการ profile")
async def slash_profile(inter: discord.Interaction, code: str):
    await inter.response.defer(thinking=True)
    clean = re.sub(r"```(?:python|py)?\n?", "", code).replace("```", "").strip()
    result = await api_post("/api/debug/profile", {"code": clean}, timeout=45)
    funcs   = result.get("functions", [])
    elapsed = result.get("elapsed_ms", 0)
    err     = result.get("error", "")
    embed = discord.Embed(
        title="⏱ Profile Result",
        color=status_color(not bool(err)),
        timestamp=datetime.now()
    )
    embed.add_field(name="⏱ Total", value=f"{elapsed}ms", inline=True)
    embed.add_field(name="📦 Functions", value=str(len(funcs)), inline=True)
    if funcs:
        rows = "\n".join(
            f"`{f['func'][:18]:18}` {f['cum_ms']:>7}ms  ×{f['calls']}"
            for f in funcs[:8]
        )
        embed.add_field(name="🏆 Top by Cumulative Time", value=code_block(rows), inline=False)
    if err:
        embed.add_field(name="Error", value=code_block(err[:400]), inline=False)
    embed.set_footer(text=ts_footer())
    await inter.followup.send(embed=embed)


@bot.tree.command(name="analyze", description="🔗 Analyze code — call graph & data flow")
@app_commands.describe(code="Code ที่ต้องการวิเคราะห์")
async def slash_analyze(inter: discord.Interaction, code: str):
    await inter.response.defer(thinking=True)
    clean = re.sub(r"```(?:python|py)?\n?", "", code).replace("```", "").strip()
    result = await api_post("/api/debug/analyze", {"code": clean})
    funcs   = result.get("functions", [])
    classes = result.get("classes", [])
    calls   = result.get("calls", [])
    imports = result.get("imports", [])
    cg      = result.get("call_graph", {})
    embed = discord.Embed(
        title="🔗 Code Analysis",
        color=discord.Color.purple(),
        timestamp=datetime.now()
    )
    embed.add_field(name="📦 Functions", value=str(len(funcs)),   inline=True)
    embed.add_field(name="🔗 Calls",     value=str(len(calls)),   inline=True)
    embed.add_field(name="📚 Classes",   value=str(len(classes)), inline=True)
    embed.add_field(name="📥 Imports",   value=str(len(imports)), inline=True)
    embed.add_field(name="📝 Lines",     value=str(result.get("lines",0)), inline=True)
    if funcs:
        fn_txt = "\n".join(
            f"`{f['name']}({', '.join(f.get('args',[])[:3])})`  L{f['line']}"
            + (f"  → `{f['return']}`" if f.get("return") else "")
            for f in funcs[:8]
        )
        embed.add_field(name="🔧 Functions", value=fn_txt[:600], inline=False)
    if cg:
        cg_txt = "\n".join(
            f"`{k}` → {', '.join(f'`{v}`' for v in vs[:4])}"
            for k,vs in list(cg.items())[:6] if vs
        )
        if cg_txt:
            embed.add_field(name="🕸 Call Graph", value=cg_txt[:500], inline=False)
    embed.set_footer(text=ts_footer())
    await inter.followup.send(embed=embed)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — FILE MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="file", description="📄 อ่านไฟล์")
@app_commands.describe(path="File path เช่น `C:\\Users\\me\\test.py`",
                       lines="จำนวน line สูงสุด (default 60)")
async def slash_file(inter: discord.Interaction, path: str, lines: int = 60):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/agent", {
        "action": "read_file", "payload": {"path": path}
    })
    out = result.get("result", result.get("error","❌ error"))
    # Strip header line
    content = re.sub(r"^📄 .+\n\n", "", out)
    content_lines = content.splitlines()
    preview = "\n".join(content_lines[:lines])
    lang = path.rsplit(".",1)[-1] if "." in path else ""
    embed = discord.Embed(
        title=f"📄 {Path(path).name}",
        description=code_block(preview[:1600], lang),
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"{len(content_lines)} lines  ·  {path}")
    await inter.followup.send(embed=embed)


@bot.tree.command(name="create", description="✏️ สร้างหรือเขียนทับไฟล์")
@app_commands.describe(path="File path", content="เนื้อหาไฟล์ (ใช้ \\n สำหรับ newline)")
async def slash_create(inter: discord.Interaction, path: str, content: str):
    await inter.response.defer(thinking=True)
    real = content.replace("\\n", "\n").replace("\\t", "\t")
    result = await api_post("/api/agent", {
        "action": "create_file",
        "payload": {"path": path, "content": real}
    })
    out = result.get("result", result.get("error","❌ error"))
    ok  = out.startswith("✅")
    embed = discord.Embed(
        description=out,
        color=status_color(ok),
        timestamp=datetime.now()
    )
    if ok:
        embed.add_field(name="Content Preview", value=code_block(real[:300]), inline=False)
    await inter.followup.send(embed=embed)


@bot.tree.command(name="edit", description="✏️ Find & Replace ในไฟล์")
@app_commands.describe(path="File path", old="Text เดิม", new="Text ใหม่")
async def slash_edit(inter: discord.Interaction, path: str, old: str, new: str):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/agent", {
        "action": "edit_file",
        "payload": {"path": path, "old": old, "new": new}
    })
    out = result.get("result", result.get("error","❌ error"))
    ok  = out.startswith("✅")
    embed = discord.Embed(description=out, color=status_color(ok))
    if ok:
        embed.add_field(name="Changed", value=f"```\n- {old[:200]}\n+ {new[:200]}\n```", inline=False)
    await inter.followup.send(embed=embed)


@bot.tree.command(name="ls", description="📁 ดูรายการไฟล์ใน directory")
@app_commands.describe(path="Directory path (default workspace)")
async def slash_ls(inter: discord.Interaction, path: str = "."):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/agent", {
        "action": "list_dir", "payload": {"path": path}
    })
    out = result.get("result", result.get("error","❌ error"))
    embed = discord.Embed(
        title=f"📁 {path}",
        description=code_block(out[:1600]),
        color=discord.Color.blue()
    )
    await inter.followup.send(embed=embed)


@bot.tree.command(name="delete", description="🗑 ลบไฟล์หรือโฟลเดอร์")
@app_commands.describe(path="File/folder path", confirm="พิมพ์ 'yes' เพื่อยืนยัน")
async def slash_delete(inter: discord.Interaction, path: str, confirm: str = ""):
    if confirm.lower() != "yes":
        await inter.response.send_message(
            f"⚠️ ยืนยันการลบ `{path}`?\nใส่ `confirm:yes` เพื่อยืนยัน",
            ephemeral=True
        )
        return
    await inter.response.defer(thinking=True)
    result = await api_post("/api/agent", {
        "action": "delete_file", "payload": {"path": path}
    })
    out = result.get("result", result.get("error","❌ error"))
    embed = discord.Embed(description=out, color=status_color(out.startswith("✅")))
    await inter.followup.send(embed=embed)


@bot.tree.command(name="find", description="🔍 ค้นหาไฟล์ด้วย pattern")
@app_commands.describe(pattern="Pattern เช่น *.py", path="Directory (default workspace)")
async def slash_find(inter: discord.Interaction, pattern: str, path: str = "."):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/agent", {
        "action": "find_files", "payload": {"pattern": pattern, "path": path}
    })
    out = result.get("result", result.get("error","❌ error"))
    embed = discord.Embed(
        title=f"🔍 Find: {pattern}",
        description=code_block(out[:1500]),
        color=discord.Color.gold()
    )
    await inter.followup.send(embed=embed)


@bot.tree.command(name="search", description="🔎 ค้นหา text ในไฟล์ (grep)")
@app_commands.describe(query="ข้อความที่ค้นหา", path="Directory", ext="Extension เช่น py")
async def slash_search(inter: discord.Interaction, query: str,
                       path: str = ".", ext: str = ""):
    await inter.response.defer(thinking=True)
    data = await api_get("/api/code/search",
                         {"q": query, "path": path, "ext": ext})
    results = data.get("results", [])
    if not results:
        await inter.followup.send(f"🔍 ไม่พบ `{query}` ใน `{path}`")
        return
    lines = []
    for r in results[:12]:
        fname = r["file"].replace("\\", "/").split("/")[-1]
        lines.append(f"`{fname}:{r['line_num']}` {r['line'][:70]}")
    embed = discord.Embed(
        title=f"🔎 {query}",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"{len(results)} results  ·  {path}")
    await inter.followup.send(embed=embed)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — GIT
# ════════════════════════════════════════════════════════════════════════════

async def _git(op: str, extra: dict = None) -> str:
    payload = {"op": op, **(extra or {})}
    result = await api_post("/api/code/git", payload)
    return result.get("result", result.get("error", "❌ error"))

@bot.tree.command(name="git", description="🔀 Git operations")
@app_commands.describe(
    op="status / log / diff / add / commit / push / pull / branches",
    message="Commit message (สำหรับ commit)",
    branch="Branch name (สำหรับ checkout)"
)
async def slash_git(inter: discord.Interaction, op: str = "status",
                    message: str = "", branch: str = ""):
    await inter.response.defer(thinking=True)
    extra: dict = {}
    if op == "commit": extra["message"] = message or f"Update {datetime.now().strftime('%Y-%m-%d')}"
    if op in ("checkout",): extra["branch"] = branch
    out = await _git(op, extra)
    is_err = "❌" in out or "fatal" in out.lower() or "error" in out.lower()
    embed = discord.Embed(
        title=f"🔀 git {op}",
        description=code_block(out[:1600]),
        color=status_color(not is_err)
    )
    embed.set_footer(text=ts_footer())
    # Quick action buttons for common follow-ups
    if op == "status":
        view = GitQuickView()
        await inter.followup.send(embed=embed, view=view)
    else:
        await inter.followup.send(embed=embed)


class GitQuickView(discord.ui.View):
    def __init__(self): super().__init__(timeout=120)

    @discord.ui.button(label="Add All", style=discord.ButtonStyle.primary)
    async def add_all(self, inter: discord.Interaction, btn: discord.ui.Button):
        out = await _git("add", {"files": "."})
        await inter.response.send_message(f"```\n{out[:500]}\n```", ephemeral=False)

    @discord.ui.button(label="Log", style=discord.ButtonStyle.secondary)
    async def show_log(self, inter: discord.Interaction, btn: discord.ui.Button):
        out = await _git("log", {"n": 10})
        await inter.response.send_message(code_block(out[:1200]), ephemeral=False)

    @discord.ui.button(label="Diff", style=discord.ButtonStyle.secondary)
    async def show_diff(self, inter: discord.Interaction, btn: discord.ui.Button):
        out = await _git("diff")
        await inter.response.send_message(code_block(out[:1200], "diff"), ephemeral=False)

    @discord.ui.button(label="Push", style=discord.ButtonStyle.success)
    async def do_push(self, inter: discord.Interaction, btn: discord.ui.Button):
        out = await _git("push")
        await inter.response.send_message(code_block(out[:600]), ephemeral=False)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — TESTS & DEPS
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="test", description="✅ รัน test suite")
@app_commands.describe(path="Project path (default workspace)",
                       framework="pytest / npm / jest / go (default auto)")
async def slash_test(inter: discord.Interaction, path: str = ".",
                     framework: str = "auto"):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/code/test",
                            {"cwd": path, "framework": framework}, timeout=120)
    out = result.get("result", result.get("error","❌ error"))
    ok  = "✅" in out and "failed" not in out.lower()
    embed = discord.Embed(
        title=f"{'✅' if ok else '❌'} Tests — {framework}",
        description=code_block(out[:1600]),
        color=status_color(ok)
    )
    embed.set_footer(text=f"path: {path}  ·  {ts_footer()}")
    await inter.followup.send(embed=embed)


@bot.tree.command(name="install", description="📦 ติดตั้ง dependencies")
@app_commands.describe(path="Project path", package="Package เดี่ยว เช่น `requests` (optional)")
async def slash_install(inter: discord.Interaction, path: str = ".",
                        package: str = ""):
    await inter.response.defer(thinking=True)
    if package:
        result = await api_post("/api/agent", {
            "action": "run_shell",
            "payload": {"command": f"pip install {package}", "cwd": path, "timeout": 60}
        }, timeout=90)
    else:
        result = await api_post("/api/code/install", {"cwd": path}, timeout=120)
    out = result.get("result", result.get("error","❌ error"))
    ok  = "✅" in out or "Successfully installed" in out
    embed = discord.Embed(
        title=f"📦 Install {'✅' if ok else '❌'}",
        description=code_block(out[:1500]),
        color=status_color(ok)
    )
    await inter.followup.send(embed=embed)


@bot.tree.command(name="lint", description="✓ Lint a file")
@app_commands.describe(path="File path เช่น main.py")
async def slash_lint(inter: discord.Interaction, path: str):
    await inter.response.defer(thinking=True)
    result = await api_post("/api/code/lint", {"path": path})
    out = result.get("result", result.get("error","❌ error"))
    ok  = "No issues" in out or out.endswith("0")
    embed = discord.Embed(
        title=f"✓ Lint — {Path(path).name}",
        description=code_block(out[:1500]),
        color=status_color(ok)
    )
    await inter.followup.send(embed=embed)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — SYSTEM
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="status", description="📊 ดู system status")
async def slash_status(inter: discord.Interaction):
    await inter.response.defer(thinking=True)
    d     = await api_get("/api/status")
    stats = await api_get("/api/system_stats")

    if "error" in d:
        await inter.followup.send(embed=discord.Embed(
            description=d["error"], color=discord.Color.red()))
        return

    cpu = stats.get("cpu", {})   if isinstance(stats, dict) else {}
    mem = stats.get("memory",{}) if isinstance(stats, dict) else {}
    gpu = stats.get("gpu", {})   if isinstance(stats, dict) else {}

    embed = discord.Embed(
        title="🦾 Aria AGI — Status",
        color=discord.Color.from_rgb(0,212,255) if d.get("ollama") else discord.Color.red(),
        timestamp=datetime.now()
    )
    # Row 1
    embed.add_field(name="🤖 Ollama", value="✅ Online" if d.get("ollama") else "❌ Offline", inline=True)
    embed.add_field(name="📦 Model",  value=f"`{d.get('current_model','?')}`",              inline=True)
    embed.add_field(name="🎮 Mode",   value=d.get("mode","normal"),                          inline=True)
    # Row 2
    cpu_v = f"{cpu.get('total',0)}%  ({cpu.get('count',0)} cores)" if cpu else "N/A"
    mem_v = f"{mem.get('percent',0)}%  ({mem.get('used_gb',0)}/{mem.get('total_gb',0)} GB)" if mem else "N/A"
    embed.add_field(name="⚡ CPU",  value=cpu_v, inline=True)
    embed.add_field(name="🧠 RAM",  value=mem_v, inline=True)
    if gpu and gpu.get("available"):
        embed.add_field(name="🎮 GPU",
            value=f"{gpu['name'][:20]}\n{gpu['util_pct']}% util  {gpu['mem_used_mb']}MB/{gpu['mem_total_mb']}MB",
            inline=True)
    else:
        embed.add_field(name="🎮 GPU", value="Not available", inline=True)
    # Row 3
    vol_v = f"{'🔇 Muted' if d.get('muted') else '🔊'} {d.get('volume',0)}%"
    embed.add_field(name="🔊 Volume",  value=vol_v,                        inline=True)
    embed.add_field(name="🌐 Web UI",  value=f"[Open]({ARIA_URL})",        inline=True)
    embed.add_field(name="🏠 Version", value=f"`{d.get('version','?')}`",  inline=True)

    models = d.get("models", [])
    if models:
        embed.add_field(name=f"📦 Models ({len(models)})",
                        value=" · ".join(f"`{m}`" for m in models[:6]),
                        inline=False)
    embed.set_footer(text=f"workspace: {d.get('workspace','.')}  ·  {ts_footer()}")

    view = StatusView()
    await inter.followup.send(embed=embed, view=view)


class StatusView(discord.ui.View):
    def __init__(self): super().__init__(timeout=120)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, inter: discord.Interaction, btn: discord.ui.Button):
        await inter.response.defer()
        d     = await api_get("/api/status")
        stats = await api_get("/api/system_stats")
        cpu   = stats.get("cpu",{}) if isinstance(stats,dict) else {}
        mem   = stats.get("memory",{}) if isinstance(stats,dict) else {}
        msg   = (f"⚡ CPU: {cpu.get('total',0)}%  |  "
                 f"🧠 RAM: {mem.get('percent',0)}%  |  "
                 f"🤖 Ollama: {'✅' if d.get('ollama') else '❌'}")
        await inter.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="🔇 Toggle Mute", style=discord.ButtonStyle.secondary)
    async def mute(self, inter: discord.Interaction, btn: discord.ui.Button):
        r = await api_post("/api/volume", {"action": "toggle_mute"})
        await inter.response.send_message(r.get("result","?"), ephemeral=True)

    @discord.ui.button(label="🔊 Vol+10", style=discord.ButtonStyle.secondary)
    async def vol_up(self, inter: discord.Interaction, btn: discord.ui.Button):
        r = await api_post("/api/volume", {"action": "up", "delta": 10})
        await inter.response.send_message(r.get("result","?"), ephemeral=True)


@bot.tree.command(name="models", description="🤖 ดู models ที่ติดตั้ง")
async def slash_models(inter: discord.Interaction):
    await inter.response.defer(thinking=True)
    data = await api_get("/api/models")
    d2   = await api_get("/api/status")
    models  = data.get("models", [])
    current = d2.get("current_model", "")
    if not models:
        await inter.followup.send("❌ ไม่พบ models — รัน: `ollama pull qwen2.5:7b`")
        return
    lines = [
        f"{'▶ ' if m==current else '  '}`{m}`{'  ← current' if m==current else ''}"
        for m in models
    ]
    embed = discord.Embed(
        title=f"🤖 Models ({len(models)} installed)",
        description="\n".join(lines),
        color=discord.Color.purple()
    )
    embed.set_footer(text=f"current: {current}")
    await inter.followup.send(embed=embed)


@bot.tree.command(name="switch", description="🔄 เปลี่ยน AI model")
@app_commands.describe(model="Model name เช่น `deepseek-r1:8b`")
async def slash_switch(inter: discord.Interaction, model: str):
    await inter.response.defer(thinking=True)
    r = await api_post("/api/switch_model", {"model": model})
    ok = r.get("ok", False)
    embed = discord.Embed(
        description=f"{'✅ Switched to' if ok else '❌ Failed:'} `{model}`",
        color=status_color(ok)
    )
    if ok:
        # Clear all conversation history since model changed
        _conv.clear()
        embed.set_footer(text="Conversation history cleared")
    await inter.followup.send(embed=embed)


@bot.tree.command(name="pull", description="⬇ Download model จาก Ollama")
@app_commands.describe(model="เช่น `deepseek-r1:8b` `llama3.1:8b` `gemma3:9b`")
async def slash_pull(inter: discord.Interaction, model: str):
    await inter.response.defer(thinking=True)
    msg = await inter.followup.send(f"⬇ Pulling `{model}`… (อาจใช้เวลาหลายนาที)")
    last_status = ""
    try:
        url = f"{ARIA_URL}/api/pull_model"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"model": model},
                              timeout=aiohttp.ClientTimeout(total=600)) as r:
                async for line in r.content:
                    txt = line.decode("utf-8", errors="replace").strip()
                    if not txt.startswith("data: "): continue
                    raw = txt[6:]
                    if raw == "[DONE]":
                        await msg.edit(content=f"✅ `{model}` downloaded!")
                        return
                    try:
                        d = json.loads(raw)
                        status = d.get("status","")
                        if status and status != last_status:
                            last_status = status
                            await msg.edit(content=f"⬇ `{model}`: {status[:100]}")
                    except: pass
    except Exception as e:
        await msg.edit(content=f"❌ Pull failed: {e}")


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — MEMORY + WEATHER + WEB
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="memory", description="🧠 Aria memory management")
@app_commands.describe(
    action="get / set / forget / clear",
    key="Memory key", value="Memory value (สำหรับ set)"
)
async def slash_memory(inter: discord.Interaction, action: str = "get",
                       key: str = "", value: str = ""):
    await inter.response.defer(thinking=True)
    if action == "get":
        d    = await api_get("/api/memory")
        mems = d.get("memories", [])
        if not mems:
            await inter.followup.send("🧠 ยังไม่มีความจำ — ลอง `จำว่า X คือ Y` ใน chat")
            return
        lines = [f"• **{m['key']}**: {m['value']}" for m in mems[:20]]
        embed = discord.Embed(
            title=f"🧠 Memory ({len(mems)} entries)",
            description="\n".join(lines),
            color=discord.Color.purple()
        )
        await inter.followup.send(embed=embed)
    elif action == "set" and key:
        r = await api_post("/api/memory", {"action":"remember","key":key,"value":value})
        await inter.followup.send(f"✅ จำแล้ว: **{key}** = {value}")
    elif action == "forget" and key:
        await api_post("/api/memory", {"action":"forget","key":key})
        await inter.followup.send(f"🗑 ลืม: **{key}**")
    elif action == "clear":
        _conv.clear()
        await inter.followup.send("✅ ล้าง conversation history ทั้งหมด")


@bot.tree.command(name="weather", description="🌤 ดูสภาพอากาศ")
@app_commands.describe(city="ชื่อเมือง เช่น Bangkok, Chiang Mai, Tokyo", lang="th หรือ en")
async def slash_weather(inter: discord.Interaction, city: str = "Bangkok",
                        lang: str = "th"):
    await inter.response.defer(thinking=True)
    d = await api_get("/api/weather", {"city": city, "lang": lang})
    if not d.get("ok"):
        await inter.followup.send(f"❌ {d.get('error','error')}")
        return
    c   = d.get("current", {})
    loc = d.get("location", {})
    fc  = d.get("forecast", [])
    embed = discord.Embed(
        title=f"{c.get('icon','')} {loc.get('name',city)}, {loc.get('country','')}",
        color=discord.Color.from_rgb(0,180,255),
        timestamp=datetime.now()
    )
    embed.add_field(name="🌡 Temp",     value=f"{c.get('temp','?')}°C (feels {c.get('feels','?')}°C)", inline=True)
    embed.add_field(name="💧 Humidity", value=f"{c.get('humid','?')}%", inline=True)
    embed.add_field(name="💨 Wind",     value=f"{c.get('wind_speed','?')} km/h {c.get('wind_dir','')}", inline=True)
    embed.add_field(name="☔ Rain",     value=f"{c.get('rain','?')} mm", inline=True)
    embed.add_field(name="☀️ UV",       value=f"{(c.get('uv') or 0):.1f}", inline=True)
    embed.add_field(name="🔵 Pressure", value=f"{c.get('pressure','?')} hPa", inline=True)
    if fc:
        fc_str = "  ".join(f"{f['day']} {f['icon']} **{f['max']}**/{f['min']}° {f['rain_p']}%💧" for f in fc[:5])
        embed.add_field(name="📅 5-Day Forecast", value=fc_str, inline=False)
    embed.set_footer(text=f"{c.get('desc','')} · {'☀️ Day' if c.get('is_day') else '🌙 Night'}")
    await inter.followup.send(embed=embed)


@bot.tree.command(name="websearch", description="🌐 ค้นหาอินเทอร์เน็ต")
@app_commands.describe(query="คำค้นหา", results="จำนวนผลลัพธ์ (1-8)")
async def slash_websearch(inter: discord.Interaction, query: str, results: int = 5):
    await inter.response.defer(thinking=True)
    data = await api_get("/api/web/search", {"q": query, "n": min(results,8)})
    items = data.get("results", [])
    if not items:
        await inter.followup.send(f"❌ ไม่พบผลลัพธ์สำหรับ: `{query}`")
        return
    embed = discord.Embed(
        title=f"🌐 {query[:60]}",
        color=discord.Color.blue()
    )
    for r in items[:5]:
        if r.get("title"):
            snippet = r.get("snippet","")[:120]
            url     = r.get("url","")
            embed.add_field(
                name=r["title"][:100],
                value=f"{snippet}\n[{url[:50]}]({url})" if url else snippet,
                inline=False
            )
    embed.set_footer(text=f"{len(items)} results  ·  {ts_footer()}")
    await inter.followup.send(embed=embed)


# ════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS — WORKSPACE + HELP
# ════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="workspace", description="📁 ตั้ง/ดู workspace directory")
@app_commands.describe(path="Path ที่ต้องการตั้ง (เว้นว่างเพื่อดูปัจจุบัน)")
async def slash_workspace(inter: discord.Interaction, path: str = ""):
    await inter.response.defer(thinking=True)
    if not path:
        d = await api_get("/api/status")
        await inter.followup.send(f"📁 Workspace: `{d.get('workspace','.')}`")
        return
    r = await api_post("/api/code/workspace", {"path": path})
    ok = r.get("ok", False)
    embed = discord.Embed(
        description=f"{'✅' if ok else '❌'} Workspace: `{r.get('workspace', path)}`",
        color=status_color(ok)
    )
    await inter.followup.send(embed=embed)


@bot.tree.command(name="help", description="❓ ดูคำสั่งทั้งหมด")
async def slash_help(inter: discord.Interaction):
    embed = discord.Embed(
        title="🦾 Aria AGI — Command Reference",
        description=f"AI + Full Local System Access\nAria Server: {ARIA_URL}",
        color=discord.Color.from_rgb(0,212,255)
    )
    GROUPS = [
        ("💬 Chat & AI", [
            ("/aria <msg> [mode] [clear]", "Chat with AI — mode: normal/coding/3d/creative"),
            ("@Aria <msg>",               "Mention bot anywhere"),
        ]),
        ("🐍 Code Execution", [
            ("/run <code>",      "Execute Python code"),
            ("/shell <cmd>",     "Run shell/terminal command"),
            ("/trace <code>",    "Step-by-step debug trace with locals"),
            ("/profile <code>",  "cProfile — per-function timing"),
            ("/analyze <code>",  "AST analysis — call graph & data flow"),
        ]),
        ("📁 File Management", [
            ("/file <path>",              "Read file"),
            ("/create <path> <content>",  "Create or overwrite file"),
            ("/edit <path> <old> <new>",  "Find & replace in file"),
            ("/ls <path>",                "List directory"),
            ("/find <pattern>",           "Find files by pattern"),
            ("/delete <path> confirm:yes","Delete file/folder"),
            ("/search <query>",           "Grep search in files"),
        ]),
        ("🔀 Git", [
            ("/git status",          "Git status + quick action buttons"),
            ("/git log",             "Git log"),
            ("/git commit <msg>",    "Commit with message"),
            ("/git push",            "Push to remote"),
            ("/git pull",            "Pull from remote"),
            ("/git diff",            "Show diff"),
        ]),
        ("🔧 Dev Tools", [
            ("/test [path]",        "Run tests (auto-detect pytest/jest/go)"),
            ("/install [pkg]",      "Install dependencies"),
            ("/lint <file>",        "Lint file (ruff/flake8/eslint)"),
            ("/workspace [path]",   "Set/view workspace directory"),
        ]),
        ("🤖 Models", [
            ("/models",         "List installed models"),
            ("/switch <model>", "Switch AI model"),
            ("/pull <model>",   "Download model from Ollama"),
        ]),
        ("🌐 Web & Info", [
            ("/websearch <q>",   "Search the web (DuckDuckGo)"),
            ("/weather <city>",  "Weather forecast"),
            ("/status",          "System stats + quick actions"),
            ("/memory <action>", "get / set key=val / forget / clear"),
        ]),
    ]
    for group, cmds in GROUPS:
        val = "\n".join(f"`{cmd}` — {desc}" for cmd,desc in cmds)
        embed.add_field(name=group, value=val, inline=False)
    embed.set_footer(text="Aria AGI v2 · discord.py · Local-first AI")
    await inter.followup.send(embed=embed)


# ════════════════════════════════════════════════════════════════════════════
#  LEGACY ! COMMANDS (fallback)
# ════════════════════════════════════════════════════════════════════════════

@bot.command(name="aria", aliases=["a"])
async def legacy_chat(ctx, *, message: str):
    add_history(ctx.channel.id, "user", message)
    async with ctx.typing():
        resp = await stream_chat(message, history=get_history(ctx.channel.id))
    add_history(ctx.channel.id, "assistant", resp)
    for chunk in split_msg(resp):
        await ctx.reply(chunk)

@bot.command(name="run")
async def legacy_run(ctx, *, code: str):
    clean = re.sub(r"```(?:python|py)?\n?", "", code).replace("```","").strip()
    async with ctx.typing():
        r = await api_post("/api/agent", {"action":"run_python","payload":{"code":clean}})
    await ctx.reply(code_block(r.get("result",r.get("error","❌"))[:1800]))

@bot.command(name="sh")
async def legacy_shell(ctx, *, command: str):
    async with ctx.typing():
        r = await api_post("/api/agent", {"action":"run_shell","payload":{"command":command,"cwd":"."}})
    await ctx.reply(code_block(r.get("result",r.get("error","❌"))[:1800]))


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    token = BOT_TOKEN
    if not token:
        print("""
╔════════════════════════════════════════════════╗
║  ❌ Discord Bot Token not found!               ║
╠════════════════════════════════════════════════╣
║  วิธีตั้งค่า:                                  ║
║  1. ไปที่ discord.com/developers/applications  ║
║  2. New Application → Bot → Reset Token        ║
║  3. ใส่ token ใน config.json:                  ║
║     { "discord_token": "YOUR_TOKEN" }          ║
║  4. หรือ environment variable:                 ║
║     set DISCORD_TOKEN=YOUR_TOKEN  (Windows)    ║
║     export DISCORD_TOKEN=YOUR_TOKEN (Linux)    ║
╠════════════════════════════════════════════════╣
║  Invite Bot URL:                               ║
║  discord.com/oauth2/authorize                  ║
║    ?client_id=YOUR_CLIENT_ID                   ║
║    &permissions=277025770560                   ║
║    &scope=bot%20applications.commands          ║
╚════════════════════════════════════════════════╝
""")
        return

    print(f"""
╔════════════════════════════════════════════════╗
║  🦾 Aria Discord Bot v2                       ║
╠════════════════════════════════════════════════╣
║  Aria Server: {ARIA_URL:<33}║
║  Make sure: python server.py is running!      ║
╚════════════════════════════════════════════════╝
""")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
