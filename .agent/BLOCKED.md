# Blocked, awaiting the operator

Nothing here stopped the run. Each item is something only the operator can do. Work continued around
all of them.

## B-001: Revoke the exposed GitHub personal access token. CRITICAL, act first.

`.kiro/settings/mcp.json` contained a live `github_pat_` bearer token in plain text, in a git working
tree, with `X-MCP-Readonly: false`, `X-MCP-Lockdown: false` and `autoApprove: ["*"]`.

What the agent did: refused to stage it, added `.kiro/settings/` to `.gitignore`, snapshotted the file
outside the repository, and verified by pickaxe search across all refs that no commit on any branch
contains the token or the file.

What the agent cannot do: revoke it. That needs the owner, at https://github.com/settings/tokens.

Why it must be revoked anyway: the value was printed into the session transcript by the agent's own
secret scan command, which was a defect in how that command was written. Treat the token as
compromised independently of anything in git. When re-adding it, reference an environment variable
rather than embedding the literal, so the file cannot carry a secret again.

## B-002: Run the two gates the agent is not permitted to execute.

The operator instructed the agent not to start servers, and docker is not installed on this machine.
Two DONE criteria therefore cannot be closed by the agent.

```powershell
# criterion 9, 14, 18: the visual suite, which is what caught two CSP bugs historically
npm run test:visual --workspace apps/web

# criteria 12, 13: the container stack and the PDF memo
docker compose -f infra/docker-compose.yml up -d
```

The CI workflow change in plan Task 4 makes the visual suite run automatically, so this becomes a
one time handover rather than a standing gap.

## B-003: Supply a language model key, or accept hand labelling as the only route to the corpus.

Extraction has never read a real document because no key is configured. Stage 4 refuses rather than
inventing facts, which is correct. The golden fixtures in `tests/golden/` exist to measure accuracy the
day a key exists. Until then the 400 label target is reachable only by hand, at the 30 to 60 rows per
day rate that `data/labels/README.md` cites.

## B-004: Two items that are outside software entirely.

From the audit, recorded so they are not lost:

- Errors and omissions insurance and a lawyer reviewed terms of service before the first sale.
  `docs/TERMS.md` and `docs/PRIVACY.md` exist and are not a substitute. Specification section 15.1
  calls this non negotiable.
- A trademark clearance opinion on Permission Bureau. One search found no company or mark using the
  name, which is not a clearance opinion.
