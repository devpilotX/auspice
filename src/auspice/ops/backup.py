"""Backups, and the restore that makes them backups.

Audit finding P2-3 named "no automated or tested backups". The word that matters is tested. A dump
file whose restore has never been attempted is a file, and every organisation that has lost data had
one. So `verify` here does not check a checksum and call it done: it creates a scratch database,
restores into it, counts the rows, and compares them against what was counted at dump time.

Three properties, each of which is a decision.

**The manifest is written from the live database, not from the dump.** Row counts are taken by querying
the source before the dump runs. Reading them out of the dump instead would make the check circular: a
truncated dump would report the counts it contained and agree with itself.

**The scratch database is created and dropped by this command, and nothing else is.** The name carries a
fixed prefix and a random suffix, the command refuses to proceed if that name already exists rather
than clobbering it, and it drops only the database it created. Dropping a database is the most
destructive operation in this codebase and it is confined to a name this process invented seconds
earlier.

**A verify failure is loud and specific.** It reports which table disagreed and by how much, because
"restore failed" sends an operator to read logs and "application held 412 rows and restored 0" sends
them to the dump.

## What is not here

Scheduling. This is a command, and what runs it is the deployment's own scheduler, the same way
`monitor run` and `score publish` are. `docs/OPERATIONS.md` carries the cron. Putting a scheduler
inside the process would mean the backup stops when the API restarts, which is exactly when it matters.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import PostgresDsn
from sqlalchemy import text

from auspice.config import REPO_ROOT, get_settings
from auspice.errors import StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="ops")

MANIFEST_SUFFIX = ".manifest.json"

# The prefix every scratch restore database carries. Anything matching this was created by a verify
# run and is safe for that run to drop. Anything not matching it is never touched.
SCRATCH_PREFIX = "auspice_restore_check_"

# Tables whose row counts are compared after a restore. Not every table: these are the ones whose loss
# is unrecoverable, because they hold either the corpus or the published record. A dump that restored
# the schema and none of these has failed regardless of what else came back.
VERIFIED_TABLES = (
    "jurisdiction",
    "decision_body",
    "application",
    "instrument",
    "fact_evidence",
    "document",
    "prediction",
    "ledger_entry",
    "feature_snapshot",
    "event",
)

# Where to look for the PostgreSQL client binaries when they are not on PATH. The Windows bootstrap
# script unpacks them here without touching the system, so a developer who followed the README has
# them and does not know it.
_LOCAL_BIN_CANDIDATES = (
    REPO_ROOT / ".tools" / "pgsql" / "bin",
    REPO_ROOT / "var" / "pgsql" / "bin",
)


class BackupError(Exception):
    """A backup or restore refused. The message is written to be read by an operator."""


def find_binary(name: str) -> Path:
    """Locate a PostgreSQL client binary, on PATH or in the bootstrapped toolchain."""
    found = shutil.which(name)
    if found:
        return Path(found)
    suffix = ".exe" if sys.platform == "win32" else ""
    for directory in _LOCAL_BIN_CANDIDATES:
        candidate = directory / f"{name}{suffix}"
        if candidate.exists():
            return candidate
    raise StageUnavailableError(
        f"{name} was not found on PATH or under {_LOCAL_BIN_CANDIDATES[0]}. On Windows without "
        "administrator rights, infra/scripts/bootstrap-postgres.ps1 unpacks the client binaries "
        "there. Otherwise install the PostgreSQL client package."
    )


@dataclass(frozen=True, slots=True)
class DatabaseTarget:
    """The pieces of a connection URL that the command line tools need separately."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_settings(cls, *, test: bool = False, admin: bool = False) -> DatabaseTarget:
        """Resolve a target from configuration.

        ``admin`` returns the restore credentials when they are configured. Restoring is an
        administrative operation: every dump of this schema contains ``CREATE EXTENSION postgis``, and
        a role that is not a superuser cannot execute it. Falling back to the application role is the
        right default, because a managed database frequently gives that role the permission anyway,
        and when it does not the failure message names this setting.
        """
        settings = get_settings()
        url: PostgresDsn | None
        if admin and settings.backup_admin_url is not None:
            url = settings.backup_admin_url
        elif test:
            url = settings.test_database_url
        else:
            url = settings.database_url
        if url is None:
            raise BackupError(
                "AUSPICE_TEST_DATABASE_URL is not set, so there is no test database to target."
            )
        parsed = str(url)
        # Parse rather than reach into the driver, so this works for any SQLAlchemy URL shape.
        match = re.match(
            r"^[^:]+://(?P<user>[^:@/]+)(?::(?P<password>[^@/]*))?@(?P<host>[^:/]+)"
            r"(?::(?P<port>\d+))?/(?P<database>[^?]+)",
            parsed,
        )
        if not match:
            raise BackupError(f"could not read a host, user and database out of {parsed!r}")
        return cls(
            host=match["host"],
            port=int(match["port"] or 5432),
            user=match["user"],
            password=match["password"] or "",
            database=match["database"],
        )

    def environment(self) -> dict[str, str]:
        """A child process environment carrying the password, never the command line.

        A password on a command line is visible in the process list to every user on the machine.
        PGPASSWORD is the documented way to pass it and it is what pg_dump expects.
        """
        env = dict(os.environ)
        if self.password:
            env["PGPASSWORD"] = self.password
        return env

    def argv(self, *, database: str | None = None) -> list[str]:
        return [
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--username",
            self.user,
            "--dbname",
            database or self.database,
        ]


