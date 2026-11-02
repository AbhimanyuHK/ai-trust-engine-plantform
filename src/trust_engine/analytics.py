"""Governed natural-language analytics with strict read-only SQL checks."""
from __future__ import annotations
import re
from typing import Any
from trust_engine.cortex import complete
from trust_engine.db import query
FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|CALL|COPY|PUT|GET|REMOVE|GRANT|REVOKE)\b",re.I)

def validate_read_only_sql(sql: str, allowed_objects: set[str] | None = None) -> str:
    candidate = sql.strip().rstrip(";")
    if not candidate:
        raise ValueError("SQL is empty")
    if ";" in candidate:
        raise ValueError("Only one SQL statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b",candidate,re.I):
        raise ValueError("Only SELECT statements are allowed")
    if FORBIDDEN.search(candidate):
        raise ValueError("Mutating or administrative SQL is not allowed")
    if any(token in candidate for token in ("--","/*","*/")):
        raise ValueError("SQL comments are not allowed")
    if allowed_objects:
        refs = {x.upper() for x in re.findall(r"(?i)\b(?:FROM|JOIN)\s+([\w.]+)",candidate)}
        permitted = {x.upper() for x in allowed_objects}
        if not refs or not refs.issubset(permitted):
            raise ValueError(f"Query references objects outside allowlist: {refs-permitted}")
    if not re.search(r"\\bLIMIT\\s+\\d+\\b",candidate,re.I):
        candidate += " LIMIT 1000"
    return candidate

def generate_sql(question: str, semantic_context: str) -> str:
    prompt = ("Generate exactly one read-only Snowflake SELECT query. Use only objects and "
      "columns in the semantic context. Return SQL only.\nSEMANTIC CONTEXT:\n"
      f"{semantic_context}\nQUESTION:\n{question}")
    return complete(prompt).strip().removeprefix("```sql").removesuffix("```").strip()

def ask_analytics(question: str, semantic_context: str,
                  allowed_objects: set[str]) -> dict[str,Any]:
    sql = validate_read_only_sql(generate_sql(question,semantic_context),allowed_objects)
    rows = query(sql)
    return {"question":question,"sql":sql,"rows":rows,"row_count":len(rows)}
