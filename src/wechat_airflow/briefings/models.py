from __future__ import annotations

from dataclasses import dataclass
from typing import Any

JsonDict = dict[str, Any]


class DailyBriefingError(RuntimeError):
    """Base error for the personal daily briefing workflow."""


class DailyBriefingConfigError(DailyBriefingError):
    """Raised when an enabled briefing is missing required configuration."""


class DailyBriefingApiError(DailyBriefingError):
    """Raised when the Responses API cannot generate a usable briefing."""


@dataclass(frozen=True)
class BriefingSource:
    title: str
    url: str
