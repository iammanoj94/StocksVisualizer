from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Literal


Freshness = Literal["Fresh", "Delayed", "Stale", "Unavailable"]


@dataclass(frozen=True)
class PriceStatus:
    value: float | None
    currency: str
    source: str
    exchange: str
    as_of: datetime | None
    recorded_at: datetime | None
    freshness: Freshness


def exchange_from_symbol(ticker: str) -> str:
    suffix = ticker.rsplit(".", 1)[-1].upper() if "." in ticker else ""
    if suffix == "NS":
        return "NSE (inferred from ticker; unverified)"
    if suffix == "BO":
        return "BSE (inferred from ticker; unverified)"
    return "Unknown"


def _parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def assess_price(
    *,
    ticker: str,
    value: float | None,
    source: str | None,
    as_of: str | datetime | None,
    recorded_at: str | datetime | None,
    now: datetime | None = None,
) -> PriceStatus:
    """Assess price recency using source as-of time, never import time."""
    parsed_as_of = _parse_timestamp(as_of)
    parsed_recorded_at = _parse_timestamp(recorded_at)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    if value is None:
        normalized_value = None
    else:
        try:
            normalized_value = float(value)
        except (TypeError, ValueError, OverflowError):
            normalized_value = None
        if normalized_value is not None and (
            not math.isfinite(normalized_value) or normalized_value <= 0
        ):
            normalized_value = None

    if normalized_value is None or not source or parsed_as_of is None:
        freshness: Freshness = (
            "Stale"
            if normalized_value is not None and source
            else "Unavailable"
        )
    else:
        age = reference - parsed_as_of
        if age < timedelta(minutes=-5):
            freshness = "Unavailable"
            normalized_value = None
        elif age <= timedelta(minutes=15):
            freshness = "Fresh"
        elif age <= timedelta(days=1):
            freshness = "Delayed"
        else:
            freshness = "Stale"

    return PriceStatus(
        value=normalized_value,
        currency="INR",
        source=source or "Unavailable",
        exchange=exchange_from_symbol(ticker),
        as_of=parsed_as_of,
        recorded_at=parsed_recorded_at,
        freshness=freshness,
    )
