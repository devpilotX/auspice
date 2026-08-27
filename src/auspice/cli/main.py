"""The `auspice` command.

One entry point, one sub-app per pipeline stage. Running `auspice` with no arguments prints the
stage list, which doubles as a map of the system.
"""

from __future__ import annotations

import typer

from auspice.cli import (
    labels_cmd,
    ledger_cmd,
    model_cmd,
    pipeline_cmd,
    registry_cmd,
    score_cmd,
)
from auspice.cli.output import console, heading, note, render_table
from auspice.config import get_settings

app = typer.Typer(
    name="auspice",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
    help="Auspice: a rating bureau for the right to build.",
)

app.add_typer(registry_cmd.app, name="registry")
app.add_typer(labels_cmd.app, name="labels")
app.add_typer(pipeline_cmd.ingest_app, name="ingest")
app.add_typer(pipeline_cmd.parse_app, name="parse")
app.add_typer(pipeline_cmd.transcribe_app, name="transcribe")
app.add_typer(pipeline_cmd.extract_app, name="extract")
app.add_typer(pipeline_cmd.resolve_app, name="resolve")
app.add_typer(model_cmd.features_app, name="features")
app.add_typer(model_cmd.train_app, name="train")
app.add_typer(model_cmd.eval_app, name="eval")
app.add_typer(score_cmd.score_app, name="score")
app.add_typer(score_cmd.memo_app, name="memo")
app.add_typer(pipeline_cmd.monitor_app, name="monitor")
app.add_typer(ledger_cmd.app, name="ledger")


@app.command("version")
def version() -> None:
    """Print the version and the resolved configuration that matters."""
    from auspice import __version__

    settings = get_settings()
    heading(f"Auspice {__version__}")
    render_table(
        [
            {"setting": "environment", "value": settings.env.value},
            {"setting": "database", "value": str(settings.database_url).split("@")[-1]},
            {
                "setting": "raw store",
                "value": f"{settings.raw_backend.value}: {settings.raw_local_root if settings.raw_backend.value == 'local' else settings.raw_bucket}",
            },
            {
                "setting": "language models",
                "value": settings.llm_provider if settings.llm_configured else "not configured",
            },
            {"setting": "crawler contact", "value": settings.crawler_contact or "not set"},
        ],
        columns=("setting", "value"),
    )


@app.command("stages")
def stages() -> None:
    """The eleven pipeline stages and the command that drives each one.

    Where a stage has no single run command, this names what does exist rather than something that does not.
    A command list that promises more than the code delivers is the first thing that makes an operator
    distrust the rest of it.
    """
    heading("Pipeline")
    render_table(
        [
            {"stage": 0, "name": "jurisdiction registry", "command": "auspice registry load"},
            {"stage": 1, "name": "ingestion", "command": "auspice ingest run"},
            {"stage": 2, "name": "document processing", "command": "auspice parse run"},
            {"stage": 3, "name": "transcription", "command": "auspice transcribe status"},
            {"stage": 4, "name": "extraction", "command": "auspice extract run"},
            {"stage": 5, "name": "entity resolution", "command": "auspice resolve run"},
            {"stage": 6, "name": "the Permission Graph", "command": "auspice labels stats"},
            {"stage": 7, "name": "feature engineering", "command": "auspice features build"},
            {"stage": 8, "name": "modelling", "command": "auspice train all"},
            {"stage": 9, "name": "calibration and evaluation", "command": "auspice eval kill-test"},
            {"stage": 10, "name": "output generation", "command": "POST /v1/score"},
            {"stage": 11, "name": "monitoring", "command": "auspice monitor run"},
        ],
        columns=("stage", "name", "command"),
        numeric=("stage",),
    )
    console.print()
    note(
        "Labels come before pipelines. `auspice labels validate` is the first command that matters."
    )


def main() -> None:  # pragma: no cover - console script shim
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
