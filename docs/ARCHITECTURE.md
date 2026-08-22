# AI TRUST Engine — Architecture & Workflow

## 1. Purpose

AI TRUST Engine is an AI-assisted enterprise platform for transaction analytics, demand/revenue forecasting, contract intelligence, recommendations, and governed human approval.

The architecture is intentionally designed so that each technology has a clear responsibility:

- **Snowflake** — enterprise data platform and system of record
- **Snowflake Cortex** — AI execution, embeddings, enterprise search, and natural-language data capabilities
- **LangGraph** — stateful workflow and agent orchestration where multi-step decisions require it
- **LangChain** — optional reusable LLM/RAG/tool application components; not mandatory for every workflow
- **LangSmith** — LLM/agent tracing, evaluation, and debugging where required
- **S3** — optional AWS landing/staging layer for raw files and contract documents
- **Streamlit/API** — user-facing application layer
- **HITL** — human approval and governance for high-impact decisions

The architecture avoids introducing AWS Bedrock, SageMaker, Pinecone, SQS, SNS, Lambda, or Glue unless a concrete requirement justifies them.

---

## 2. High-Level Architecture

```text
                           USERS
                             |
                             v
                      Streamlit / API
                             |
                             v
                  +-----------------------+
                  |    TRUST Application  |
                  +-----------+-----------+
                              |
                +-------------+-------------+
                |                           |
                v                           v
          LangGraph                    Direct AI/Data
        Orchestration                  capabilities
                |                           |
       +--------+--------+             Snowflake
       |        |        |                 |
       v        v        v          +------+------+
    Cortex   SQL/ML  Business       |             |
    Search  Results   Rules       Cortex        Tables
       |                            Search      / Views
       v                              |
   Cortex AI / LLM                   |
       |                              |
       +--------------+---------------+
                      |
                      v
               Recommendation
                      |
                      v
                    HITL
               /            \
          Approve           Reject/Modify
             |                  |
             v                  v
        Business Action       Revision

        LangSmith observes/evaluates LLM and agent execution

AWS landing option:

Source Systems -> S3 -> Snowflake -> Cortex / Application
```

---

## 3. Core Design Principle

The platform does **not** treat every component as mandatory.

The design follows separation of concerns:

| Component | Responsibility | Required? |
|---|---|---|
| Snowflake | Structured data, contracts, metadata, SQL, governance | Yes for the Snowflake-native design |
| Cortex | LLM/AI execution, embeddings, search and AI capabilities | Yes for the Cortex-first AI design |
| LangChain | Reusable prompts, retrievers, tools, model/application abstractions | Optional |
| LangGraph | Stateful, conditional, multi-step workflows | Only where workflow complexity requires it |
| LangSmith | Tracing, evaluation, debugging and observability | Optional, based on observability requirements |
| S3 | Raw/landing storage before Snowflake | Optional but a good AWS integration point |
| AWS Glue | AWS-side ETL | Not required unless source transformations justify it |
| SQS/SNS | Async queues / event fan-out | Not required for the current core workflow |
| Lambda | Lightweight event-driven processing | Not required for the current core workflow |
| Bedrock | Alternative managed model access layer | Not required when Cortex satisfies model requirements |
| SageMaker | Alternative ML platform | Not required for the current design |
| External vector DB | External semantic retrieval | Not required; keep retrieval in Snowflake |

---

# 4. Business Workflows

The platform has four major business workflows. They are **not all LangGraph workflows**.

1. Demand & Revenue Forecasting
2. Contract Intelligence & Recommendation
3. HITL Governance & Contract Activation
4. Natural-Language Analytics & Visualization

---

# 5. Workflow 1 — Demand & Revenue Forecasting

## Objective

Predict future demand, revenue and royalty-related values from historical transaction data.

## Algorithm

```text
Historical Transactions
        |
        v
Extract from Snowflake
        |
        v
Data Cleaning & Business Semantics
        |
        v
Aggregate to Forecasting Grain
        |
        v
Feature Engineering
        |
        +--------------------+
        |                    |
        v                    v
   XGBoost Model        LSTM Model
        |                    |
        +---------+----------+
                  |
                  v
             Model Evaluation
                  |
                  v
        Select / combine best model
                  |
                  v
             Forecast 30-60 days
                  |
                  v
       Revenue / Royalty Calculation
                  |
                  v
          Store Predictions
```

## Detailed algorithm

### Step 1 — Extract

Read historical transaction records from Snowflake.

Typical attributes include:

- transaction date
- partner/contractor
- actor/talent/product dimensions as applicable
- transaction type
- quantity
- gross amount
- discounts/adjustments
- net amount
- royalty/revenue-share attributes

