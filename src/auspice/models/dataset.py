"""The training frame.

One place that turns the graph into a matrix, so every model sees identical data and the dataset
hash means something. Two rules are enforced here rather than in each model.

**Only verified rows train.** An application whose outcome is not backed by at least one quote found
verbatim in a stored source does not enter the training set. Section 6.7 decision (b). This is the
join that makes the trust architecture load bearing instead of decorative: if the verifier rejects a
citation, the row silently stops influencing the number.

**Missing is missing.** Features that could not be computed arrive as NaN and stay NaN. XGBoost
handles them natively. The hierarchical model imputes explicitly and records that it did. Nothing
is zero filled, because zero is a value and "unknown" is not.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Connection

from auspice.domain import APPROVAL_OUTCOMES, CompetingRisk, Outcome, competing_risk_for
from auspice.errors import InsufficientDataError
from auspice.logging import get_logger
from auspice.pipeline.features.dictionary import FEATURE_SET_VERSION, feature_names

log = get_logger(__name__, _stage="models")

_FRAME_SQL = text(
    """
    SELECT
        a.id                    AS application_id,
        j.slug                  AS jurisdiction,
        j.region,
        j.legal_framework,
        j.kind                  AS jurisdiction_kind,
        j.population,
        j.land_area_sq_km,
        a.use_class,
        a.outcome,
        a.filed_on,
        a.decided_on,
        a.censored,
        a.months_to_decision,
        a.label_source,
        fs.as_of,
        fs.features,
        fs.missing,
        EXISTS (
            SELECT 1 FROM fact_evidence fe
            WHERE fe.subject_table = 'application' AND fe.subject_id = a.id AND fe.verified
        )                       AS evidence_verified
    FROM application a
    JOIN jurisdiction j ON j.id = a.jurisdiction_id
    LEFT JOIN feature_snapshot fs
        ON fs.application_id = a.id
       AND fs.feature_set_version = :feature_set_version
    ORDER BY a.decided_on NULLS LAST, a.id
    """
)


@dataclass(slots=True)
class Dataset:
    """A model ready frame, plus everything needed to reproduce it."""

    frame: pl.DataFrame
    feature_columns: list[str]
    feature_set_version: str
    require_verified: bool
    excluded_unverified: int = 0
    excluded_no_features: int = 0
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return self.frame.height

    @property
    def terminal(self) -> pl.DataFrame:
        """Rows that reached a terminal outcome. The classifier trains on these."""
        return self.frame.filter(~pl.col("censored"))

    @property
    def decided(self) -> pl.DataFrame:
        """Terminal rows excluding withdrawals.

        A withdrawal is not a denial. It is a third exit, and folding it into the binary label
        teaches the model that quiet death and a public no are the same event. The survival model
        keeps all three as competing risks; the classifier trains on approve versus deny.
        """
        return self.frame.filter(
            ~pl.col("censored") & (pl.col("outcome") != Outcome.withdrawn.value)
        )

    def x(self, subset: pl.DataFrame | None = None) -> np.ndarray:
        source = self.frame if subset is None else subset
        if not self.feature_columns:
            return np.zeros((source.height, 0), dtype=np.float64)
        return source.select(self.feature_columns).to_numpy().astype(np.float64)

    def y(self, subset: pl.DataFrame | None = None) -> np.ndarray:
        source = self.frame if subset is None else subset
        return source.select("approved").to_numpy().ravel().astype(np.int8)

    def groups(self, subset: pl.DataFrame | None = None) -> np.ndarray:
        source = self.frame if subset is None else subset
        return source.select("jurisdiction").to_numpy().ravel()

    def hash(self) -> str:
        """SHA-256 over the sorted rows.

        Two runs with the same hash saw the same data. That is what makes a published accuracy
        record reproducible, and it is written into ``model_run.dataset_hash``.
        """
        digest = hashlib.sha256()
        digest.update(self.feature_set_version.encode())
        digest.update(b"|".join(c.encode() for c in sorted(self.feature_columns)))
        ordered = self.frame.sort("application_id")
        for row in ordered.iter_rows(named=True):
            digest.update(str(row["application_id"]).encode())
            digest.update(str(row["outcome"]).encode())
            digest.update(str(row["decided_on"]).encode())
            for column in sorted(self.feature_columns):
                digest.update(f"{column}={row[column]!r}".encode())
        return digest.hexdigest()

    def temporal_split(self, cutoff: date) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Train on decisions strictly before ``cutoff``, test on or after it.

        Section 6.9 validation rule 1: temporal splits only. Random k-fold is invalid here and
        produces a beautiful, worthless result, because it leaks future ordinances and future board
        compositions into the training set.
        """
        decided = self.decided
        train = decided.filter(pl.col("decided_on") < cutoff)
        test = decided.filter(pl.col("decided_on") >= cutoff)
        return train, test

    def jurisdiction_folds(self) -> list[tuple[pl.DataFrame, pl.DataFrame]]:
        """Leave one jurisdiction out.

        Section 6.9 validation rule 2. This is the test that matters for expansion: it asks whether
        the model generalises to a county it has never seen, which is exactly what happens on every
        new customer's first site.
        """
        decided = self.decided
        folds: list[tuple[pl.DataFrame, pl.DataFrame]] = []
        for slug in sorted(decided.select("jurisdiction").unique().to_series().to_list()):
            held_out = decided.filter(pl.col("jurisdiction") == slug)
            rest = decided.filter(pl.col("jurisdiction") != slug)
            if held_out.height and rest.height:
                folds.append((rest, held_out))
        return folds

    def depth_by_jurisdiction(self) -> dict[str, int]:
        counts = (
            self.decided.group_by("jurisdiction").len().sort("jurisdiction").iter_rows(named=True)
        )
        return {row["jurisdiction"]: int(row["len"]) for row in counts}


