"""CLI entry points for operational workflows."""
from __future__ import annotations
import json
import uuid
from pathlib import Path
import typer
from rich import print
from trust_engine.documents import chunk_pages,extract_pdf,persist_chunks
from trust_engine.forecasting import load_daily_revenue,persist_forecast,train_and_forecast
from trust_engine.governance import decide_approval,get_approval
from trust_engine.settings import load_pipeline_config
app = typer.Typer(no_args_is_help=True,help="AI TRUST Engine operations")

@app.command()
def validate_config(path: str="config/pipelines/trust-engine.yaml") -> None:
    config=load_pipeline_config(path)
    print({"project":config.get("project"),"environment":config.get("environment",{}).get("name")})

@app.command()
def ingest_contract(pdf: Path,contract_id: str,partner_id: str="",effective_date: str="",
                    expiry_date: str="",chunk_size: int=800,overlap: int=100) -> None:
    if not pdf.exists() or pdf.suffix.lower()!=".pdf":
        raise typer.BadParameter("Provide an existing PDF file")
    pages=extract_pdf(pdf)
    chunks=chunk_pages(pages,contract_id,pdf.name,partner_id or None,effective_date or None,
                       expiry_date or None,chunk_size,overlap)
    if not chunks:
        raise typer.Exit("No extractable text found; route scanned PDF to an OCR worker.")
    print({"contract_id":contract_id,"pages":len(pages),"chunks":len(chunks),"merged":persist_chunks(chunks)})

@app.command()
def forecast(horizon_days: int=60,partner_id: str="") -> None:
    result=train_and_forecast(load_daily_revenue(partner_id or None),horizon_days,partner_id or None)
    run_id=str(uuid.uuid4())
    print({"run_id":run_id,"rows":persist_forecast(result,run_id),"mae":result.mae,"rmse":result.rmse})

@app.command()
def approval_status(approval_id: str) -> None:
    result=get_approval(approval_id)
    if result is None:
        raise typer.Exit("Approval request not found")
    print(result)

@app.command()
def decide(approval_id: str,decision: str,reviewer: str,role: str,reason: str,
           modified_payload: str="") -> None:
    decide_approval(approval_id,decision,reviewer,role,reason,
                    json.loads(modified_payload) if modified_payload else None)
    print({"approval_id":approval_id,"decision":decision.upper()})

if __name__=="__main__":
    app()
