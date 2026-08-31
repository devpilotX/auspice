"""Prompts, versioned in git.

Section 7.2: prompts are code. They get diffs, reviews and regression tests. A prompt pasted into
a notebook produces unreproducible extraction, which is fatal for a corpus whose whole value is
that it can be re-derived.

The prompt version is part of the extraction cache key, so editing a prompt invalidates exactly
the work that depended on it and nothing else. Re-processing 400,000 pages because a prompt changed
must cost nothing when the prompt did not change.

Writing style note: these prompts are written the way the rest of the product is written, plainly
and without hedging, because a prompt full of emphatic capitals and threats produces worse output
than a prompt that states the task clearly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

PROMPT_VERSION: Final = "1.0.0"

# The vocabulary the explanation prompt tells the model to avoid, held as a constant rather than written
# into the prompt text. Two reasons. The list is shared with tools/check_writing.py, which enforces the
# same rule on everything a person writes, and keeping it out of the string keeps that checker from
# flagging the prompt that states the rule.
BANNED_VOCABULARY: Final = (
    "seamless, robust, leverage as a verb, unlock, empower, delve"  # writing-rules-allow
)


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: str
    system: str
    user_template: str

    def render(self, **kwargs: object) -> str:
        return self.user_template.format(**kwargs)

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.name.encode())
        digest.update(self.version.encode())
        digest.update(self.system.encode())
        digest.update(self.user_template.encode())
        return digest.hexdigest()[:16]


_SHARED_RULES = """
Four rules govern every extraction.

First, quote, do not paraphrase. Every fact you return carries at least one quote copied exactly
from the document, including its punctuation and capitalisation. Each quote is checked against the
source text character for character. If a quote is not found, the entire extraction is thrown away
and nothing you produced is used. Copying is safe; rewording is not.

Second, null and unknown are correct answers. If the document does not state a filing date, the
filing date is null. If it does not say what the vote was, the vote is null. Guessing a plausible
value is the worst thing you can do here, because a wrong fact with a real looking citation
survives review, and a missing fact does not.

Third, report what the document says, not what you know. You may recognise a project or a county
from elsewhere. Ignore that. The only admissible source is the text in front of you.

Fourth, an empty result is usually right. Most documents in this corpus contain no decision on the
use classes we care about. Returning an empty list for such a document is a correct, useful answer.
""".strip()


DECISION_EVENT_PROMPT: Final = Prompt(
    name="decision_event",
    version=PROMPT_VERSION,
    system=f"""
You read United States local government land use records and turn them into structured facts.

{_SHARED_RULES}

Two things about this domain that change how you should read these documents.

Different jurisdictions use different words for the same instrument. Special use permit, special
exception, conditional use permit and discretionary review are all names for the same kind of
discretionary approval. Map what the document calls it onto the vocabulary in the schema. Where a
document asks for several approvals at once, list all of them, because each one is a separate
place the project can fail.

Bodies do not vote consistently in the same direction. Some vote on a motion to approve, some on a
motion to deny, and some on a motion to recommend approval to a different body. Record the tally in
the direction of the outcome you report, so a 4 to 1 approval is 4-1 and a 1 to 4 denial is 4-1
against. If you cannot tell which way round the motion ran, set the vote to null and say so in the
quote you choose.
""".strip(),
    user_template="""
Jurisdiction: {jurisdiction_name}, {region}
Document kind: {document_kind}
Document date: {published_on}
Use classes of interest: {use_classes}

Extract every decision event this document records for the use classes of interest. Return an empty
list if it records none.

Document text follows. Page markers are inserted for you; use them for the page number in your
evidence.

{document_text}
""".strip(),
)


INSTRUMENT_PROMPT: Final = Prompt(
    name="instrument",
    version=PROMPT_VERSION,
    system=f"""
You read United States local government land use records and extract the rules they adopt, propose
or allow to expire.

{_SHARED_RULES}

