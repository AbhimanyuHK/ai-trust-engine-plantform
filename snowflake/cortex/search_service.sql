USE DATABASE TRUST_DB;

-- Cortex Search service definition.
-- Review target warehouse, refresh settings and attributes for the
-- Snowflake account before deployment.

CREATE OR REPLACE CORTEX SEARCH SERVICE AI.CONTRACT_SEARCH_SERVICE
  ON CHUNK_TEXT
  ATTRIBUTES CONTRACT_ID, PARTNER_ID, SECTION, PAGE_NUMBER
  WAREHOUSE = TRUST_WH
  TARGET_LAG = '1 hour'
  AS (
    SELECT
      CHUNK_TEXT,
      CONTRACT_ID,
      PARTNER_ID,
      SECTION,
      PAGE_NUMBER
    FROM AI.DOCUMENT_CHUNKS
  );
