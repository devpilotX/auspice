"""Fit every model and record the run.

One place that owns the sequence, so a training run is reproducible from its ``model_run`` row. Every
run records the dataset hash, the feature set version, the cutoff and the fitted parameters, because
section 7.2 makes experiment tracking mandatory: the public accuracy record depends on being able to
say exactly which data produced which number.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.domain import ModelKind, UseClass
from auspice.logging import get_logger
from auspice.models.baseline.base_rate import MODEL_VERSION as BASE_RATE_VERSION
from auspice.models.baseline.base_rate import BaseRateModel
from auspice.models.baseline.boosted import MODEL_VERSION as BOOSTED_VERSION
from auspice.models.baseline.boosted import BoostedModel
from auspice.models.dataset import Dataset
from auspice.models.hierarchical.model import MODEL_VERSION as HIERARCHICAL_VERSION
from auspice.models.hierarchical.model import HierarchicalModel
from auspice.models.rulechange.model import MODEL_VERSION as RULE_CHANGE_VERSION
from auspice.models.rulechange.model import RuleChangeModel
from auspice.models.survival.model import MODEL_VERSION as SURVIVAL_VERSION
from auspice.models.survival.model import SurvivalModel

log = get_logger(__name__, _stage="models")


def _record(
    conn: Connection,
    *,
    kind: ModelKind,
    version: str,
    dataset: Dataset,
    cutoff: date,
    n_train: int,
    n_test: int,
    params: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    calibrator: dict[str, Any] | None = None,
) -> int:
    statement = pg_insert(schema.model_run).values(
        kind=kind.value,
        version=version,
        feature_set_version=dataset.feature_set_version,
        dataset_hash=dataset.hash(),
        train_cutoff=cutoff,
        n_train=n_train,
        n_test=n_test,
        params=json.loads(json.dumps(params, default=str)),
        metrics=json.loads(json.dumps(metrics or {}, default=str)),
        calibrator=calibrator,
        trained_at=datetime.now(UTC),
    )
    upsert = statement.on_conflict_do_update(
        index_elements=[
            schema.model_run.c.kind,
            schema.model_run.c.version,
            schema.model_run.c.dataset_hash,
        ],
        set_={
            "params": statement.excluded.params,
            "metrics": statement.excluded.metrics,
            "calibrator": statement.excluded.calibrator,
            "trained_at": statement.excluded.trained_at,
            "n_train": statement.excluded.n_train,
            "n_test": statement.excluded.n_test,
        },
    ).returning(schema.model_run.c.id)
    return int(conn.execute(upsert).scalar_one())


def train_and_record(
    conn: Connection,
    *,
    dataset: Dataset,
    cutoff: date,
    samples: int = 1500,
    chains: int = 2,
) -> dict[str, Any]:
    """Fit the five models, record each run, and return a summary for the CLI."""
    train, test = dataset.temporal_split(cutoff)
    rows: list[dict[str, Any]] = []
    notes: list[str] = list(dataset.notes)

    # --- Base rate. The benchmark, always fitted, never skipped. ----------
    base_rate = BaseRateModel().fit(train)
    _record(
        conn,
        kind=ModelKind.base_rate,
        version=BASE_RATE_VERSION,
        dataset=dataset,
        cutoff=cutoff,
        n_train=train.height,
        n_test=test.height,
        params=base_rate.params(),
    )
    rows.append(
        {
            "model": "base_rate",
            "version": BASE_RATE_VERSION,
            "n_train": train.height,
            "n_test": test.height,
            "note": f"global rate {base_rate.global_rate:.3f}, prior strength {base_rate.prior_strength:.1f}",
        }
    )

    # --- Boosted floor ----------------------------------------------------
    boosted = BoostedModel(feature_columns=dataset.feature_columns).fit(train)
    _record(
        conn,
        kind=ModelKind.gradient_boosted,
        version=BOOSTED_VERSION,
        dataset=dataset,
        cutoff=cutoff,
        n_train=train.height,
        n_test=test.height,
        params={"importances": boosted.importances(), **boosted.params},
    )
    rows.append(
        {
            "model": "gradient_boosted",
            "version": BOOSTED_VERSION,
            "n_train": boosted.n_train,
            "n_test": test.height,
            "note": "declined, only one outcome class present"
            if boosted.booster is None
            else f"depth {boosted.params.get('max_depth')}, {len(boosted.ensemble)} bootstrap members",
        }
    )

    # --- Hierarchical -----------------------------------------------------
    hierarchical = HierarchicalModel(feature_columns=dataset.feature_columns)
    if train.height >= 40 and train.select("approved").to_series().n_unique() > 1:
        hierarchical.fit(train, samples=samples, warmup=samples // 2, chains=chains)
        _record(
            conn,
            kind=ModelKind.hierarchical,
            version=HIERARCHICAL_VERSION,
            dataset=dataset,
            cutoff=cutoff,
            n_train=train.height,
            n_test=test.height,
            params=hierarchical.params(),
        )
        rows.append(
            {
                "model": "hierarchical",
                "version": HIERARCHICAL_VERSION,
                "n_train": hierarchical.n_train,
                "n_test": test.height,
                "note": f"converged, r-hat {hierarchical.diagnostics.get('max_r_hat')}"
                if hierarchical.converged
                else f"did not converge, {hierarchical.diagnostics.get('divergences')} divergences",
            }
        )
        if not hierarchical.converged:
            notes.append(
                "the hierarchical model did not converge, so it must not serve. An interval from an "
                "untrustworthy posterior is worse than no interval."
            )
    else:
        notes.append(
            f"the hierarchical model needs at least 40 training rows with both outcomes and the "
            f"graph provides {train.height}. It is not fitted, and the base rate serves instead."
        )

    # --- Survival ---------------------------------------------------------
    survival = SurvivalModel(feature_columns=dataset.feature_columns)
    survival.fit(dataset.frame, as_of=cutoff)
    _record(
        conn,
        kind=ModelKind.survival,
        version=SURVIVAL_VERSION,
        dataset=dataset,
        cutoff=cutoff,
        n_train=survival.n_train,
        n_test=test.height,
        params=survival.params(),
    )
    rows.append(
        {
            "model": "survival",
            "version": SURVIVAL_VERSION,
            "n_train": survival.n_train,
            "n_test": survival.n_events,
            "note": f"{survival.n_censored} censored rows kept"
            if survival.aft is not None
            else "declined, too few observed exits",
        }
    )

    # --- Rule change ------------------------------------------------------
    for use_class in sorted(
        {str(u) for u in dataset.frame.select("use_class").to_series().unique()}
    ):
        try:
            resolved_use_class = UseClass(use_class)
        except ValueError:
            continue
        rule_change = RuleChangeModel(use_class=resolved_use_class.value)
        rule_change.fit(conn, start=date(cutoff.year - 8, 1, 1), end=cutoff)
        _record(
            conn,
            kind=ModelKind.rule_change,
            version=RULE_CHANGE_VERSION,
            dataset=dataset,
            cutoff=cutoff,
            n_train=rule_change.n_rows,
            n_test=0,
            params=rule_change.params(),
        )
        rows.append(
            {
                "model": f"rule_change:{resolved_use_class.value}",
                "version": RULE_CHANGE_VERSION,
                "n_train": rule_change.n_rows,
                "n_test": rule_change.n_events,
                "note": f"monthly hazard {rule_change.baseline_monthly_hazard:.5f}",
            }
        )
        notes.extend(rule_change.notes)

    log.info("training complete", models=len(rows), cutoff=cutoff.isoformat())
    return {"models": rows, "notes": notes, "dataset_hash": dataset.hash()}


def promote(conn: Connection, *, kind: ModelKind, version: str, dataset_hash: str) -> None:
    """Mark a run as serving, retiring whatever it replaces.

    Promotion is separate from training on purpose. A model that trained is not a model that should
    serve, and the hierarchical model in particular must not serve unless it converged.
    """
    from sqlalchemy import and_, update

    conn.execute(
        update(schema.model_run)
        .where(
            and_(
                schema.model_run.c.kind == kind.value,
                schema.model_run.c.retired_at.is_(None),
                schema.model_run.c.promoted_at.isnot(None),
            )
        )
        .values(retired_at=datetime.now(UTC))
    )
    conn.execute(
        update(schema.model_run)
        .where(
            and_(
                schema.model_run.c.kind == kind.value,
                schema.model_run.c.version == version,
                schema.model_run.c.dataset_hash == dataset_hash,
            )
        )
        .values(promoted_at=datetime.now(UTC), retired_at=None)
    )
    log.info("promoted", kind=kind.value, version=version)