Transaction semantics must be explicitly defined for values such as `INCOME`, `RETURN`, `APPEASEMENT`, `ADJUSTMENT`, `CREDIT`, `DEBIT`, and `CANCELLATION`.

### Step 2 — Clean

- Remove or reconcile duplicates.
- Validate dates and numeric fields.
- Handle missing values according to business rules.
- Normalize transaction signs and transaction-type semantics.
- Identify abnormal/outlier records.

### Step 3 — Aggregate

Transform transaction-level data into a consistent forecasting grain, for example:

```text
Date + Partner + Product/Actor
```

Calculate measures such as daily quantity, revenue, returns and royalty amount.

### Step 4 — Feature engineering

Create time-series features such as:

```text
lag_1
lag_3
lag_7
lag_12
rolling_mean_7
rolling_mean_14
rolling_mean_30
day_of_week
week_of_year
month
promotion / campaign indicators
partner / product dimensions
```

The exact lag windows are determined from the available history and business seasonality.

### Step 5 — Time-aware split

Do not randomly shuffle time-series observations. Use chronological train/validation/test splits to avoid future-data leakage.

### Step 6 — XGBoost

Use engineered tabular features to predict the target. XGBoost is useful for nonlinear relationships and feature interactions in structured data.

### Step 7 — LSTM

Convert historical observations into sequences and train an LSTM where sequential dependencies justify the additional model complexity.

### Step 8 — Evaluation

Evaluate candidates using forecasting metrics such as:

- MAE
- RMSE
- MAPE or sMAPE where appropriate

Select the best validated model or an ensemble if that produces a demonstrable improvement.

### Step 9 — Forecast

Generate the required future horizon, such as 30–60 days, according to the business reporting requirement.

### Step 10 — Royalty calculation

Use the applicable contract/business rule to calculate expected royalty/revenue-share values from predicted revenue. The LLM must not invent the royalty rate.

### Step 11 — Persistence

Store prediction results with model version and prediction timestamp so that forecasts are auditable and can be compared against actual outcomes later.

Example fields:

```text
forecast_date
partner_id
product_or_actor_id
predicted_demand
predicted_revenue
predicted_royalty
model_name
model_version
prediction_timestamp
```

## Technology mapping

- **Snowflake:** source and prediction storage
- **Python/ML:** feature engineering and model training/inference
- **XGBoost:** tabular forecasting model
- **LSTM:** sequential forecasting model
- **LangGraph:** not required
- **LLM:** not required for the mathematical forecast itself

---

# 6. Workflow 2 — Contract Intelligence & Recommendation

## Objective

Use contract documents plus structured business information to answer contract questions and produce grounded recommendations.

## Algorithm

```text
User Request
     |
     v
Intent Detection
     |
     v
Project / Partner / Contract Context
     |
     +---------------------+
     |                     |
     v                     v
Structured Retrieval   Contract Retrieval
(Snowflake SQL)        (Cortex Search)
     |                     |
     +----------+----------+
                |
                v
          Relevant Context
                |
                v
          Prompt Construction
                |
                v
             Cortex LLM
                |
                v
         Response Validation
                |
         +------+------+
         |             |
       Answer     Recommendation
                       |
                       v
                      HITL
```

## Document ingestion algorithm

```text
Contract PDF
    |
    v
S3 / Snowflake Stage
    |
    v
Text Extraction
    |
    v
Cleaning / Normalization
    |
    v
Recursive Chunking
    |
    v
Chunk Metadata
    |
    v
Embeddings
    |
    v
Snowflake / Cortex Search
```

Store useful metadata with each chunk, such as contract ID, partner, document version, page/section information, effective date and expiry date where available.

## Detailed runtime algorithm

### Step 1 — Intent detection

Classify the request, for example:

- contract lookup
- contract recommendation
- renewal analysis
- discount analysis
- royalty question
- general analytics

### Step 2 — Context detection

Resolve the relevant partner/contract/project and any time or geography constraints.

### Step 3 — Structured retrieval

Query Snowflake for factual structured information such as historical revenue, forecasts, contract metadata and partner attributes.

### Step 4 — Unstructured retrieval

Use Cortex Search to retrieve relevant contract chunks. Apply metadata filtering when possible so that the search is restricted to the correct contract or partner.

### Step 5 — Context assembly

Combine:

```text
Contract evidence
+
Structured business data
+
Business rules
+
User request
```

### Step 6 — LLM generation

Send the grounded context to the selected Cortex model. The model generates the response or recommendation.

### Step 7 — Validation

Validate that:

- the correct contract/partner was used;
- required evidence exists;
- the response does not invent missing contract values;
- business rules are respected;
- high-impact actions are routed to HITL.

