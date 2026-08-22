USE DATABASE TRUST_DB;

CREATE OR REPLACE TASK AI.CONTRACT_PROCESSING_TASK
  WAREHOUSE = TRUST_WH
  SCHEDULE = 'USING CRON 0 3 * * * UTC'
  COMMENT = 'Contract document processing and expiry-check trigger';

-- Enable after the contract processing procedure is deployed:
-- ALTER TASK AI.CONTRACT_PROCESSING_TASK RESUME;
