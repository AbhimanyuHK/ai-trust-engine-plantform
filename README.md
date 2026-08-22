# AI TRUST Engine Platform

## End-to-End Project Summary & High-Level Architecture

**AI TRUST Engine** is an enterprise AI platform for royalty and revenue-sharing operations, demand forecasting, contract intelligence, intelligent contract renewal, Human-in-the-Loop governance, and natural-language analytics.

**Core principle:** Snowflake is the single source of truth. Structured transaction data and sensitive contract intelligence remain governed inside Snowflake. The architecture does not use an external vector database such as Pinecone, Weaviate, or Milvus.

---

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/0b77b406-65ba-423b-b926-9dafe7866e01" />

---

## 1. Business Objective

The platform combines:

- Retail and wholesale transaction data
- Contract PDFs and legal agreements
- Data cleaning and validation
- Demand/revenue forecasting
- XGBoost + LSTM ensemble modeling
- Snowflake Cortex
- Cortex Search
- Retrieval-Augmented Generation (RAG)
- Llama 3.1 70B / approved Cortex-hosted LLMs
- LangChain and LangGraph
- Pydantic validation
- Human-in-the-Loop approval
- Cortex Analyst
- Streamlit and Plotly
- LangSmith, Ragas, and Arize Phoenix
- Snowflake RBAC and audit controls

The architecture deliberately separates:

**Data → Retrieval → AI Reasoning → Deterministic Business Rules → Human Approval**

The LLM recommends and explains; it does not become the authoritative financial calculator or contract activation engine.

---

## 2. Source Systems

### Retail
Retail transaction/invoice data.

### Wholesale
Wholesale transaction/invoice data.

### Contract Documents
Legal/licensing/royalty agreements, generally supplied as PDF documents.

### Transaction Types

- `INCOME`
- `RETURN`
- `APPEASEMENT`
- `ADJUSTMENT`
- `CREDIT`
- `DEBIT`
- `CANCELLATION`

Business entities include:

- Contractors
- Contacts
- Country
- Currency
- Actor / Talent
- Organization

The platform intentionally uses transaction/invoice terminology rather than an `ORDERS` domain model.

---

## 3. High-Level Architecture

```text
                           SOURCE SYSTEMS
                ┌──────────────────────────────┐
                │ Retail Transactions          │
                │ Wholesale Transactions       │
                │ Contract PDFs                │
                └───────────────┬──────────────┘
                                │
                                ▼
                         ┌──────────────┐
                         │   AWS S3     │
                         │ Raw Files    │
                         └──────┬───────┘
                                │
                                ▼
                   ┌───────────────────────────┐
                   │ Snowflake External Stage  │
                   └─────────────┬─────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
                  ▼                             ▼
          Structured Data                Contract Documents
                  │                             │
                  ▼                             ▼
        Data Cleaning / QA              PDF Text Extraction
                  │                             │
                  ▼                             ▼
          Snowflake Tables             Clean Text / JSON
                  │                             │
                  │                             ▼
                  │                    Chunking + Metadata
                  │                             │
                  │                             ▼
                  │                    CONTRACT_CHUNKS
                  │                             │
                  │                             ▼
                  │                    Cortex Search Service
                  │                     ┌────────┴────────┐
                  │                     │                 │
                  │                Keyword Index     Vector Index
                  │                     │                 │
                  │                     └────────┬────────┘
                  │                              │
                  │                              ▼
                  │                         Hybrid Search
                  │                              │
                  ├──────────────────────────────┤
                  │                              │
                  ▼                              ▼
          Forecasting Layer               GenAI / RAG Layer
          XGBoost + LSTM                   LangChain
                  │                        LangGraph
                  │                           │
                  ▼                           ▼
          Demand / Revenue             Retrieved Context
          Forecast                      + User Question
                  │                           │
                  ▼                           ▼
          Royalty Calculation             Llama 3.1 70B
          Deterministic Rules                 │
                  │                           ▼
                  │                    Grounded Response
                  │                           │
                  └──────────────┬────────────┘
                                 │
                                 ▼
                         Validation / Guardrails
                                 │
                                 ▼
                         Human-in-the-Loop
                                 │
                       ┌─────────┼─────────┐
                       │         │         │
                    Approve   Modify    Reject
                       │         │         │
                       └─────────┼─────────┘
                                 │
                                 ▼
                        Contract Activation
                                 │
                                 ▼
                         Snowflake Audit Log


             NATURAL LANGUAGE ANALYTICS PATH

 Business User → Streamlit → Cortex Analyst
              → Semantic Model/YAML
              → Governed SQL → Snowflake
              → DataFrame → Plotly
```

