import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import Table

from app.models.agent_runs import (
    AgentObservationRecord,
    AgentPlanVersion,
    AgentRun,
    AgentStep,
)

FORBIDDEN_COLUMNS = {
    "question",
    "prompt",
    "reasoning",
    "arguments",
    "excerpt",
    "document_text",
    "memory_content",
    "authorization_scope",
    "credentials",
    "token",
    "password",
    "stack_trace",
    "filesystem_path",
}


def test_persistence_models_have_only_metadata_columns_and_named_constraints() -> None:
    tables: tuple[Table, ...] = (
        AgentRun.__table__,
        AgentPlanVersion.__table__,
        AgentStep.__table__,
        AgentObservationRecord.__table__,
    )
    all_columns = {column.name for table in tables for column in table.columns}

    assert FORBIDDEN_COLUMNS.isdisjoint(all_columns)
    assert {table.name for table in tables} == {
        "agent_runs",
        "agent_plan_versions",
        "agent_steps",
        "agent_observation_records",
    }
    constraint_names = {
        constraint.name for table in tables for constraint in table.constraints if constraint.name
    }
    assert "ck_agent_runs_status" in constraint_names
    assert "uq_agent_plan_versions_run_version" in constraint_names
    assert "uq_agent_steps_run_step" in constraint_names
    assert "uq_agent_observations_run_step" in constraint_names


class _OperationRecorder:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.dropped: list[str] = []
        self.executed: list[str] = []

    def create_table(self, name: str, *_: object, **__: object) -> None:
        self.created.append(name)

    def drop_table(self, name: str, **_: object) -> None:
        self.dropped.append(name)

    def create_index(self, *_: object, **__: object) -> None:
        return None

    def drop_index(self, *_: object, **__: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.executed.append(statement)


def test_migration_declares_reversible_tables_and_immutable_plan_trigger(monkeypatch: Any) -> None:
    path = Path(__file__).parents[3] / "alembic/versions/20260822_0010_persistent_agent_runs.py"
    spec = importlib.util.spec_from_file_location("persistent_agent_runs_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert isinstance(migration, ModuleType)
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()
    migration.downgrade()

    expected = [
        "agent_runs",
        "agent_plan_versions",
        "agent_steps",
        "agent_observation_records",
    ]
    assert migration.down_revision == "20260821_0009"
    assert recorder.created == expected
    assert recorder.dropped == list(reversed(expected))
    assert any("trg_agent_plan_versions_immutable" in item for item in recorder.executed)
    assert any(
        "DROP FUNCTION prevent_agent_plan_version_update" in item for item in recorder.executed
    )
