"""Runtime configuration, loaded from the environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# The statutory monthly exemption ceiling the user is tracking against, in agorot.
# Seeded on first run; editable from the bot's Settings menu, and versioned by
# effective date so the annual update never rewrites past months.
DEFAULT_CEILING_AGOROT = 1_011_300  # 10,113 NIS

DEFAULT_CITY = "tel_aviv"
DEFAULT_DAILY_OT_THRESHOLD = 8.0  # hours before overtime kicks in
DEFAULT_OT1_SPAN = 2.0            # first N overtime hours at the lower premium


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_user_ids: frozenset[int]
    db_path: Path
    log_level: str

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


def _parse_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return frozenset(ids)


def load_config() -> Config:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    db_path = Path(os.environ.get("DB_PATH", "data/salary.db")).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=token,
        allowed_user_ids=_parse_ids(os.environ.get("ALLOWED_USER_IDS", "")),
        db_path=db_path,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