---

## 4. S3 and Snowflake External Stage

Raw contract PDFs can first land in Amazon S3.

```text
S3
 |
 v
Snowflake External Stage
 |
 v
Snowflake Processing
 |
 v
Governed Snowflake Data
```

S3 is the raw landing zone. Snowflake remains the governed analytical and AI source of truth.

---

## 5. Contract PDF Ingestion

### Step 1 — PDF Arrival

Example:

```text
s3://trust-contracts/contracts/contract_101.pdf
```

### Step 2 — External Stage

Snowflake exposes the S3 location through an external stage.

### Step 3 — PDF Text Extraction

A Python/Snowpark processing job extracts the text.

```text
contract_101.pdf
       |
       v
PDF parser
       |
       v
Raw text
```

### Step 4 — Cleaning

The extraction process can:

- Normalize whitespace and line breaks
- Remove extraction artifacts
- Normalize encoding
- Preserve section boundaries
- Preserve page/section references

### Step 5 — Structured JSON

A structured representation can be produced for downstream processing:

```json
{
  "contract_id": "CONTRACT_101",
  "document_name": "contract_101.pdf",
  "effective_date": "2026-01-01",
  "expiration_date": "2026-12-31",
  "sections": [
    {
      "section_id": "4.2",
      "page": 14,
      "title": "Royalty Terms",
      "text": "The licensor shall receive..."
    },
    {
      "section_id": "7.1",
      "page": 21,
      "title": "Renewal",
      "text": "The agreement may be renewed..."
    }
  ]
}
```

This JSON is a structured intermediate representation. Important fields should also be stored as proper Snowflake columns rather than being hidden only inside JSON.

---

## 6. Why PDF → JSON?

PDF is primarily a document/presentation format. AI and database workflows benefit from structured data.

```text
PDF
 |
 v
Extracted Text
 |
 v
Structured JSON
 |
 +--> Metadata
 +--> Sections
 +--> Page references
 +--> Text
 |
 v
Chunking
 |
 v
CONTRACT_CHUNKS
```

Benefits:

- Easier downstream processing
- Easier debugging
- Preserves document metadata
- Page/section traceability
- Easier Python integration
- Easier auditing
- Can be consumed by downstream application services

The canonical enterprise data remains governed in Snowflake.

---

## 7. Contract Chunking

Large contracts are not sent directly to the LLM.

The document is split into manageable chunks, typically around **500–1000 tokens**, with configurable overlap.

```text
Contract
   |
   +-- Chunk 001
   +-- Chunk 002
   +-- Chunk 003
   +-- Chunk 004
   +-- ...
```

Typical `CONTRACT_CHUNKS` fields:

```text
CONTRACT_ID
CHUNK_ID
CHUNK_TEXT
EFFECTIVE_DATE
METADATA
```

Useful metadata can include:

```text
DOCUMENT_NAME
PAGE_NUMBER
SECTION_ID
CONTRACT_TYPE
COUNTRY
CURRENCY
VERSION
SOURCE_PATH
```

---

## 8. How Indexing Works

**Llama 3.1 70B does not index contracts.**

Llama is the generation/reasoning model.

The retrieval layer is handled by **Snowflake Cortex Search**.

Conceptually:

```text
CONTRACT_CHUNKS
       |
       v
Cortex Search Service
       |
       +-------------------+
       |                   |
       v                   v
 Keyword / Text Index   Vector Index
       |                   |
       +---------+---------+
                 |
                 v
           Hybrid Retrieval
                 |
                 v
       Relevant Contract Chunks
```

The Cortex Search service manages the indexed/searchable representation. The application does not need to operate a separate Pinecone/Weaviate/Milvus index.

---

## 9. Keyword Search

Keyword/text search is useful for exact or near-exact business and legal terminology.

Examples:

- `minimum guarantee`
- `royalty rate`
- `termination`
- `renewal`
- Contract IDs
- Specific percentages
- Names

Legal documents contain precise language, so keyword retrieval remains valuable.

```text
User:
"Find the termination clause."

        |
        v

Keyword/Text Search

        |
        v

Relevant termination chunks
```

---

## 10. Vector / Semantic Search

Vector search represents text semantically.

A contract chunk can be represented using a Snowflake embedding model such as:

`snowflake-arctic-embed-l-v2.0`