### Step 8 — Recommendation

Generate a recommendation with supporting evidence and relevant business metrics.

## Technology mapping

- **Snowflake:** structured facts and document data
- **Cortex Search:** semantic/enterprise contract retrieval
- **Cortex embeddings:** vector representation for retrieval
- **Cortex LLM:** grounded generation/reasoning
- **LangGraph:** useful for multi-step stateful orchestration and conditional paths
- **LangChain:** optional for reusable prompts, retrievers, tools and application abstractions
- **LangSmith:** useful for tracing and evaluating retrieval/LLM behavior

---

# 7. Workflow 3 — HITL Governance & Contract Activation

## Objective

Prevent high-impact AI recommendations from becoming business actions without appropriate human review.

## Algorithm

```text
AI Recommendation
       |
       v
Business Rule Validation
       |
       v
Risk / Approval Assessment
       |
       +----------------------+
       |                      |
   Low risk              Approval required
       |                      |
       v                      v
 Automatic path          Human Review Queue
                              |
                    +---------+---------+
                    |         |         |
                    v         v         v
                 Approve    Reject    Modify
                    |         |         |
                    v         |         v
              Business      Revision   Re-evaluate
                Action
                    |
                    v
                  Audit
```

## Detailed algorithm

### Step 1 — Receive recommendation

Capture the AI-generated recommendation and its evidence.

### Step 2 — Deterministic validation

Apply business rules such as:

- minimum/maximum royalty constraints
- allowed discount ranges
- contract status
- contract expiry
- required data presence
- partner validity

### Step 3 — Determine approval requirement

Use configured policy/risk rules to determine whether the recommendation can proceed automatically or requires human approval.

### Step 4 — Human review

Present the recommendation, evidence, contract clause, forecast and financial impact in the application.

### Step 5 — Decision

The authorized reviewer can:

- approve
- reject
- modify/request revision

### Step 6 — Activation

Only approved actions proceed to the downstream business process.

### Step 7 — Audit

Record the recommendation, evidence, AI/model version, human decision, reviewer, timestamp and reason for the decision.

## Technology mapping

- **LangGraph:** useful when approval is part of a stateful workflow
- **Business rules:** deterministic validation outside the LLM
- **Streamlit/API:** human review UI
- **Snowflake:** audit and business records
- **LangSmith:** trace/evaluate the AI portion; not a replacement for the business audit trail

---

# 8. Workflow 4 — Natural-Language Analytics & Visualization

## Objective

Allow business users to ask analytical questions in natural language and receive governed Snowflake results and visualizations.

## Algorithm

```text
Natural Language Question
          |
          v
Intent / Scope Detection
          |
          v
Semantic Schema Context
          |
          v
SQL Generation
          |
          v
SQL Validation / Guardrails
          |
          v
Snowflake Execution
          |
          v
Result Validation
          |
          v
Visualization Selection
          |
          v
Natural-Language Response
```

## Detailed algorithm

### Step 1 — Receive question

Example:

> Show revenue by partner for the last three months.

### Step 2 — Determine intent and scope

Identify requested measures, dimensions, filters and time range.

### Step 3 — Provide semantic context

Supply the model with approved tables/views, columns, relationships and business definitions.

### Step 4 — Generate SQL

Generate a read-only query based on the approved semantic context.

### Step 5 — Validate SQL

Check:

- referenced objects exist;
- columns are valid;
- query is read-only;
- filters and date ranges are valid;
- business definitions are respected;
- unsafe operations are rejected.

### Step 6 — Execute

Run the validated SQL against Snowflake.

### Step 7 — Validate result

Handle query errors, empty results, excessive result sets and unexpected structures.

### Step 8 — Visualize

Choose an appropriate visualization based on the result structure, such as a line chart for time series or a bar chart for category comparisons.

### Step 9 — Respond

Return the result and a concise natural-language explanation.

## Technology mapping

- **Snowflake:** execution and data source
- **Cortex Analyst / Cortex AI:** useful for natural-language structured-data interaction
- **LangGraph:** optional; only needed if analytics becomes a multi-step agentic workflow
- **LangChain:** optional
- **LangSmith:** useful for tracing/evaluating generated SQL and LLM behavior

---

# 9. LangChain vs LangGraph vs Cortex vs LangSmith

These components should not be described as interchangeable.

| Technology | Mental model | Role |
|---|---|---|
| **Cortex** | Execute AI | LLMs, embeddings, Search and AI capabilities close to Snowflake data |
| **LangChain** | Build AI components | Prompts, retrievers, tools, model/application abstractions |
| **LangGraph** | Orchestrate AI | Stateful graphs, conditional routing, retries, multi-step workflows and HITL |
| **LangSmith** | Observe AI | Tracing, evaluation, debugging and monitoring of LLM/agent applications |

