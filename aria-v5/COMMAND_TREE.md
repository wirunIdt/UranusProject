# ARIA v5 Command Tree

## High-Level Runtime

```text
User
  -> Browser UI: templates/terminal.html
    -> JavaScript command parser: run(cmd, args)
      -> Flask API: server.py
        -> Local modules: modules/*.py
          -> SQLite DB files, Ollama, OS tools, web APIs
```

## Startup Tree

```text
python server.py
  -> create Flask app + CORS
  -> import modules
       system.py        system metrics via psutil/NVML
       weather.py       weather data
       finance.py       crypto/forex/market helpers
       alerts.py        notifications
       freeinet.py      DNS/Tor/network helpers
       personal_ai_prompt.py  main assistant prompt
  -> ensure_ollama()
       checks http://localhost:11434/api/tags
       starts "ollama serve" if available and offline
  -> init_db()
       aria.db tables:
         short_memory, long_memory, episodic_memory
         task_queue, audit_log, personality_traits
         mesh_nodes, mesh_messages
  -> start background threads
       mesh_listen       LAN node discovery via UDP
       mesh_heartbeat    periodic broadcast
       task_runner       runs pending AI task_queue items
  -> serve pages and /api/* endpoints
```

## Main Chat Flow

```text
/ or /terminal
  -> templates/terminal.html
    -> POST /api/chat {message, model, memory}
      -> server.api_chat()
        -> build_system_prompt()
          -> modules/personal_ai_prompt.build_personal_ai_prompt()
        -> short_memory read/write in aria.db
        -> ollama_chat_stream()
          -> POST OLLAMA_URL/api/chat
        -> Server-Sent Events stream back to UI
```

## Assistant Persona

```text
modules/personal_ai_prompt.py
  -> normalize_mode()
       LOCAL | ONLINE | HYBRID
  -> build_personal_ai_prompt()
       Iron Man-style personal AI coworker
       addresses user as Sir/Ma'am
       structured response format
       agentic behavior rules
       memory/adaptation rules
       safe tool and recovery boundaries
```

## Terminal Command Tree

```text
Model
  /models                -> GET  /api/models
  /switch <model>         -> POST /api/models/switch
  /pull <model:tag>       -> POST /api/models/pull

AI
  /agent <task>           -> POST /api/agent/run
  /run <task>             -> POST /api/agent/run
  /rag stats              -> GET  /api/rag/stats
  /rag list               -> GET  /api/rag/docs
  /rag upload <path/text> -> POST /api/rag/upload
  /rag ask <question>     -> POST /api/rag/ask/stream
  /rag delete <doc_id>    -> DELETE /api/rag/docs/<doc_id>
  /joke                   -> GET  /api/joke

System
  /status                 -> GET  /api/status
  /ps                     -> GET  /api/processes
  /kill <pid>             -> POST /api/processes/<pid>/kill
  /shell <cmd> or /sh     -> POST /api/shell
  /py <code>              -> POST /api/python
  /trace <code>           -> POST /api/trace
  /profile <code>         -> POST /api/python/profile
  /ast <code>             -> POST /api/ast

Files
  /ls [path]              -> GET  /api/fs/list
  /file <path>, /cat      -> GET  /api/fs/read
  /write <path> <content> -> POST /api/fs/write
  /find <query>           -> GET  /api/fs/search
  /git [action]           -> POST /api/git
  /upload                 -> browser file picker, expects upload/analyze APIs if enabled
  /uploads                -> list uploaded files if upload API exists
  /analyze <path> [q]     -> analyze file if analyze API exists

Memory
  /mem, /memory           -> GET  /api/memory/short or extended memory handler
  /memlong                -> GET  /api/memory/long
  /memset <key> <value>   -> POST /api/memory/long
  /memclear [short|long]  -> POST /api/memory/clear
  /history                -> local browser chat history
  /exporthistory          -> download browser chat history
  /clearhistory           -> clear browser chat history

Tasks and Logs
  /tasks                  -> GET  /api/tasks or scheduler handler
  /task <description>     -> POST /api/tasks
  /audit                  -> GET  /api/audit

Web and Apps
  /search <query>         -> GET  /api/websearch
  /web <url>              -> browser opens URL
  /open <app>             -> POST /api/shell with OS open/start/xdg-open
  /apps                   -> help text

Network and Mesh
  /peers                  -> GET  /api/mesh/nodes
  /scan                   -> POST /api/mesh/scan
  /send <ip:port> <msg>   -> POST /api/mesh/send
  /broadcast <msg>        -> POST /api/mesh/broadcast
  /inbox                  -> GET  /api/mesh/messages
  /warmode                -> GET  /api/intranet/connectivity
  /dns                    -> GET  /api/intranet/dns
  /dnsadd <host> <ip>     -> POST /api/intranet/dns/add
  /intranet               -> GET  dns + mesh + connectivity status
  /ip                     -> GET  /api/status

Encrypted Chat
  /echat status           -> GET  /api/echat/rooms
  /echat setup [phrase]   -> POST /api/echat/setup
  /echat join <key>       -> POST /api/echat/join
  /echat send <message>   -> POST /api/echat/send
  /echat read             -> GET  /api/echat/messages

Weather, Internet, Alerts
  /weather [city]         -> weather API route in server.py
  /hotspot <action>       -> hotspot API route if enabled
  /alert, /ntfy           -> notification API flow in terminal handler
```

