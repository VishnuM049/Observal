#!/usr/bin/env python3
"""Kiro stop hook enrichment script.

When a Kiro agent's ``stop`` hook fires, this script:
1. Reads the hook JSON payload from stdin.
2. Queries the Kiro SQLite database for the most recent
   conversation matching the working directory (``cwd``).
3. Extracts per-turn metadata: model_id, input/output char counts,
   credit usage, tools used, and context usage.
4. Merges the enriched fields into the payload and POSTs to Observal.

Usage (in a Kiro agent hook):
    python -m observal_cli.hooks.kiro_stop_hook --url http://host/api/v1/telemetry/hooks --agent-name my-agent
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


def _get_kiro_db() -> Path | None:
    """Return the first existing Kiro SQLite database across standard data dirs."""
    candidates = []
    if sys.platform == "win32":
        for var in ("LOCALAPPDATA", "APPDATA"):
            val = os.environ.get(var)
            if val:
                candidates.append(Path(val) / "kiro-cli" / "data.sqlite3")
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            candidates.append(Path(xdg) / "kiro-cli" / "data.sqlite3")
        home = Path.home()
        candidates.append(home / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3")
        candidates.append(home / ".local" / "share" / "kiro-cli" / "data.sqlite3")
    for p in candidates:
        if p.exists():
            return p
    return None


def _enrich(payload: dict) -> dict:
    """Read the Kiro SQLite DB and merge session-level stats into *payload*."""
    kiro_db = _get_kiro_db()
    if not kiro_db:
        return payload

    cwd = payload.get("cwd", "")

    try:
        conn = sqlite3.connect(f"file:{kiro_db}?mode=ro", uri=True)
        cur = conn.cursor()

        # Find the most recent conversation for this cwd
        if cwd:
            cur.execute(
                "SELECT conversation_id, value FROM conversations_v2 WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
                (cwd,),
            )
        else:
            cur.execute("SELECT conversation_id, value FROM conversations_v2 ORDER BY updated_at DESC LIMIT 1")

        row = cur.fetchone()
        conn.close()

        if not row:
            return payload

        conversation_id, value_str = row
        conv = json.loads(value_str)

        # Include the real conversation_id for cross-session linking.
        # The $PPID-based session_id (injected via sed before this script) groups
        # events within a single kiro-cli run. The conversation_id persists across
        # resumed sessions — the dashboard can use it to link related sessions.
        if conversation_id:
            payload["conversation_id"] = conversation_id
    except Exception:
        return payload

    # --- Extract model info ---
    model_info = conv.get("model_info", {})
    model_id = model_info.get("model_id", "")

    # --- Aggregate per-turn metadata ---
    history = conv.get("history", [])
    total_input_chars = 0
    total_output_chars = 0
    turn_count = 0
    models_used: set[str] = set()
    tools_used: list[str] = []
    max_context_pct = 0.0

    for entry in history:
        rm = entry.get("request_metadata")
        if not rm:
            continue
        turn_count += 1
        total_input_chars += rm.get("user_prompt_length", 0)
        total_output_chars += rm.get("response_size", 0)
        mid = rm.get("model_id", "")
        if mid:
            models_used.add(mid)
        ctx_pct = rm.get("context_usage_percentage", 0.0)
        if ctx_pct > max_context_pct:
            max_context_pct = ctx_pct
        for tool_pair in rm.get("tool_use_ids_and_names", []):
            if isinstance(tool_pair, list) and len(tool_pair) >= 2:
                tools_used.append(tool_pair[1])

    # --- Credit usage ---
    utm = conv.get("user_turn_metadata", {})
    usage_info = utm.get("usage_info", [])
    total_credits = 0.0
    for u in usage_info:
        total_credits += u.get("value", 0.0)

    # --- Resolve the actual model used ---
    # If model_id is "auto", try to use per-turn model_ids
    resolved_model = model_id
    if model_id == "auto" and models_used - {"auto"}:
        # Use the most common non-auto model
        non_auto = [m for m in models_used if m != "auto"]
        if non_auto:
            resolved_model = non_auto[0]

    # --- Merge into payload ---
    if resolved_model and not payload.get("model"):
        payload["model"] = resolved_model
    payload["turn_count"] = str(turn_count)
    payload["credits"] = f"{total_credits:.6f}"

    if tools_used:
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_tools = []
        for t in tools_used:
            if t not in seen:
                unique_tools.append(t)
                seen.add(t)
        payload["tools_used"] = ",".join(unique_tools[:20])

    return payload


def _get_parent_pid(pid: int) -> int | None:
    """Return the parent PID of *pid*, or None on failure."""
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                stat = f.read().decode(errors="ignore")
            rpar = stat.rfind(")")
            parts = stat[rpar + 2 :].split()
            return int(parts[1])
        except Exception:
            return None
    elif sys.platform == "darwin":
        import subprocess

        try:
            out = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "ppid="], text=True, timeout=2
            ).strip()
            return int(out)
        except Exception:
            return None
    elif sys.platform == "win32":
        import ctypes

        TH32CS_SNAPPROCESS = 0x00000002  # noqa: N806

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_char * 260),
            ]

        h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h == -1:
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if ctypes.windll.kernel32.Process32First(h, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == pid:
                        return entry.th32ParentProcessID
                    if not ctypes.windll.kernel32.Process32Next(h, ctypes.byref(entry)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
        return None
    return None


def _is_kiro_cli_process(pid: int) -> bool:
    """Return True if *pid* is a kiro-cli process (exact binary name check)."""
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                stat = f.read()
            start = stat.find(b"(") + 1
            end = stat.rfind(b")")
            comm = stat[start:end].decode(errors="ignore")
            return "kiro-cli" in comm
        except Exception:
            return False
    elif sys.platform == "darwin":
        import subprocess

        try:
            out = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "comm="], text=True, timeout=2
            ).strip()
            return "kiro-cli" in out
        except Exception:
            return False
    elif sys.platform == "win32":
        import ctypes

        TH32CS_SNAPPROCESS = 0x00000002  # noqa: N806

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_char * 260),
            ]

        h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h == -1:
            return False
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if ctypes.windll.kernel32.Process32First(h, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == pid:
                        exe = entry.szExeFile.decode(errors="ignore").lower()
                        return "kiro-cli" in exe
                    if not ctypes.windll.kernel32.Process32Next(h, ctypes.byref(entry)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
        return False
    return False


def _find_kiro_cli_pid() -> int | None:
    """Walk up the process tree to find the kiro-cli process PID."""
    current = os.getpid()
    for _ in range(20):
        ppid = _get_parent_pid(current)
        if ppid is None or ppid <= 1:
            break
        if _is_kiro_cli_process(ppid):
            return ppid
        current = ppid
    return None


def _resolve_hooks_url() -> str:
    """Read hooks URL from config file when no --url is provided."""
    cfg_path = Path.home() / ".observal" / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            server = cfg.get("server_url", "")
            if server:
                return f"{server.rstrip('/')}/api/v1/telemetry/hooks"
        except Exception:
            pass
    return ""


def main():
    import urllib.request

    url = ""
    agent_name = ""
    model = ""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--url" and i + 1 < len(args):
            url = args[i + 1]
        elif arg == "--agent-name" and i + 1 < len(args):
            agent_name = args[i + 1]
        elif arg == "--model" and i + 1 < len(args):
            model = args[i + 1]
    if not url:
        url = _resolve_hooks_url()
    if not url:
        sys.exit(0)

    # Read hook payload from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    payload.setdefault("service_name", "kiro")

    if not payload.get("session_id"):
        env_pid = os.environ.get("KIRO_CLI_PID")
        if env_pid:
            payload["session_id"] = f"kiro-cli-{env_pid}"
        else:
            kiro_pid = _find_kiro_cli_pid()
            if kiro_pid:
                payload["session_id"] = f"kiro-cli-{kiro_pid}"
            else:
                payload["session_id"] = f"kiro-{os.getppid()}"

    # Inject user_id and user_name from Observal config if not already present
    if not payload.get("user_id") or not payload.get("user_name"):
        try:
            cfg_path = Path.home() / ".observal" / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text())
                if not payload.get("user_id") and cfg.get("user_id"):
                    payload["user_id"] = cfg["user_id"]
                if not payload.get("user_name") and cfg.get("user_name"):
                    payload["user_name"] = cfg["user_name"]
        except Exception:
            pass

    # Inject metadata from CLI args (used on Windows where sed is unavailable)
    if agent_name:
        payload.setdefault("agent_name", agent_name)
    if model:
        payload.setdefault("model", model)

    # Enrich with SQLite data
    payload = _enrich(payload)

    # POST to Observal
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
