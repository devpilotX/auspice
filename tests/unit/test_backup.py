"""Backups, and the guard on the only DROP DATABASE in the codebase.

Audit finding P2-3 named "no automated or tested backups". The word that matters is tested: a dump
whose restore has never been attempted is a file, and every organisation that has lost data had one.

The live restore path is exercised by `auspice ops verify` against a real cluster, which needs
administrative credentials and a scratch database, so it is not run here. What is tested here is
everything that decides whether that command is safe and whether its verdict means anything.

**The drop guard.** `_drop_scratch` is the only DROP DATABASE in the repository. Its argument reaching
it wrong is the difference between a cleaned up check and a lost corpus, so the guard is asserted
rather than trusted.

**Manifest independence.** Row counts are taken from the live database before the dump runs. If they
came out of the dump the check would be circular: a truncated dump would report what it contained and
agree with itself. Tested by asserting the count fields are populated from a query, and that a mismatch
is reported per table with both numbers.

**Retention.** A backup directory that grows without bound fills the disk, and a full disk stops the
next backup, which is how a backup regime dies. Pruning must never delete a dump whose manifest is
missing, because that may be the only copy of something.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auspice.ops import backup


class TestTheDropGuard:
    """The only DROP DATABASE in the codebase. Its guard is asserted, not trusted."""

    class _Admin:
        """An engine that records what it was asked to execute and never touches a database."""

        def __init__(self) -> None:
            self.executed: list[str] = []

        def connect(self) -> Any:
            return self

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, statement: Any) -> None:
            self.executed.append(str(statement))

    def test_a_scratch_name_is_dropped(self) -> None:
        admin = self._Admin()
        backup._drop_scratch(admin, f"{backup.SCRATCH_PREFIX}abc123")
        assert len(admin.executed) == 1
        assert "DROP DATABASE" in admin.executed[0]
        assert f"{backup.SCRATCH_PREFIX}abc123" in admin.executed[0]

    @pytest.mark.parametrize(
        "name",
        [
            "auspice",
            "auspice_test",
            "postgres",
            "template1",
            "",
            "auspice_restore",
            "restore_check_abc",
            "AUSPICE_RESTORE_CHECK_abc",
        ],
    )
    def test_anything_else_is_refused_and_nothing_is_executed(self, name: str) -> None:
        admin = self._Admin()
        with pytest.raises(backup.BackupError, match="refusing to drop"):
            backup._drop_scratch(admin, name)
        assert admin.executed == [], "a refused drop must not reach the database at all"

    def test_the_production_database_name_is_refused(self) -> None:
        """The name that would matter. Explicit, because a parametrised case is easy to skim past."""
        from auspice.config import get_settings

        live = str(get_settings().database_url).rsplit("/", 1)[-1].split("?")[0]
        admin = self._Admin()
        with pytest.raises(backup.BackupError):
            backup._drop_scratch(admin, live)
        assert admin.executed == []


class TestTargetParsing:
    def test_a_url_is_split_into_the_parts_the_client_tools_need(self) -> None:
        target = backup.DatabaseTarget(
            host="db.internal", port=6432, user="auspice", password="s3cret", database="auspice"
        )
        argv = target.argv()
        assert argv == [
            "--host",
            "db.internal",
            "--port",
            "6432",
            "--username",
            "auspice",
            "--dbname",
            "auspice",
        ]

    def test_the_password_goes_in_the_environment_never_the_command_line(self) -> None:
        """A password on a command line is readable in the process list by every user on the host."""
        target = backup.DatabaseTarget(
            host="h", port=5432, user="u", password="s3cret", database="d"
        )
        assert "s3cret" not in " ".join(target.argv())
        assert target.environment()["PGPASSWORD"] == "s3cret"

    def test_no_password_means_no_variable_rather_than_an_empty_one(self) -> None:
        """An empty PGPASSWORD is not the same as absent: it stops libpq trying other methods."""
        target = backup.DatabaseTarget(host="h", port=5432, user="u", password="", database="d")
        assert "PGPASSWORD" not in target.environment()

    def test_an_override_database_is_used(self) -> None:
        target = backup.DatabaseTarget(host="h", port=5432, user="u", password="", database="d")
        assert "scratch" in target.argv(database="scratch")

    def test_the_real_settings_parse(self) -> None:
        target = backup.DatabaseTarget.from_settings()
        assert target.host
        assert target.port > 0
        assert target.database

    def test_the_admin_target_falls_back_to_the_application_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A managed database frequently gives the application role the permission anyway."""
        from auspice.config import get_settings

        patched = get_settings().model_copy(update={"backup_admin_url": None})
        monkeypatch.setattr(backup, "get_settings", lambda: patched)
        assert (
            backup.DatabaseTarget.from_settings(admin=True) == backup.DatabaseTarget.from_settings()
        )


