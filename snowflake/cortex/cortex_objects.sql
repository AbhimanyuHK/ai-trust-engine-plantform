USE DATABASE TRUST_DB;

-- Cortex Search owns the managed text/vector retrieval index.
-- AI.DOCUMENT_CHUNKS intentionally does not store a manually dimensioned
-- embedding column; the service selects EMBEDDING_MODEL in search_service.sql.

-- The application uses AI_COMPLETE (the current Cortex generation function)
-- for grounded responses. The Python layer binds model and prompt values.
-- Grant the application role the SNOWFLAKE.CORTEX_USER database role:
-- GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE TRUST_APP_ROLE;
