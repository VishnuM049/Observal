# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Project-skill install/presence proof; Kiro use remains unsupported here."""

from __future__ import annotations

import hashlib

from observal_cli.cmd_skill import install_skill_registry_direct
from observal_cli.harness.kiro import KiroAdapter
from observal_cli.layer import _skill_status, build_layer_manifest, skill_location_sha256
from observal_shared.harness_registry import HARNESS_REGISTRY
from services.session_parsers.skill_evidence import kind_recorded

ALIAS = "triad-proof"
CONTENT = "---\nname: triad-proof\ndescription: Inert triad proof.\n---\n\n# Safe\n"


def test_kiro_project_install_has_fingerprinted_active_path_not_confirmed_use(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    project.mkdir()
    (project / ".kiro").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KIRO_HOME", raising=False)

    installed = install_skill_registry_direct(
        name=ALIAS, skill_md_content=CONTENT, harness="kiro", scope="project", cwd=project
    )
    assert installed == project / ".agents" / "skills" / ALIAS
    active = f"project:.kiro/skills/{ALIAS}/SKILL.md"
    visible = project / ".kiro" / "skills" / ALIAS / "SKILL.md"
    assert visible.is_file() and visible.parent.is_symlink()
    assert visible.read_text() == CONTENT
    adapter = KiroAdapter()
    assert adapter.skill_manifest_path("project", ALIAS) == active
    assert adapter.skill_manifest_path("user", ALIAS) == f"user:skills/{ALIAS}/SKILL.md"
    # V3 records the .kiro symlink path, not its canonical .agents target.
    assert adapter.skill_location("project", str(project), ALIAS) == str(visible)
    expected = f"sha256-{hashlib.sha256(CONTENT.encode()).hexdigest()}"
    assert _skill_status("kiro", "project", str(project), ALIAS, expected, {active: expected}) == "verified"
    assert (
        skill_location_sha256("kiro", "project", str(project), ALIAS)
        == hashlib.sha256(str(visible).encode()).hexdigest()
    )
    assert "skills" in HARNESS_REGISTRY["kiro"]["capabilities"]
    assert not any(kind_recorded("kiro", kind, "project") for kind in ("available", "load", "invoked"))

    pin = {
        "harnesses": {
            "kiro": {
                "agents": [],
                "standalone": [
                    {
                        "type": "skill",
                        "id": "b7aac287-4f8d-4ecd-907f-a25e97e8b614",
                        "version_id": "0d794862-71c3-47ef-b664-a811f1216a47",
                        "local_name": ALIAS,
                        "scope": "project",
                        "directory": str(project),
                        "skill_integrity": expected,
                    }
                ],
            }
        }
    }
    manifest = build_layer_manifest("kiro", str(project), registry_data=pin)
    hashes = {row["path"]: row["hash"] for row in manifest}
    assert hashes[active] == expected
    assert "observal:skill-verification" in hashes
    assert all(CONTENT not in str(row) for row in manifest)

    visible.write_text("changed")
    changed = build_layer_manifest("kiro", str(project), registry_data=pin)
    changed_hashes = {row["path"]: row["hash"] for row in changed}
    assert changed_hashes[active] != expected
    # The file hash itself changes the layer identity; the synthetic entry
    # records inputs outside the file manifest (location and shadow files).
    assert changed_hashes != hashes
    assert _skill_status("kiro", "project", str(project), ALIAS, expected, changed_hashes) == "drifted"

    visible.write_text(CONTENT)
    shadow = home / ".kiro" / "skills" / ALIAS / "SKILL.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text(CONTENT)
    assert _skill_status("kiro", "project", str(project), ALIAS, expected, {active: expected}) == "unverified"
    shadow_manifest = build_layer_manifest("kiro", str(project), registry_data=pin)
    assert {row["path"]: row["hash"] for row in shadow_manifest}["observal:skill-verification"] != hashes[
        "observal:skill-verification"
    ]


def test_kiro_user_skill_path_and_nested_project_shadow(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = home / "workspace"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KIRO_HOME", raising=False)
    installed = install_skill_registry_direct(name=ALIAS, skill_md_content=CONTENT, harness="kiro", scope="user")
    user_path = f"user:skills/{ALIAS}/SKILL.md"
    adapter = KiroAdapter()
    assert installed == home / ".kiro" / "skills" / ALIAS
    assert adapter.skill_manifest_path("user", ALIAS) == user_path
    assert adapter.skill_location("user", str(project), ALIAS) == str(installed / "SKILL.md")
    expected = f"sha256-{hashlib.sha256(CONTENT.encode()).hexdigest()}"
    # An ancestor equal to the active home path is not another skill.
    shadows = adapter.skill_shadow_paths("user", str(project), ALIAS)
    assert installed / "SKILL.md" not in shadows
    assert not any(path.exists() for path in shadows)
    assert _skill_status("kiro", "user", str(project), ALIAS, expected, {user_path: expected}) == "verified"
    shadow = project / ".kiro" / "skills" / ALIAS / "SKILL.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text(CONTENT)
    assert _skill_status("kiro", "user", str(project), ALIAS, expected, {user_path: expected}) == "unverified"
    assert not kind_recorded("kiro", "load", "user")


def test_relocated_kiro_profile_cannot_claim_fixed_layer_location(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("KIRO_HOME", str(tmp_path / "moved-profile"))
    adapter = KiroAdapter()
    assert adapter.skill_manifest_path("project", ALIAS) is None
    assert adapter.skill_location("project", str(tmp_path / "workspace"), ALIAS) is None
    assert _skill_status("kiro", "project", str(tmp_path / "workspace"), ALIAS, "sha256-any", {}) == "unverified"
