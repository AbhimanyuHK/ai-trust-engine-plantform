-- Managed Snowflake Cortex Search index for contract evidence.
-- Apply after AI.DOCUMENT_CHUNKS exists and the TRUST_WH warehouse is available.
-- The service creates/manages embeddings from CHUNK_TEXT; do not persist a
-- second vector column unless a separate vector-search use case requires it.

CREATE CORTEX SEARCH SERVICE IF NOT EXISTS AI.CONTRACT_SEARCH_SERVICE
    ON CHUNK_TEXT
    PRIMARY KEY (CHUNK_ID)
    ATTRIBUTES
        CONTRACT_ID,
        PARTNER_ID,
        DOCUMENT_ID,
        DOCUMENT_NAME,
        DOCUMENT_VERSION,
        CONTRACT_VERSION,
        DOCUMENT_TYPE,
        PAGE_NUMBER,
        PAGE_END,
        SECTION,
        CLAUSE_NUMBER,
        EFFECTIVE_DATE,
        EXPIRY_DATE,
        SOURCE_URI
    WAREHOUSE = TRUST_WH
    TARGET_LAG = '1 hour'
    EMBEDDING_MODEL = 'snowflake-arctic-embed-l-v2.0'
AS
SELECT
    CHUNK_ID,
    CHUNK_TEXT,
    CONTRACT_ID,
    PARTNER_ID,
    DOCUMENT_ID,
    DOCUMENT_NAME,
    DOCUMENT_VERSION,
    CONTRACT_VERSION,
    DOCUMENT_TYPE,
    PAGE_NUMBER,
    PAGE_END,
    SECTION,
    CLAUSE_NUMBER,
    EFFECTIVE_DATE,
    EXPIRY_DATE,
    SOURCE_URI
FROM AI.DOCUMENT_CHUNKS
WHERE CHUNK_TEXT IS NOT NULL;
