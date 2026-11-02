from datetime import date

from trust_engine.contract_intelligence.terms import (
    _validate_candidate,
    validate_amendment_precedence,
)


def test_candidate_requires_verbatim_source_evidence():
    chunk = {
        "DOCUMENT_ID": "DOC-1", "CONTRACT_ID": "C-1", "CONTRACT_VERSION": 2,
        "PAGE_NUMBER": 4, "CLAUSE_NUMBER": "5.2",
        "CHUNK_TEXT": "The royalty rate shall be twelve percent (12%) of net sales.",
    }
    item = {
        "term_code": "royalty_rate", "royalty_percentage": 12,
        "effective_from": "2026-01-01", "clause_type": "ROYALTY",
        "clause_text": "The royalty rate shall be twelve percent (12%) of net sales.",
        "evidence_quote": "twelve percent (12%) of net sales",
    }
    candidate = _validate_candidate(item, chunk)
    assert candidate.approval_status == "PENDING"
    assert candidate.royalty_percentage == 12
    assert candidate.source_page_number == 4


def test_candidate_rejects_hallucinated_quote():
    chunk = {
        "DOCUMENT_ID": "DOC-1", "CONTRACT_ID": "C-1", "CONTRACT_VERSION": 1,
        "PAGE_NUMBER": 1, "CHUNK_TEXT": "Royalty shall be ten percent.",
    }
    item = {
        "term_code": "ROYALTY_RATE", "royalty_percentage": 15,
        "clause_text": "Royalty shall be fifteen percent.",
        "evidence_quote": "fifteen percent",
    }
    try:
        _validate_candidate(item, chunk)
    except ValueError as exc:
        assert "evidence_quote" in str(exc)
    else:
        raise AssertionError("unsupported extraction must be rejected")


def test_candidate_rejects_invalid_dates_and_rate():
    chunk = {
        "DOCUMENT_ID": "DOC-1", "CONTRACT_ID": "C-1", "CONTRACT_VERSION": 1,
        "PAGE_NUMBER": 1, "CHUNK_TEXT": "Royalty shall be ten percent.",
    }
    base = {
        "term_code": "ROYALTY_RATE", "clause_text": "Royalty shall be ten percent.",
        "evidence_quote": "ten percent",
    }
    for item in (
        {**base, "royalty_percentage": 101},
        {**base, "effective_from": "2026-13-01"},
        {**base, "effective_from": "2026-12-01", "effective_to": "2026-11-30"},
    ):
        try:
            _validate_candidate(item, chunk)
        except ValueError:
            continue
        raise AssertionError("invalid candidate should be rejected")


def test_amendment_validation_flags_missing_parent_and_effective_date(monkeypatch):
    import trust_engine.contract_intelligence.terms as terms

    def fake_query(sql, params=None, settings=None):
        if "FROM AI.DOCUMENTS WHERE DOCUMENT_ID" in sql:
            return [{
                "DOCUMENT_ID": "DOC-A", "CONTRACT_ID": "C-1", "DOCUMENT_TYPE": "AMENDMENT",
                "CONTRACT_VERSION": 2, "PARENT_DOCUMENT_ID": None, "EFFECTIVE_DATE": None,
            }]
        if "FROM AI.CONTRACT_TERM_CANDIDATES" in sql:
            return []
        if "FROM AI.APPROVED_CONTRACT_TERMS" in sql:
            return []
        return []

    monkeypatch.setattr(terms, "query", fake_query)
    result = validate_amendment_precedence("DOC-A")
    assert result["status"] == "INVALID"
    assert {item["code"] for item in result["findings"]} == {
        "MISSING_PARENT", "MISSING_AMENDMENT_EFFECTIVE_DATE"
    }
