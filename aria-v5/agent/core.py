"""
Aria Agent Core — Claude Code / Cowork Style
- Autonomous tool-use loop (plan → tool → observe → continue)
- Multi-step reasoning with self-correction
- Streaming output
- Context window management
"""
import requests, json, threading, time, re
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
#  SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════

BASE_SYSTEM = """You are Aria — an advanced AI assistant with full local system access, similar to Claude Code.

## Capabilities
You have DIRECT access to the user's computer. When asked to do something, DO IT immediately:
- **Files**: create, read, edit, delete, move, copy any file/folder
- **Shell**: run any terminal command
- **Code**: write and execute Python, JavaScript, shell scripts
- **Git**: status, commit, push, pull, branch management
- **Search**: search codebase, web search
- **Tests**: run pytest, jest, cargo test, etc.
- **Install**: pip install, npm install, cargo build

## Response Style
- **CONCISE**: Short, direct answers. No padding.
- **ACTION-FIRST**: When asked to do something, do it — then explain briefly
- **Human**: Natural Thai/English, not robotic
- **Smart**: Anticipate what the user actually needs
- For CODE: working examples immediately, minimal explanation
- For TASKS: confirm what was done in 1 line

## Tool Output Format
When you execute something, format as:
```
[ACTION] description
[RESULT] output here
```

## Context
Time: {datetime}
Model: {model}
Workspace: {workspace}
Session messages: {n}
"""

CODING_SYSTEM = BASE_SYSTEM + """
## Coding Expert Mode
You are now in expert coding mode. Additional rules:
- Always produce COMPLETE, RUNNABLE code (not pseudocode)
- Include proper error handling
- Use best practices for the language
- If fixing a bug: explain what was wrong in 1 sentence
- If writing new code: add brief inline comments for complex logic
- Suggest tests if writing a new function
"""

DESIGN_3D_SYSTEM = BASE_SYSTEM + """
## 3D Design Expert Mode
Expert in: Blender Python API, Three.js, WebGL, Unity C#, Unreal Blueprint/C++, 
CAD (FreeCAD, OpenSCAD), 3D printing (Cura/PrusaSlicer settings), GLSL shaders,
Procedural generation, Physics simulation, PBR materials.

For 3D tasks:
- Provide complete, runnable code snippets
- Explain coordinate systems and transforms clearly  
- Include material/texture setup when relevant
- Suggest optimization tips for real-time rendering
"""


# ══════════════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS (for model awareness)
# ══════════════════════════════════════════════════════════════════════

TOOL_DESCRIPTIONS = """
Available tools (use [TOOL: name] syntax in reasoning):
- [TOOL: shell] — run terminal command
- [TOOL: python] — execute Python code  
- [TOOL: create_file] — create/overwrite file
- [TOOL: read_file] — read file contents
- [TOOL: edit_file] — find & replace in file
- [TOOL: list_dir] — list directory
- [TOOL: search] — search in files
- [TOOL: git] — git operations
- [TOOL: web_search] — search the web
- [TOOL: run_tests] — run test suite
"""


# ══════════════════════════════════════════════════════════════════════
#  AGENT CLASS
# ══════════════════════════════════════════════════════════════════════