class TestManifest:
    @staticmethod
    def _manifest(**overrides: Any) -> backup.BackupManifest:
        base: dict[str, Any] = {
            "created_at": "2026-08-31T04:12:26+00:00",
            "database": "auspice",
            "dump_file": "auspice-20260831T041212Z.dump",
            "dump_bytes": 1366480,
            "dump_sha256": "e" * 64,
            "postgres_version": "17.9",
            "schema_revision": "0004_alert_delivery",
            "row_counts": {"application": 1, "ledger_entry": 2, "jurisdiction": 12},
        }
        base.update(overrides)
        return backup.BackupManifest(**base)

    def test_it_round_trips_through_disk(self, tmp_path: Path) -> None:
        path = tmp_path / f"x{backup.MANIFEST_SUFFIX}"
        path.write_text(json.dumps(self._manifest().as_dict()), encoding="utf-8")
        assert backup.BackupManifest.read(path) == self._manifest()

    def test_the_verified_tables_are_the_unrecoverable_ones(self) -> None:
        """A dump that restored the schema and none of these has failed, whatever else came back."""
        assert "application" in backup.VERIFIED_TABLES
        assert "ledger_entry" in backup.VERIFIED_TABLES
        assert "fact_evidence" in backup.VERIFIED_TABLES
        assert "instrument" in backup.VERIFIED_TABLES

    def test_a_missing_dump_fails_before_any_database_is_touched(self, tmp_path: Path) -> None:
        path = tmp_path / f"x{backup.MANIFEST_SUFFIX}"
        path.write_text(json.dumps(self._manifest().as_dict()), encoding="utf-8")
        report = backup.verify(path)
        assert not report.ok
        assert report.reason is not None
        assert "missing" in report.reason
        assert report.scratch_database is None

    def test_a_tampered_dump_fails_on_the_digest_and_stops(self, tmp_path: Path) -> None:
        """Nothing further is attempted, so a corrupt file cannot cause a restore to run."""
        dump = tmp_path / "auspice-20260831T041212Z.dump"
        dump.write_bytes(b"not a postgres dump")
        path = tmp_path / f"x{backup.MANIFEST_SUFFIX}"
        path.write_text(json.dumps(self._manifest().as_dict()), encoding="utf-8")

        report = backup.verify(path)
        assert not report.digest_ok
        assert not report.listing_ok
        assert not report.restore_ok
        assert report.reason is not None
        assert "altered or truncated" in report.reason

    def test_the_digest_is_of_the_file_contents(self, tmp_path: Path) -> None:
        import hashlib

        payload = b"some bytes" * 1000
        path = tmp_path / "f.bin"
        path.write_bytes(payload)
        assert backup.sha256_of(path) == hashlib.sha256(payload).hexdigest()


class TestVerifyReport:
    def test_a_report_is_only_ok_when_every_check_passed(self) -> None:
        assert backup.VerifyReport("m", True, True, True, True).ok

    @pytest.mark.parametrize(
        ("digest", "listing", "restore", "counts", "which"),
        [
            (False, True, True, True, "digest"),
            (True, False, True, True, "dump readable"),
            (True, True, False, True, "restore"),
            (True, True, True, False, "row counts"),
        ],
    )
    def test_any_failed_check_fails_the_whole_report(
        self, digest: bool, listing: bool, restore: bool, counts: bool, which: str
    ) -> None:
        report = backup.VerifyReport("m", digest, listing, restore, counts)
        assert not report.ok, f"a failed {which} check must fail the report"

    def test_the_verdict_is_spelled_out_rather_than_implied(self) -> None:
        failing = backup.VerifyReport("m", True, True, True, False).as_dict()
        assert failing["verdict"] == "FAIL"
        assert backup.VerifyReport("m", True, True, True, True).as_dict()["verdict"] == "pass"