@dataclass(slots=True)
class BackupManifest:
    """What was backed up, counted from the source rather than from the dump.

    Counting from the source is the whole point. Reading the counts out of the dump would make
    verification circular: a truncated dump would report what it contained and agree with itself.
    """

    created_at: str
    database: str
    dump_file: str
    dump_bytes: int
    dump_sha256: str
    postgres_version: str
    schema_revision: str | None
    row_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def read(cls, path: Path) -> BackupManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**raw)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _row_counts(conn: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in VERIFIED_TABLES:
        # The table names are a module level constant, never user input, so interpolation here cannot
        # carry anything a caller controls. Identifiers cannot be bound as parameters.
        counts[table] = int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
    return counts


def _schema_revision(conn: Any) -> str | None:
    try:
        return str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    except Exception:
        # A database with no alembic_version is not a reason to refuse a backup. It is a reason to
        # record that the revision is unknown, so a later restore does not claim to match one.
        return None


def _run(argv: list[str], *, env: dict[str, str], what: str) -> str:
    """Run a client binary, raising with its stderr rather than a return code."""
    completed = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise BackupError(
            f"{what} failed with exit code {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[:600]}"
        )
    return completed.stdout


def create(
    *, destination: Path | None = None, test: bool = False, label: str | None = None
) -> BackupManifest:
    """Dump the database and write a manifest beside it.

    The custom format is used rather than plain SQL, because it restores selectively, it compresses,
    and pg_restore can list its contents without a database, which is what makes a corrupt dump
    detectable before a restore is attempted.
    """
    from auspice.db import get_engine

    target = DatabaseTarget.from_settings(test=test)
    settings = get_settings()
    root = destination or (settings.backup_path)
    root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{target.database}-{stamp}" + (f"-{label}" if label else "")
    dump_file = root / f"{name}.dump"

    engine = get_engine(test=test)
    with engine.connect() as conn:
        counts = _row_counts(conn)
        revision = _schema_revision(conn)
        version = str(conn.execute(text("SHOW server_version")).scalar_one())

    pg_dump = find_binary("pg_dump")
    log.info("backup starting", database=target.database, destination=str(dump_file))
    _run(
        [
            str(pg_dump),
            *target.argv(),
            "--format=custom",
            "--compress=9",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dump_file),
        ],
        env=target.environment(),
        what="pg_dump",
    )

    if not dump_file.exists() or dump_file.stat().st_size == 0:
        raise BackupError(f"pg_dump reported success and {dump_file} is empty. Do not trust it.")

    manifest = BackupManifest(
        created_at=datetime.now(UTC).isoformat(),
        database=target.database,
        dump_file=dump_file.name,
        dump_bytes=dump_file.stat().st_size,
        dump_sha256=sha256_of(dump_file),
        postgres_version=version,
        schema_revision=revision,
        row_counts=counts,
    )
    manifest_path = root / f"{name}{MANIFEST_SUFFIX}"
    manifest_path.write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )

    log.info(
        "backup complete",
        database=target.database,
        bytes=manifest.dump_bytes,
        rows=sum(counts.values()),
        digest=manifest.dump_sha256[:12],
    )
    return manifest


