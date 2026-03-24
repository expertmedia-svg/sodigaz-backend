from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a naive UTC datetime without relying on deprecated utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_now_iso() -> str:
    return utc_now().isoformat()