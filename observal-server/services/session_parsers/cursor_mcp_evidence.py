# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Independent validation of the Cursor collector's canonical source lines.

This is deliberately NOT a registered invocation extractor. Hook records are
client-originated; validating their shape, native-attempt count, scoped layer
and configuration fingerprint is not proof of hook-script bytes or a verified
no-call denominator. Never return transcript text or hook payloads to callers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .invocation_types import SourceInvocation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_KEY = "_observal_cursor_mcp_v1"
_VERSION = "2026.10.14-941492e"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_ALIAS = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOOL = re.compile(r"[A-Za-z0-9_.-]{1,256}\Z")
_BASE = frozenset(
    {
        "event",
        "session",
        "version",
        "platform",
        "root_sha256",
        "transcript_sha256",
        "hooks_sha256",
        "user_sha256",
        "observed_at",
    }
)
_CALL = frozenset({"call_sha256", "server", "tool"})
_MAX_COLLECTOR_LINES = 1000


@dataclass(frozen=True)
class CursorMCPValidation:
    status: str  # structurally_complete, unsupported, incomplete, or binding_missing
    invocations: tuple[SourceInvocation, ...] = ()
    native_attempts: int = 0
    rejected_attempts: int = 0


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        parsed = parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        return None
    return parsed if datetime(1971, 1, 1, tzinfo=UTC) <= parsed < datetime(2100, 1, 1, tzinfo=UTC) else None


def _manifest_hash(snapshot: Mapping[str, object]) -> str | None:
    harnesses = snapshot.get("harnesses")
    cursor = harnesses.get("cursor") if isinstance(harnesses, dict) else None
    if not isinstance(cursor, list):
        return None
    hooks = [item for item in cursor if isinstance(item, dict) and item.get("path") == "user:hooks.json"]
    # A project-level hook may run alongside the user hook. Its presence removes
    # the sole-handler guarantee even when no project hook was observed.
    if len(hooks) != 1 or any(
        isinstance(item, dict) and item.get("path") == "project:.cursor/hooks.json" for item in cursor
    ):
        return None
    file_hash = hooks[0].get("hash")
    if not isinstance(file_hash, str) or not file_hash.startswith("sha256-") or not _SHA.fullmatch(file_hash[7:]):
        return None
    return file_hash[7:]


