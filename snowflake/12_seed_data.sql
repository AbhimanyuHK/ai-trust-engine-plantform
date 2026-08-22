-- AI TRUST Engine
-- 12_seed_data.sql

INSERT INTO IDENTIFIER('${TRUST_DB}.METADATA.AI_MODEL_METADATA')
  (MODEL_NAME, MODEL_PROVIDER, MODEL_TYPE, MODEL_VERSION, PURPOSE, CONFIG)
SELECT
  '${CORTEX_EMBEDDING_MODEL}',
  'snowflake_cortex',
  'embedding',
  'configured',
  'Contract semantic retrieval',
  PARSE_JSON('{"source":"config/pipelines/trust-engine.yaml"}');

INSERT INTO IDENTIFIER('${TRUST_DB}.METADATA.AI_MODEL_METADATA')
  (MODEL_NAME, MODEL_PROVIDER, MODEL_TYPE, MODEL_VERSION, PURPOSE, CONFIG)
SELECT
  '${CORTEX_LLM_MODEL}',
  'snowflake_cortex',
  'llm',
  'configured',
  'Contract recommendation and natural-language analytics',
  PARSE_JSON('{"temperature":0.1,"source":"config/pipelines/trust-engine.yaml"}');
