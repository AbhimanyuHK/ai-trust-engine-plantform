-- AI TRUST Engine
-- 02_stages.sql
-- For a free-trial POC, an internal Snowflake stage is sufficient.
-- An external S3 stage can be added later if required.

CREATE STAGE IF NOT EXISTS IDENTIFIER('${TRUST_DB}.RAW.CONTRACT_STAGE')
  DIRECTORY = (ENABLE = TRUE);

CREATE STAGE IF NOT EXISTS IDENTIFIER('${TRUST_DB}.RAW.RETAIL_STAGE');
CREATE STAGE IF NOT EXISTS IDENTIFIER('${TRUST_DB}.RAW.WHOLESALE_STAGE');

-- Optional S3 pattern (configure credentials/storage integration separately):
-- CREATE STAGE <stage_name>
--   URL = 's3://<bucket>/<prefix>/'
--   STORAGE_INTEGRATION = <storage_integration>
--   FILE_FORMAT = (TYPE = PARQUET);
