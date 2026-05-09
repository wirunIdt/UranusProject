"""
ARIA-AGI Discord Bot v2 — 25 slash commands + mesh network support
"""
import os, sys, json, time, asyncio, aiohttp, logging

try:
    import discord
    from discord import app_commands
    from discord.ext import commands, tasks
except ImportError:
    print("Install: pip install 'discord.py>=2.0' aiohttp")
    sys.exit(1)

log = logging.getLogger("ARIA-Discord")
logging.basicConfig(level=logging.INFO)

ARIA_URL   = os.environ.get("ARIA_URL",    "http://localhost:5000")
BOT_TOKEN  = os.environ.get("DISCORD_TOKEN", "")
GUILD_ID   = os.environ.get("GUILD_ID",    "")

intents            = discord.Intents.default()
intents.message_content = True
bot                = commands.Bot(command_prefix="!", intents=intents)
tree               = bot.tree
conversation_memory = {}  # channel_id -> [{role, content}]
MAX_HISTORY        = 20

# ── Helpers ────────────────────────────────────────────────────────────────
async def aria(method: str, path: str, body=None, timeout=30):
    async with aiohttp.ClientSession() as s:
        kw = {"timeout": aiohttp.ClientTimeout(total=timeout)}
        if method == "GET":
            async with s.get(f"{ARIA_URL}{path}", **kw) as r:
                return await r.json()
        else:
            async with s.post(f"{ARIA_URL}{path}", json=body or {}, **kw) as r:
                return await r.json()

def add_history(channel_id, role, content):
    h = conversation_memory.setdefault(channel_id, [])
    h.append({"role": role, "content": content[:2000]})
    if len(h) > MAX_HISTORY:
        h.pop(0)

def embed(title, desc="", color=0x00ff88):
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text="ARIA-AGI v3.0")
    return e

def err_embed(msg):
    return embed("❌ Error", msg, 0xff3c3c)

async def safe_reply(interaction, **kw):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(**kw)
        else:
            await interaction.followup.send(**kw)
    except Exception as e:
        log.error(f"Reply error: {e}")

# ── Bot Events ─────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await tree.sync()
    log.info(f"ARIA Bot ready: {bot.user}")
    status_task.start()

@tasks.loop(seconds=60)
async def status_task():
    try:
        r = await aria("GET", "/api/status")
        cpu = r.get("cpu",{}).get("percent",0)
        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"CPU {cpu:.0f}% | {r.get('model','?')}"
        ))
    except:
        pass

# ── /aria ──────────────────────────────────────────────────────────────────
@tree.command(name="aria", description="คุยกับ ARIA AI")
@app_commands.describe(message="ข้อความ")
async def cmd_aria(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)
    cid = str(interaction.channel_id)
    add_history(cid, "user", message)
    try:
        async with aiohttp.ClientSession() as s:
            full = ""
            async with s.post(f"{ARIA_URL}/api/chat",
                json={"message": message, "memory": False},
                timeout=aiohttp.ClientTimeout(total=60)) as r:
                async for line in r.content:
                    line = line.decode().strip()
                    if line.startswith("data: "):
                        try:
                            d = json.loads(line[6:])
                            if d.get("content"): full += d["content"]
                        except: pass
        add_history(cid, "assistant", full)
        e = embed("🤖 ARIA", full[:4000] or "No response")
        await interaction.followup.send(embed=e)
    except Exception as ex:
        await interaction.followup.send(embed=err_embed(str(ex)))

