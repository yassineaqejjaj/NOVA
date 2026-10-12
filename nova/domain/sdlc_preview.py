"""Preview of a pull request: which deployment of a commit is the one a person should look at.

Pure (no I/O). Hosting platforms (Vercel, Netlify, Railway PR environments…) report each deployment of a commit to
GitHub as a deployment with statuses. The preview is the newest *successful* one that is not production, and its URL
must be https: NOVA never links to anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

PRODUCTION_WORDS = ("production", "prod")
PREVIEW_MARKER = "<!-- nova-preview -->"


@dataclass(frozen=True)
class DeploymentStatus:
    environment: str
    state: str  # latest status of the deployment: success | failure | pending | in_progress…
    url: str | None  # environment_url, else target_url
    at: str  # ISO timestamp, sortable as text


def _is_production(environment: str) -> bool:
    name = environment.lower()
    return any(word in name for word in PRODUCTION_WORDS) and "preview" not in name


def _safe(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    return url.strip() if parsed.scheme == "https" and parsed.netloc else None


def pick_preview(deployments: list[DeploymentStatus]) -> str | None:
    """URL of the newest successful non-production deployment, or ``None``."""
    usable = [d for d in deployments if d.state == "success" and not _is_production(d.environment) and _safe(d.url)]
    if not usable:
        return None
    return _safe(max(usable, key=lambda d: d.at).url)


def preview_comment(url: str, sha: str) -> str:
    """The pull request comment announcing the preview (marker makes it recognisable and posted once)."""
    return f"{PREVIEW_MARKER}\n**Preview ready** for commit `{sha[:7]}`: {url}\n\nLook at the change running before approving the merge."
