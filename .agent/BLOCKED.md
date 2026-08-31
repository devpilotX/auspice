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

## B-005: Decide the correct adoption date for the Linn County moratorium row.

Finding NEW-03. The row `linn-data-center-moratorium-2026` records `adopted_on: 2026-04-08` and
`effective_on: 2026-04-08`. Its primary citation,
`https://www.linncountyiowa.gov/m/newsflash/Home/Detail/4487`, describes a different event: posted
1 July 2026, "has approved an 18-month moratorium on accepting new applications to rezone property to
the EU-3 Large-Scale Data Center Zoning District in unincorporated Linn County", "takes effect
immediately", and it refers to the February 2026 ordinance as a separate earlier action. Nothing on the
page mentions 8 April.

Where 8 April 2026 does appear verbatim is the Newton County resolution cited two rows above, as the
expiry of Newton's earlier emergency moratorium. That is a plausible route for the value to have
crossed rows during hand labelling, and it is a hypothesis rather than a conclusion.

What the agent did: nothing to the dates. Repairing the quote alone would make the citation verify and
admit the row to training with a date its own source contradicts. An unverified row is excluded by the
training query; a verified one is not. So the safe state is the current one, and the row stays out of
training until the date is settled.

What the operator has to decide: whether the moratorium was adopted around 1 July 2026 and the date
should be corrected, or whether there was an earlier April action and the citation is simply the wrong
page for this row. Both are one edit. Neither is the agent's to guess under the rule that no label is
fabricated.

Once decided, `auspice labels quote --url <the right page> --find <a phrase>` produces a verbatim quote
that cannot fail verification.

## B-006: Two cited sources cannot be verified because they render client side.

Finding NEW-04. `wsbtv.com` parses to 219 characters and `cbs2iowa.com` to 7636, both of which are
application shell rather than article text. No transcription of any quote from either can be located,
so those citations stay unverified permanently as things stand.

This does not currently block a row: the Newton row now carries a verified primary citation alongside
the unverifiable WSB-TV one, and the training query needs only one verified item. It will block rows
whose only source is a client rendered news site.

The mechanism to fix it already exists in the repository. `pipeline/adapters/` has a Playwright path for
pages that need JavaScript. `pipeline/extract/verify.py` does not use it. Routing verification through
that path when a fetch parses to implausibly little text is the fix, and it is engineering rather than
an operator decision, so it is recorded here only because it explains why two citations will stay
unverified until it is done.

## B-004: Two items that are outside software entirely.

From the audit, recorded so they are not lost:

- Errors and omissions insurance and a lawyer reviewed terms of service before the first sale.
  `docs/TERMS.md` and `docs/PRIVACY.md` exist and are not a substitute. Specification section 15.1
  calls this non negotiable.
- A trademark clearance opinion on Permission Bureau. One search found no company or mark using the
  name, which is not a clearance opinion.
