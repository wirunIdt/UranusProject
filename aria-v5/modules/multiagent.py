"""modules/multiagent.py — Multi-Agent: Planner → Researcher → Executor → Critic"""
import os, json, time, logging, requests, re
from typing import Generator

log = logging.getLogger("ARIA.MultiAgent")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

_DANGEROUS_SHELL_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdel\s+/[sq]\b",
    r"\brmdir\s+/s\b",
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\breg\s+(add|delete)\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bcurl\b.+\|\s*(sh|bash|powershell|pwsh)",
    r"\biwr\b.+\|\s*(iex|powershell|pwsh)",
    r"\binvoke-webrequest\b.+\|\s*(iex|powershell|pwsh)",
]


def _shell_allowed(cmd: str) -> tuple[bool, str]:
    lowered = cmd.lower()
    for pattern in _DANGEROUS_SHELL_PATTERNS:
        if re.search(pattern, lowered):
            return False, f"Blocked potentially dangerous shell command pattern: {pattern}"
    return True, ""

AGENT_ROLES = {
    "planner": {
        "model": os.environ.get("PLANNER_MODEL", "qwen2.5:7b"),
        "system": """You are the Planner agent. Given a task, decompose it into 3-5 clear steps.
Output ONLY valid JSON: {"steps": [{"step":1,"action":"...","tool":"...","description":"..."}]}
Tools available: web_search, shell, http_get, get_weather, get_crypto, send_alert, save_memory, read_file, write_file, finish.
Use shell/write_file only for clearly requested local work. Do not delete, overwrite, install, exfiltrate secrets, or change security settings unless the user explicitly requested that exact action.""",
    },
    "researcher": {
        "model": os.environ.get("RESEARCHER_MODEL", "qwen2.5:7b"),
        "system": """You are the Researcher agent. Gather information needed for the given step.
Output ONLY valid JSON: {"findings": "...", "confidence": 0.0-1.0, "sources": [...]}""",
    },
    "executor": {
        "model": os.environ.get("EXECUTOR_MODEL", "qwen2.5:7b"),
        "system": """You are the Executor agent. Execute the given step using available tools.
Output ONLY valid JSON: {"tool": "tool_name", "params": {...}, "reason": "..."}""",
    },
    "critic": {
        "model": os.environ.get("CRITIC_MODEL", "qwen2.5:7b"),
        "system": """You are the Critic agent. Evaluate if the step result is satisfactory.
Output ONLY valid JSON: {"passed": true/false, "score": 0-10, "issues": [...], "suggestion": "..."}
If score < 6, set passed to false.""",
    },
    "synthesizer": {
        "model": os.environ.get("SYNTH_MODEL", "qwen2.5:7b"),
        "system": """You are the Synthesizer. Combine all step results into a final coherent answer.
Be concise, accurate, and helpful. Format with markdown if appropriate.""",
    },
}

def _llm(role: str, messages: list, timeout: int = 60) -> str:
    cfg = AGENT_ROLES[role]
    payload = {
        "model": cfg["model"],
        "stream": False,
        "messages": [{"role":"system","content":cfg["system"]}] + messages,
        "format": "json" if role != "synthesizer" else None,
        "options": {"temperature": 0.2},
    }
    if not payload["format"]:
        del payload["format"]
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        return r.json().get("message", {}).get("content", "{}").strip()
    except Exception as e:
        log.error(f"LLM error ({role}): {e}")
        return "{}"

def _parse_json(text: str) -> dict:
    import re
    try:
        return json.loads(text)
    except:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try: return json.loads(m.group())
            except: pass
        return {}

def _execute_tool(tool: str, params: dict) -> str:
    """Execute a tool — same as agent.py but standalone"""
    try:
        if tool == "web_search":
            q = params.get("query","")
            r = requests.get("https://api.duckduckgo.com/",
                params={"q":q,"format":"json","no_html":1}, timeout=8)
            d = r.json()
            return d.get("Abstract") or "\n".join(
                t.get("Text","")[:100] for t in d.get("RelatedTopics",[])[:3])
        elif tool == "get_weather":
            from modules.weather import get_weather
            w = get_weather(params.get("city","Bangkok"))
            return f"{w.get('city')}: {w.get('temp')}°C {w.get('desc')}"
        elif tool == "get_crypto":
            from modules.finance import get_crypto_prices
            syms = params.get("symbols","BTC").upper().split(",")
            prices = get_crypto_prices(syms[:3])
            return "\n".join(f"{p['symbol']}: ${p['price']:,.2f} ({p['change24h']:+.2f}%)" for p in prices if "price" in p)
        elif tool == "shell":
            import subprocess
            cmd = params.get("cmd","")
            allowed, reason = _shell_allowed(cmd)
            if not allowed:
                return reason
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr).strip()[:1000]
        elif tool == "http_get":
            r = requests.get(params.get("url",""), timeout=8)
            import re as re2
            return re2.sub(r'<[^>]+>','',r.text)[:1500]
        elif tool == "save_memory":
            from modules.memory import save_fact
            save_fact(params.get("key",""), params.get("value",""), "multiagent")
            return f"Saved: {params.get('key')}"
        elif tool == "finish":
            return params.get("answer","Done")
        else:
            return f"Unknown tool: {tool}"
    except Exception as e:
        return f"Tool error: {str(e)[:200]}"

