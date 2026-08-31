"""Operations commands: backups, and the restore that makes them backups."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from auspice.cli.output import console, fail, heading, note, ok, render_table
from auspice.config import get_settings
from auspice.errors import StageUnavailableError
from auspice.ops import backup as backup_module

app = typer.Typer(no_args_is_help=True, help="Operational tasks: backups and restore verification.")


@app.command("backup")
def create_backup(
    label: Annotated[
        str | None, typer.Option(help="Appended to the filename, for a reason")
    ] = None,
    destination: Annotated[Path | None, typer.Option(help="Override the backup directory")] = None,
    verify_now: Annotated[
        bool, typer.Option("--verify/--no-verify", help="Restore it immediately and compare")
    ] = True,
) -> None:
    """Dump the database, write a manifest, and by default prove the dump restores.

    Verification is on by default because a dump whose restore has never been attempted is a file, and
    every organisation that has lost data had one. `--no-verify` exists for the case where the restore
    target is busy, and using it means the backup is unproven.
    """
    heading("Backup")
    try:
        manifest = backup_module.create(destination=destination, label=label)
    except (backup_module.BackupError, StageUnavailableError) as exc:
        fail(str(exc))

    render_table(
        [
            {"field": "database", "value": manifest.database},
            {"field": "file", "value": manifest.dump_file},
            {"field": "bytes", "value": manifest.dump_bytes},
            {"field": "sha256", "value": manifest.dump_sha256[:16]},
            {"field": "postgres", "value": manifest.postgres_version},
            {"field": "schema revision", "value": manifest.schema_revision or "unknown"},
        ],
        columns=("field", "value"),
    )
    console.print()
    render_table(
        [{"table": name, "rows": count} for name, count in sorted(manifest.row_counts.items())],
        numeric=("rows",),
        title="Counted from the live database, not from the dump",
    )

    if not verify_now:
        console.print()
        note("not verified. This dump is a file until a restore has been attempted against it.")
        return

    root = destination or get_settings().backup_path
    manifest_path = root / manifest.dump_file.replace(".dump", backup_module.MANIFEST_SUFFIX)
    console.print()
    _verify_one(manifest_path)


@app.command("verify")
def verify_backup(
    manifest: Annotated[
        Path | None, typer.Argument(help="Manifest to verify. Omit for the newest.")
    ] = None,
    keep: Annotated[
        bool, typer.Option(help="Leave the scratch database in place for inspection")
    ] = False,
) -> None:
    """Restore a dump into a scratch database and compare row counts against its manifest.

    The scratch database is created by this command with a random name, is dropped by it, and nothing
    else is ever dropped. That guard is checked in code rather than trusted, because this is the only
    DROP DATABASE in the codebase.
    """
    heading("Restore verification")
    resolved = manifest or _newest_manifest()
    if resolved is None:
        fail("no backups found. Run `auspice ops backup` first.")
    _verify_one(resolved, keep=keep)


def _verify_one(manifest_path: Path, *, keep: bool = False) -> None:
    try:
        report = backup_module.verify(manifest_path, keep=keep)
    except (backup_module.BackupError, StageUnavailableError) as exc:
        fail(str(exc))

    render_table(
        [{"check": key, "result": value} for key, value in report.as_dict().items()],
        columns=("check", "result"),
    )
    console.print()
    if report.scratch_database:
        note(f"scratch database kept: {report.scratch_database}. Drop it when you are done.")
    if report.ok:
        ok("this backup restores and the data matches what was counted at dump time")
        return
    if report.mismatches:
        render_table(
            [
                {"table": table, "expected": expected, "restored": got}
                for table, (expected, got) in sorted(report.mismatches.items())
            ],
            numeric=("expected", "restored"),
            title="Row counts that disagree",
        )
        console.print()
    fail(report.reason or "verification failed without a reason, which is itself a defect")


@app.command("list")
def list_backups() -> None:
    """Every backup that has a manifest, newest first."""
    heading("Backups")
    manifests = backup_module.list_backups()
    if not manifests:
        note(f"none in {get_settings().backup_path}")
        return

    render_table(
        [
            {
                "created": m.created_at[:19],
                "file": m.dump_file,
                "bytes": m.dump_bytes,
                "rows": sum(m.row_counts.values()),
                "revision": m.schema_revision or "unknown",
            }
            for m in manifests
        ],
        numeric=("bytes", "rows"),
    )
    console.print()
    note("`auspice ops verify` restores the newest one and compares its row counts.")


@app.command("prune")
def prune_backups(
    keep: Annotated[int, typer.Option(help="How many of the newest to keep")] = 7,
) -> None:
    """Delete all but the newest backups.

    A backup directory that grows without bound fills the disk, and a full disk stops the next backup,
    which is how a backup regime dies. A dump whose manifest is missing is never deleted: it may be
    the only copy of something.
    """
    heading("Pruning backups")
    try:
        removed = backup_module.prune(keep=keep)
    except backup_module.BackupError as exc:
        fail(str(exc))

    if not removed:
        ok(f"nothing to remove, {keep} or fewer backups held")
        return
    for name in removed:
        console.print(f"  removed {name}")
    console.print()
    ok(f"{len(removed)} backup(s) removed, {keep} kept")


def _newest_manifest() -> Path | None:
    root = get_settings().backup_path
    if not root.exists():
        return None
    manifests = sorted(root.glob(f"*{backup_module.MANIFEST_SUFFIX}"), reverse=True)
    return manifests[0] if manifests else None
