"""Snowflake Cortex Search SDK and current AI_COMPLETE adapters."""
from __future__ import annotations

import json
from typing import Any

from snowflake.core import Root
from snowflake.snowpark import Session

from trust_engine.common.config.settings import Settings
from trust_engine.common.infrastructure.db import query


def search_contracts(
    question: str,
    *,
    contract_id: str | None = None,
    partner_id: str | None = None,
    contract_version: int | None = None,
    document_version: int | None = None,
    limit: int = 5,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Search indexed chunks, optionally restricting results to a known version.

    The configured Cortex Search service must expose every requested metadata
    column in its searchable attributes.
    """
    if not question.strip():
        raise ValueError("question must not be empty")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    cfg = settings or Settings()
    parts = cfg.cortex_search_service.split(".")
    if len(parts) != 3:
        raise ValueError("CORTEX_SEARCH_SERVICE must be DATABASE.SCHEMA.SERVICE")
    database, schema, service_name = parts

    filters: list[dict[str, Any]] = []
    if contract_id:
        filters.append({"@eq": {"CONTRACT_ID": contract_id}})
    if partner_id:
        filters.append({"@eq": {"PARTNER_ID": partner_id}})
    if contract_version is not None:
        filters.append({"@eq": {"CONTRACT_VERSION": contract_version}})
    if document_version is not None:
        filters.append({"@eq": {"DOCUMENT_VERSION": document_version}})
    search_filter = {"@and": filters} if len(filters) > 1 else (filters[0] if filters else None)

    session = Session.builder.configs(cfg.snowflake_config).create()
    try:
        service = Root(session).databases[database].schemas[schema].cortex_search_services[service_name]
        kwargs: dict[str, Any] = {
            "query": question,
            "columns": [
                "CHUNK_TEXT", "CONTRACT_ID", "DOCUMENT_ID", "DOCUMENT_NAME",
                "DOCUMENT_VERSION", "CONTRACT_VERSION", "DOCUMENT_TYPE",
                "PAGE_NUMBER", "PAGE_END", "SECTION", "CLAUSE_NUMBER",
                "PARTNER_ID", "EFFECTIVE_DATE", "EXPIRY_DATE", "SOURCE_URI",
            ],
            "limit": limit,
        }
        if search_filter:
            kwargs["filter"] = search_filter
        return json.loads(service.search(**kwargs).to_json()).get("results", [])
    finally:
        session.close()


def complete(
    prompt: str, *, model: str | None = None, settings: Settings | None = None
) -> str:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    cfg = settings or Settings()
    sql = """SELECT AI_COMPLETE(
        %s, %s, OBJECT_CONSTRUCT('temperature', 0.1, 'max_tokens', 2000)
    )::VARCHAR AS RESPONSE"""
    rows = query(sql, (model or cfg.cortex_llm_model, prompt), cfg)
    return str(rows[0].get("RESPONSE") or rows[0].get("response") or "") if rows else ""


def grounded_contract_answer(
    question: str,
    *,
    contract_id: str | None = None,
    partner_id: str | None = None,
    contract_version: int | None = None,
    document_version: int | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    hits = search_contracts(
        question, contract_id=contract_id, partner_id=partner_id,
        contract_version=contract_version, document_version=document_version, limit=top_k,
    )
    if not hits:
        return {"answer": "I could not find supporting contract text.", "citations": [], "grounded": False}

    evidence: list[str] = []
    citations: list[dict[str, Any]] = []
    for hit in hits:
        evidence.append(str(hit.get("CHUNK_TEXT") or hit.get("chunk_text") or ""))
        citations.append({
            "contract_id": hit.get("CONTRACT_ID") or hit.get("contract_id"),
            "document_id": hit.get("DOCUMENT_ID") or hit.get("document_id"),
            "document_name": hit.get("DOCUMENT_NAME") or hit.get("document_name"),
            "document_version": hit.get("DOCUMENT_VERSION") or hit.get("document_version"),
            "contract_version": hit.get("CONTRACT_VERSION") or hit.get("contract_version"),
            "page_number": hit.get("PAGE_NUMBER") or hit.get("page_number"),
            "page_end": hit.get("PAGE_END") or hit.get("page_end"),
            "section": hit.get("SECTION") or hit.get("section"),
            "clause_number": hit.get("CLAUSE_NUMBER") or hit.get("clause_number"),
            "source_uri": hit.get("SOURCE_URI") or hit.get("source_uri"),
        })
    prompt = (
        "Answer only from the contract evidence below. If evidence does not answer the question, "
        "say so. Do not infer missing rates, dates or obligations. Cite factual claims using "
        "contract ID, document version, page and clause where available. Distinguish historical "
        "and amended terms; do not assume the newest document is effective for every transaction.\n"
        f"QUESTION: {question}\nEVIDENCE:\n" + "\n---\n".join(evidence)
    )
    return {"answer": complete(prompt), "citations": citations, "grounded": True}