### Are all four required?

No.

For simple RAG:

```text
User -> Cortex Search -> Cortex LLM -> Answer
```

may be enough.

For a more complex agentic workflow:

```text
User -> LangGraph -> Cortex Search / SQL / LLM -> HITL -> Action
```

LangGraph becomes justified.

LangChain should be introduced only where its abstractions reduce development complexity.

LangSmith should be introduced when detailed application-level tracing and evaluation justify the additional dependency.

---

# 10. Why Cortex Instead of AWS Bedrock?

Cortex is preferred as the primary AI layer when the required models and capabilities are available because the enterprise data is already centralized in Snowflake.

Advantages:

- data and AI capabilities remain close together;
- native Snowflake search and structured-data integration;
- simpler governance and access-control model;
- fewer external integrations;
- lower architectural complexity.

Bedrock remains a valid alternative when a specific model, AWS-native requirement, regional requirement or existing AWS standard makes it preferable.

The decision is not that Bedrock is inferior; it is that **Cortex is a better fit when Snowflake is the center of the enterprise AI architecture**.

---

# 11. AWS Usage

AWS is optional around the core AI layer.

A simple AWS-integrated deployment is:

```text
Source Systems
      |
      v
     S3
      |
      v
  Snowflake
      |
      v
Cortex / TRUST Engine
```

## S3

S3 is a good landing/staging location for raw transaction files and contract PDFs when source systems already use AWS.

## Glue

Use Glue only when AWS-side ETL/transformation is genuinely required. It is not mandatory if Snowflake can perform the required ingestion/transformation.

## SQS/SNS

Use SQS for asynchronous buffering/retry and SNS for event fan-out only when those requirements exist.

## Lambda

Use Lambda for lightweight event-driven processing or triggers when appropriate. It is not required for the core AI workflow.

Therefore, the recommended starting point is **S3 + Snowflake + Cortex**, adding other AWS services only when a concrete workload requires them.

---

# 12. End-to-End Data Flow

```text
                  RAW / SOURCE DATA
                         |
              +----------+----------+
              |                     |
              v                     v
       Transaction Files       Contract PDFs
              |                     |
              +----------+----------+
                         |
                         v
                    AWS S3
                  (optional)
                         |
                         v
                    Snowflake
             +-----------+-----------+
             |                       |
             v                       v
      Structured Tables       Contract Documents
             |                       |
             |                 Text Extraction
             |                       |
             |                    Chunking
             |                       |
             |                   Embeddings
             |                       |
             |                  Cortex Search
             |                       |
             +-----------+-----------+
                         |
                         v
                    AI Services
                  Cortex AI / LLM
                         |
                         v
                    LangGraph
                  when required
                         |
          +--------------+--------------+
          |                             |
          v                             v
     Recommendation               Analytics Answer
          |
          v
         HITL
          |
     +----+----+
     |         |
  Approve    Reject/Modify
     |
     v
 Business Action

LangSmith observes/evaluates the LLM and agent execution where enabled.
```

---

# 13. Architecture Decision Summary

### Keep

- Snowflake as the enterprise source of truth
- Cortex Search for contract retrieval
- Cortex AI/LLMs for AI execution where supported requirements are met
- LangGraph for genuinely stateful/conditional workflows
- HITL for high-impact business decisions
- S3 as an AWS landing zone when AWS ingestion is required

### Use selectively

- LangChain
- LangSmith
- Glue
- Lambda
- SQS
- SNS

### Avoid unless a specific requirement appears

- AWS Bedrock as a duplicate model-serving layer
- SageMaker as a duplicate ML platform
- External vector databases such as Pinecone when Snowflake-native retrieval is sufficient

---

# 14. Interview Summary

> **AI TRUST Engine is an AI-assisted enterprise decision platform rather than simply a chatbot. Snowflake acts as the system of record for structured transactions, contract data and AI metadata. Cortex provides the primary AI capabilities, including enterprise search, embeddings and LLM execution. The platform has four major business workflows: demand and revenue forecasting, contract intelligence and recommendation, HITL governance, and natural-language analytics. Forecasting uses XGBoost/LSTM, contract intelligence uses RAG and LLM reasoning, HITL uses deterministic business rules plus human approval, and natural-language analytics uses governed Text-to-SQL against Snowflake. LangGraph is introduced only where stateful multi-step orchestration is required, LangChain is optional for reusable AI application components, and LangSmith is used when detailed LLM/agent tracing and evaluation are needed. AWS S3 can provide the raw landing layer, while additional AWS services are added only when a concrete ingestion or event-processing requirement justifies them.**
