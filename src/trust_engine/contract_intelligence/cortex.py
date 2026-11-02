"""Snowflake Cortex Search SDK and current AI_COMPLETE adapters."""
from __future__ import annotations
import json
from typing import Any
from snowflake.snowpark import Session
from snowflake.core import Root
from trust_engine.common.infrastructure.db import query
from trust_engine.common.config.settings import Settings

def search_contracts(question: str, *, contract_id: str | None = None, partner_id: str | None = None,
                     limit: int = 5, settings: Settings | None = None) -> list[dict[str, Any]]:
    if not question.strip(): raise ValueError("question must not be empty")
    if not 1 <= limit <= 20: raise ValueError("limit must be between 1 and 20")
    cfg=settings or Settings()
    parts=cfg.cortex_search_service.split(".")
    if len(parts)!=3: raise ValueError("CORTEX_SEARCH_SERVICE must be DATABASE.SCHEMA.SERVICE")
    database,schema,service_name=parts
    filters=[]
    if contract_id: filters.append({"@eq":{"CONTRACT_ID":contract_id}})
    if partner_id: filters.append({"@eq":{"PARTNER_ID":partner_id}})
    search_filter={"@and":filters} if len(filters)>1 else (filters[0] if filters else None)
    session=Session.builder.configs(cfg.snowflake_config).create()
    try:
        service=Root(session).databases[database].schemas[schema].cortex_search_services[service_name]
        kwargs={"query":question,"columns":["CHUNK_TEXT","CONTRACT_ID","DOCUMENT_NAME","PAGE_NUMBER","SECTION","PARTNER_ID","COUNTRY"],"limit":limit}
        if search_filter: kwargs["filter"]=search_filter
        return json.loads(service.search(**kwargs).to_json()).get("results",[])
    finally: session.close()

def complete(prompt: str, *, model: str | None = None, settings: Settings | None = None) -> str:
    if not prompt.strip(): raise ValueError("prompt must not be empty")
    cfg=settings or Settings()
    sql="""SELECT AI_COMPLETE(%s,%s,OBJECT_CONSTRUCT('temperature',0.1,'max_tokens',2000))::VARCHAR AS RESPONSE"""
    rows=query(sql,(model or cfg.cortex_llm_model,prompt),cfg)
    return str(rows[0].get("RESPONSE") or rows[0].get("response") or "") if rows else ""

def grounded_contract_answer(question: str, *, contract_id: str | None = None,
                             partner_id: str | None = None, top_k: int = 5) -> dict[str, Any]:
    hits=search_contracts(question,contract_id=contract_id,partner_id=partner_id,limit=top_k)
    if not hits: return {"answer":"I could not find supporting contract text.","citations":[],"grounded":False}
    evidence,citations=[],[]
    for hit in hits:
        evidence.append(str(hit.get("CHUNK_TEXT") or hit.get("chunk_text") or ""))
        citations.append({"contract_id":hit.get("CONTRACT_ID") or hit.get("contract_id"),
          "document_name":hit.get("DOCUMENT_NAME") or hit.get("document_name"),
          "page_number":hit.get("PAGE_NUMBER") or hit.get("page_number"),
          "section":hit.get("SECTION") or hit.get("section")})
    prompt=("Answer only from the contract evidence below. If evidence does not answer the question, say so. "
      "Do not infer missing rates, dates or obligations. Cite factual claims using contract ID, page and section.\n"
      f"QUESTION: {question}\nEVIDENCE:\n"+"\n---\n".join(evidence))
    return {"answer":complete(prompt),"citations":citations,"grounded":True}
