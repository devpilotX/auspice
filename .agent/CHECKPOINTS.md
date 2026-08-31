# Checkpoints

Restore points, in order. Rewind with `git reset --hard <tag>`. See `.agent/RESTORE.md`.

| Tag | Commit | What it holds |
|---|---|---|
| `checkpoint/000-baseline` | `2d8efdf` | The operator's `main`, untouched. Pre agent state. Nothing was committed here. |
| `checkpoint/001-ignore-kiro-settings` | `149612c` | `.kiro/settings/` added to `.gitignore` so the MCP bearer token cannot reach a commit. Skill definitions tracked. Amended once to fix a CRLF rewrite of the whole file. |
| `checkpoint/002-agent-artifacts` | `9f49370` | The `.agent/` scaffold and `AUDIT_REPORT.md`. |
| `checkpoint/003` to `005` | | Vitest attempt, its revert, CI harness, Phase A close. |
| `checkpoint/006` to `010` | | Phase B: memo extra, Dockerfile and CORS, TLS proxy, portfolio proxy route. |
| `checkpoint/011` to `015` | | Phase C: healthz, event loop, verify_head, verification cache, public endpoints. |
| `checkpoint/016-test-isolation` | `f3885ae` | NEW-01. Endpoint tests no longer read the developer's database. |
| `checkpoint/017-resume-state` | | This snapshot, written so a session restart loses nothing. |

## Off repository backups, never delete

| Path | What it is | Verified |
|---|---|---|
| `C:\Dev\apps\.agent-backups\auspice-20260830-172555.bundle` | Complete history, all refs, 4366984 bytes | `git bundle verify` reports a complete history, and a scratch clone produced 218 tracked files at `2d8efdf` |
| `C:\Dev\apps\.agent-backups\auspice-ignored-20260830-172555\` | The 87 gitignored files a bundle cannot carry: `.env`, `.kiro\`, `artifacts\`, `bootstrap.log`, `var\pg.superuser.pw`, `data-raw\` with 80 corpus files | Copied and counted |
