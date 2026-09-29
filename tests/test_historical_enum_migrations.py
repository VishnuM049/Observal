# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Guard against duplicate CREATE TYPE in migrations from the v1 baseline."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

VERSIONS = Path(__file__).resolve().parents[1] / "observal-server" / "alembic" / "versions"


def _migration(filename: str):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("filename", "method"),
    [("007_invites.py", "upgrade"), ("008_remove_invites.py", "downgrade")],
)
def test_invite_table_reuses_existing_userrole(filename, method, monkeypatch):
    migration = _migration(filename)
    columns = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(create_table=lambda _, *args: columns.extend(args)))

    getattr(migration, method)()

    role = next(column for column in columns if isinstance(column, sa.Column) and column.name == "role")
    assert isinstance(role.type, ENUM)
    assert role.type.name == "userrole"
    assert role.type.create_type is False


def test_migration_jobs_does_not_recreate_explicitly_created_enums(monkeypatch):
    migration = _migration("014_migration_jobs.py")
    created = []
    columns = []
    monkeypatch.setattr(sa.Enum, "create", lambda self, bind, checkfirst: created.append((self.name, checkfirst)))
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(
            get_bind=lambda: object(),
            create_table=lambda _, *args: columns.extend(args),
            create_foreign_key=lambda *args, **kwargs: None,
            create_index=lambda *args, **kwargs: None,
        ),
    )

    migration.upgrade()

    assert created == [(name, True) for name in ("migration_operation", "migration_scope", "migration_status")]
    for column in columns:
        if isinstance(column, sa.Column) and column.name in ("operation_type", "data_scope", "status"):
            assert isinstance(column.type, ENUM)
            assert column.type.create_type is False
