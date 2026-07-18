"""Text formatting helpers."""

from string import Formatter

from config.settings import settings


def text_context(**extra: str) -> dict[str, str]:
    """Build placeholder dict for message templates."""
    base = {
        "master_name": settings.master_name,
        "master_username": settings.master_username,
        "master_phone": settings.master_phone,
        "channel_link": settings.channel_link,
        "channel_name": settings.channel_name,
    }
    base.update(extra)
    return base


def format_message(template: str, **extra: str) -> str:
    """Format only placeholders that exist in the template."""
    keys = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    if not keys:
        return template
    data = text_context(**extra)
    return template.format(**{key: data[key] for key in keys})
