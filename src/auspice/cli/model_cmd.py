"""Feature, training and evaluation commands."""

from __future__ import annotations

from datetime import date
from typing import Annotated

import typer

from auspice.cli.output import ABSENT, console, fail, heading, note, ok, render_table
from auspice.db import transaction
from auspice.models.eval.thresholds import (
    COVERAGE_BAND,
    MAX_ECE,
    MIN_BRIER_SKILL,
    TARGET_BRIER_SKILL,
)

features_app = typer.Typer(
    no_args_is_help=True, help="Stage 7: point in time feature construction."
)
train_app = typer.Typer(no_args_is_help=True, help="Stage 8: fit the models.")
eval_app = typer.Typer(
    no_args_is_help=True, help="Stage 9: calibration, evaluation, the kill test."
)

DEFAULT_CUTOFF = date(2026, 1, 1)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
@features_app.command("build")
def features_build(
    dry_run: Annotated[bool, typer.Option(help="Compute without writing snapshots")] = False,
) -> None:
    """Build a point in time feature snapshot for every application in the graph."""
    from auspice.pipeline.features import build_all

    heading("Building features")
    with transaction() as conn:
        report = build_all(conn, persist=not dry_run)

    if not report.rows:
        fail("no applications in the graph", hint="Run `auspice labels load` first")

    render_table(
        [
            {
                "feature": name,
                "coverage": round(report.coverage.get(name, 0.0), 3),
                "usable": name in report.usable,
                "excluded_because": report.excluded.get(name, ABSENT),
            }
            for name in sorted(report.coverage, key=lambda n: -report.coverage.get(n, 0.0))
        ],
        numeric=("coverage",),
    )
    console.print()
    ok(f"{report.rows} snapshots, {len(report.usable)} features usable")
    note(
        f"{len(report.excluded)} excluded. Section 6.7 requires 80 percent coverage, a verified "
        "source, and one plain sentence a customer can read."
    )


@features_app.command("show")
def features_show(application_id: Annotated[int, typer.Argument()]) -> None:
    """Every feature for one application, with the sentence a customer would see."""
    from auspice.pipeline.features import build_for_application, describe

    with transaction() as conn:
        row = build_for_application(conn, application_id)

    heading(f"Application {application_id} as of {row.as_of}")
    render_table(
        [
            {
                "feature": name,
                "value": value,
                "plain_language": describe(name, value) if value is not None else "not known",
            }
            for name, value in sorted(row.values.items())
        ],
    )
    console.print()
    if row.missing:
        note(
            f"{len(row.missing)} feature(s) could not be computed: {', '.join(sorted(row.missing))}"
        )
        note("These are recorded as unknown rather than zero filled.")


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
@train_app.command("all")
def train_all(
    cutoff: Annotated[str, typer.Option(help="Train on decisions before this date")] = "2026-01-01",
    samples: Annotated[int, typer.Option(help="NUTS posterior samples")] = 1500,
    chains: Annotated[int, typer.Option(help="NUTS chains")] = 2,
) -> None:
    """Fit every model on the current graph and record the run."""
    from auspice.models.dataset import load_dataset
    from auspice.models.trainer import train_and_record

    resolved_cutoff = date.fromisoformat(cutoff)
    heading(f"Training on decisions before {resolved_cutoff}")

    with transaction() as conn:
        dataset = load_dataset(conn)
        if dataset.decided.height == 0:
            fail(
                "the graph holds no decided applications with verified evidence",
                hint="Run `auspice labels load` then `auspice labels verify`, then `auspice features build`",
            )
        report = train_and_record(
            conn, dataset=dataset, cutoff=resolved_cutoff, samples=samples, chains=chains
        )

    render_table(report["models"], numeric=("n_train", "n_test", "rows"))
    console.print()
    for message in report["notes"]:
        note(message)
    ok(f"{len(report['models'])} model run(s) recorded")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@eval_app.command("kill-test")
