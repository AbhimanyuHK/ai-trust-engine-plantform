"""Snowflake Cortex Search and LLM adapters."""
from __future__ import annotations
import json
from typing import Any
from trust_engine.db import query
from trust_engine.settings import Settings

def search_contracts(question: str, *, contract_id: str | None = None,
                     partner_id: str | None = None, limit: int = 5,
                     settings: Settings | None = None) -> list[dict[str, Any]]:
    if not question.strip():
        raise ValueError("question must not be empty")
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    cfg = settings or Settings()
    filters = {}
    if contract_id:
        filters["CONTRACT_ID"] = contract_id
    if partner_id:
        filters["PARTNER_ID"] = partner_id
    options = {"query": question, "columns": ["CHUNK_TEXT","CONTRACT_ID","DOCUMENT_NAME",
               "PAGE_NUMBER","SECTION","PARTNER_ID"], "limit": limit}
    if filters:
        options["filter"] = {"@and": [{"@eq": {k: v}} for k, v in filters.items()]}
    rows = query("SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW(%s, PARSE_JSON(%s)) AS RESULT",
                 (cfg.cortex_search_service, json.dumps(options)), cfg)
    if not rows:
        return []
    raw = rows[0].get("RESULT") or rows[0].get("result")
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return parsed.get("results", []) if isinstance(parsed, dict) else []

def complete(prompt: str, *, model: str | None = None,
             settings: Settings | None = None) -> str:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    cfg = settings or Settings()
    rows = query("SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, %s) AS RESPONSE",
                 (model or cfg.cortex_llm_model, prompt), cfg)
    return str(rows[0].get("RESPONSE") or rows[0].get("response") or "") if rows else ""

def grounded_contract_answer(question: str, *, contract_id: str | None = None,
                             partner_id: str | None = None, top_k: int = 5) -> dict[str, Any]:
    hits = search_contracts(question, contract_id=contract_id, partner_id=partner_id, limit=top_k)
    if not hits:
        return {"answer": "I could not find supporting contract text.", "citations": [], "grounded": False}
    evidence, citations = [], []
    for hit in hits:
        evidence.append(str(hit.get("CHUNK_TEXT") or hit.get("chunk_text") or ""))
        citations.append({"contract_id": hit.get("CONTRACT_ID") or hit.get("contract_id"),
            "document_name": hit.get("DOCUMENT_NAME") or hit.get("document_name"),
            "page_number": hit.get("PAGE_NUMBER") or hit.get("page_number"),
            "section": hit.get("SECTION") or hit.get("section")})
    prompt = ("Answer only from the contract evidence below. If evidence does not answer the "
      "question, say so. Do not infer missing rates, dates or obligations. Cite factual claims.\n"
      f"QUESTION: {question}\nEVIDENCE:\n" + "\n---\n".join(evidence))
    return {"answer": complete(prompt), "citations": citations, "grounded": True}