def load_dataset(
    conn: Connection,
    *,
    feature_columns: list[str] | None = None,
    feature_set_version: str = FEATURE_SET_VERSION,
    require_verified: bool = True,
    hand_labelled_only: bool = False,
) -> Dataset:
    """Read the graph into a frame.

    ``require_verified`` defaults to true and should only be turned off for diagnostics. Turning it
    off is how an unverified citation ends up influencing a published number.
    """
    records = (
        conn.execute(_FRAME_SQL, {"feature_set_version": feature_set_version}).mappings().all()
    )

    columns = feature_columns if feature_columns is not None else feature_names()
    rows: list[dict[str, object]] = []
    excluded_unverified = 0
    excluded_no_features = 0

    for record in records:
        if hand_labelled_only and record["label_source"] != "hand_labelled":
            continue
        if require_verified and not record["evidence_verified"]:
            excluded_unverified += 1
            continue
        if record["features"] is None:
            excluded_no_features += 1
            continue

        features = dict(record["features"])
        outcome = Outcome(record["outcome"])
        row: dict[str, object] = {
            "application_id": int(record["application_id"]),
            "jurisdiction": record["jurisdiction"],
            "region": record["region"],
            "legal_framework": record["legal_framework"],
            "use_class": record["use_class"],
            "outcome": outcome.value,
            "approved": 1 if outcome in APPROVAL_OUTCOMES else 0,
            "censored": bool(record["censored"]),
            "risk": competing_risk_for(outcome).value,
            "filed_on": record["filed_on"],
            "decided_on": record["decided_on"],
            "as_of": record["as_of"],
            "months_to_decision": (
                float(record["months_to_decision"])
                if record["months_to_decision"] is not None
                else None
            ),
            "n_missing": len(record["missing"] or []),
        }
        for column in columns:
            value = features.get(column)
            if isinstance(value, bool):
                row[column] = float(value)
            elif value is None:
                row[column] = None
            else:
                row[column] = float(value)
        rows.append(row)

    schema_overrides = dict.fromkeys(columns, pl.Float64)
    frame = (
        pl.DataFrame(rows, schema_overrides=schema_overrides)
        if rows
        else pl.DataFrame(
            schema={
                "application_id": pl.Int64,
                "jurisdiction": pl.Utf8,
                "region": pl.Utf8,
                "legal_framework": pl.Utf8,
                "use_class": pl.Utf8,
                "outcome": pl.Utf8,
                "approved": pl.Int64,
                "censored": pl.Boolean,
                "risk": pl.Utf8,
                "filed_on": pl.Date,
                "decided_on": pl.Date,
                "as_of": pl.Date,
                "months_to_decision": pl.Float64,
                "n_missing": pl.Int64,
                **schema_overrides,
            }
        )
    )

    dataset = Dataset(
        frame=frame,
        feature_columns=columns,
        feature_set_version=feature_set_version,
        require_verified=require_verified,
        excluded_unverified=excluded_unverified,
        excluded_no_features=excluded_no_features,
    )
    if excluded_unverified:
        dataset.notes.append(
            f"{excluded_unverified} row(s) excluded: outcome not backed by a verified quote"
        )
    if excluded_no_features:
        dataset.notes.append(
            f"{excluded_no_features} row(s) excluded: no feature snapshot at version {feature_set_version}"
        )

    log.info(
        "dataset loaded",
        rows=frame.height,
        features=len(columns),
        excluded_unverified=excluded_unverified,
        excluded_no_features=excluded_no_features,
    )
    return dataset


def dataset_from_frame(frame: pl.DataFrame, feature_columns: list[str]) -> Dataset:
    """Wrap an in memory frame. Used by the synthetic tests, never by a published run."""
    return Dataset(
        frame=frame,
        feature_columns=feature_columns,
        feature_set_version=f"synthetic:{FEATURE_SET_VERSION}",
        require_verified=False,
        notes=["synthetic frame: for testing model mathematics only"],
    )


def require_minimum(dataset: Dataset, *, need: int, what: str) -> None:
    have = dataset.decided.height
    if have < need:
        raise InsufficientDataError(
            f"{what} needs {need} decided applications and the graph holds {have}",
            have=have,
            need=need,
        )


def competing_risk_arrays(dataset: Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Duration, event indicator and risk code, for the survival model.

    Censored rows are kept. A project filed fourteen months ago with no decision is not a missing
    value, it is the information that at least fourteen months have elapsed. Dropping those rows
    biases every timeline estimate optimistically, which is exactly the direction that destroys
    customer trust.
    """
    frame = dataset.frame
    today = date.today()

    durations: list[float] = []
    events: list[int] = []
    risks: list[int] = []
    risk_codes = {
        CompetingRisk.approval.value: 1,
        CompetingRisk.denial.value: 2,
        CompetingRisk.withdrawal.value: 3,
        CompetingRisk.censored.value: 0,
    }

    for row in frame.iter_rows(named=True):
        months = row["months_to_decision"]
        if months is None:
            filed = row["filed_on"]
            if filed is None:
                continue
            months = (today.toordinal() - filed.toordinal()) / 30.44
        durations.append(max(float(months), 0.03))
        censored = bool(row["censored"])
        events.append(0 if censored else 1)
        risks.append(risk_codes.get(str(row["risk"]), 0))

    return (
        np.asarray(durations, dtype=np.float64),
        np.asarray(events, dtype=np.int8),
        np.asarray(risks, dtype=np.int8),
    )