# ── /run ───────────────────────────────────────────────────────────────────
@tree.command(name="run", description="รัน shell command")
@app_commands.describe(command="shell command")
async def cmd_run(interaction: discord.Interaction, command: str):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/shell", {"cmd": command})
        out = (r.get("stdout","") + r.get("stderr",""))[:3000] or "(no output)"
        e = embed(f"$ {command[:50]}", f"```\n{out}\n```", 0x00aaff)
        e.add_field(name="Exit", value=str(r.get("code",0)))
        await safe_reply(interaction, embed=e)
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /py ────────────────────────────────────────────────────────────────────
@tree.command(name="py", description="รัน Python code")
@app_commands.describe(code="Python code")
async def cmd_py(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/python", {"code": code})
        out = r.get("stdout","") or r.get("error","") or "(no output)"
        e = embed("⟩ Python", f"```python\n{code[:500]}\n```\n```\n{out[:1000]}\n```")
        await safe_reply(interaction, embed=e)
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /shell ─────────────────────────────────────────────────────────────────
@tree.command(name="shell", description="รัน bash command")
@app_commands.describe(cmd="bash command")
async def cmd_shell(interaction: discord.Interaction, cmd: str):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/shell", {"cmd": cmd})
        out = (r.get("stdout","") + r.get("stderr",""))[:2000] or "(empty)"
        await safe_reply(interaction, embed=embed("$", f"```\n{out}\n```", 0x00cc6a))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /status ────────────────────────────────────────────────────────────────
@tree.command(name="status", description="ดู system status")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/status")
        def fmtb(b): return f"{b/1073741824:.1f}GB" if b>1e9 else f"{b/1048576:.0f}MB"
        e = embed("⎈ System Status", color=0x00aaff)
        e.add_field(name="CPU",  value=f"{r.get('cpu',{}).get('percent',0):.1f}%")
        e.add_field(name="RAM",  value=f"{r.get('memory',{}).get('percent',0):.1f}%")
        e.add_field(name="Disk", value=f"{r.get('disk',{}).get('percent',0):.1f}%")
        e.add_field(name="GPU",  value=r.get('gpu',{}).get('name','N/A') if r.get('gpu',{}).get('available') else "N/A")
        e.add_field(name="Ollama",  value="✅" if r.get("ollama") else "❌")
        e.add_field(name="Model",   value=r.get("model","--"))
        e.add_field(name="Peers",   value=str(r.get("mesh_peers",0)))
        e.add_field(name="Node IP", value=r.get("local_ip","--"))
        await safe_reply(interaction, embed=e)
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /models ────────────────────────────────────────────────────────────────
@tree.command(name="models", description="แสดง Ollama models")
async def cmd_models(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/models")
        models = r.get("models",[])
        lines = [f"{'✅' if m['name']==r.get('current') else '⬜'} {m['name']}" for m in models]
        await safe_reply(interaction, embed=embed("🤖 Models", "\n".join(lines) or "No models"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /switch ────────────────────────────────────────────────────────────────
@tree.command(name="switch", description="เปลี่ยน model")
@app_commands.describe(model="model name")
async def cmd_switch(interaction: discord.Interaction, model: str):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/models/switch", {"name": model})
        await safe_reply(interaction, embed=embed("✅ Model", f"Switched to: **{model}**"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /pull ──────────────────────────────────────────────────────────────────
@tree.command(name="pull", description="ดาวน์โหลด model")
@app_commands.describe(model="model name e.g. llama3:8b")
async def cmd_pull(interaction: discord.Interaction, model: str):
    await interaction.response.defer()
    msg = await interaction.followup.send(f"⬇ Pulling `{model}`...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{ARIA_URL}/api/models/pull", json={"name": model},
                              timeout=aiohttp.ClientTimeout(total=600)) as r:
                last = ""
                async for line in r.content:
                    line = line.decode().strip()
                    if line.startswith("data: "):
                        try:
                            d = json.loads(line[6:])
                            status = d.get("status","")
                            pct = ""
                            if d.get("total"):
                                pct = f" {d.get('completed',0)/d['total']*100:.0f}%"
                            txt = f"{status}{pct}"
                            if txt != last:
                                await msg.edit(content=f"⬇ `{model}`: {txt}")
                                last = txt
                            if d.get("done"):
                                await msg.edit(content=f"✅ `{model}` ready!")
                        except: pass
    except Exception as ex:
        await msg.edit(content=f"❌ Pull failed: {ex}")

# ── /memory ────────────────────────────────────────────────────────────────
@tree.command(name="memory", description="ดู AI memory")
@app_commands.describe(type="short/long/episodic")
async def cmd_memory(interaction: discord.Interaction, type: str = "short"):
    await interaction.response.defer()
    try:
        if type == "long":
            r = await aria("GET", "/api/memory/long")
            items = [(m["key"], m["value"][:50]) for m in r.get("memories",[])]
        elif type == "episodic":
            r = await aria("GET", "/api/memory/episodic")
            items = [(m["event"], m["detail"][:50]) for m in r.get("episodes",[])]
        else:
            r = await aria("GET", "/api/memory/short")
            items = [(m["role"], m["content"][:60]) for m in r.get("messages",[])]
        lines = [f"**{k}**: {v}" for k,v in items[:10]]
        await safe_reply(interaction, embed=embed(f"🧠 {type.title()} Memory", "\n".join(lines) or "Empty"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /peers ─────────────────────────────────────────────────────────────────
@tree.command(name="peers", description="แสดง mesh network peers")
async def cmd_peers(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/mesh/nodes")
        nodes = r.get("nodes",[])
        lines = [f"{'🔵' if n.get('is_self') else '🟢'} **{n['name']}** `{n['ip']}:{n['port']}`" for n in nodes]
        e = embed("◉ Mesh Network", "\n".join(lines) or "No peers", 0x00c8ff)
        e.add_field(name="Total", value=str(len(nodes)))
        await safe_reply(interaction, embed=e)
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /broadcast ─────────────────────────────────────────────────────────────
@tree.command(name="broadcast", description="ส่งข้อความถึงทุก mesh node")
@app_commands.describe(message="ข้อความ")
async def cmd_broadcast(interaction: discord.Interaction, message: str):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/mesh/broadcast", {"content": message})
        await safe_reply(interaction, embed=embed("📢 Broadcast", f"Sent to **{r.get('sent_to',0)}** peers: {message}"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /file ──────────────────────────────────────────────────────────────────
@tree.command(name="file", description="อ่านไฟล์")
@app_commands.describe(path="file path")
async def cmd_file(interaction: discord.Interaction, path: str):
    await interaction.response.defer()
    try:
        r = await aria("GET", f"/api/fs/read?path={path}")
        content = r.get("content","")[:3000] or r.get("error","empty")
        await safe_reply(interaction, embed=embed(f"📄 {path.split('/')[-1]}", f"```\n{content}\n```"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /ls ────────────────────────────────────────────────────────────────────
@tree.command(name="ls", description="list directory")
@app_commands.describe(path="directory path")
async def cmd_ls(interaction: discord.Interaction, path: str = "."):
    await interaction.response.defer()
    try:
        r = await aria("GET", f"/api/fs/list?path={path}")
        items = [f"{'📁' if i['type']=='dir' else '📄'} {i['name']}" for i in r.get("items",[])]
        await safe_reply(interaction, embed=embed(f"📁 {path}", "\n".join(items[:30]) or "empty"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /git ───────────────────────────────────────────────────────────────────
@tree.command(name="git", description="Git operations")
@app_commands.describe(action="status/log/diff/add/commit/push/pull")
async def cmd_git(interaction: discord.Interaction, action: str = "status"):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/git", {"action": action})
        out = (r.get("stdout","") + r.get("stderr",""))[:2000] or "(no output)"
        await safe_reply(interaction, embed=embed(f"⎇ git {action}", f"```\n{out}\n```"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /search ────────────────────────────────────────────────────────────────
@tree.command(name="search", description="Web search (DuckDuckGo)")
@app_commands.describe(query="search query")
async def cmd_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    try:
        r = await aria("GET", f"/api/websearch?q={query}")
        results = r.get("results",[])[:5]
        lines = [f"**{i+1}.** [{x.get('title','?')[:60]}]({x.get('href','')})" for i,x in enumerate(results)]
        await safe_reply(interaction, embed=embed(f"🔍 {query}", "\n".join(lines) or "No results"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /tasks ─────────────────────────────────────────────────────────────────
@tree.command(name="tasks", description="ดู task queue")
async def cmd_tasks(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/tasks")
        tasks_list = r.get("tasks",[])[:10]
        emoji = {"pending":"⏳","done":"✅","failed":"❌"}
        lines = [f"{emoji.get(t['status'],'?')} `{t['id']}` {t['desc'][:50]}" for t in tasks_list]
        await safe_reply(interaction, embed=embed("📋 Tasks", "\n".join(lines) or "No tasks"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /trace ─────────────────────────────────────────────────────────────────
@tree.command(name="trace", description="Step-by-step trace Python code")
@app_commands.describe(code="Python code")
async def cmd_trace(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    try:
        r = await aria("POST", "/api/trace", {"code": code})
        steps = r.get("steps",[])[:10]
        lines = [f"`{s['event']}` {s.get('func','')}:{s.get('line','')} {str(s.get('locals',{}))[:60]}" for s in steps]
        await safe_reply(interaction, embed=embed("🔍 Trace", "\n".join(lines) or "No steps"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /dns ───────────────────────────────────────────────────────────────────
@tree.command(name="dns", description="ดู Local DNS (.aria)")
async def cmd_dns(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/intranet/dns")
        entries = r.get("dns",{})
        lines = [f"`{h}` → `{ip}`" for h,ip in entries.items()]
        await safe_reply(interaction, embed=embed("🌐 Local DNS", "\n".join(lines) or "Empty", 0x00e5cc))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /warmode ───────────────────────────────────────────────────────────────
@tree.command(name="warmode", description="แสดง Intranet / War Mode info")
async def cmd_warmode(interaction: discord.Interaction):
    try:
        r = await aria("GET", "/api/mesh/nodes")
        peers = len([n for n in r.get("nodes",[]) if not n.get("is_self")])
        ri = await aria("GET", "/api/intranet/dns")
        rc = await aria("GET", "/api/intranet/connectivity")
        e = embed("⚔ War Mode / Offline Network", color=0xff8c00)
        e.add_field(name="External Internet", value="✅ Online" if rc.get("online") else "❌ OFFLINE")
        e.add_field(name="Mesh Peers", value=str(peers))
        e.add_field(name="DNS Entries", value=str(len(ri.get("dns",{}))))
        e.add_field(name="File Share", value="Port 47780")
        e.add_field(name="DNS Port", value="UDP 5354 (.aria)")
        e.description = "เครือข่ายภายในทำงานได้แม้ไม่มี internet จากโลกภายนอก"
        await interaction.response.send_message(embed=e)
    except Exception as ex:
        await interaction.response.send_message(embed=err_embed(str(ex)))

# ── /audit ─────────────────────────────────────────────────────────────────
@tree.command(name="audit", description="ดู audit log")
async def cmd_audit(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/audit")
        logs = r.get("logs",[])[:10]
        lines = [f"`{l['action']}` {l.get('detail','')[:40]} · {l.get('ip','')}" for l in logs]
        await safe_reply(interaction, embed=embed("🔍 Audit", "\n".join(lines) or "Empty"))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /joke ──────────────────────────────────────────────────────────────────
@tree.command(name="joke", description="ขอเรื่องตลก AI")
async def cmd_joke(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        r = await aria("GET", "/api/joke")
        await safe_reply(interaction, embed=embed("😄 Joke", r.get("joke","No joke"), 0xffb800))
    except Exception as ex:
        await safe_reply(interaction, embed=err_embed(str(ex)))

# ── /help ──────────────────────────────────────────────────────────────────
@tree.command(name="help", description="แสดงคำสั่งทั้งหมด")
async def cmd_help(interaction: discord.Interaction):
    e = embed("🤖 ARIA-AGI Bot Commands", color=0x00ff88)
    e.add_field(name="AI", value="/aria /py /shell /run /trace /search", inline=False)
    e.add_field(name="System", value="/status /models /switch /pull /tasks /audit", inline=False)
    e.add_field(name="Files", value="/file /ls /git", inline=False)
    e.add_field(name="Memory", value="/memory", inline=False)
    e.add_field(name="Mesh", value="/peers /broadcast /dns /warmode", inline=False)
    e.add_field(name="Fun", value="/joke", inline=False)
    await interaction.response.send_message(embed=e)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Set DISCORD_TOKEN environment variable")
        sys.exit(1)
    bot.run(BOT_TOKEN)
