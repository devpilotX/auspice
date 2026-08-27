"""Two ways to forge a citation or a record that an audit found and the code now refuses.

Kept as their own file because both were found by attacking the system rather than by reading it, and both
passed every existing test at the time. That is the useful thing to record: the mechanisms were correct in
the cases they were written for, and wrong in a case nobody had tried.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text

from auspice import ledger
from auspice.domain import ParseMethod
from auspice.pipeline.extract.verify import MAX_ELIDED_GAP_CHARS, verify_quote
from auspice.pipeline.parse import ParsedDocument, parse_plain_text
from tests.conftest import requires_db
from tests.unit.test_ledger import _payload, _seed_prediction


def _document(body: str) -> ParsedDocument:
    return parse_plain_text(body, document_id="0" * 64, method=ParseMethod.native_text)


class TestAnEllipsisCannotStitchUnrelatedStatements:
    """An ellipsis elides a clause. It must not join two statements about different things.

    Piecewise verification required every fragment to appear, in order, and to be at least twelve
    characters. It did not bound the distance between them, so two fragments from opposite ends of a long
    document verified as one quotation and read as one sentence. The fragments were real, the order was
    real, and the sentence was fabricated.
    """

    LONG = (
        "The Board voted to approve the Northgate rezoning by a vote of six to one. "
        + " ".join(
            f"Item {n}. The Commission reviewed a routine site plan and continued it to the next meeting."
            for n in range(1, 12)
        )
        + " A separate application by Cinder Lake Compute was denied for insufficient water supply."
    )

    def test_an_approval_cannot_be_stitched_to_an_unrelated_denial(self) -> None:
        result = verify_quote(
            _document(self.LONG),
            "voted to approve the Northgate rezoning ... was denied for insufficient water supply",
        )
        assert not result.verified
        assert result.reason is not None
        assert "ellipsis spans" in result.reason

    def test_a_denial_reason_cannot_be_moved_onto_another_project(self) -> None:
        result = verify_quote(
            _document(self.LONG),
            "the Northgate rezoning ... denied for insufficient water supply",
        )
        assert not result.verified

    def test_a_real_elision_inside_one_sentence_still_verifies(self) -> None:
        """The bound must not break the case the feature exists for.

        A long sentence with a parenthetical removed is a legitimate citation and the most common one in
        this corpus, so a fix that refused it would be worse than the defect.
        """
        parsed = _document(
            "The Board finds that the application, having been reviewed by staff and the Planning "
            "Commission and having been the subject of two public hearings at which forty one speakers "
            "were heard, does not satisfy the water supply standard of section 18-402."
        )
        result = verify_quote(
            parsed,
            "The Board finds that the application ... does not satisfy the water supply standard",
        )
        assert result.verified, result.reason

    @pytest.mark.parametrize(
        ("gap", "expected"),
        [
            (100, True),
            (MAX_ELIDED_GAP_CHARS - 1, True),
            (MAX_ELIDED_GAP_CHARS + 1, False),
            (5000, False),
        ],
    )
    def test_the_bound_is_where_it_says_it_is(self, gap: int, expected: bool) -> None:
        parsed = _document(
            "The motion carried unanimously." + ("x" * gap) + "The application is denied."
        )
        result = verify_quote(
            parsed, "The motion carried unanimously ... The application is denied"
        )
        assert result.verified is expected

    def test_two_true_statements_about_the_same_decision_still_verify(self) -> None:
        """Not everything joined by an ellipsis is a fabrication.

        Both halves here are true of this document and close together, and refusing them would make the
        verifier useless for the documents it exists to read.
        """
        parsed = _document(
            "The Board finds that the application satisfies the comprehensive plan. "
            "A motion to approve the rezoning was made by Supervisor Hall. "
            "The motion failed on a vote of two to five. "
            "The application is hereby denied without prejudice."
        )
        assert verify_quote(
            parsed, "the application satisfies the comprehensive plan ... is hereby denied"
        ).verified


@requires_db
class TestDeletingTheEndOfTheLedgerIsDetected:
    """The deletion someone would actually make.

    Removing an entry from the middle breaks the next entry's prev_hash and was always caught. Removing
    the last entry was not: what remains is a shorter chain that verifies perfectly. The most recent
    predictions are the ones that have just been proved wrong, so the tail is precisely what an operator
    under pressure would delete.
    """

    @staticmethod
    def _publish_four(conn: Connection) -> None:
        for index in range(1, 5):
            prediction_id = _seed_prediction(conn, index)
            ledger.publish(conn, prediction_id=prediction_id, payload=_payload(index))

    def test_four_entries_verify(self, clean_db: Connection) -> None:
        self._publish_four(clean_db)
        report = ledger.verify(clean_db)
        assert report.ok
        assert report.entries == 4

    def test_deleting_the_last_entry_breaks_verification(self, clean_db: Connection) -> None:
        self._publish_four(clean_db)
        clean_db.execute(text("DELETE FROM ledger_entry WHERE seq = 4"))

        report = ledger.verify(clean_db)
        assert not report.ok, "a truncated ledger must not verify"
        assert report.broken_at == 4
        assert report.reason is not None
        assert "deleted from the end" in report.reason

    def test_deleting_the_last_two_entries_reports_both(self, clean_db: Connection) -> None:
        self._publish_four(clean_db)
        clean_db.execute(text("DELETE FROM ledger_entry WHERE seq >= 3"))

        report = ledger.verify(clean_db)
        assert not report.ok
        assert report.broken_at == 3
        assert report.reason is not None
        assert "2 entry or entries" in report.reason

    def test_deleting_from_the_middle_is_still_caught(self, clean_db: Connection) -> None:
        """The original guarantee, asserted so the new check cannot be mistaken for the only one."""
        self._publish_four(clean_db)
        clean_db.execute(text("DELETE FROM ledger_entry WHERE seq = 2"))

        report = ledger.verify(clean_db)
        assert not report.ok
        assert report.broken_at == 3
        assert report.reason is not None
        assert "prev_hash" in report.reason

    def test_publishing_on_a_truncated_chain_is_refused(self, clean_db: Connection) -> None:
        """The consequence that matters. A broken chain must not be extended."""
        from auspice.errors import LedgerTamperError

        self._publish_four(clean_db)
        clean_db.execute(text("DELETE FROM ledger_entry WHERE seq = 4"))

        with pytest.raises(LedgerTamperError, match="deleted from the end"):
            ledger.require_intact(clean_db)

    def test_an_empty_ledger_verifies(self, clean_db: Connection) -> None:
        """Nothing published is not the same as something deleted, and must not be reported as tampering."""
        report = ledger.verify(clean_db)
        assert report.ok
        assert report.entries == 0
        assert report.head is None