Conceptually:

```text
"The licensor may adjust the royalty rate during renewal."
                       |
                       v
             Embedding Representation
                       |
                       v
                  Vector Index
```

A user can ask:

> "Can the partner's percentage change when the agreement is renewed?"

The wording does not need to exactly match the contract for semantic retrieval to find relevant content.

---

## 11. Hybrid Search

The TRUST Engine uses the concept of hybrid retrieval:

```text
                   User Query
                       |
             ┌─────────┴─────────┐
             │                   │
             v                   v
       Keyword Search       Vector Search
             │                   │
             └─────────┬─────────┘
                       │
                       v
                Ranked Results
                       |
                       v
                Top-K Chunks
```

### Keyword Search

Strong for:

- Exact legal terminology
- Contract IDs
- Clause names
- Specific percentages
- Identifiers

### Vector Search

Strong for:

- Semantic similarity
- Paraphrased questions
- Conceptual matching
- Natural-language queries

### Hybrid

Combines both strengths. This is particularly useful for legal/contract data because contracts contain both exact terminology and semantically equivalent expressions.

---

## 12. Where Metadata Is Stored

Metadata remains associated with the Snowflake source records.

Example:

```text
CONTRACT_CHUNKS

+----------------+----------------+
| Column         | Example        |
+----------------+----------------+
| contract_id    | CONTRACT_101   |
| chunk_id       | CHUNK_0042     |
| chunk_text     | royalty clause |
| effective_date | 2026-01-01     |
| metadata       | JSON           |
+----------------+----------------+
```

Important filterable fields should preferably be dedicated columns:

```text
contract_id
effective_date
country
contract_type
version
```

rather than being stored only inside a JSON object.

Cortex Search can expose selected source columns as searchable/filterable attributes.

Example:

```text
Query:
"Find royalty renewal terms"

Filter:
contract_id = CONTRACT_101

Search:
hybrid semantic + keyword

Result:
Top relevant chunks for CONTRACT_101
```

---

## 13. Is the Vector Stored Like a Normal Table?

The application should not treat Cortex Search like a manually managed external vector database.

Instead:

```text
Snowflake Source Table
          |
          v
Cortex Search Service
          |
          v
Snowflake-managed Search Index
```

The application interacts with the **Cortex Search Service**.

This avoids creating a second enterprise vector data platform.

---

## 14. How GenAI Interacts with Retrieval

Example question:

> "Summarize the royalty discount terms for Contract 101 expiring next month."

Runtime flow:

```text
User Question
      |
      v
LangGraph
      |
      v
Cortex Search
      |
      +--> Keyword Retrieval
      |
      +--> Vector Retrieval
      |
      v
Top-K Contract Chunks
      |
      v
Context Construction
      |
      +----------------------+
      | User Question        |
      | Retrieved Chunks     |
      | Contract Metadata    |
      +----------+-----------+
                 |
                 v
          Llama 3.1 70B
                 |
                 v
          Grounded Answer
```

The LLM does not need the entire contract. It receives relevant evidence retrieved at runtime.

---

## 15. Why RAG?

RAG means **Retrieval-Augmented Generation**.

Without RAG:

```text
Question → LLM → Answer
```

With RAG:

```text
Question
   |
   v
Retriever
   |
   v
Enterprise Evidence
   |
   v
LLM
   |
   v
Grounded Answer
```

This is important because the model needs the actual current contract language rather than relying on pretrained knowledge.

Benefits:

- Better grounding
- Better traceability
- Better relevance
- Current enterprise information
- Lower hallucination risk

---

## 16. Why Llama 3.1 70B?

Llama 3.1 70B is used as the generative reasoning model for:

- Contract summarization
- Clause explanation
- RAG answers
- Renewal recommendations
- Proposal drafting
- Business explanations

It is **not** responsible for:

- Authoritative royalty calculations
- Access control
- Contract activation
- Effective-date enforcement

Those responsibilities remain deterministic and governed.

---

## 17. Why LangChain?

LangChain provides reusable AI application components for:

- Prompt templates
- LLM invocation
- Retriever integration
- Structured output
- RAG components
- Tool integration

Conceptually:

```text
Cortex Search
      |
      v
Retriever
      |
      v
LangChain
      |
      v
LLM
```

LangChain is primarily the AI integration/component layer.

---

## 18. Why LangGraph?

Contract renewal is not a simple:

```text
Question → LLM → Answer
```

It is a stateful workflow:

