USE DATABASE TRUST_DB;

CREATE STAGE IF NOT EXISTS RAW.TRANSACTION_STAGE
  COMMENT = 'Landing stage for retail and wholesale transaction files';