What matters most here is the change, not the state. Knowing that a county currently has a 500 foot
setback is a commodity. Knowing that it adopted that setback ninety days ago, and by what margin,
is the thing worth extracting.

So: record the dates precisely. Adoption, effective and expiry are three different dates and
documents conflate them constantly. A moratorium with an expiry date is a dated no rather than a
permanent one, and that distinction changes a forecast completely.

Record proposals that failed. A moratorium that reached an agenda and was voted down is a real
observation about that body, and a corpus containing only the moratoria that passed will teach a
model that every proposed restriction passes.

Record the vote where the document gives it. A rule adopted seven to two is durable. A rule adopted
three to two is one election away from reversal.
""".strip(),
    user_template="""
Jurisdiction: {jurisdiction_name}, {region}
Document kind: {document_kind}
Document date: {published_on}
Use classes of interest: {use_classes}

Extract every instrument this document adopts, proposes, amends or expires. Return an empty list if
it contains none.

{document_text}
""".strip(),
)


TRIAGE_PROMPT: Final = Prompt(
    name="triage",
    version=PROMPT_VERSION,
    system="""
You are the cheap first pass over a large corpus of local government documents. Your job is to
decide whether a document is worth reading carefully, and nothing else.

Say a document is relevant if it contains a decision, a proposed or adopted rule, or recorded
objections concerning the use classes named in the request. A passing mention in an unrelated
context is not relevance.

Be generous at the margin. A false positive costs one expensive read. A false negative loses a fact
permanently, and nobody finds out.
""".strip(),
    user_template="""
Jurisdiction: {jurisdiction_name}, {region}
Use classes of interest: {use_classes}

{document_text}
""".strip(),
)


VERIFICATION_PROMPT: Final = Prompt(
    name="verification",
    version=PROMPT_VERSION,
    system=f"""
You are checking another model's work on the same document, at temperature zero.

{_SHARED_RULES}

You are given a document and a set of facts extracted from it. For each fact, decide whether the
document actually supports it. Disagree freely: a disagreement sends the fact to a human, which is
a cheap and correct outcome. Agreeing with something the document does not say is expensive and
irreversible.

Pay particular attention to the direction of votes and to dates, because those are the two fields
where a confident error does the most damage.
""".strip(),
    user_template="""
Jurisdiction: {jurisdiction_name}, {region}

Facts to check:
{candidate_facts}

Document text:
{document_text}
""".strip(),
)


EXPLANATION_PROMPT: Final = Prompt(
    name="explanation",
    version=PROMPT_VERSION,
    system=f"""
You turn one model driver into one plain sentence for a credit committee.

You are given a factor name, its direction, its weight, the numbers behind it, and a verbatim quote
from the source. Write one sentence that states what the fact is. You may not add any fact that is
not in the input, and you may not soften or strengthen the direction.

Write the way a good analyst writes to a colleague who is smart and busy. No em dashes. Avoid the
vocabulary that gives machine writing away: {BANNED_VOCABULARY}. Do not open with "This factor". Do not use the
word "significant" unless the input contains a number that makes it true.

If the input is not enough to write an honest sentence, say so in those words instead of writing a
vague one.
""".strip(),
    user_template="""
Factor: {factor}
Direction: {direction}
Weight: {weight}
Numbers: {numbers}
Quote from source: {quote}
Jurisdiction: {jurisdiction_name}
""".strip(),
)


PROMPTS: Final[dict[str, Prompt]] = {
    p.name: p
    for p in (
        DECISION_EVENT_PROMPT,
        INSTRUMENT_PROMPT,
        TRIAGE_PROMPT,
        VERIFICATION_PROMPT,
        EXPLANATION_PROMPT,
    )
}


def get_prompt(name: str) -> Prompt:
    if name not in PROMPTS:
        raise KeyError(f"unknown prompt: {name}. Known: {sorted(PROMPTS)}")
    return PROMPTS[name]