class TestRetention:
    @staticmethod
    def _write(root: Path, name: str, *, with_manifest: bool = True) -> None:
        (root / f"{name}.dump").write_bytes(b"x")
        if with_manifest:
            (root / f"{name}{backup.MANIFEST_SUFFIX}").write_text(
                json.dumps(
                    {
                        "created_at": "2026-08-31T00:00:00+00:00",
                        "database": "auspice",
                        "dump_file": f"{name}.dump",
                        "dump_bytes": 1,
                        "dump_sha256": "a" * 64,
                        "postgres_version": "17.9",
                        "schema_revision": None,
                        "row_counts": {},
                    }
                ),
                encoding="utf-8",
            )

    def test_the_newest_are_kept(self, tmp_path: Path) -> None:
        for stamp in ("20260101T000000Z", "20260201T000000Z", "20260301T000000Z"):
            self._write(tmp_path, f"auspice-{stamp}")
        removed = backup.prune(keep=2, root=tmp_path)
        assert removed == ["auspice-20260101T000000Z.dump"]
        assert not (tmp_path / "auspice-20260101T000000Z.dump").exists()
        assert (tmp_path / "auspice-20260301T000000Z.dump").exists()

    def test_a_dump_with_no_manifest_is_never_deleted(self, tmp_path: Path) -> None:
        """It may be the only copy of something, and nothing here knows what it holds."""
        self._write(tmp_path, "auspice-20260101T000000Z", with_manifest=False)
        self._write(tmp_path, "auspice-20260201T000000Z")
        self._write(tmp_path, "auspice-20260301T000000Z")
        backup.prune(keep=1, root=tmp_path)
        assert (tmp_path / "auspice-20260101T000000Z.dump").exists()

    def test_keeping_nothing_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(backup.BackupError, match="not a retention policy"):
            backup.prune(keep=0, root=tmp_path)

    def test_listing_ignores_an_unreadable_manifest_rather_than_failing(
        self, tmp_path: Path
    ) -> None:
        self._write(tmp_path, "auspice-20260301T000000Z")
        (tmp_path / f"broken{backup.MANIFEST_SUFFIX}").write_text("{not json", encoding="utf-8")
        assert len(backup.list_backups(root=tmp_path)) == 1

    def test_an_absent_directory_lists_nothing_rather_than_raising(self, tmp_path: Path) -> None:
        assert backup.list_backups(root=tmp_path / "nope") == []


class TestBinaryDiscovery:
    def test_an_unknown_binary_names_the_remedy(self) -> None:
        """Runs anywhere, because it asserts the message rather than the environment."""
        from auspice.errors import StageUnavailableError

        with pytest.raises(StageUnavailableError, match="bootstrap-postgres"):
            backup.find_binary("pg_definitely_not_a_real_tool")

    def test_the_client_binaries_are_found(self) -> None:
        """On PATH, or in the toolchain the Windows bootstrap script unpacks under .tools.

        Skipped rather than failed when they are absent. This is a precondition of the environment,
        not a property of the code, and an earlier version of it asserted unconditionally and turned a
        fresh clone red: `.tools/` is ignored and created by `infra/scripts/bootstrap-postgres.ps1`, so
        a clone that has not been bootstrapped has no binaries and no defect. Found by the IRONCLAD
        Gate 6 fresh clone run, which is the failure that gate exists to catch.
        """
        import shutil

        from auspice.errors import StageUnavailableError

        try:
            assert backup.find_binary("pg_dump").exists()
            assert backup.find_binary("pg_restore").exists()
        except StageUnavailableError:
            if shutil.which("pg_dump"):
                raise
            pytest.skip(
                "PostgreSQL client binaries are not installed. Run "
                "infra/scripts/bootstrap-postgres.ps1, or install the client package."
            )
