-- Snowflake-backed lifecycle for contract_intelligence_workflow.
-- Apply after 001_create_contract_intelligence_tables.sql.
-- Standard-table PK constraints are informational; use stable run IDs and
-- application-level duplicate checks/idempotent MERGE operations.

CREATE TABLE IF NOT EXISTS AI.CONTRACT_INTELLIGENCE_WORKFLOW_RUNS (
    RUN_ID              VARCHAR(128) NOT NULL,
    DOCUMENT_ID         VARCHAR(128) NOT NULL,
    CONTRACT_ID         VARCHAR(128) NOT NULL,
    PARTNER_ID          VARCHAR(128),
    SOURCE_URI          VARCHAR(2048) NOT NULL,
    STATUS              VARCHAR(32) NOT NULL,
    CURRENT_STAGE       VARCHAR(64) NOT NULL,
    ATTEMPT             NUMBER(10,0) NOT NULL DEFAULT 1,
    CHUNK_COUNT         NUMBER(10,0),
    ERROR_MESSAGE       VARCHAR(16000),
    REQUEST_PAYLOAD     VARIANT,
    STARTED_AT          TIMESTAMP_NTZ,
    COMPLETED_AT        TIMESTAMP_NTZ,
    CREATED_AT          TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT          TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_CONTRACT_INTELLIGENCE_WORKFLOW_RUNS PRIMARY KEY (RUN_ID),
    CONSTRAINT CK_CONTRACT_INTELLIGENCE_WORKFLOW_ATTEMPT CHECK (ATTEMPT >= 1)
)
COMMENT = 'Current execution state and replay request for contract intelligence PDF ingestion';

CREATE TABLE IF NOT EXISTS AI.CONTRACT_INTELLIGENCE_WORKFLOW_EVENTS (
    EVENT_ID            VARCHAR(36) NOT NULL,
    RUN_ID              VARCHAR(128) NOT NULL,
    DOCUMENT_ID         VARCHAR(128) NOT NULL,
    EVENT_TYPE          VARCHAR(64) NOT NULL,
    STAGE               VARCHAR(64) NOT NULL,
    STATUS              VARCHAR(32) NOT NULL,
    ATTEMPT             NUMBER(10,0) NOT NULL DEFAULT 1,
    DETAILS             VARIANT,
    CREATED_AT          TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_CONTRACT_INTELLIGENCE_WORKFLOW_EVENTS PRIMARY KEY (EVENT_ID)
)
COMMENT = 'Append-only lifecycle events for contract_intelligence_workflow';
