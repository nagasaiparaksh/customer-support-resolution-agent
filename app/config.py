"""Central settings, read once from environment variables."""
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("SUPPORT_DB", "support.db"))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("SUPPORT_MODEL", "claude-haiku-5-5"))

    # Business rules (see app/policy.py)
    refund_window_days: int = 30
    auto_resolve_limit: float = 100.0   # above this amount a human must approve
    repeat_complaint_limit: int = 3     # prior tickets in 90 days that trigger human review
    late_credit_amount: float = 10.0


settings = Settings()
