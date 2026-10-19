import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const API = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname.startsWith("/api")
    || pathname.startsWith("/_next")
    || pathname.startsWith("/login")
    || pathname.startsWith("/access-denied")
  ) {
    return NextResponse.next();
  }
  try {
    const me = await fetch(`${API}/api/auth/me`, {
      headers: { cookie: request.headers.get("cookie") || "" },
      cache: "no-store",
    });
    if (!me.ok) return NextResponse.next();
    const data = await me.json();
    if (data.auth_disabled || data.authenticated) return NextResponse.next();
  } catch {
    return NextResponse.next();
  }
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
