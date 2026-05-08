"""
Chatbot configuration loaded from environment variables.

BigQuery credential precedence (checked in order by bq_client.py):
  1. GOOGLE_CREDENTIALS_JSON        — full service account JSON as a string (Render / PaaS)
  2. GOOGLE_APPLICATION_CREDENTIALS — path to a service account JSON file  (local dev)
  3. neither set                    — Application Default Credentials       (Cloud Run / GCP)
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str
    GOOGLE_CREDENTIALS_JSON: str
    GOOGLE_APPLICATION_CREDENTIALS: str
    BQ_PROJECT_ID: str

    @classmethod
    def from_env(cls) -> "Config":
        """Construct Config from environment variables, applying defaults where safe."""
        return cls(
            ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY", ""),
            # Swap to claude-opus-4-7 for higher accuracy at higher cost
            CLAUDE_MODEL=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
            GOOGLE_CREDENTIALS_JSON=os.getenv("GOOGLE_CREDENTIALS_JSON", ""),
            GOOGLE_APPLICATION_CREDENTIALS=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            BQ_PROJECT_ID=os.getenv("BQ_PROJECT_ID", "reflected-codex-468204-m7"),
        )