def validate_cursor_mcp_source(
    rows: Sequence[Mapping[str, object]],
    *,
    user_id: str,
    session_id: str,
    layer_hash: str,
    snapshot: Mapping[str, object],
) -> CursorMCPValidation:
    """Validate one bounded, contiguous, immutable source and one same-layer snapshot.

    The journal has no native call ID in the persisted transcript; pairing is
    limited to unique hook-side digests plus equality with native attempt count.
    Caller must separately authenticate the owner and ensure that the snapshot
    belongs to this project, user and layer hash (see ``validate_cursor_session``).
    """
    unsupported = CursorMCPValidation("unsupported")
    incomplete = CursorMCPValidation("incomplete")
    if not _UUID.fullmatch(session_id) or not _UUID.fullmatch(user_id) or not rows or len(rows) > 50_000:
        return unsupported
    manifest_hash = _manifest_hash(snapshot)
    if manifest_hash is None:
        return CursorMCPValidation("binding_missing")
    records: list[tuple[int, dict]] = []
    layers: set[str] = set()
    native_attempts = 0
    for expected_offset, row in enumerate(rows):
        raw = row.get("raw_line")
        line_layer_hash = row.get("layer_hash")
        if (
            row.get("is_source_record") != 1
            or type(row.get("line_offset")) is not int
            or row["line_offset"] != expected_offset
            or not isinstance(raw, str)
            or not raw
            or row.get("raw_line_truncated")
            or not isinstance(line_layer_hash, str)
            or not line_layer_hash.startswith("v2_")
            or not isinstance(row.get("source_sha256"), str)
        ):
            return incomplete
        try:
            if row["source_sha256"] != hashlib.sha256(raw.encode()).hexdigest():
                return incomplete
            data = json.loads(raw)
        except (ValueError, RecursionError, UnicodeError):
            return incomplete
        layers.add(line_layer_hash)
        if not isinstance(data, dict):
            return incomplete
        if _KEY in data:
            if set(data) != {_KEY} or not isinstance(data[_KEY], dict):
                return incomplete
            records.append((expected_offset, data[_KEY]))
            continue
        message = data.get("message")
        if not isinstance(message, dict):
            continue
        blocks = message.get("content", [])
        if not isinstance(blocks, list):
            return incomplete
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name == "CallDynamicTool":
                native_attempts += 1
            elif name != "GetDynamicTools":
                return unsupported  # A new native form might itself be an MCP call.
    if len(layers) != 1 or layer_hash != next(iter(layers)):
        return CursorMCPValidation("binding_missing")
    if len(records) < 2 or len(records) > _MAX_COLLECTOR_LINES:
        return unsupported  # pre-instrumentation is never a zero-use source
    events = [record for _, record in records]
    if events[0].get("event") != "start" or events[-1].get("event") != "end":
        return incomplete
    digest = hashlib.sha256(user_id.encode()).hexdigest()
    binding = {
        key: events[0].get(key)
        for key in ("session", "version", "platform", "root_sha256", "transcript_sha256", "hooks_sha256", "user_sha256")
    }
    if (
        binding["session"] != session_id
        or binding["version"] != _VERSION
        or binding["platform"] != "darwin"  # tested CLI/collector surface only
        or binding["hooks_sha256"] != manifest_hash
        or binding["user_sha256"] != digest
        or not all(
            isinstance(binding[key], str) and _SHA.fullmatch(binding[key])
            for key in ("root_sha256", "transcript_sha256")
        )
    ):
        return CursorMCPValidation("binding_missing")
    before: dict[str, tuple[int, dict, datetime]] = {}
    seen_after: set[str] = set()
    rejected_attempts = 0
    invocations: list[SourceInvocation] = []
    last_time: datetime | None = None
    for offset, record in records:
        stage = record.get("event")
        if not isinstance(stage, str):
            return incomplete
        expected_keys = _BASE | (_CALL if stage in {"before", "after"} else frozenset())
        if stage == "after":
            expected_keys |= {"outcome"}
        if set(record) != expected_keys or any(record.get(key) != value for key, value in binding.items()):
            return incomplete
        at = _time(record.get("observed_at"))
        if at is None or (last_time is not None and at < last_time):
            return incomplete
        last_time = at
        if stage in {"start", "end"}:
            if (stage == "start" and offset != records[0][0]) or (stage == "end" and offset != records[-1][0]):
                return incomplete
            continue
        if stage not in {"before", "after"}:
            return incomplete
        call = record["call_sha256"]
        server = record["server"]
        tool = record["tool"]
        if (
            not isinstance(call, str)
            or not _SHA.fullmatch(call)
            or not isinstance(server, str)
            or not _ALIAS.fullmatch(server)
            or not isinstance(tool, str)
            or not _TOOL.fullmatch(tool)
        ):
            return incomplete
        if stage == "before":
            if call in before or call in seen_after:
                return incomplete
            before[call] = offset, record, at
        else:
            prior = before.get(call)
            if prior is None or call in seen_after or (prior[1]["server"], prior[1]["tool"]) != (server, tool):
                return incomplete
            outcome = record.get("outcome")
            if not isinstance(outcome, str) or outcome not in {"success", "error", "rejected"}:
                return incomplete
            seen_after.add(call)
            rejected_attempts += int(outcome == "rejected")
            if outcome != "rejected":
                invocations.append(
                    SourceInvocation(
                        prior[0],
                        f"cursor-call:{call}",
                        tool,
                        "",
                        at,
                        "success" if outcome == "success" else "error",
                        mcp_server=server,
                    )
                )
    if len(before) != len(seen_after) or native_attempts != len(before):
        return incomplete
    return CursorMCPValidation("structurally_complete", tuple(invocations), native_attempts, rejected_attempts)
