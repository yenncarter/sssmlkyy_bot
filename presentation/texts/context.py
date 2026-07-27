"""Text formatting helpers."""

from string import Formatter

from config.settings import Settings, settings as default_settings


def text_context(settings: Settings | None = None, **extra: str) -> dict[str, str]:
    """Build placeholder dict for message templates."""
    cfg = settings or default_settings
    base = {
        "master_name": cfg.master_name,
        "master_username": cfg.master_username,
        "master_phone": cfg.master_phone,
        "channel_link": cfg.channel_link,
        "channel_name": cfg.channel_name,
        "payment_link": cfg.payment_link,
    }
    base.update(extra)
    return base


def format_message(
    template: str,
    settings: Settings | None = None,
    **extra: str,
) -> str:
    """Format only placeholders that exist in the template."""
    keys = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    if not keys:
        return template
    data = text_context(settings, **extra)
    return template.format(**{key: data[key] for key in keys})