```text
Contract Expiry
      |
      v
Performance Evaluation
      |
      v
Retrieve Contract Clauses
      |
      v
Generate Recommendation
      |
      v
Validate Output
      |
      v
Margin Guardrail
      |
   ┌──┴──┐
   |     |
 PASS   FAIL
   |     |
   v     v
 HITL   Financial Review
```

LangGraph is useful for:

- Stateful workflows
- Nodes
- Conditional routing
- Tool calls
- Retries
- Human approval points
- Error paths

It makes the agent workflow explicit rather than hiding business logic inside prompts.

---

## 19. Why Pydantic?

LLMs produce probabilistic output, while downstream systems need predictable schemas.

Example:

```json
{
  "contract_id": "CONTRACT_101",
  "recommended_rate": 0.065,
  "projected_margin": 0.18,
  "recommendation": "RENEW",
  "approval_required": true
}
```

Pydantic validates the structure before downstream processing.

```text
LLM
 |
 v
Structured Output
 |
 v
Pydantic Validation
 |
 +--> Valid   → Continue
 |
 +--> Invalid → Retry / Reject
```

---

## 20. AI vs Deterministic Business Logic

A critical TRUST Engine principle:

**The LLM recommends; deterministic systems decide financial truth.**

### LLM

May say:

> "Based on historical performance and contract clauses, a renewal at 6.5% appears commercially reasonable."

### Deterministic Engine

Calculates:

```text
Projected Revenue
Royalty Payout
Minimum Guarantee
Net Margin
Margin Floor
```

Financial calculations should be reproducible and testable rather than delegated to generated text.

---

## 21. Margin Guardrails

```text
Recommended Royalty Rate
          |
          v
Financial Calculation
          |
          v
Projected Net Margin
          |
          v
Is Margin >= Minimum Floor?
          |
       ┌──┴──┐
       |     |
      YES    NO
       |     |
       v     v
      HITL   Manual Financial Review
```

This prevents an agent from automatically generating commercially unsafe terms.

---

## 22. Human-in-the-Loop

The AI does not directly activate a contract.

```text
AI Recommendation
       |
       v
HITL Review
       |
   ┌───┼────┐
   │   │    │
Approve Modify Reject
   │   │    │
   └───┼────┘
       |
       v
Approved Action
```

Reviewers can inspect:

- Contract clauses
- Financial projections
- Recommended rates
- Margin impact
- AI rationale
- Draft communication

Only after approval can the workflow proceed to activation or external communication.

---

## 23. Contract Activation

After external acceptance/signature:

```text
Partner Acceptance
       |
       v
Effective Date
       |
       v
Active Contract Rules
       |
       v
Future Transactions
```

Historical transactions remain governed by their applicable historical contract terms. Transactions on or after the new effective date use the new rules.

---

## 24. Natural-Language Analytics

Example:

> "What was the total revenue for July 2026 by promotion type?"

Flow:

```text
Business User
      |
      v
Streamlit
      |
      v
Cortex Analyst
      |
      v
Semantic Model / YAML
      |
      v
Governed SQL
      |
      v
Snowflake
      |
      v
DataFrame
      |
      v
Plotly
```

The semantic model defines business concepts such as:

- Revenue
- Royalty payout
- Promotion type
- Fulfillment status
- Contract
- Transaction date

This improves Text-to-SQL accuracy and business terminology consistency.

---

## 25. Observability & Evaluation

### LangSmith

Used for:

- Agent tracing
- Prompt tracing
- Tool-call tracing
- Retrieval tracing
- LLM execution tracing
- Debugging

### Ragas

Used for:

- RAG evaluation
- Context relevance
- Answer relevance
- Faithfulness
- Retrieval quality

### Arize Phoenix

Used for:

- LLM observability
- AI tracing
- Retrieval analysis
- Model behavior investigation
- Evaluation

```text
                AI REQUEST
                    |
                    v
                LangGraph
                    |
          ┌─────────┼─────────┐
          |         |         |
          v         v         v
       Search      LLM      Tools
          |         |         |
          └─────────┼─────────┘
                    |
                    v
                 Response

       ┌────────────┼────────────┐
       v            v            v
  LangSmith      Phoenix       Ragas
    Trace       Observe       Evaluate
```

---

## 26. Security and Governance

Snowflake RBAC controls access to enterprise data.

```text
User
 |
 v
Authentication / Authorization
 |
 v
Snowflake RBAC
 |
 v
Permitted Data
 |
 v
AI Retrieval / Analytics
```

