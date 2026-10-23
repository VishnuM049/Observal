# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Independent server-side negative gates for the unregistered Cursor source."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from services.component_activity.matcher import match_invocations
from services.session_parsers.cursor_mcp_evidence import validate_cursor_mcp_source

USER = "22222222-2222-4222-8222-222222222222"
SESSION = "11111111-1111-4111-8111-111111111111"
LAYER = "v2_" + "a" * 60
HOOK_HASH = "b" * 64
ROOT_HASH = "c" * 64
PATH_HASH = "d" * 64
PRIVATE = "DO_NOT_WRITE_PROMPT_OR_SECRET_TO_EVIDENCE"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _event(stage: str, second: int, **extra: object) -> dict:
    return {
        "event": stage,
        "session": SESSION,
        "version": "2026.10.14-941492e",
        "platform": "darwin",
        "root_sha256": ROOT_HASH,
        "transcript_sha256": PATH_HASH,
        "hooks_sha256": HOOK_HASH,
        "user_sha256": _hash(USER),
        "observed_at": (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=second)).isoformat(),
        **extra,
    }


def _rows(events: list[dict], *, native_calls: int = 0, extra_native_tool: str = "") -> list[dict]:
    source = [{"role": "user", "message": {"content": [{"type": "text", "text": PRIVATE}]}}]
    for i in range(native_calls):
        source.append(
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "CallDynamicTool", "id": str(i), "input": {"password": PRIVATE}}
                    ]
                },
            }
        )
    if extra_native_tool:
        source.append({"role": "assistant", "message": {"content": [{"type": "tool_use", "name": extra_native_tool}]}})
    source.extend({"_observal_cursor_mcp_v1": event} for event in events)
    return [
        {
            "line_offset": index,
            "is_source_record": 1,
            "raw_line": raw,
            "source_sha256": _hash(raw),
            "line_hash": _hash(raw),
            "raw_line_truncated": 0,
            "layer_hash": LAYER,
        }
        for index, item in enumerate(source)
        if (raw := json.dumps(item, separators=(",", ":")))
    ]


def _snapshot() -> dict:
    return {
        "hash": LAYER,
        "harnesses": {"cursor": [{"path": "user:hooks.json", "hash": "sha256-" + HOOK_HASH, "content": ""}]},
    }


def _case(outcome: str = "success") -> list[dict]:
    call = _hash("unique-hook-call")
    extras = {"call_sha256": call, "server": "tracked", "tool": "ping"}
    return _rows(
        [
            _event("start", 0),
            _event("before", 1, **extras),
            _event("after", 2, **extras, outcome=outcome),
            _event("end", 3),
        ],
        native_calls=1,
    )


def _validate(rows: list[dict], snapshot: dict | None = None):
    return validate_cursor_mcp_source(
        rows, user_id=USER, session_id=SESSION, layer_hash=LAYER, snapshot=snapshot or _snapshot()
    )


def _reindex(rows: list[dict]) -> None:
    for index, row in enumerate(rows):
        row["line_offset"] = index


def _change_event(rows: list[dict], index: int, key: str, value: object) -> None:
    data = json.loads(rows[index]["raw_line"])
    data["_observal_cursor_mcp_v1"][key] = value
    raw = json.dumps(data)
    rows[index]["raw_line"] = raw
    rows[index]["source_sha256"] = _hash(raw)


def test_no_tool_requires_both_heartbeats_and_snapshot_binding():
    rows = _rows([_event("start", 0), _event("end", 1)])
    valid = _validate(rows)
    assert valid.status == "structurally_complete" and valid.native_attempts == 0 and valid.invocations == ()
    assert _validate(rows[:1]).status != "structurally_complete"
    assert _validate(rows[:2]).status == "unsupported"  # uninstrumented prior session
    assert _validate(rows, {"hash": LAYER, "harnesses": {"cursor": []}}).status == "binding_missing"
    snapshot = _snapshot()
    snapshot["harnesses"]["cursor"].append({"path": "project:.cursor/hooks.json", "hash": "sha256-" + "e" * 64})
    assert _validate(rows, snapshot).status == "binding_missing"


