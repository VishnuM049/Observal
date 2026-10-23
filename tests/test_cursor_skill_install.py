# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Cursor's user-scope native skill folder is not its legacy rules directory."""

from __future__ import annotations

import hashlib

from observal_cli.cmd_skill import install_skill_registry_direct
from observal_cli.harness.cursor import CursorAdapter
from observal_cli.layer import _skill_status, build_layer_manifest, skill_location_sha256
from observal_shared.harness_registry import HARNESS_REGISTRY
from services.session_parsers.skill_evidence import kind_recorded


def test_cursor_user_skill_stays_in_native_skill_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    installed = install_skill_registry_direct(
        name="triad-proof",
        skill_md_content="---\nname: triad-proof\ndescription: Inert proof\n---\n",
        harness="cursor",
        scope="user",
    )
    assert installed == home / ".cursor" / "skills" / "triad-proof"
    assert (installed / "SKILL.md").is_file()
    assert not (home / ".cursor" / "rules" / "triad-proof").exists()
    assert "skills" in HARNESS_REGISTRY["cursor"]["capabilities"]
    user_path = "user:skills/triad-proof/SKILL.md"
    assert CursorAdapter().skill_manifest_path("user", "triad-proof") == user_path
    assert CursorAdapter().skill_location("user", None, "triad-proof") == str(installed / "SKILL.md")
    expected = f"sha256-{hashlib.sha256((installed / 'SKILL.md').read_bytes()).hexdigest()}"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert _skill_status("cursor", "user", str(workspace), "triad-proof", expected, {user_path: expected}) == (
        "verified"
    )
    # Correct placement is an install fact, not a claim of native use.
    assert not any(kind_recorded("cursor", kind, "user") for kind in ("available", "load", "invoked"))


def test_cursor_project_native_symlink_is_bound_to_canonical_location(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    project.mkdir()
    (project / ".cursor").mkdir()
    monkeypatch.setenv("HOME", str(home))
    content = "---\nname: triad-proof\ndescription: Inert proof\n---\nSafe"
    installed = install_skill_registry_direct(
        name="triad-proof", skill_md_content=content, harness="cursor", scope="project", cwd=project
    )
    assert installed == project / ".agents" / "skills" / "triad-proof"
    active = "project:.cursor/skills/triad-proof/SKILL.md"
    visible = project / ".cursor" / "skills" / "triad-proof" / "SKILL.md"
    assert visible.is_file() and visible.parent.is_symlink()
    adapter = CursorAdapter()
    # Cursor 2026.10.14's native expansion resolves the link, unlike Kiro V3.
    assert adapter.skill_location("project", str(project), "triad-proof") == str((installed / "SKILL.md").resolve())
    expected = f"sha256-{hashlib.sha256(content.encode()).hexdigest()}"
    assert _skill_status("cursor", "project", str(project), "triad-proof", expected, {active: expected}) == "verified"
    assert (
        skill_location_sha256("cursor", "project", str(project), "triad-proof")
        == hashlib.sha256(str((installed / "SKILL.md").resolve()).encode()).hexdigest()
    )
    pin = {
        "harnesses": {
            "cursor": {
                "agents": [],
                "standalone": [
                    {
                        "type": "skill",
                        "id": "da0b30ce-26fe-454c-beed-c0e2c8a47aad",
                        "version_id": "9808b4b8-e29f-4b04-8731-27760075ea0c",
                        "local_name": "triad-proof",
                        "scope": "project",
                        "directory": str(project),
                        "skill_integrity": expected,
                    }
                ],
            }
        }
    }
    hashes = {v["path"]: v["hash"] for v in build_layer_manifest("cursor", str(project), registry_data=pin)}
    assert hashes[active] == expected
    assert "observal:skill-verification" in hashes
    visible.write_text("changed")
    changed = {v["path"]: v["hash"] for v in build_layer_manifest("cursor", str(project), registry_data=pin)}
    assert changed[active] != expected
    assert _skill_status("cursor", "project", str(project), "triad-proof", expected, changed) == "drifted"
    visible.write_text(content)
    shadow = home / ".cursor" / "skills" / "triad-proof" / "SKILL.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text(content)
    assert _skill_status("cursor", "project", str(project), "triad-proof", expected, {active: expected}) == (
        "unverified"
    )
    assert {v["path"]: v["hash"] for v in build_layer_manifest("cursor", str(project), registry_data=pin)}[
        "observal:skill-verification"
    ] != hashes["observal:skill-verification"]