AI must not bypass enterprise permissions.

Audit records should capture:

- Proposal ID
- Contract ID
- AI recommendation
- Reviewer
- Approval/rejection
- Modified terms
- Timestamp
- Effective date
- Activation status

---

## 27. Forecasting Flow

```text
Retail / Wholesale Transactions
             |
             v
          Snowflake
             |
             v
     Data Cleaning / QA
             |
             v
      Feature Engineering
             |
       ┌─────┴─────┐
       v           v
    XGBoost       LSTM
       |           |
       └─────┬─────┘
             v
      Stacking Model
             |
             v
      Demand Forecast
             |
             v
      Revenue Forecast
             |
             v
      Royalty Engine
             |
             v
     Projected Payout
             |
             v
       Margin Analysis
```

---

## 28. Technology Stack

### Data Platform
- Snowflake
- Snowflake SQL
- Snowpark
- AWS S3
- Snowflake External Stage

### Data Engineering
- Python
- PySpark
- Data Cleaning
- Data Validation
- Feature Engineering

### Machine Learning
- XGBoost
- LSTM
- PyTorch / TensorFlow
- Stacking / Ensemble Learning

### Generative AI
- Snowflake Cortex
- Llama 3.1 70B
- `snowflake-arctic-embed-l-v2.0`
- Cortex Search
- Cortex Analyst
- RAG

### Agentic AI
- LangChain
- LangGraph
- Pydantic

### Application
- Streamlit
- Plotly

### Workflow
- Apache Airflow

### Observability / Evaluation
- LangSmith
- Ragas
- Arize Phoenix

### Governance
- Snowflake RBAC
- Human-in-the-Loop
- Audit Logging
- Financial Guardrails

---

## 29. Why This Architecture Instead of an External Vector Database?

A traditional architecture might be:

```text
Snowflake
    |
    v
External Vector DB
    |
    v
LLM
```

The TRUST Engine uses:

```text
Snowflake
    |
    +--> Cortex Search
    +--> Cortex Embeddings
    +--> Cortex LLM
    +--> Cortex Analyst
```

Advantages:

- Less data movement
- No duplicate contract vector store
- Centralized governance
- Simplified architecture
- Snowflake-native security
- Easier lineage
- Fewer synchronization pipelines
- Lower operational complexity

The decision is not that external vector databases are inherently bad. The decision is that Snowflake already provides the required storage, search, governance, and AI capabilities for this enterprise use case.

---

## 30. Core Architecture Principle

```text
              ┌───────────────────────┐
              │       DATA            │
              │     Snowflake         │
              └───────────┬───────────┘
                          |
              ┌───────────▼───────────┐
              │      RETRIEVAL        │
              │    Cortex Search      │
              └───────────┬───────────┘
                          |
              ┌───────────▼───────────┐
              │      REASONING        │
              │   Llama / GenAI       │
              └───────────┬───────────┘
                          |
              ┌───────────▼───────────┐
              │     ORCHESTRATION     │
              │      LangGraph        │
              └───────────┬───────────┘
                          |
              ┌───────────▼───────────┐
              │     VALIDATION        │
              │ Pydantic + Guardrails │
              └───────────┬───────────┘
                          |
              ┌───────────▼───────────┐
              │     HUMAN CONTROL     │
              │        HITL            │
              └───────────┬───────────┘
                          |
              ┌───────────▼───────────┐
              │   AUTHORITATIVE RULES │
              │ Snowflake / SQL       │
              └───────────────────────┘
```

This separation makes the platform more reliable, explainable, auditable, and appropriate for financial/contractual workloads.

---

## 31. Interview-Ready Explanation

> "The TRUST Engine keeps Snowflake as the single source of truth. Contract PDFs land in S3 and are exposed through a Snowflake external stage. We extract the PDF text, clean it, preserve document metadata, and represent the document in a structured JSON form before creating manageable contract chunks in Snowflake.
>
> We then use Snowflake Cortex Search for retrieval. The search layer combines keyword-based retrieval with vector/semantic retrieval, using Snowflake's Arctic embedding model for semantic representation. Contract ID, effective date, and other metadata remain associated with the Snowflake source records and can be used as search filters.
>
> Llama 3.1 70B is not responsible for indexing. It is the generation and reasoning model. At runtime, the user query goes through LangGraph, Cortex Search retrieves the most relevant contract chunks, and those chunks are supplied to Llama as grounded context. The model then produces a structured response that is validated with Pydantic.
>
> LangGraph is used because contract renewal is a stateful workflow with conditional routing, financial validation, and human approval rather than a simple LLM call. Financial calculations and margin rules remain deterministic in Snowflake instead of being delegated to the LLM.
>
> Finally, LangSmith provides agent/application tracing, Ragas evaluates RAG quality, and Arize Phoenix provides additional AI/LLM observability and evaluation. High-impact recommendations always go through HITL before contract activation or external communication."