def run_multiagent(task: str, max_retries: int = 2) -> Generator:
    """
    Full Planner → Researcher → Executor → Critic pipeline
    Yields events for SSE streaming
    """
    start_ts = time.time()
    yield {"type":"start","task":task,"agents":list(AGENT_ROLES.keys())}

    # ── PHASE 1: PLAN ─────────────────────────────────────────────────────
    yield {"type":"phase","phase":"planning","agent":"planner"}
    plan_raw = _llm("planner", [{"role":"user","content":f"Task: {task}"}])
    plan = _parse_json(plan_raw)
    steps = plan.get("steps", [{"step":1,"action":"answer_directly","description":task}])
    yield {"type":"plan","steps":steps,"count":len(steps)}

    all_results = []

    # ── PHASE 2: RESEARCH → EXECUTE → CRITIQUE each step ──────────────────
    for step in steps:
        step_n = step.get("step", 0)
        desc   = step.get("description", "")
        yield {"type":"step_start","step":step_n,"description":desc}

        # RESEARCH
        yield {"type":"phase","phase":"researching","step":step_n,"agent":"researcher"}
        research_raw = _llm("researcher", [
            {"role":"user","content":f"Task: {task}\nCurrent step: {desc}\nPrevious results: {json.dumps(all_results[-2:])}\nGather info needed."}
        ])
        research = _parse_json(research_raw)
        yield {"type":"research","step":step_n,"findings":research.get("findings",""),"confidence":research.get("confidence",0)}

        # EXECUTE (with retry on critic fail)
        step_result = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                yield {"type":"retry","step":step_n,"attempt":attempt}

            yield {"type":"phase","phase":"executing","step":step_n,"agent":"executor"}
            exec_raw = _llm("executor", [
                {"role":"user","content":f"Task: {task}\nStep: {desc}\nResearch: {research.get('findings','')}\nExecute this step."}
            ])
            exec_plan = _parse_json(exec_raw)
            tool   = exec_plan.get("tool","finish")
            params = exec_plan.get("params",{})
            yield {"type":"executing","step":step_n,"tool":tool,"params":params}

            tool_result = _execute_tool(tool, params)
            yield {"type":"tool_result","step":step_n,"tool":tool,"result":tool_result[:300]}

            # CRITIQUE
            yield {"type":"phase","phase":"critiquing","step":step_n,"agent":"critic"}
            crit_raw = _llm("critic", [
                {"role":"user","content":f"Task: {task}\nStep: {desc}\nExpected: {step.get('action','')}\nResult: {tool_result[:500]}\nEvaluate quality."}
            ])
            critique = _parse_json(crit_raw)
            yield {"type":"critique","step":step_n,"passed":critique.get("passed",True),
                   "score":critique.get("score",7),"issues":critique.get("issues",[])}

            if critique.get("passed", True) or attempt >= max_retries:
                step_result = {"step":step_n,"description":desc,"tool":tool,
                               "result":tool_result,"score":critique.get("score",7)}
                break
            # Adjust for retry using critic suggestion
            desc = critique.get("suggestion", desc)

        all_results.append(step_result)
        yield {"type":"step_done","step":step_n,"result":step_result}

    # ── PHASE 3: SYNTHESIZE ───────────────────────────────────────────────
    yield {"type":"phase","phase":"synthesizing","agent":"synthesizer"}
    results_summary = "\n".join(
        f"Step {r['step']}: {r['description']}\nResult: {r['result'][:300]}"
        for r in all_results if r
    )
    final_raw = _llm("synthesizer", [
        {"role":"user","content":f"Original task: {task}\n\nAll step results:\n{results_summary}\n\nProvide final answer."}
    ], timeout=120)

    elapsed = round(time.time() - start_ts, 1)
    yield {"type":"answer","answer":final_raw,"steps_completed":len(all_results),"elapsed_s":elapsed}

def run_multiagent_sync(task: str) -> dict:
    steps, answer = [], ""
    for ev in run_multiagent(task):
        steps.append(ev)
        if ev["type"] == "answer":
            answer = ev["answer"]
    return {"answer": answer, "events": steps}


def run_multi_agent(task: str, model: str = None, max_retries: int = 2) -> Generator:
    """Backward-compatible stream entrypoint used by server.py.

    The current multi-agent module uses per-role models from AGENT_ROLES. The
    optional model parameter is accepted for older callers and ignored.
    """
    yield from run_multiagent(task, max_retries=max_retries)


def run_multi_agent_sync(task: str, model: str = None) -> dict:
    """Backward-compatible sync entrypoint used by older callers."""
    return run_multiagent_sync(task)
