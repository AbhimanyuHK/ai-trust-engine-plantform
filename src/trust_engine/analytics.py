"""Governed natural-language analytics with AST-based read-only SQL validation."""
from __future__ import annotations
import re
from typing import Any
import sqlglot
from sqlglot import exp
from trust_engine.cortex import complete
from trust_engine.db import query

def validate_read_only_sql(sql: str, allowed_objects: set[str] | None = None) -> str:
    candidate=sql.strip().rstrip(";")
    if not candidate:
        raise ValueError("SQL is empty")
    if any(token in candidate for token in ("--","/*","*/")):
        raise ValueError("SQL comments are not allowed")
    try:
        statements=sqlglot.parse(candidate,read="snowflake")
    except sqlglot.errors.ParseError as exc:
        raise ValueError("Generated SQL could not be parsed as Snowflake SQL") from exc
    if len(statements)!=1 or statements[0] is None:
        raise ValueError("Only one SQL statement is allowed")
    tree=statements[0]
    if not isinstance(tree,(exp.Select,exp.Union)):
        raise ValueError("Only SELECT queries are allowed")
    forbidden=(exp.Insert,exp.Update,exp.Delete,exp.Merge,exp.Create,exp.Drop,exp.Alter,
               exp.Command,exp.Copy)
    if any(tree.find(kind) is not None for kind in forbidden):
        raise ValueError("Mutating or administrative SQL is not allowed")
    if allowed_objects is not None:
        permitted={name.upper() for name in allowed_objects}
        cte_names={cte.alias_or_name.upper() for cte in tree.find_all(exp.CTE)}
        referenced=set()
        for table in tree.find_all(exp.Table):
            name=".".join(part for part in (table.catalog,table.db,table.name) if part).upper()
            if table.name.upper() not in cte_names:
                referenced.add(name)
        if not referenced:
            raise ValueError("Query must read from an approved semantic object")
        if not referenced.issubset(permitted):
            raise ValueError(f"Query references objects outside allowlist: {referenced-permitted}")
    if not re.search(r"\bLIMIT\s+\d+\b",candidate,re.I):
        candidate += " LIMIT 1000"
    return candidate

def generate_sql(question: str,semantic_context: str) -> str:
    prompt=("Generate exactly one read-only Snowflake SELECT query. Use only objects and columns "
      "in the semantic context. Never use DDL/DML, stored procedures or system functions. "
      "Return SQL only.\nSEMANTIC CONTEXT:\n"
      f"{semantic_context}\nQUESTION:\n{question}")
    return complete(prompt).strip().removeprefix("```sql").removesuffix("```").strip()

def ask_analytics(question: str,semantic_context: str,
                  allowed_objects: set[str]) -> dict[str,Any]:
    sql=validate_read_only_sql(generate_sql(question,semantic_context),allowed_objects)
    rows=query(sql)
    return {"question":question,"sql":sql,"rows":rows,"row_count":len(rows)}
