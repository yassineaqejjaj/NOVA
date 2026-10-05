"""Authenticated proxy in front of a local OpenAI-compatible server (LM Studio, Ollama…) for the NOVA demo tunnel.

* Requires `Authorization: Bearer <key>` (constant-time comparison); everything else gets 401.
* Only /v1/chat/completions and /v1/models are forwarded.
* Non-streamed completions can take minutes on a laptop, longer than the tunnel's time-to-first-byte limit:
  the proxy answers immediately and sends JSON-insignificant whitespace every 15 s until the body is ready.
"""

import asyncio
import hmac
import json
import os
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

KEY = Path(os.environ["PROXY_KEY_FILE"]).read_text().strip()
# LM Studio: http://127.0.0.1:1234 · Ollama: http://127.0.0.1:11434
UPSTREAM = os.environ.get("LLM_UPSTREAM_URL") or os.environ.get("OLLAMA_URL", "http://127.0.0.1:1234")
client = httpx.AsyncClient(base_url=UPSTREAM, timeout=httpx.Timeout(900.0, connect=10.0))


def authorized(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    return header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), KEY.encode())


async def models(request: Request):
    if not authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    r = await client.get("/v1/models")
    return JSONResponse(r.json(), status_code=r.status_code)


async def chat(request: Request):
    if not authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.body()
    if json.loads(body or b"{}").get("stream"):
        upstream = client.build_request(
            "POST", "/v1/chat/completions", content=body, headers={"content-type": "application/json"}
        )
        response = await client.send(upstream, stream=True)

        async def relay():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(relay(), status_code=response.status_code, media_type="text/event-stream")

    async def keepalive():
        task = asyncio.create_task(
            client.post("/v1/chat/completions", content=body, headers={"content-type": "application/json"})
        )
        while True:
            done, _ = await asyncio.wait({task}, timeout=15)
            if done:
                break
            yield b" "
        try:
            r = task.result()
            yield (
                r.content
                if r.status_code < 400
                else json.dumps({"error": {"status": r.status_code, "message": r.text[:500]}}).encode()
            )
        except Exception as exc:  # upstream unreachable
            yield json.dumps({"error": {"message": f"Local LLM server unavailable: {exc}"}}).encode()

    return StreamingResponse(keepalive(), media_type="application/json")


async def health(_: Request):
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/v1/models", models),
        Route("/v1/chat/completions", chat, methods=["POST"]),
    ]
)
