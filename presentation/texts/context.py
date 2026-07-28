"""Text formatting helpers."""

from string import Formatter

from config.settings import Settings


class _KeepMissing(dict):
    """Leave unknown placeholders as-is instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def text_context(settings: Settings, **extra: str) -> dict[str, str]:
    """Build the placeholder dict for message templates."""
    base = {
        "master_name": settings.master_name,
        "master_username": settings.master_username,
        "master_phone": settings.master_phone,
        "channel_link": settings.channel_link,
        "channel_name": settings.channel_name,
        "payment_link": settings.payment_link,
    }
    base.update(extra)
    return base


def format_message(template: str, settings: Settings, **extra: str) -> str:
    """Substitute known placeholders; leave the rest untouched.

    Several templates carry booking-specific fields (`{date}`, `{time}`, …)
    that the caller fills in later, so a missing key must not be fatal.
    """
    keys = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    if not keys:
        return template
    return template.format_map(_KeepMissing(text_context(settings, **extra)))