class Agent:
    def __init__(self, model: str = "qwen2.5:7b", host: str = "http://localhost:11434"):
        self.model     = model
        self.host      = host.rstrip("/")
        self.history:  list[dict] = []
        self._busy     = False
        self._lock     = threading.Lock()
        self.workspace = "."          # current working directory
        self.mode      = "normal"     # normal / coding / 3d / creative

    # ── Connection ──────────────────────────────────────────────────────────
    def check_connection(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except:
            return False

    def get_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except:
            pass
        return []

    # ── Build system prompt ─────────────────────────────────────────────────
    def _build_system(self, override: str | None = None) -> str:
        if override:
            tmpl = override
        elif self.mode == "coding":
            tmpl = CODING_SYSTEM
        elif self.mode == "3d":
            tmpl = DESIGN_3D_SYSTEM
        else:
            tmpl = BASE_SYSTEM

        # Inject context
        base = tmpl.format(
            datetime  = datetime.now().strftime("%Y-%m-%d %H:%M"),
            model     = self.model,
            workspace = self.workspace,
            n         = len(self.history),
        )

        # Add memory context if available
        try:
            from skills.memory import build_memory_context
            mem = build_memory_context("")
            if mem:
                base += f"\n\n## Your Memory\n{mem}"
        except:
            pass

        return base

    # ── Core streaming ──────────────────────────────────────────────────────
    def _stream(self, messages, on_chunk, on_done, on_error,
                system_prompt=None, tools_enabled=True):
        with self._lock:
            if self._busy:
                if on_error: on_error("กำลังประมวลผล กรุณารอ")
                return
            self._busy = True
        try:
            sys_msg = self._build_system(system_prompt)
            if tools_enabled:
                sys_msg += "\n\n" + TOOL_DESCRIPTIONS

            all_msgs = [{"role": "system", "content": sys_msg}] + messages[-60:]

            payload = {
                "model":   self.model,
                "messages": all_msgs,
                "stream":  True,
                "options": {
                    "temperature":    0.65,
                    "num_ctx":        16384,   # larger context
                    "repeat_penalty": 1.05,
                    "top_p":          0.9,
                }
            }
            resp = requests.post(
                f"{self.host}/api/chat",
                json=payload, stream=True, timeout=300
            )
            resp.raise_for_status()

            full = ""
            for raw in resp.iter_lines():
                if not raw: continue
                try: data = json.loads(raw)
                except: continue
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    full += chunk
                    if on_chunk: on_chunk(chunk)
                if data.get("done"): break

            self.history.append({"role": "assistant", "content": full})
            if on_done: on_done(full)

            # Auto-execute tool calls found in response
            if tools_enabled:
                self._try_auto_execute(full, on_chunk, on_done)

        except requests.ConnectionError:
            if self.history and self.history[-1]["role"] == "user":
                self.history.pop()
            if on_error: on_error("❌ Ollama ไม่ได้รัน — รัน: `ollama serve`")
        except requests.Timeout:
            if on_error: on_error("⏱️ Timeout — model loading, please retry")
        except Exception as e:
            if on_error: on_error(f"❌ {type(e).__name__}: {e}")
        finally:
            with self._lock: self._busy = False

    def _try_auto_execute(self, text: str, on_chunk=None, on_done=None):
        """Detect shell/python code blocks in response and optionally execute."""
        # Look for ```python ... ``` or ```bash ... ``` blocks marked [RUN]
        pattern = re.compile(
            r'\[RUN\]\s*```(?:python|bash|sh)\n(.*?)```',
            re.DOTALL
        )
        for m in pattern.finditer(text):
            code = m.group(1).strip()
            if '```python' in text[text.index('[RUN]'):text.index('[RUN]')+30]:
                from skills.agent_system import run_python
                result = run_python(code)
            else:
                from skills.agent_system import run_shell
                result = run_shell(code, cwd=self.workspace)

            if on_chunk:
                on_chunk(f"\n\n```\n{result}\n```")

    # ── Public API ──────────────────────────────────────────────────────────
    def chat(self, message: str, on_chunk=None, on_done=None,
             on_error=None, system_prompt=None):
        self.history.append({"role": "user", "content": message})
        threading.Thread(
            target=self._stream,
            args=(list(self.history), on_chunk, on_done, on_error, system_prompt, True),
            daemon=True
        ).start()

    def chat_with_content(self, content_list: list, on_chunk=None,
                          on_done=None, on_error=None, system_prompt=None):
        texts, images = [], []
        for p in content_list:
            if p.get("type") == "text":
                texts.append(p.get("text", ""))
            elif p.get("type") == "image_url":
                url = p.get("image_url", {}).get("url", "")
                if "," in url:
                    images.append(url.split(",", 1)[1])
        msg = {"role": "user", "content": "\n\n".join(texts)}
        if images: msg["images"] = images
        self.history.append(msg)
        threading.Thread(
            target=self._stream,
            args=(list(self.history), on_chunk, on_done, on_error, system_prompt, False),
            daemon=True
        ).start()

    def clear_history(self):
        self.history.clear()

    def switch_model(self, name: str):
        self.model = name
        self.history.clear()

    def set_workspace(self, path: str):
        from pathlib import Path
        p = Path(path).expanduser()
        if p.is_dir():
            self.workspace = str(p)
            return True
        return False