def kill_test(
    cutoff: Annotated[
        str, typer.Option(help="Train before this date, test on or after it")
    ] = "2026-01-01",
    samples: Annotated[int, typer.Option(help="NUTS posterior samples")] = 1500,
    chains: Annotated[int, typer.Option(help="NUTS chains")] = 2,
    skip_hierarchical: Annotated[
        bool, typer.Option(help="Boosted model only, for a fast check")
    ] = False,
    json_out: Annotated[str, typer.Option(help="Write the full result to this path")] = "",
) -> None:
    """The test that decides everything. Section 12, days 15 to 16.

    Trains on decisions before the cutoff and predicts the held out decisions after it. Reports the
    Brier score against the base rate benchmark, expected calibration error, interval coverage and
    abstention precision.

    It refuses to report a verdict on a sample too small to support one. That is not a limitation, it
    is the point: a verdict computed on twelve decisions would be quoted by someone.
    """

    from auspice.models.eval.killtest import (
        VERDICT_INSUFFICIENT,
        VERDICT_PASS,
        run_kill_test,
    )

    resolved_cutoff = date.fromisoformat(cutoff)
    heading("The kill test")
    note(f"train on decisions before {resolved_cutoff}, predict the rest")

    with transaction() as conn:
        result = run_kill_test(
            conn,
            cutoff=resolved_cutoff,
            include_hierarchical=not skip_hierarchical,
            hierarchical_samples=samples,
            hierarchical_chains=chains,
        )

    console.print()
    render_table(
        [
            {"quantity": "labelled decisions", "value": result.n_labelled},
            {"quantity": "training rows", "value": result.n_train},
            {"quantity": "held out rows", "value": result.n_test},
            {"quantity": "jurisdictions with depth", "value": result.jurisdictions_with_depth},
            {"quantity": "dataset hash", "value": (result.dataset_hash or ABSENT)[:16]},
        ],
        columns=("quantity", "value"),
    )

    if result.verdict == VERDICT_INSUFFICIENT:
        console.print()
        console.print("INSUFFICIENT DATA", style="stale")
        console.print()
        for blocker in result.blockers:
            console.print(f"  {blocker}")
        console.print()
        note("No verdict is reported, and no accuracy claim of any kind is published, until these")
        note("close. A verdict computed on a sample too small to support one is worse than no")
        note("verdict, because someone will quote it.")
        if json_out:
            _write_json(json_out, result.as_dict())
        raise typer.Exit(0)

    console.print()
    heading("Models")
    render_table(
        [
            {
                "model": name,
                "brier": metrics["brier"],
                "skill": metrics["brier_skill_vs_base_rate"],
                "auc": metrics["auc"],
                "ece": metrics["expected_calibration_error"],
                "ece_raw": metrics["expected_calibration_error_uncalibrated"],
                "coverage_80": metrics["coverage_80"],
                "interval": metrics["interval_kind"],
                "width": metrics["mean_interval_width"],
            }
            for name, metrics in result.metrics["models"].items()
        ],
        numeric=("brier", "skill", "auc", "ece", "ece_raw", "coverage_80", "width"),
    )
    console.print()
    note(f"base rate benchmark Brier score: {result.metrics['base_rate_brier']:.5f}")
    note(f"reported model: {result.metrics['primary_model']}")

    console.print()
    heading("Gates")
    render_table(
        [g.as_dict() for g in result.gates],
        columns=("name", "observed", "condition", "passed"),
        numeric=("observed",),
    )

    if result.reliability.get("bins"):
        console.print()
        heading("Reliability curve")
        render_table(
            [
                {
                    "bin": f"{b['lower']:.1f} to {b['upper']:.1f}",
                    "n": b["count"],
                    "predicted": b["mean_predicted"],
                    "observed": b["observed_frequency"],
                    "gap": round(b["observed_frequency"] - b["mean_predicted"], 4),
                    "interval": f"{b['interval'][0]:.2f} to {b['interval'][1]:.2f}",
                }
                for b in result.reliability["bins"]
                if b["count"] > 0
            ],
            numeric=("n", "predicted", "observed", "gap"),
        )

    if result.residual_notes:
        console.print()
        heading("Residuals")
        for message in result.residual_notes:
            console.print(f"  {message}")

    console.print()
    if result.verdict == VERDICT_PASS:
        console.print("PASS", style="fresh")
        note(
            f"Brier skill of at least {MIN_BRIER_SKILL:.2f} against the base rate, expected "
            f"calibration error under {MAX_ECE:.2f}, coverage between {COVERAGE_BAND[0]:.2f} and "
            f"{COVERAGE_BAND[1]:.2f}. Target skill is {TARGET_BRIER_SKILL:.2f}."
        )
    else:
        console.print("FAIL", style="broken")
        console.print()
        for gate in result.gates:
            if not gate.passed:
                console.print(f"  {gate.name}: observed {gate.observed}, needs {gate.condition}")
        console.print()
        note("Section 14 risk 1: the wedge is wrong. Do not adjust the test until it passes.")
        note(
            "Read the residual notes, write down what you saw, and change the wedge or the country."
        )

    if json_out:
        _write_json(json_out, result.as_dict())


@eval_app.command("sufficiency")
def sufficiency(
    cutoff: Annotated[str, typer.Option()] = "2026-01-01",
) -> None:
    """What stands between the corpus and a reportable verdict. Fast, no model fitting."""
    from auspice.models.dataset import load_dataset
    from auspice.models.eval.killtest import check_sufficiency

    resolved_cutoff = date.fromisoformat(cutoff)
    heading("Kill test sufficiency")

    with transaction() as conn:
        dataset = load_dataset(conn)
        blockers = check_sufficiency(dataset, cutoff=resolved_cutoff)
        depth = dataset.depth_by_jurisdiction()

    render_table(
        [{"jurisdiction": slug, "decided": count} for slug, count in sorted(depth.items())],
        numeric=("decided",),
    )
    console.print()
    for message in dataset.notes:
        note(message)

    console.print()
    if not blockers:
        ok("the kill test can run")
        return
    for blocker in blockers:
        console.print(f"  {blocker}")


def _write_json(path: str, payload: dict[str, object]) -> None:
    import json
    from pathlib import Path

    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    note(f"written to {path}")
