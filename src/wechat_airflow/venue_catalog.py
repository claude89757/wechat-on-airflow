"""The active venues. To add one, add one line to venue_catalog.json.

Python, the web app, production health and browser QA all read that file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict


class Venue(TypedDict):
    id: str
    name: str
    wechatName: str
    dagId: str


VENUE_CATALOG: Final[tuple[Venue, ...]] = tuple(
    json.loads(Path(__file__).with_name("venue_catalog.json").read_text(encoding="utf-8"))
)
