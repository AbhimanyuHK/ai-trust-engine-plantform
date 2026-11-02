"""Streamlit UI for business users; deploy behind enterprise authentication."""
from __future__ import annotations
import json
import pandas as pd
import streamlit as st
from trust_engine.analytics import ask_analytics
from trust_engine.contract_intelligence.cortex import grounded_contract_answer
from trust_engine.governance import decide_approval,get_approval

st.set_page_config(page_title="AI TRUST Engine",layout="wide")
st.title("AI TRUST Engine")
st.caption("Snowflake-governed contract intelligence, forecasting and approvals")
contract_tab,analytics_tab,approval_tab=st.tabs(["Contract Intelligence","Analytics","Approvals"])

with contract_tab:
    question=st.text_area("Ask a question about a contract")
    contract_id=st.text_input("Contract ID (optional)")
    partner_id=st.text_input("Contractor / partner ID (optional)")
    if st.button("Search contract",key="contract_search") and question.strip():
        with st.spinner("Retrieving contract evidence..."):
            result=grounded_contract_answer(question,contract_id=contract_id or None,
                                            partner_id=partner_id or None)
        st.write(result["answer"])
        if result["citations"]:
            st.dataframe(pd.DataFrame(result["citations"]),use_container_width=True)
        if not result["grounded"]:
            st.warning("No supporting contract text was retrieved.")

with analytics_tab:
    prompt=st.text_input("Ask a business question")
    if st.button("Run analytics") and prompt.strip():
        semantic="""CORE.TRANSACTIONS(TRANSACTION_DATE,PARTNER_ID,TRANSACTION_TYPE,AMOUNT,CURRENCY);
CORE.CONTRACTS(CONTRACT_ID,PARTNER_ID,EFFECTIVE_DATE,EXPIRY_DATE,COUNTRY,STATUS);
FORECAST.DEMAND_FORECAST(FORECAST_DATE,PARTNER_ID,PREDICTED_REVENUE,PREDICTED_ROYALTY,MODEL_NAME)."""
        with st.spinner("Generating and validating read-only SQL..."):
            result=ask_analytics(prompt,semantic,{"CORE.TRANSACTIONS","CORE.CONTRACTS",
                                                 "FORECAST.DEMAND_FORECAST"})
        st.code(result["sql"],language="sql")
        frame=pd.DataFrame(result["rows"])
        st.dataframe(frame,use_container_width=True)
        numeric=frame.select_dtypes(include="number").columns.tolist()
        dimensions=[c for c in frame.columns if c not in numeric]
        if numeric and dimensions and not frame.empty:
            st.bar_chart(frame.set_index(dimensions[0])[numeric[0]])

with approval_tab:
    approval_id=st.text_input("Approval request ID")
    if st.button("Load approval") and approval_id.strip():
        record=get_approval(approval_id)
        if record is None:
            st.error("Approval request not found")
        else:
            st.json(record)
            st.session_state["trust_current_approval"]=record
    current=st.session_state.get("trust_current_approval")
    if current and current.get("STATUS")=="PENDING":
        reviewer=st.text_input("Reviewer identity")
        role=st.selectbox("Reviewer role",["finance","partner_relations"])
        reason=st.text_area("Decision reason")
        decision=st.selectbox("Decision",["APPROVED","REJECTED","MODIFIED"])
        modified=st.text_area("Modified payload JSON (only for MODIFIED)")
        if st.button("Submit decision"):
            try:
                payload=json.loads(modified) if modified.strip() else None
                decide_approval(str(current["APPROVAL_ID"]),decision,reviewer,role,reason,payload)
                st.success("Decision recorded. Reload the approval to view its new status.")
            except Exception as exc:
                st.error(str(exc))
