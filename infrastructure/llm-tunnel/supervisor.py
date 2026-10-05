"""Keeps the demo LLM tunnel alive and NOVA (Railway) pointed at it.

Runs `cloudflared tunnel --url http://127.0.0.1:11500` (quick tunnel, no Cloudflare account). Quick tunnels
get a new random URL on every start and are dropped by Cloudflare after long interruptions (laptop asleep):
* every new URL is pushed to NOVA_LLM_BASE_URL on the Railway services (api, worker, beat);
* "Tunnel not found" errors (tunnel deleted server-side) restart cloudflared;
* cloudflared exiting is restarted with back-off (launchd also keeps this supervisor alive).

Environment: CLOUDFLARED (binary), RAILWAY (CLI path), RAILWAY_PROJECT (project id), RAILWAY_SERVICES
(comma separated, default api,worker,beat), STATE_DIR (stores the current URL), PROXY_URL.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

CLOUDFLARED = os.environ["CLOUDFLARED"]
RAILWAY = os.environ.get("RAILWAY", "railway")
PROJECT = os.environ["RAILWAY_PROJECT"]
ENVIRONMENT = os.environ.get("RAILWAY_ENVIRONMENT", "production")
SERVICES = [s for s in os.environ.get("RAILWAY_SERVICES", "api,worker,beat").split(",") if s]
STATE = Path(os.environ.get("STATE_DIR", Path.home() / ".nova-llm-tunnel"))
PROXY_URL = os.environ.get("PROXY_URL", "http://127.0.0.1:11500")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
GONE = ("Tunnel not found", "failed to unmarshal quick Tunnel", "error code: 1033")


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def push_url(url: str) -> None:
    current = STATE / "url"
    if current.exists() and current.read_text().strip() == url:
        return
    ok = True
    for service in SERVICES:
        result = subprocess.run(
            [RAILWAY, "variable", "set", "-p", PROJECT, "-e", ENVIRONMENT, "-s", service, f"NOVA_LLM_BASE_URL={url}/v1"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        ok = ok and result.returncode == 0
        log(f"railway {service}: {'ok' if result.returncode == 0 else result.stderr.strip()[:200]}")
    if ok:  # otherwise retried on the next URL announcement / restart
        current.write_text(url)


def run_once() -> None:
    process = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--no-autoupdate", "--url", PROXY_URL],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    gone = 0
    assert process.stdout is not None
    for line in process.stdout:
        if match := URL_RE.search(line):
            log(f"tunnel up: {match.group(0)}")
            push_url(match.group(0))
        if any(marker in line for marker in GONE):
            gone += 1
            if gone >= 3:
                log("tunnel deleted by Cloudflare: restarting")
                process.terminate()
                break
    process.wait(timeout=30)


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    delay = 5
    while True:
        started = time.time()
        try:
            run_once()
        except Exception as exc:  # keep supervising
            log(f"error: {exc}")
        delay = 5 if time.time() - started > 300 else min(delay * 2, 300)
        log(f"cloudflared stopped, restarting in {delay}s")
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())
