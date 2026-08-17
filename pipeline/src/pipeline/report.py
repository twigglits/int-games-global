"""Structured reports produced by the pipeline stages.

Each stage returns a report object beside its data. ``main`` merges them into a
:class:`RunReport`, prints a human-readable summary to stdout, and writes the
same content as JSON so that a later run can be compared against it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class Action:
    """One issue found in the data and the action taken for it.

    Attributes:
        issue: Short identifier of the problem, for example ``duplicate_rows``.
        field_name: Column the issue applies to, or ``"*"`` for whole records.
        count: Number of records affected.
        action: What the pipeline did about it.
        detail: Optional extra context such as fitted coefficients.
    """

    issue: str
    field_name: str
    count: int
    action: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "issue": self.issue,
            "field": self.field_name,
            "count": self.count,
            "action": self.action,
            "detail": self.detail,
        }


@dataclass
class CleaningReport:
    """Counts of issues found during cleaning and the action taken for each."""

    rows_in: int = 0
    rows_out: int = 0
    actions: list[Action] = field(default_factory=list)

    def add(self, issue: str, field_name: str, count: int, action: str, detail: str = "") -> None:
        """Record one cleaning action. Zero-count actions are kept on purpose,
        because "we checked and found none" is itself a useful report line."""
        self.actions.append(Action(issue, field_name, count, action, detail))

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_dropped": self.rows_in - self.rows_out,
            "actions": [a.as_dict() for a in self.actions],
        }


@dataclass
class ImputationReport:
    """Per-field imputation counts, strategies and reasons."""

    decisions: list[Action] = field(default_factory=list)

    def add(self, field_name: str, count: int, strategy: str, reason: str) -> None:
        self.decisions.append(Action("missing_values", field_name, count, strategy, reason))

    def as_dict(self) -> dict[str, Any]:
        return {"decisions": [d.as_dict() for d in self.decisions]}


@dataclass
class AugmentationReport:
    """Derived features that were created, with the rationale for each."""

    features: list[Action] = field(default_factory=list)

    def add(self, field_name: str, count: int, rationale: str) -> None:
        self.features.append(Action("derived_feature", field_name, count, "created", rationale))

    def as_dict(self) -> dict[str, Any]:
        return {"features": [f.as_dict() for f in self.features]}


@dataclass
class EmbeddingReport:
    """Outcome of the embedding stage."""

    model_id: str = ""
    dimension: int = 0
    batch_size: int = 0
    texts_embedded: int = 0
    texts_reused: int = 0
    batches: int = 0
    failures: int = 0
    duration_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "dimension": self.dimension,
            "batch_size": self.batch_size,
            "texts_embedded": self.texts_embedded,
            "texts_reused": self.texts_reused,
            "batches": self.batches,
            "failures": self.failures,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass
class LoadReport:
    """Outcome of the database load."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    total_rows_in_table: int = 0
    duration_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "total_rows_in_table": self.total_rows_in_table,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass
class RunReport:
    """The complete report for one pipeline run."""

    pipeline_version: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str = ""
    source_records: int = 0
    cleaning: CleaningReport = field(default_factory=CleaningReport)
    imputation: ImputationReport = field(default_factory=ImputationReport)
    augmentation: AugmentationReport = field(default_factory=AugmentationReport)
    embedding: EmbeddingReport = field(default_factory=EmbeddingReport)
    load: LoadReport = field(default_factory=LoadReport)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "source_records": self.source_records,
            "cleaning": self.cleaning.as_dict(),
            "imputation": self.imputation.as_dict(),
            "augmentation": self.augmentation.as_dict(),
            "embedding": self.embedding.as_dict(),
            "load": self.load.as_dict(),
        }

    def write_json(self, directory: Path, filename: str = "pipeline_report.json") -> Path:
        """Write the report as JSON and return the path written."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        return path

    def render_text(self) -> str:
        """Render the report as a plain-text summary for stdout."""
        lines: list[str] = []
        rule = "=" * 78

        def header(title: str) -> None:
            lines.append("")
            lines.append(rule)
            lines.append(title)
            lines.append(rule)

        def table(rows: list[Action]) -> None:
            if not rows:
                lines.append("  (none)")
                return
            width_field = max(len(r.field_name) for r in rows)
            width_action = max(len(r.action) for r in rows)
            for r in rows:
                lines.append(
                    f"  {r.field_name:<{width_field}}  {r.count:>6}  "
                    f"{r.action:<{width_action}}  {r.detail}"
                )

        header(f"PIPELINE RUN SUMMARY  (version {self.pipeline_version})")
        lines.append(f"  started  : {self.started_at}")
        lines.append(f"  finished : {self.finished_at}")
        lines.append(f"  source records read : {self.source_records}")

        header("1. CLEANING")
        lines.append(
            f"  rows in {self.cleaning.rows_in} -> rows out {self.cleaning.rows_out} "
            f"(dropped {self.cleaning.rows_in - self.cleaning.rows_out})"
        )
        lines.append("  field / count / action / detail")
        table(self.cleaning.actions)

        header("2. IMPUTATION")
        lines.append("  field / count / strategy / reason")
        table(self.imputation.decisions)

        header("3. FEATURE AUGMENTATION")
        lines.append("  feature / count / action / rationale")
        table(self.augmentation.features)

        header("4. EMBEDDING")
        e = self.embedding
        lines.append(f"  model      : {e.model_id} ({e.dimension} dimensions)")
        lines.append(f"  batch size : {e.batch_size}   batches: {e.batches}")
        lines.append(f"  embedded   : {e.texts_embedded}   reused unchanged: {e.texts_reused}")
        lines.append(f"  failures   : {e.failures}   duration: {e.duration_seconds:.2f}s")

        header("5. DATABASE LOAD")
        load = self.load
        lines.append(f"  inserted   : {load.inserted}")
        lines.append(f"  updated    : {load.updated}")
        lines.append(f"  unchanged  : {load.unchanged}")
        lines.append(f"  rows now in movies table : {load.total_rows_in_table}")
        lines.append(f"  duration   : {load.duration_seconds:.2f}s")
        lines.append(rule)
        return "\n".join(lines)
