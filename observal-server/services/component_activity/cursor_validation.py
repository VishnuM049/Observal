# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Read-only, fully scoped Cursor MCP collector diagnostic, not a publication.

No registry opt-in or API route uses this diagnostic. It enables isolated
warehouse acceptance without turning a hook heartbeat into a measured zero.
"""

from __future__ import annotations

from services.layer_components.extractor import _snapshot
from services.session_parsers.cursor_mcp_evidence import validate_cursor_mcp_source

from .matcher import match_invocations
from .projector import _inputs_unchanged, _mapping, _source_revision, _source_rows


async def validate_cursor_session(project_id: str, user_id: str, session_id: str) -> dict:
    """Return safe counts only; authenticate/authorize *before* calling this."""
    if not project_id or not user_id or not session_id:
        raise ValueError("The diagnostic requires a fully scoped session")
    params = {
        "param_project_id": project_id,
        "param_user_id": user_id,
        "param_harness": "cursor",
        "param_session_id": session_id,
    }
    source = await _source_rows(params)
    revision = _source_revision(source) if source is not None else None
    if revision is None:
        return {"status": "source_unavailable"}
    layer = source[0].get("layer_hash")
    if (
        not isinstance(layer, str)
        or not layer.startswith("v2_")
        or any(row.get("layer_hash") != layer for row in source)
    ):
        return {"status": "binding_missing"}
    snapshot, conflict = await _snapshot(project_id, user_id, layer)
    if conflict or snapshot is None:
        return {"status": "binding_missing"}
    validated = validate_cursor_mcp_source(
        source, user_id=user_id, session_id=session_id, layer_hash=layer, snapshot=snapshot
    )
    if validated.status != "structurally_complete":
        return {"status": validated.status}
    status, generation, candidates = await _mapping(project_id, user_id, layer, "cursor")
    if status != "complete":
        return {"status": status}
    matched = match_invocations(
        validated.invocations, {layer: candidates}, {int(row["line_offset"]): layer for row in source}
    )
    # The source, snapshot identity and mapped pin must still be identical at
    # the end of this read. Publication would need the same check at write time.
    if not await _inputs_unchanged(params, revision, source, {layer: generation}, project_id, user_id, "cursor"):
        return {"status": "stale"}
    current_snapshot, current_conflict = await _snapshot(project_id, user_id, layer)
    if current_conflict or current_snapshot != snapshot:
        return {"status": "stale"}
    return {
        "status": "structurally_complete_not_published",
        "native_attempts": validated.native_attempts,
        "rejected_attempts": validated.rejected_attempts,
        "completed_calls": len(validated.invocations),
        "matched_completed_calls": len(matched.rows),
        "unmatched_completed_calls": matched.unmatched_count,
        "collision_completed_calls": matched.collision_count,
    }
