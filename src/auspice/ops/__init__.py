"""Operational tasks that are not part of the pipeline or the serving process.

Backups live here rather than under `pipeline/` because they are not a stage: nothing downstream
consumes their output, and they run on the deployment's schedule rather than in dependency order.
"""

from __future__ import annotations

from auspice.ops.backup import (
    MANIFEST_SUFFIX,
    SCRATCH_PREFIX,
    VERIFIED_TABLES,
    BackupError,
    BackupManifest,
    DatabaseTarget,
    VerifyReport,
    create,
    find_binary,
    list_backups,
    prune,
    sha256_of,
    verify,
)

__all__ = [
    "MANIFEST_SUFFIX",
    "SCRATCH_PREFIX",
    "VERIFIED_TABLES",
    "BackupError",
    "BackupManifest",
    "DatabaseTarget",
    "VerifyReport",
    "create",
    "find_binary",
    "list_backups",
    "prune",
    "sha256_of",
    "verify",
]
