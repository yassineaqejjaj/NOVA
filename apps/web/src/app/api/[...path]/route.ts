// Same-origin proxy to the NOVA API, resolved at runtime (NOVA_API_URL) — Next.js rewrites are fixed at build
// time, which would break container/Kubernetes deployments. Bodies are streamed both ways (SSE included).
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
// Live execution streams (SSE) stay open while NOVA works; EventSource reconnects and replays after this limit.
export const maxDuration = 300;

const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"]);

async function proxy(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await params;
  const base = (process.env.NOVA_API_URL ?? "http://localhost:8200").replace(/\/$/, "");
  const target = `${base}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set("x-forwarded-host", request.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual", // SSO redirects (login/callback) go back to the browser untouched
    cache: "no-store",
    // @ts-expect-error — required by Node's fetch to stream a request body
    duplex: hasBody ? "half" : undefined,
  });

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie" && key.toLowerCase() !== "content-encoding") {
      responseHeaders.set(key, value);
    }
  });
  for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
  if (upstream.headers.get("content-type")?.includes("text/event-stream")) {
    responseHeaders.set("cache-control", "no-cache, no-transform");
    responseHeaders.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
