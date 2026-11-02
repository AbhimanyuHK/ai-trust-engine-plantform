"""Environment and YAML configuration loading."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    trust_env: str = "dev"
    trust_database: str = "TRUST_DB"
    trust_schema: str = "CORE"
    trust_warehouse: str = "TRUST_WH"
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_role: str = ""
    snowflake_authenticator: str = "snowflake"
    contract_stage: str = "@TRUST_DB.RAW.CONTRACT_STAGE"
    cortex_search_service: str = "TRUST_DB.AI.CONTRACT_SEARCH_SERVICE"
    cortex_embedding_model: str = "snowflake-arctic-embed-l-v2.0"
    cortex_llm_model: str = "llama3.1-70b"
    trust_checkpoint_db: str = "./.trust/checkpoints.sqlite"
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""

    @property
    def snowflake_config(self) -> dict[str, str]:
        required = {"account": self.snowflake_account, "user": self.snowflake_user}
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing Snowflake settings: {', '.join(missing)}")
        result = {"account": self.snowflake_account, "user": self.snowflake_user,
                  "warehouse": self.trust_warehouse, "database": self.trust_database,
                  "schema": self.trust_schema, "authenticator": self.snowflake_authenticator}
        if self.snowflake_password:
            result["password"] = self.snowflake_password
        if self.snowflake_role:
            result["role"] = self.snowflake_role
        return result

def load_pipeline_config(path: str | Path = "config/pipelines/trust-engine.yaml") -> dict[str, Any]:
    """Load YAML and resolve environment placeholders without mutating the file."""
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, str) and value.startswith("$" + "{") and value.endswith("}"):
            return os.getenv(value[2:-1], "")
        return value
    return resolve(raw)
