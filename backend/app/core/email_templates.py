"""Code-stored email templates: name -> (subject, body) Jinja2 pairs.

Storage is code (git-versioned), not DB — template changes ride a deploy and
the send-time audit discipline; no user-supplied Jinja2 ever executes, so no
sandboxing problem exists. Render at ENQUEUE time: a template error is then a
400 on the write that caused it, never a worker failure after the fact.
"""
from __future__ import annotations

from jinja2 import Environment, StrictUndefined, TemplateError

from app.routers.deps import get_settings

# Text emails: autoescape would mangle names like O'Brien. StrictUndefined
# makes a missing context key a loud error instead of silently blank text.
_env = Environment(autoescape=False, undefined=StrictUndefined, enable_async=False)


class TemplateRenderError(ValueError):
    """Unknown name or failed render — surfaces as 400 at enqueue time."""


_TEMPLATES: dict[str, dict[str, str]] = {
    "review_reminder": {
        "subject": "[IAG] Review reminder: campaign '{{ campaign_name }}'",
        "body": (
            "Hello {{ first_name }},\n"
            "\n"
            "You have pending access reviews in campaign '{{ campaign_name }}'.\n"
            "Open them at {{ review_url }}\n"
            "\n"
            "This is an automated reminder."
        ),
    },
}


def available_templates() -> list[str]:
    return sorted(_TEMPLATES)


def render_email(name: str, **context) -> tuple[str, str]:
    """Render (subject, body) or raise TemplateRenderError. No silent
    fallbacks: enqueue either composes a complete email or refuses."""
    if name not in _TEMPLATES:
        raise TemplateRenderError(f"unknown email template: {name!r}")
    try:
        subject = _env.from_string(_TEMPLATES[name]["subject"]).render(**context)
        body = _env.from_string(_TEMPLATES[name]["body"]).render(**context)
    except TemplateError as exc:
        raise TemplateRenderError(
            f"email template {name!r} failed to render: {exc}") from exc
    if not subject.strip():
        raise TemplateRenderError(f"email template {name!r} rendered empty subject")
    return subject, body


def build_review_url(campaign_id: int) -> str:
    """Absolute sign-in URL for reminder bodies. Frontend base comes from
    settings so the URL is correct behind nginx or in dev, without parsing
    Host headers."""
    settings = get_settings()
    return f"{settings.app_base_url.rstrip('/')}/reviews?campaign={campaign_id}"