@pytest.mark.parametrize("outcome,expected", [("success", "success"), ("error", "error"), ("rejected", None)])
def test_native_attempts_and_paired_hook_outcomes_are_distinct(outcome, expected):
    valid = _validate(_case(outcome))
    assert valid.status == "structurally_complete" and valid.native_attempts == 1
    assert valid.rejected_attempts == int(outcome == "rejected")
    assert len(valid.invocations) == int(outcome != "rejected")
    if expected:
        assert (valid.invocations[0].mcp_server, valid.invocations[0].tool_name, valid.invocations[0].result_state) == (
            "tracked",
            "ping",
            expected,
        )
    assert PRIVATE not in repr(valid)


def test_verified_alias_and_same_tool_other_server_are_not_interchangeable():
    call1, call2 = _hash("call-one"), _hash("call-two")
    events = [_event("start", 0)]
    for i, (call, alias) in enumerate(((call1, "tracked"), (call2, "untracked"))):
        extra = {"call_sha256": call, "server": alias, "tool": "ping"}
        events.extend((_event("before", i * 2 + 1, **extra), _event("after", i * 2 + 2, **extra, outcome="success")))
    events.append(_event("end", 5))
    rows = _rows(events, native_calls=2)
    valid = _validate(rows)
    assert valid.status == "structurally_complete"
    candidate = {
        "local_name": "tracked",
        "component_id": "component",
        "component_version_id": "version",
        "identity_status": "resolved",
        "verification_status": "verified",
    }
    matched = match_invocations(
        valid.invocations, {LAYER: [candidate]}, {int(row["line_offset"]): LAYER for row in rows}
    )
    assert (matched.candidate_count, len(matched.rows), matched.unmatched_count) == (2, 1, 1)
    assert matched.rows[0]["component_id"] == "component"
    assert _hash("call-one") in matched.rows[0]["source_block_key"]
    assert PRIVATE not in str(matched.rows)
    assert (
        match_invocations(
            valid.invocations, {LAYER: [candidate, candidate]}, {int(row["line_offset"]): LAYER for row in rows}
        ).collision_count
        == 1
    )
    candidate["verification_status"] = "drifted"
    assert not match_invocations(
        valid.invocations, {LAYER: [candidate]}, {int(row["line_offset"]): LAYER for row in rows}
    ).rows


@pytest.mark.parametrize(
    "change",
    [
        "no_start",
        "no_before",
        "no_after",
        "no_end",
        "extra_native",
        "untested_tool",
        "duplicate_before",
        "duplicate_after",
        "duplicate_end",
        "duplicate_id",
        "wrong_server",
        "reorder",
        "offset_gap",
        "truncated",
        "altered_raw",
        "layer_changed",
        "other_user",
        "other_session",
        "other_version",
        "other_platform",
        "config_changed",
        "path_changed",
        "unknown_outcome",
        "private_extra",
    ],
)
def test_incomplete_ambiguous_or_unbound_source_never_validates(change):
    rows = _case()
    if change.startswith("no_"):
        offset = {"no_start": 2, "no_before": 3, "no_after": 4, "no_end": 5}[change]
        rows.pop(offset)
        _reindex(rows)
    elif change == "extra_native":
        rows = _rows([json.loads(r["raw_line"])["_observal_cursor_mcp_v1"] for r in rows[2:]], native_calls=2)
    elif change == "untested_tool":
        rows = _rows(
            [json.loads(r["raw_line"])["_observal_cursor_mcp_v1"] for r in rows[2:]],
            native_calls=1,
            extra_native_tool="future-mcp-call",
        )
    elif change.startswith("duplicate_"):
        offset = {"duplicate_before": 3, "duplicate_after": 4, "duplicate_end": 5, "duplicate_id": 3}[change]
        insertion = 4 if change == "duplicate_before" else 5
        rows.insert(insertion, copy.deepcopy(rows[offset]))
        if change == "duplicate_id":
            _change_event(rows, insertion, "observed_at", _event("before", 2)["observed_at"])
        _reindex(rows)
    elif change == "wrong_server":
        _change_event(rows, 4, "server", "other")
    elif change == "reorder":
        rows[3], rows[4] = rows[4], rows[3]
        _reindex(rows)
    elif change == "offset_gap":
        rows[3]["line_offset"] += 1
    elif change == "truncated":
        rows[3]["raw_line_truncated"] = 1
    elif change == "altered_raw":
        rows[3]["raw_line"] += " "
    elif change == "layer_changed":
        rows[4]["layer_hash"] = "v2_" + "f" * 60
    else:
        offset, key, value = {
            "other_user": (3, "user_sha256", _hash("another-user")),
            "other_session": (3, "session", "another-session"),
            "other_version": (3, "version", "future"),
            "other_platform": (3, "platform", "linux"),
            "config_changed": (3, "hooks_sha256", "e" * 64),
            "path_changed": (4, "transcript_sha256", "e" * 64),
            "unknown_outcome": (4, "outcome", "completed"),
            "private_extra": (4, "result_json", PRIVATE),
        }[change]
        _change_event(rows, offset, key, value)
    assert _validate(rows).status != "structurally_complete"


