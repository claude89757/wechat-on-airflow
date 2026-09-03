"""Host-owned subscription and notification runtime.

The package intentionally uses the existing Airflow PostgreSQL service as its
reliable store while keeping Redis optional and disposable.  Cloudflare is an
edge transport only; no delivery decision depends on D1.
"""

from .database import ensure_schema, get_engine
from .service import active_subscription_for_venue, ingest_observation

__all__ = [
    "active_subscription_for_venue",
    "ensure_schema",
    "get_engine",
    "ingest_observation",
]