---

## 32. Final Architecture in One Sentence

**S3 provides raw document storage, Snowflake provides the governed source of truth, Cortex Search provides hybrid retrieval, Llama provides grounded generation, LangGraph orchestrates the agent workflow, deterministic rules protect financial correctness, HITL provides human governance, and LangSmith / Ragas / Phoenix provide AI observability and evaluation.**

### Project Structure

```
ai-trust-engine/
│
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
│
├── config/
│   ├── environments/
│   │   ├── dev.yaml
│   │   ├── qa.yaml
│   │   ├── uat.yaml
│   │   └── prod.yaml
│   │
│   └── pipelines/
│       └── trust-engine.yaml
│
├── src/
│   └── trust_engine/
│
│       ├── config/
│       │   ├── loader.py
│       │   ├── validator.py
│       │   └── models.py
│       │
│       ├── ingestion/
│       │   ├── retail.py
│       │   ├── wholesale.py
│       │   └── contracts.py
│       │
│       ├── data/
│       │   ├── transformations.py
│       │   ├── validation.py
│       │   ├── deduplication.py
│       │   └── feature_engineering.py
│       │
│       ├── documents/
│       │   ├── detector.py
│       │   ├── extractor.py
│       │   ├── ocr.py
│       │   ├── chunker.py
│       │   └── metadata.py
│       │
│       ├── ai/
│       │   ├── embeddings.py
│       │   ├── cortex.py
│       │   ├── search.py
│       │   ├── prompts.py
│       │   └── rag.py
│       │
│       ├── forecasting/
│       │   ├── features.py
│       │   ├── xgboost_model.py
│       │   ├── lstm_model.py
│       │   ├── trainer.py
│       │   └── predictor.py
│       │
│       ├── workflows/
│       │   ├── contract_recommendation.py
│       │   ├── forecasting.py
│       │   └── analytics.py
│       │
│       ├── governance/
│       │   ├── hitl.py
│       │   ├── guardrails.py
│       │   ├── audit.py
│       │   └── policy.py
│       │
│       ├── observability/
│       │   ├── logging.py
│       │   ├── tracing.py
│       │   └── evaluation.py
│       │
│       ├── services/
│       │   ├── contract_service.py
│       │   ├── forecast_service.py
│       │   └── analytics_service.py
│       │
│       └── main.py
│
├── snowflake/
│   │
│   ├── database/
│   │   ├── databases.sql
│   │   └── schemas.sql
│   │
│   ├── stages/
│   │   ├── transaction_stage.sql
│   │   └── contract_stage.sql
│   │
│   ├── tables/
│   │   ├── raw_transactions.sql
│   │   ├── transactions.sql
│   │   ├── contracts.sql
│   │   ├── document_chunks.sql
│   │   ├── forecasts.sql
│   │   └── ai_metadata.sql
│   │
│   ├── cortex/
│   │   ├── search_service.sql
│   │   └── cortex_objects.sql
│   │
│   ├── tasks/
│   │   ├── forecasting_task.sql
│   │   └── contract_processing_task.sql
│   │
│   └── procedures/
│       └── processing_procedures.sql
│
├── tests/
│   ├── unit/
│   │   ├── test_chunker.py
│   │   ├── test_validation.py
│   │   ├── test_rag.py
│   │   └── test_forecasting.py
│   │
│   ├── integration/
│   │   ├── test_snowflake.py
│   │   └── test_cortex.py
│   │
│   └── evaluation/
│       ├── rag_evaluation.py
│       └── llm_evaluation.py
│
├── scripts/
│   ├── deploy.py
│   ├── validate_config.py
│   └── run_pipeline.py
│
├── infrastructure/
│   ├── terraform/
│   └── github-actions/
│       ├── ci.yml
│       ├── deploy-dev.yml
│       └── deploy-prod.yml
│
└── docs/
    ├── architecture.md
    ├── data-flow.md
    ├── ai-architecture.md
    ├── deployment.md
    ├── security.md
    └── workflows.md
```
