"""Which deployment of a commit is the preview a person should look at."""

from __future__ import annotations

from nova.domain.sdlc_preview import PREVIEW_MARKER, DeploymentStatus, pick_preview, preview_comment


def _d(env: str, state: str, url: str | None, at: str) -> DeploymentStatus:
    return DeploymentStatus(env, state, url, at)


def test_the_newest_successful_non_production_deployment_is_the_preview():
    found = pick_preview(
        [
            _d("Preview", "success", "https://old.vercel.app", "2026-10-12T08:00:00Z"),
            _d("Preview", "success", "https://new.vercel.app", "2026-10-12T09:00:00Z"),
            _d("Preview", "failure", "https://broken.vercel.app", "2026-10-12T10:00:00Z"),
            _d("Production", "success", "https://app.example.com", "2026-10-12T11:00:00Z"),
        ]
    )
    assert found == "https://new.vercel.app"


def test_nothing_usable_means_no_preview():
    assert pick_preview([]) is None
    assert pick_preview([_d("Production", "success", "https://app.example.com", "t")]) is None
    assert pick_preview([_d("Preview", "pending", "https://x.vercel.app", "t")]) is None
    assert pick_preview([_d("Preview", "success", None, "t")]) is None


def test_only_https_urls_are_ever_linked():
    assert pick_preview([_d("Preview", "success", "http://insecure.example.com", "t")]) is None
    assert pick_preview([_d("Preview", "success", "javascript:alert(1)", "t")]) is None
    assert pick_preview([_d("Preview", "success", "https://", "t")]) is None


def test_an_environment_named_preview_of_production_is_still_a_preview():
    assert pick_preview([_d("Preview – production-like", "success", "https://p.vercel.app", "t")]) == "https://p.vercel.app"


def test_the_comment_carries_the_marker_the_link_and_the_short_commit():
    text = preview_comment("https://p.vercel.app", "0123456789abcdef")
    assert text.startswith(PREVIEW_MARKER) and "https://p.vercel.app" in text and "`0123456`" in text
