"""
modules/agent.py — AI Agent / Auto-pilot
Multi-step task planning + execution with tools
"""
import os, json, time, threading, requests, subprocess, logging
from typing import Generator

log = logging.getLogger("ARIA.Agent")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# ── Available Tools ───────────────────────────────────────────────────────
TOOLS = {
    "web_search": {
        "desc": "Search the web for current information",
        "params": {"query": "search query string"},
    },
    "shell": {
        "desc": "Execute a shell command on the system",
        "params": {"cmd": "shell command to run"},
    },
    "read_file": {
        "desc": "Read contents of a file",
        "params": {"path": "absolute or relative file path"},
    },
    "write_file": {
        "desc": "Write content to a file",
        "params": {"path": "file path", "content": "text content"},
    },
    "http_get": {
        "desc": "Fetch a URL and return its content",
        "params": {"url": "URL to fetch"},
    },
    "get_weather": {
        "desc": "Get current weather and forecast for a city",
        "params": {"city": "city name"},
    },
    "get_crypto": {
        "desc": "Get current crypto prices",
        "params": {"symbols": "comma-separated symbols like BTC,ETH"},
    },
    "send_alert": {
        "desc": "Send an alert/notification via configured channels",
        "params": {"title": "alert title", "message": "alert body", "channel": "ntfy|telegram|all"},
    },
    "save_memory": {
        "desc": "Save important information to persistent memory",
        "params": {"key": "fact name", "value": "fact value"},
    },
    "finish": {
        "desc": "Task complete — return final answer to user",
        "params": {"answer": "final answer/result to present to user"},
    },
}

SYSTEM_PROMPT = """You are ARIA, an AI agent that can autonomously execute multi-step tasks.

You have access to these tools:
{tools}

RULES:
1. Think step-by-step. Plan before acting.
2. Use tools when you need real data — don't guess.
3. After each tool result, decide the next step.
4. Always call 'finish' when done with the final answer.
5. Be concise. Max 3-4 tool calls per task.

Respond ONLY with valid JSON in this format:
{{"thought": "your reasoning", "tool": "tool_name", "params": {{"param": "value"}}}}
"""

def _tool_schema_str() -> str:
    lines = []
    for name, meta in TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in meta["params"].items())
        lines.append(f"  - {name}({params}): {meta['desc']}")
    return "\n".join(lines)

