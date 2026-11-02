"""Evidence-grounded contract clause and royalty-term extraction.

LLM output is treated as an untrusted proposal. Every extracted value must carry
a verbatim quote found in the source chunk and is persisted as PENDING; this
module never approves or activates contractual terms.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from trust_engine.common.config.settings import Settings
from trust_engine.common.infrastructure.db import execute, query
from .cortex import complete


@dataclass(frozen=True)
class ContractTermCandidate:
    candidate_id: str
    contract_id: str
    document_id: str
    contract_version: int
    term_code: str
    term_value: str | None
    royalty_percentage: float | None
    currency: str | None
    rate_unit: str | None
    effective_from: str | None
    effective_to: str | None
    clause_type: str
    clause_text: str
    evidence_quote: str
    source_clause_number: str | None
    source_page_number: int
    approval_status: str = "PENDING"


def _value(row: dict[str, Any], key: str, default: Any = None) -> Any:
    return row.get(key, row.get(key.lower(), default))


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _parse_json_response(raw: str) -> dict[str, Any]:
    value = raw.strip()
    value = re.sub(r"^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$", "", value, flags=re.I)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Cortex did not return valid JSON for contract-term extraction") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("terms"), list):
        raise ValueError("Extraction response must be an object containing a terms array")
    return parsed


def _validate_candidate(item: dict[str, Any], chunk: dict[str, Any]) -> ContractTermCandidate:
    quote = str(item.get("evidence_quote") or "").strip()
    chunk_text = str(_value(chunk, "CHUNK_TEXT", "") or "")
    if not quote or _normal(quote) not in _normal(chunk_text):
        raise ValueError("Extracted term rejected: evidence_quote is not present in its source chunk")

    code = re.sub(r"[^A-Z0-9_]+", "_", str(item.get("term_code") or "").upper()).strip("_")
    if not code:
        raise ValueError("Extracted term is missing term_code")
    percentage = item.get("royalty_percentage")
    if percentage is not None:
        percentage = float(percentage)
        if not 0 <= percentage <= 100:
            raise ValueError("royalty_percentage must be between 0 and 100")
    start = item.get("effective_from")
    end = item.get("effective_to")
    for label, raw in (("effective_from", start), ("effective_to", end)):
        if raw:
            try:
                date.fromisoformat(str(raw))
            except ValueError as exc:
                raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc
    if start and end and date.fromisoformat(str(end)) < date.fromisoformat(str(start)):
        raise ValueError("effective_to cannot precede effective_from")

    document_id = str(_value(chunk, "DOCUMENT_ID", "") or "")
    contract_id = str(_value(chunk, "CONTRACT_ID", "") or "")
    version = int(_value(chunk, "CONTRACT_VERSION", 1) or 1)
    page = int(_value(chunk, "PAGE_NUMBER", 0) or 0)
    clause = _value(chunk, "CLAUSE_NUMBER")
    clause_text = str(item.get("clause_text") or "").strip()
    if not clause_text or not document_id or not contract_id or page < 1:
        raise ValueError("Candidate is missing source document, contract, page, or clause text")
    identity = "|".join((document_id, code, str(start or ""), str(end or ""), quote))
    candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return ContractTermCandidate(
        candidate_id=candidate_id,
        contract_id=contract_id,
        document_id=document_id,
        contract_version=version,
        term_code=code,
        term_value=str(item["term_value"]) if item.get("term_value") is not None else None,
        royalty_percentage=percentage,
        currency=str(item["currency"]).upper() if item.get("currency") else None,
        rate_unit=str(item["rate_unit"]) if item.get("rate_unit") else None,
        effective_from=str(start) if start else None,
        effective_to=str(end) if end else None,
        clause_type=str(item.get("clause_type") or "OTHER").upper(),
        clause_text=clause_text,
        evidence_quote=quote,
        source_clause_number=str(clause) if clause is not None else None,
        source_page_number=page,
    )


def persist_term_candidates(
    candidates: list[ContractTermCandidate], *, settings: Settings | None = None
) -> int:
    """Idempotently persist extraction proposals; never write approved terms here."""
    if not candidates:
        return 0
    sql = """
    MERGE INTO AI.CONTRACT_TERM_CANDIDATES T
    USING (
      SELECT %s::VARCHAR CANDIDATE_ID, %s::VARCHAR CONTRACT_ID,
             %s::VARCHAR DOCUMENT_ID, %s::NUMBER CONTRACT_VERSION,
             %s::VARCHAR TERM_CODE, %s::VARCHAR TERM_VALUE,
             %s::NUMBER(9,6) ROYALTY_PERCENTAGE, %s::VARCHAR CURRENCY,
             %s::VARCHAR RATE_UNIT, %s::DATE EFFECTIVE_FROM,
             %s::DATE EFFECTIVE_TO, %s::VARCHAR CLAUSE_TYPE,
             %s::VARCHAR CLAUSE_TEXT, %s::VARCHAR EVIDENCE_QUOTE,
             %s::VARCHAR SOURCE_CLAUSE_NUMBER, %s::NUMBER SOURCE_PAGE_NUMBER
    ) S
    ON T.CANDIDATE_ID = S.CANDIDATE_ID
    WHEN MATCHED THEN UPDATE SET
      T.CLAUSE_TEXT = S.CLAUSE_TEXT, T.EVIDENCE_QUOTE = S.EVIDENCE_QUOTE,
      T.UPDATED_AT = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT (
      CANDIDATE_ID, CONTRACT_ID, DOCUMENT_ID, CONTRACT_VERSION, TERM_CODE,
      TERM_VALUE, ROYALTY_PERCENTAGE, CURRENCY, RATE_UNIT, EFFECTIVE_FROM,
      EFFECTIVE_TO, CLAUSE_TYPE, CLAUSE_TEXT, EVIDENCE_QUOTE,
      SOURCE_CLAUSE_NUMBER, SOURCE_PAGE_NUMBER, APPROVAL_STATUS
    ) VALUES (
      S.CANDIDATE_ID, S.CONTRACT_ID, S.DOCUMENT_ID, S.CONTRACT_VERSION,
      S.TERM_CODE, S.TERM_VALUE, S.ROYALTY_PERCENTAGE, S.CURRENCY, S.RATE_UNIT,
      S.EFFECTIVE_FROM, S.EFFECTIVE_TO, S.CLAUSE_TYPE, S.CLAUSE_TEXT,
      S.EVIDENCE_QUOTE, S.SOURCE_CLAUSE_NUMBER, S.SOURCE_PAGE_NUMBER, 'PENDING'
    )
    """
    rows = [
        (
            c.candidate_id, c.contract_id, c.document_id, c.contract_version,
            c.term_code, c.term_value, c.royalty_percentage, c.currency, c.rate_unit,
            c.effective_from, c.effective_to, c.clause_type, c.clause_text,
            c.evidence_quote, c.source_clause_number, c.source_page_number,
        )
        for c in candidates
    ]
    from trust_engine.common.infrastructure.db import connection
    with connection(settings) as conn, conn.cursor() as cur:
        cur.executemany(sql, rows)
        return int(cur.rowcount or len(rows))


def extract_contract_terms(
    document_id: str, *, persist: bool = True, settings: Settings | None = None
) -> list[ContractTermCandidate]:
    """Extract clause/royalty proposals from one ingested document's Snowflake chunks."""
    if not document_id.strip():
        raise ValueError("document_id is required")
    chunks = query(
        """SELECT CHUNK_TEXT, CONTRACT_ID, DOCUMENT_ID, CONTRACT_VERSION,
                  PAGE_NUMBER, CLAUSE_NUMBER, DOCUMENT_TYPE
           FROM AI.DOCUMENT_CHUNKS WHERE DOCUMENT_ID = %s
           ORDER BY PAGE_NUMBER, CHUNK_INDEX""",
        (document_id,), settings,
    )
    if not chunks:
        raise ValueError(f"No persisted chunks found for document {document_id}")

    candidates: list[ContractTermCandidate] = []
    for chunk in chunks:
        text = str(_value(chunk, "CHUNK_TEXT", "") or "")
        if not text.strip():
            continue
        prompt = (
            "You extract contract clauses as structured review proposals. Return JSON only: "
            '{"terms":[{"term_code":"ROYALTY_RATE","term_value":"...","royalty_percentage":12.0,'
            '"currency":"USD","rate_unit":"of net sales","effective_from":"YYYY-MM-DD",'
            '"effective_to":null,"clause_type":"ROYALTY","clause_text":"complete relevant clause",'
            '"evidence_quote":"verbatim contiguous quote from supplied text"}]}. '
            "Include royalty rates, payment basis, minimum guarantees, exclusivity, term, "
            "renewal, termination, reporting, audit, territory and sublicensing clauses when "
            "explicitly present. Do not infer values or dates. Use null for unknown dates and "
            "numbers. Include only clauses supported by an exact verbatim evidence_quote. "
            "The evidence quote must be copied exactly from the source. If none, return terms [].\n"
            f"SOURCE DOCUMENT: {document_id}\nPAGE: {_value(chunk, 'PAGE_NUMBER')}\n"
            f"CLAUSE: {_value(chunk, 'CLAUSE_NUMBER')}\nTEXT:\n{text}"
        )
        response = _parse_json_response(complete(prompt, settings=settings))
        for item in response["terms"]:
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(_validate_candidate(item, chunk))
            except (TypeError, ValueError):
                # Fail closed for individual unsupported/invalid model claims.
                continue
    # Stable de-duplication handles overlapping chunks without losing source evidence.
    unique = {candidate.candidate_id: candidate for candidate in candidates}
    result = list(unique.values())
    if persist and result:
        persist_term_candidates(result, settings=settings)
    return result


