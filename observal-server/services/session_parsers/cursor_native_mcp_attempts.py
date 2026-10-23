# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Cursor native MCP *requested-attempt* candidates, never execution evidence.

The tested CLI's assistant CallDynamicTool input carries namespace/toolName,
including cached-tool calls without complete before/after MCP hooks. The native
transcript has neither a durable CLI-version discriminator, a call ID linking
those hooks, nor a result. This parser is NOT registered for publication.
It retains no request arguments, descriptions, user text or output.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_ALIAS = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOOL = re.compile(r"[A-Za-z0-9_.-]{1,256}\Z")
_INPUT_FIELDS = frozenset({"namespace", "toolName", "arguments", "mcpDetails"})


@dataclass(frozen=True)
class NativeMCPAttempt:
    source_line_offset: int
    block_index: int
    namespace: str
    tool: str


@dataclass(frozen=True)
class NativeMCPAttempts:
    status: str  # candidate_unversioned or unsupported; never a usage denominator
    attempts: tuple[NativeMCPAttempt, ...] = ()


def native_mcp_attempt_candidates(rows: Sequence[Mapping[str, object]]) -> NativeMCPAttempts:
    """Fail closed on unfamiliar native tool forms, source gaps or malformed identity.

    ``GetDynamicTools`` is not mandatory: cached sessions can issue a native
    ``CallDynamicTool`` without rediscovering the server in this session.
    Absence of calls is NOT zero use; missing hooks, an untested CLI version or
    an unseen tool form could hide completed calls. Caller must additionally
    check source revision, layer identity and published mapping before matching.
    """
    unsupported = NativeMCPAttempts("unsupported")
    if not rows or len(rows) > 50_000:
        return unsupported
    attempts: list[NativeMCPAttempt] = []
    for offset, row in enumerate(rows):
        raw = row.get("raw_line")
        if (
            row.get("is_source_record") != 1
            or type(row.get("line_offset")) is not int
            or row["line_offset"] != offset
            or not isinstance(raw, str)
            or not raw
            or row.get("raw_line_truncated")
            or not isinstance(row.get("source_sha256"), str)
        ):
            return unsupported
        try:
            if hashlib.sha256(raw.encode()).hexdigest() != row["source_sha256"]:
                return unsupported
            record = json.loads(raw)
        except (ValueError, RecursionError, UnicodeError):
            return unsupported
        if not isinstance(record, dict):
            return unsupported
        # Sanitary Observal collector lines are a separate, untrusted source;
        # they never create native tool attempts.
        if "_observal_cursor_mcp_v1" in record:
            if set(record) != {"_observal_cursor_mcp_v1"}:
                return unsupported
            continue
        role = record.get("role")
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            return unsupported
        for index, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name == "GetDynamicTools":
                continue
            if name != "CallDynamicTool" or role != "assistant":
                return unsupported  # Unknown native tool-use form; not a safe denominator.
            data = block.get("input")
            if not isinstance(data, dict) or set(data) != _INPUT_FIELDS:
                return unsupported
            namespace, tool = data.get("namespace"), data.get("toolName")
            if (
                not isinstance(namespace, str)
                or not _ALIAS.fullmatch(namespace)
                or not isinstance(tool, str)
                or not _TOOL.fullmatch(tool)
                or not isinstance(data.get("arguments"), dict)
                or not isinstance(data.get("mcpDetails"), dict)
                or set(data["mcpDetails"]) != {"description"}
            ):
                return unsupported
            attempts.append(NativeMCPAttempt(offset, index, namespace, tool))
    return NativeMCPAttempts("candidate_unversioned", tuple(attempts))