def _execute_tool(tool: str, params: dict) -> str:
    """Execute a tool and return string result"""
    try:
        if tool == "web_search":
            q = params.get("query", "")
            results = []
            # Try DuckDuckGo Instant Answer API (free, no key)
            try:
                r = requests.get("https://api.duckduckgo.com/",
                    params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
                    headers={"User-Agent": "ARIA-Agent/5"},
                    timeout=8)
                d = r.json()
                if d.get("Abstract"):
                    results.append(f"Summary: {d['Abstract'][:300]}")
                if d.get("Answer"):
                    results.append(f"Answer: {d['Answer'][:200]}")
                for t in d.get("RelatedTopics", [])[:4]:
                    if isinstance(t, dict) and t.get("Text"):
                        results.append(f"- {t['Text'][:150]}")
            except Exception as e1:
                results.append(f"DuckDuckGo error: {e1}")
            # Try SearXNG public instance
            if not results:
                try:
                    r2 = requests.get("https://searx.be/search",
                        params={"q": q, "format": "json", "language": "en"},
                        headers={"User-Agent": "ARIA-Agent/5"},
                        timeout=8)
                    d2 = r2.json()
                    for item in d2.get("results", [])[:4]:
                        results.append(f"- {item.get('title','')}: {item.get('content','')[:150]}")
                except:
                    pass
            return "\n".join(results) if results else f"No search results for: {q}"

        elif tool == "shell":
            cmd = params.get("cmd", "")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip()[:2000]
            return out or "(no output)"

        elif tool == "read_file":
            path = params.get("path", "")
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(4000)

        elif tool == "write_file":
            path = params.get("path", "")
            content = params.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Written {len(content)} chars to {path}"

        elif tool == "http_get":
            url = params.get("url", "")
            r = requests.get(url, timeout=10, headers={"User-Agent": "ARIA-Agent/5"})
            # Strip HTML tags roughly
            import re
            text = re.sub(r'<[^>]+>', '', r.text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:3000]

        elif tool == "get_weather":
            from modules.weather import get_weather
            city = params.get("city", "Bangkok")
            d = get_weather(city)
            if d.get("error"): return f"Error: {d['error']}"
            return (f"{d['city']}: {d['temp']}°C {d['desc']}, "
                    f"humidity {d['humidity']}%, wind {d['wind_kph']}km/h\n"
                    f"Forecast: " + ", ".join(
                        f"{f['date']}: {f['max']}°/{f['min']}°"
                        for f in d.get("forecast", [])[:3]))

        elif tool == "get_crypto":
            from modules.finance import get_crypto_prices
            syms = [s.strip().upper() for s in params.get("symbols", "BTC,ETH").split(",")]
            prices = get_crypto_prices(syms[:5])
            return "\n".join(
                f"{p['symbol']}: ${p['price']:,.2f} ({p['change24h']:+.2f}%)"
                for p in prices if "price" in p)

        elif tool == "send_alert":
            import modules.alerts as al
            r = al.send(params.get("title", "ARIA"), params.get("message", ""),
                        params.get("channel", "ntfy"), "default", "agent")
            return f"Alert sent: {r.get('ok')}"

        elif tool == "save_memory":
            from modules.memory import save_fact
            save_fact(params.get("key", ""), params.get("value", ""), "agent")
            return f"Saved: {params.get('key')}"

        elif tool == "finish":
            return params.get("answer", "Task complete.")

        else:
            return f"Unknown tool: {tool}"

    except Exception as e:
        return f"Tool error ({tool}): {str(e)[:200]}"


def run_agent(task: str, model: str = None, max_steps: int = 6) -> Generator:
    """
    Generator that yields step-by-step agent execution.
    Each yield is a dict: {type: 'thought'|'tool'|'result'|'answer'|'error', ...}
    """
    if not model:
        model = os.environ.get("AGENT_MODEL", "qwen2.5:7b")

    system = SYSTEM_PROMPT.format(tools=_tool_schema_str())
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": f"Task: {task}"},
    ]

    yield {"type": "start", "task": task, "model": model}

    for step in range(max_steps):
        try:
            # Call Ollama
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": False,
                      "format": "json", "options": {"temperature": 0.3}},
                timeout=60
            )
            if resp.status_code != 200:
                yield {"type": "error", "msg": f"Ollama error {resp.status_code}"}
                return

            content = resp.json().get("message", {}).get("content", "{}")

            # Parse JSON response
            try:
                action = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from text
                import re
                m = re.search(r'\{.*\}', content, re.DOTALL)
                action = json.loads(m.group()) if m else {}

            thought = action.get("thought", "")
            tool    = action.get("tool", "finish")
            params  = action.get("params", {})

            yield {"type": "thought", "step": step + 1, "thought": thought,
                   "tool": tool, "params": params}

            # If finish, we're done
            if tool == "finish":
                answer = params.get("answer", thought)
                yield {"type": "answer", "answer": answer}
                return

            # Execute tool
            yield {"type": "tool", "tool": tool, "params": params}
            result = _execute_tool(tool, params)
            yield {"type": "result", "tool": tool, "result": result[:500]}

            # Add to conversation
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user",
                             "content": f"Tool result [{tool}]:\n{result[:1500]}\n\nContinue."})

        except Exception as e:
            yield {"type": "error", "msg": str(e)[:200]}
            return

    yield {"type": "answer", "answer": f"Max steps ({max_steps}) reached. Last result obtained."}


def run_agent_sync(task: str, model: str = None, max_steps: int = 6) -> dict:
    """Synchronous version — returns full result"""
    steps = []
    answer = ""
    for event in run_agent(task, model, max_steps):
        steps.append(event)
        if event["type"] == "answer":
            answer = event["answer"]
    return {"answer": answer, "steps": steps}