## Backend API Families

```text
Pages
  /, /terminal, /finance, /worldmonitor, /code, /status, /network
  /intranet, /vault, /scanner, /logs, /iot

Core AI
  /api/chat
  /api/agent/run
  /api/agent/run_sync
  /api/multiagent/run
  /api/rag/*
  /api/vmem/*
  /api/improve/*
  /api/persona*

System and Code
  /api/shell
  /api/python
  /api/python/profile
  /api/trace
  /api/ast
  /api/status
  /api/processes*
  /api/git

Storage
  /api/fs/*
  /api/memory/*
  /api/scheduler/*
  /api/audit

Network
  /api/mesh/*
  /api/intranet/*
  /api/freeinet/*
  /api/ngrok/*

World Intelligence
  /api/weather/stream
  /api/finance/*
  /api/wm/*
  /api/layers/*
  /world

Integrations
  /api/echat/*
  /api/bot/discord/*
  /api/bot/line/*
  /api/iot/*
  /api/voice/transcribe
```

## Agent Execution Tree

```text
/agent <task>
  -> POST /api/agent/run
    -> modules/agent.run_agent()
      -> system prompt with tool list
      -> Ollama JSON action loop
        -> thought + tool + params
        -> _execute_tool()
          web_search  -> DuckDuckGo/SearXNG
          shell       -> subprocess.run with dangerous-command guard
          read_file   -> local file read
          write_file  -> workspace-only write guard
          http_get    -> requests.get
          get_weather -> modules.weather
          get_crypto  -> modules.finance
          send_alert  -> modules.alerts
          save_memory -> modules.memory.save_fact
          finish      -> final answer
      -> SSE progress events to terminal
```

## Multi-Agent Execution Tree

```text
/api/multiagent/run
  -> modules/multiagent.run_multiagent()
    -> planner      creates steps
    -> researcher   gathers info
    -> executor     chooses tool
    -> critic       scores result and requests retry
    -> synthesizer  final answer
```

## RAG Data Tree

```text
/rag upload
  -> /api/rag/upload
    -> modules/rag.index_document()
      -> chunk text
      -> embed with Ollama nomic-embed-text
      -> fallback TF-IDF embedding if Ollama embedding fails
      -> store in aria_rag.db

/rag ask
  -> /api/rag/ask/stream
    -> modules/rag.search()
      -> cosine similarity over stored embeddings
    -> build context
    -> Ollama answer using retrieved chunks
```

## Main Files and What They Use

```text
server.py
  Uses: Flask, CORS, requests, sqlite3, subprocess, psutil, threading, socket
  Role: app server, routes, DB init, Ollama bridge, mesh, APIs

templates/terminal.html
  Uses: browser JavaScript, fetch, SSE stream readers, localStorage
  Role: command console UI

modules/personal_ai_prompt.py
  Uses: pure Python
  Role: central persona/system prompt

modules/agent.py
  Uses: requests, subprocess, pathlib
  Role: single autonomous tool-using agent

modules/multiagent.py
  Uses: requests, subprocess
  Role: planner/researcher/executor/critic/synthesizer pipeline

modules/rag.py
  Uses: sqlite3, requests, embeddings, TF-IDF fallback
  Role: document indexing, semantic search, document Q&A

modules/memory.py
  Uses: sqlite3
  Role: persistent memories, facts, sessions

modules/system.py
  Uses: psutil, pynvml
  Role: CPU/RAM/GPU/disk/network/process monitoring

modules/scheduler.py
  Uses: sqlite3, subprocess
  Role: recurring jobs and logs

modules/freeinet.py, mesh_intranet.py, crypto_chat.py, iot.py, finance.py, weather.py
  Role: specialized tools for network, secure chat, IoT, markets, weather
```

## Safety Notes

```text
Removed/disabled:
  hidden emergency command backdoor
  prompt instruction to auto-execute model-produced code
  default emergency_key persistence

Guarded:
  agent shell command patterns that are destructive or suspicious
  agent write_file outside WORKSPACE

Still powerful:
  /api/shell and /api/python are direct local execution endpoints.
  Keep this app local or behind real authentication/VPN before exposing it online.
```
