# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Narrow, unversioned Cursor *requested* MCP feasibility; no use projection."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from services.session_parsers.cursor_native_mcp_attempts import native_mcp_attempt_candidates

PRIVATE = "PRIVATE_PROMPT_AND_ARGUMENT_MUST_NOT_BE_EXPORTED"
LAYER = "v2_" + "a" * 60


def _rows(records: list[dict]) -> list[dict]:
    result = []
    for index, record in enumerate(records):
        raw = json.dumps(record)
        result.append(
            {
                "line_offset": index,
                "is_source_record": 1,
                "raw_line": raw,
                "source_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "line_hash": hashlib.sha256(raw.encode()).hexdigest(),
                "raw_line_truncated": 0,
                "layer_hash": LAYER,
            }
        )
    return result


def _block(alias: object = "tracked", tool: object = "ping") -> dict:
    return {
        "type": "tool_use",
        "name": "CallDynamicTool",
        "input": {
            "namespace": alias,
            "toolName": tool,
            "arguments": {"private": PRIVATE},
            "mcpDetails": {"description": PRIVATE},
        },
    }


def _case(blocks: list[dict] | None = None) -> list[dict]:
    return _rows(
        [
            {"role": "user", "message": {"content": [{"type": "text", "text": json.dumps(_block())}]}},
            {"role": "assistant", "message": {"content": blocks if blocks is not None else [_block()]}},
            {"type": "session_end", "status": "completed"},
        ]
    )


def test_native_assistant_attempt_preserves_server_alias_without_args_or_result():
    rows = _case()
    extracted = native_mcp_attempt_candidates(rows)
    assert extracted.status == "candidate_unversioned"
    assert [(x.source_line_offset, x.block_index, x.namespace, x.tool) for x in extracted.attempts] == [
        (1, 0, "tracked", "ping")
    ]
    assert PRIVATE not in repr(extracted)
    assert extracted == native_mcp_attempt_candidates(copy.deepcopy(rows))
    from observal_shared.harness_registry import HARNESS_REGISTRY
    from services.session_parsers.invocations import extract_invocations

    assert not HARNESS_REGISTRY["cursor"].get("invocation_extractor")
    assert extract_invocations("cursor", rows).status == "unsupported"


def test_cached_calls_need_no_get_dynamic_tools_and_parallel_aliases_are_distinct():
    rows = _case([_block("tracked"), _block("other")])
    extracted = native_mcp_attempt_candidates(rows)
    assert extracted.status == "candidate_unversioned"
    assert [(a.block_index, a.namespace) for a in extracted.attempts] == [(0, "tracked"), (1, "other")]
    with_discovery = _case([{"type": "tool_use", "name": "GetDynamicTools", "input": {}}, _block()])
    assert [(a.source_line_offset, a.block_index) for a in native_mcp_attempt_candidates(with_discovery).attempts] == [
        (1, 1)
    ]
    assert native_mcp_attempt_candidates(_case([])).attempts == ()  # NOT a use denominator