def validate_amendment_precedence(
    document_id: str, *, settings: Settings | None = None
) -> dict[str, Any]:
    """Validate amendment lineage and effective-date conflicts against approved terms.

    This is a review gate, not an automatic legal interpretation or approval.
    Overlapping approved periods are surfaced for reviewer resolution; no historical
    approved row is silently changed.
    """
    documents = query(
        """SELECT DOCUMENT_ID, CONTRACT_ID, DOCUMENT_TYPE, DOCUMENT_VERSION,
                  CONTRACT_VERSION, PARENT_DOCUMENT_ID, EFFECTIVE_DATE, EXPIRY_DATE
           FROM AI.DOCUMENTS WHERE DOCUMENT_ID = %s""",
        (document_id,), settings,
    )
    if not documents:
        raise ValueError(f"Document {document_id} is not registered in AI.DOCUMENTS")
    doc = documents[0]
    contract_id = _value(doc, "CONTRACT_ID")
    doc_type = str(_value(doc, "DOCUMENT_TYPE", "ORIGINAL")).upper()
    version = int(_value(doc, "CONTRACT_VERSION", 1) or 1)
    parent_id = _value(doc, "PARENT_DOCUMENT_ID")
    findings: list[dict[str, Any]] = []

    if doc_type == "AMENDMENT":
        if not parent_id:
            findings.append({"code": "MISSING_PARENT", "severity": "BLOCKER",
                             "message": "Amendment must identify its parent document."})
        else:
            parents = query(
                """SELECT CONTRACT_ID, CONTRACT_VERSION FROM AI.DOCUMENTS
                   WHERE DOCUMENT_ID = %s""",
                (parent_id,), settings,
            )
            if not parents:
                findings.append({"code": "PARENT_NOT_FOUND", "severity": "BLOCKER",
                                 "message": "Amendment parent document is not registered."})
            elif _value(parents[0], "CONTRACT_ID") != contract_id:
                findings.append({"code": "PARENT_CONTRACT_MISMATCH", "severity": "BLOCKER",
                                 "message": "Parent document belongs to a different contract."})
            elif int(_value(parents[0], "CONTRACT_VERSION", 0)) >= version:
                findings.append({"code": "NON_MONOTONIC_VERSION", "severity": "BLOCKER",
                                 "message": "Amendment contract_version must exceed its parent."})
        if not _value(doc, "EFFECTIVE_DATE"):
            findings.append({"code": "MISSING_AMENDMENT_EFFECTIVE_DATE", "severity": "BLOCKER",
                             "message": "Amendment effective date must be explicit in document metadata."})

    proposals = query(
        """SELECT CANDIDATE_ID, TERM_CODE, ROYALTY_PERCENTAGE, EFFECTIVE_FROM,
                  EFFECTIVE_TO, APPROVAL_STATUS, SOURCE_PAGE_NUMBER
           FROM AI.CONTRACT_TERM_CANDIDATES
           WHERE DOCUMENT_ID = %s""",
        (document_id,), settings,
    )
    approved = query(
        """SELECT TERM_ID, TERM_CODE, ROYALTY_PERCENTAGE, EFFECTIVE_FROM, EFFECTIVE_TO,
                  CONTRACT_VERSION, SOURCE_DOCUMENT_ID
           FROM AI.APPROVED_CONTRACT_TERMS
           WHERE CONTRACT_ID = %s""",
        (contract_id,), settings,
    )
    for proposal in proposals:
        code = str(_value(proposal, "TERM_CODE", ""))
        start_raw = _value(proposal, "EFFECTIVE_FROM")
        end_raw = _value(proposal, "EFFECTIVE_TO")
        if not start_raw:
            findings.append({"code": "TERM_EFFECTIVE_DATE_MISSING", "severity": "REVIEW",
                             "candidate_id": _value(proposal, "CANDIDATE_ID"),
                             "message": f"{code} proposal has no explicit effective_from date."})
            continue
        start = start_raw if isinstance(start_raw, date) else date.fromisoformat(str(start_raw)[:10])
        end = (end_raw if isinstance(end_raw, date) else date.fromisoformat(str(end_raw)[:10])) if end_raw else None
        for old in approved:
            if str(_value(old, "TERM_CODE", "")) != code:
                continue
            old_start_raw = _value(old, "EFFECTIVE_FROM")
            old_end_raw = _value(old, "EFFECTIVE_TO")
            old_start = old_start_raw if isinstance(old_start_raw, date) else date.fromisoformat(str(old_start_raw)[:10])
            old_end = (old_end_raw if isinstance(old_end_raw, date) else date.fromisoformat(str(old_end_raw)[:10])) if old_end_raw else None
            overlaps = (end is None or old_start <= end) and (old_end is None or start <= old_end)
            if overlaps and _value(old, "SOURCE_DOCUMENT_ID") != document_id:
                findings.append({
                    "code": "APPROVED_TERM_PERIOD_OVERLAP",
                    "severity": "REVIEW",
                    "candidate_id": _value(proposal, "CANDIDATE_ID"),
                    "existing_term_id": _value(old, "TERM_ID"),
                    "message": (
                        f"{code} overlaps an existing approved term. A reviewer must establish "
                        "precedence and, if appropriate, close the prior period on "
                        f"{(start - timedelta(days=1)).isoformat()} before approval."
                    ),
                })

    blockers = [item for item in findings if item["severity"] == "BLOCKER"]
    reviews = [item for item in findings if item["severity"] == "REVIEW"]
    return {
        "document_id": document_id,
        "contract_id": contract_id,
        "document_type": doc_type,
        "contract_version": version,
        "status": "INVALID" if blockers else ("REVIEW_REQUIRED" if reviews else "VALID"),
        "findings": findings,
        "candidate_count": len(proposals),
        "approved_terms_are_unchanged": True,
    }
