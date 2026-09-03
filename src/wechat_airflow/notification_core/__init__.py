"""Airflow-hosted notification data plane.

The package deliberately keeps durable delivery state in PostgreSQL. Redis may
be used as a wake-up/cache layer, but correctness never depends on Redis or
Cloudflare.
"""

from wechat_airflow.notification_core.domain import (
    NormalizedObservation,
    NormalizedSlot,
    normalize_observation,
)

__all__ = ["NormalizedObservation", "NormalizedSlot", "normalize_observation"]
