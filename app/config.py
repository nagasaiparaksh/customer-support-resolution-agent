"""Central settings, read once from environment variables."""
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("SUPPORT_DB", "support.db"))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("SUPPORT_MODEL", "claude-haiku-5-5"))

    # Which model understands messages: auto | anthropic | openai | none
    #   auto      -> Claude if ANTHROPIC_API_KEY is set, else a local Ollama server if one is running
    #   openai    -> any OpenAI-compatible endpoint (LLM_BASE_URL), e.g. hosted Qwen
    #   none      -> keyword rules only
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "auto"))
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", "none"))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    local_model: str = field(default_factory=lambda: os.environ.get("SUPPORT_LOCAL_MODEL", ""))
    # Small local models are slow on CPU, so replies stay templated unless this is on.
    llm_replies: bool = field(default_factory=lambda: os.environ.get("LLM_REPLIES", "") == "1")

    # Business rules (see app/policy.py)
    refund_window_days: int = 30
    auto_resolve_limit: float = 100.0   # above this amount a human must approve
    repeat_complaint_limit: int = 3     # prior tickets in 90 days that trigger human review
    late_credit_amount: float = 10.0


settings = Settings()