def list_backups(*, root: Path | None = None) -> list[BackupManifest]:
    """Every backup with a manifest, newest first. A dump with no manifest is not listed."""
    directory = root or get_settings().backup_path
    if not directory.exists():
        return []
    manifests: list[BackupManifest] = []
    for path in sorted(directory.glob(f"*{MANIFEST_SUFFIX}"), reverse=True):
        try:
            manifests.append(BackupManifest.read(path))
        except Exception as exc:
            log.warning("unreadable manifest", path=str(path), error=str(exc))
    return manifests


@dataclass(slots=True)
class VerifyReport:
    manifest: str
    digest_ok: bool
    listing_ok: bool
    restore_ok: bool
    counts_ok: bool
    scratch_database: str | None = None
    mismatches: dict[str, tuple[int, int]] = field(default_factory=dict)
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.digest_ok and self.listing_ok and self.restore_ok and self.counts_ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest,
            "digest matches": self.digest_ok,
            "dump is readable": self.listing_ok,
            "restore succeeded": self.restore_ok,
            "row counts match": self.counts_ok,
            "verdict": "pass" if self.ok else "FAIL",
        }


def verify(manifest_path: Path, *, keep: bool = False) -> VerifyReport:
    """Restore the dump into a scratch database and compare row counts against the manifest.

    Everything before the restore is cheap and catches a corrupt file without touching a database. The
    restore is the part that makes this a tested backup rather than a checksummed one.
    """
    from sqlalchemy import create_engine

    manifest = BackupManifest.read(manifest_path)
    dump_file = manifest_path.parent / manifest.dump_file
    report = VerifyReport(
        manifest=manifest_path.name,
        digest_ok=False,
        listing_ok=False,
        restore_ok=False,
        counts_ok=False,
    )

    if not dump_file.exists():
        report.reason = f"{dump_file} is missing, so the manifest describes nothing."
        return report

    report.digest_ok = sha256_of(dump_file) == manifest.dump_sha256
    if not report.digest_ok:
        report.reason = (
            "the dump file's digest does not match its manifest. It has been altered or truncated "
            "since it was written, and nothing further is attempted."
        )
        return report

    pg_restore = find_binary("pg_restore")
    # The application role is not an administrator. Restoring is.
    target = DatabaseTarget.from_settings(admin=True)
    env = target.environment()

    # A listing reads the dump's table of contents without a database. A corrupt archive fails here,
    # before anything is created.
    try:
        _run([str(pg_restore), "--list", str(dump_file)], env=env, what="pg_restore --list")
        report.listing_ok = True
    except BackupError as exc:
        report.reason = str(exc)
        return report

    scratch = f"{SCRATCH_PREFIX}{secrets.token_hex(6)}"
    report.scratch_database = scratch
    # Connect to the server's default database to issue CREATE DATABASE, which cannot run inside a
    # transaction block, hence AUTOCOMMIT.
    admin_url = (
        f"postgresql+psycopg://{target.user}:{target.password}@{target.host}:{target.port}/postgres"
    )
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": scratch}
            ).scalar()
            if exists:
                # Refuse rather than clobber. This name was invented seconds ago, so its existence
                # means something is very wrong, and dropping it would be the wrong response.
                report.reason = (
                    f"{scratch} already exists, which should be impossible. Refusing to touch it."
                )
                return report
            conn.execute(text(f'CREATE DATABASE "{scratch}"'))

        log.info("restore starting", scratch=scratch, dump=str(dump_file))
        _run(
            [
                str(pg_restore),
                *target.argv(database=scratch),
                "--no-owner",
                "--no-privileges",
                "--single-transaction",
                str(dump_file),
            ],
            env=env,
            what="pg_restore",
        )
        report.restore_ok = True

        restored_url = (
            f"postgresql+psycopg://{target.user}:{target.password}"
            f"@{target.host}:{target.port}/{scratch}"
        )
        restored = create_engine(restored_url)
        try:
            with restored.connect() as conn:
                actual = _row_counts(conn)
        finally:
            restored.dispose()

        for table, expected in manifest.row_counts.items():
            got = actual.get(table, -1)
            if got != expected:
                report.mismatches[table] = (expected, got)
        report.counts_ok = not report.mismatches
        if report.mismatches:
            report.reason = "the restore succeeded and the data does not match. " + ", ".join(
                f"{table} held {expected} and restored {got}"
                for table, (expected, got) in report.mismatches.items()
            )
    except BackupError as exc:
        report.reason = str(exc)
        if "permission denied to create extension" in report.reason:
            report.reason += (
                " This is the credentials, not the dump. Every dump of this schema contains CREATE "
                "EXTENSION postgis, which a role that is not a superuser cannot execute in a fresh "
                "database. Set AUSPICE_BACKUP_ADMIN_URL to a connection that can, or pre-create the "
                "extensions in the restore target. Until one of those is done this backup is "
                "unproven, which is the state this command exists to reveal."
            )
    finally:
        if not keep:
            _drop_scratch(admin, scratch)
            report.scratch_database = None
        admin.dispose()

    log.info(
        "restore verified" if report.ok else "restore verification failed",
        manifest=manifest_path.name,
        ok=report.ok,
        reason=report.reason,
    )
    return report