@pytest.mark.asyncio
async def test_bound_warehouse_read_is_read_only_scoped_replay_and_fail_closed(monkeypatch):
    from services.component_activity import cursor_validation as bound

    rows = _case()
    candidate = {
        "local_name": "tracked",
        "component_id": "component",
        "component_version_id": "version",
        "identity_status": "resolved",
        "verification_status": "verified",
    }
    calls: list[tuple] = []

    async def source(params):
        calls.append(("source", dict(params)))
        return copy.deepcopy(rows)

    async def snapshot(project, user, layer):
        calls.append(("snapshot", project, user, layer))
        return copy.deepcopy(_snapshot()), False

    async def mapping(project, user, layer, harness):
        calls.append(("mapping", project, user, layer, harness))
        return "complete", 20, [dict(candidate)]

    async def unchanged(*args):
        calls.append(("unchanged", args[0]))
        return True

    monkeypatch.setattr(bound, "_source_rows", source)
    monkeypatch.setattr(bound, "_snapshot", snapshot)
    monkeypatch.setattr(bound, "_mapping", mapping)
    monkeypatch.setattr(bound, "_inputs_unchanged", unchanged)
    first = await bound.validate_cursor_session("project", USER, SESSION)
    assert first == await bound.validate_cursor_session("project", USER, SESSION)
    assert first == {
        "status": "structurally_complete_not_published",
        "native_attempts": 1,
        "rejected_attempts": 0,
        "completed_calls": 1,
        "matched_completed_calls": 1,
        "unmatched_completed_calls": 0,
        "collision_completed_calls": 0,
    }
    assert calls[0][1] == {
        "param_project_id": "project",
        "param_user_id": USER,
        "param_harness": "cursor",
        "param_session_id": SESSION,
    }
    assert all(item[1:4] == ("project", USER, LAYER) for item in calls if item[0] in {"snapshot", "mapping"})
    assert PRIVATE not in str(first)
    candidate["verification_status"] = "drifted"
    assert (await bound.validate_cursor_session("project", USER, SESSION))["matched_completed_calls"] == 0
    monkeypatch.setattr(bound, "_inputs_unchanged", lambda *_: stale())

    async def stale():
        return False

    assert (await bound.validate_cursor_session("project", USER, SESSION))["status"] == "stale"
    monkeypatch.setattr(bound, "_snapshot", lambda *_: conflict())

    async def conflict():
        return None, True

    assert (await bound.validate_cursor_session("project", USER, SESSION))["status"] == "binding_missing"


@pytest.mark.parametrize(
    "key,value,index",
    [("event", ["after"], 4), ("outcome", {"status": "success"}, 4), ("observed_at", "not-a-time", 3)],
)
def test_untrusted_hook_field_types_fail_closed(key, value, index):
    rows = _case()
    _change_event(rows, index, key, value)
    assert _validate(rows).status != "structurally_complete"


def test_replay_is_deterministic_and_unregistered():
    rows = _case()
    assert _validate(rows) == _validate(copy.deepcopy(rows))
    from observal_shared.harness_registry import HARNESS_REGISTRY
    from services.session_parsers.invocations import extract_invocations

    assert HARNESS_REGISTRY["cursor"].get("invocation_extractor") is None
    assert extract_invocations("cursor", rows).status == "unsupported"
