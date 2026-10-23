# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Read-only Cursor native requested-attempt feasibility check. No publication.

A native CallDynamicTool is a requested tool, NOT a completed call, successful
result or verified runtime version. The response intentionally exposes only
safe diagnostic counts; no API or report calls this function.
"""

from __future__ import annotations

from services.layer_components.extractor import _snapshot
from services.session_parsers.cursor_native_mcp_attempts import native_mcp_attempt_candidates

from .projector import _inputs_unchanged, _mapping, _source_revision, _source_rows


async def validate_cursor_native_attempts(project_id: str, user_id: str, session_id: str) -> dict:
    """For a caller-authorized session, match only distinct verified pinned aliases."""
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
    if snapshot is None or conflict:
        return {"status": "binding_missing"}
    extracted = native_mcp_attempt_candidates(source)
    if extracted.status != "candidate_unversioned":
        return {"status": "unsupported_native_form"}
    # No native call is not a measured zero, especially when hooks were absent.
    if not extracted.attempts:
        return {"status": "no_native_attempt_signal"}
    status, generation, candidates = await _mapping(project_id, user_id, layer, "cursor")
    if status != "complete":
        return {"status": status}
    matched = 0
    collisions = 0
    unmatched = 0
    for attempt in extracted.attempts:
        aliases = [candidate for candidate in candidates if candidate.get("local_name") == attempt.namespace]
        if len(aliases) > 1:
            collisions += 1
        elif (
            len(aliases) == 1
            and aliases[0].get("identity_status") == "resolved"
            and aliases[0].get("verification_status") == "verified"
            and aliases[0].get("component_id")
            and aliases[0].get("component_version_id")
        ):
            matched += 1
        else:
            unmatched += 1
    if not await _inputs_unchanged(params, revision, source, {layer: generation}, project_id, user_id, "cursor"):
        return {"status": "stale"}
    current_snapshot, current_conflict = await _snapshot(project_id, user_id, layer)
    if current_conflict or current_snapshot != snapshot:
        return {"status": "stale"}
    return {
        "status": "unversioned_requested_attempt_candidates_not_published",
        "requested_attempt_candidates": len(extracted.attempts),
        "pinned_alias_candidates": matched,
        "ambiguous_alias_candidates": collisions,
        "unmatched_alias_candidates": unmatched,
        "completed_calls": None,
    }