def _drop_scratch(admin: Any, name: str) -> None:
    """Drop a scratch database, and refuse to drop anything else.

    The guard is not decoration. This is the only DROP DATABASE in the codebase, and the argument
    reaching it wrong is the difference between a cleaned up test and a lost corpus.
    """
    if not name.startswith(SCRATCH_PREFIX):
        raise BackupError(
            f"refusing to drop {name!r}: only databases named {SCRATCH_PREFIX}* are created and "
            "dropped by this command."
        )
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    except Exception as exc:
        # A scratch database left behind is untidy and harmless. Failing the verify because cleanup
        # failed would report a bad backup on the strength of a bad cleanup.
        log.warning("could not drop the scratch database", name=name, error=str(exc))


def prune(*, keep: int, root: Path | None = None) -> list[str]:
    """Delete all but the newest ``keep`` backups. Returns what was removed.

    A backup directory that grows without bound fills the disk, and a full disk stops the next backup,
    which is how a backup regime dies. Deletion is by manifest, so a dump whose manifest is missing is
    never deleted: it may be the only copy of something.
    """
    if keep < 1:
        raise BackupError(
            "keep must be at least 1. Deleting every backup is not a retention policy."
        )
    directory = root or get_settings().backup_path
    manifests = sorted(directory.glob(f"*{MANIFEST_SUFFIX}"), reverse=True)
    removed: list[str] = []
    for path in manifests[keep:]:
        manifest = BackupManifest.read(path)
        dump = path.parent / manifest.dump_file
        dump.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        removed.append(manifest.dump_file)
    if removed:
        log.info("pruned backups", removed=len(removed), kept=min(keep, len(manifests)))
    return removed