@pytest.mark.parametrize(
    "change",
    [
        "missing_namespace",
        "unknown_namespace_form",
        "invalid_tool",
        "bad_args",
        "missing_details",
        "extra_field",
        "new_tool_form",
        "fake_user_role",
        "bad_digest",
        "truncated",
        "offset_gap",
        "non_object",
        "bad_collector_envelope",
    ],
)
def test_unfamiliar_or_spoofed_native_record_fails_closed(change):
    rows = _case()
    native = json.loads(rows[1]["raw_line"])
    block = native["message"]["content"][0]
    if change == "missing_namespace":
        block["input"].pop("namespace")
    elif change == "unknown_namespace_form":
        block["input"]["namespace"] = ["tracked"]
    elif change == "invalid_tool":
        block["input"]["toolName"] = "ping/../other"
    elif change == "bad_args":
        block["input"]["arguments"] = PRIVATE
    elif change == "missing_details":
        block["input"].pop("mcpDetails")
    elif change == "extra_field":
        block["input"]["secret"] = PRIVATE
    elif change == "new_tool_form":
        block["name"] = "MCP:ping"
    elif change == "fake_user_role":
        native["role"] = "user"
    elif change == "non_object":
        native = [native]
    elif change == "bad_collector_envelope":
        native = {"_observal_cursor_mcp_v1": {"event": "before"}, "role": "assistant"}
    elif change == "bad_digest":
        rows[1]["source_sha256"] = "bad"
    elif change == "truncated":
        rows[1]["raw_line_truncated"] = 1
    elif change == "offset_gap":
        rows[1]["line_offset"] = 20
    if change not in {"bad_digest", "truncated", "offset_gap"}:
        raw = json.dumps(native)
        rows[1]["raw_line"] = raw
        rows[1]["source_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    assert native_mcp_attempt_candidates(rows).status == "unsupported"


@pytest.mark.asyncio
async def test_scoped_read_only_matcher_does_not_infer_completion_or_zero(monkeypatch):
    from services.component_activity import cursor_native_validation as diagnostic

    rows = _case([_block("tracked"), _block("other"), _block("unknown")])
    candidates = [
        {
            "local_name": "tracked",
            "identity_status": "resolved",
            "verification_status": "verified",
            "component_id": "id",
            "component_version_id": "version",
        },
        {
            "local_name": "other",
            "identity_status": "resolved",
            "verification_status": "drifted",
            "component_id": "id2",
            "component_version_id": "version2",
        },
    ]
    calls = []

    async def source(params):
        calls.append(("source", dict(params)))
        return copy.deepcopy(rows)

    async def snapshot(*scope):
        calls.append(("snapshot", scope))
        return {"harnesses": {"cursor": []}}, False

    async def mapping(*scope):
        calls.append(("mapping", scope))
        return "complete", 7, copy.deepcopy(candidates)

    async def unchanged(*args):
        calls.append(("unchanged", args[0]))
        return True

    monkeypatch.setattr(diagnostic, "_source_rows", source)
    monkeypatch.setattr(diagnostic, "_snapshot", snapshot)
    monkeypatch.setattr(diagnostic, "_mapping", mapping)
    monkeypatch.setattr(diagnostic, "_inputs_unchanged", unchanged)
    first = await diagnostic.validate_cursor_native_attempts("project", "user", "session")
    assert first == await diagnostic.validate_cursor_native_attempts("project", "user", "session")
    assert first == {
        "status": "unversioned_requested_attempt_candidates_not_published",
        "requested_attempt_candidates": 3,
        "pinned_alias_candidates": 1,
        "ambiguous_alias_candidates": 0,
        "unmatched_alias_candidates": 2,
        "completed_calls": None,
    }
    assert calls[0][1] == {
        "param_project_id": "project",
        "param_user_id": "user",
        "param_harness": "cursor",
        "param_session_id": "session",
    }
    assert all(call[1][:3] == ("project", "user", LAYER) for call in calls if call[0] in {"snapshot", "mapping"})
    assert PRIVATE not in repr(first)
    candidates.append(dict(candidates[0]))
    ambiguous = await diagnostic.validate_cursor_native_attempts("project", "user", "session")
    assert (ambiguous["pinned_alias_candidates"], ambiguous["ambiguous_alias_candidates"]) == (0, 1)
    rows[:] = _case([])
    assert (await diagnostic.validate_cursor_native_attempts("project", "user", "session"))[
        "status"
    ] == "no_native_attempt_signal"
    rows[:] = _case([_block("tracked")])

    async def stale(*_args):
        return False

    monkeypatch.setattr(diagnostic, "_inputs_unchanged", stale)
    assert (await diagnostic.validate_cursor_native_attempts("project", "user", "session"))["status"] == "stale"

    async def conflicted(*_args):
        return None, True

    monkeypatch.setattr(diagnostic, "_snapshot", conflicted)
    assert (await diagnostic.validate_cursor_native_attempts("project", "user", "session"))[
        "status"
    ] == "binding_missing"
