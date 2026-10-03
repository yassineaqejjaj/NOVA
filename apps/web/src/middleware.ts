import { type NextRequest, NextResponse } from "next/server";

/** Visitors without a NOVA session see the landing page at "/"; signed-in users get the app. */
export function middleware(request: NextRequest) {
  if (!request.cookies.has("nova_session")) return NextResponse.rewrite(new URL("/landing", request.url));
  return NextResponse.next();
}

export const config = { matcher: ["/"] };
