# How to undo everything

Written for a human in a hurry. You do not need to understand the agent's work to reverse it.

## The two commands that put you back

```powershell
cd C:\Dev\apps\auspice
git switch main
```

That is it. Your branch `main` was never committed to. It still points at `2d8efdf`, which is exactly
where you left it. Every change the agent made lives on the branch
`agent/permission-bureau-20260830-172555` and on tags beginning `checkpoint/`.

Confirm with:

```powershell
git rev-parse main          # must print 2d8efdf7fc2b7a7cf26dfb2e5c74c0d232980060
git status --porcelain      # must print nothing
```

## If you want the agent's branch gone as well

```powershell
git branch -D agent/permission-bureau-20260830-172555
git tag -l "checkpoint/*" | ForEach-Object { git tag -d $_ }
```

## If something is badly wrong and you want the whole repository back from outside

There is a complete copy of the repository history in a single file, outside the working tree, made
before the agent changed anything. It survives a deleted `.git` directory.

```powershell
cd C:\Dev\apps
git clone .agent-backups\auspice-20260830-172555.bundle recovered
```

`recovered\` will be a working repository at `2d8efdf`. This was tested on 30 August 2026: the clone
produced 218 tracked files at the correct commit.

## Files that git does not protect

Git ignores `.env`, `var\`, `data\raw\`, `artifacts\` and `.kiro\settings\`, so the bundle does not
contain them. They were copied here instead:

```
C:\Dev\apps\.agent-backups\auspice-ignored-20260830-172555\
```

That directory holds `.env`, `.kiro\` (including its settings), `artifacts\`, `bootstrap.log`,
`var\pg.superuser.pw`, and `data-raw\` with the 80 files of the content addressed corpus.

To restore one of them, copy it back. Nothing in the agent's run deleted or modified any of them.

## Rewinding to a specific point mid-run

```powershell
git tag -l "checkpoint/*"                                   # list the restore points
git diff checkpoint/007-some-slug --stat                    # see what changed since one
git reset --hard checkpoint/007-some-slug                   # rewind the branch to it
git restore --source=checkpoint/007-some-slug -- some\file  # rewind one file only
```

`.agent\CHECKPOINTS.md` lists every tag with a one line description of what it contains.

## One thing that is not a rollback

`.kiro\settings\mcp.json` was found to contain a live GitHub personal access token in plain text. The
agent added that directory to `.gitignore` so the token could not reach a commit, and it is not in any
commit. Reversing the agent's work does not un-expose that token. It needs to be revoked at
https://github.com/settings/tokens regardless of what you do with this branch.
