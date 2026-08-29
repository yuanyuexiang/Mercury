// 未登录重定向 /login（技术方案 §3）。只检查 cookie 存在性；有效性由 api 401 兜底。
import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const authed = request.cookies.has("mercury_session");
  const { pathname } = request.nextUrl;

  if (pathname === "/") {
    return NextResponse.redirect(new URL(authed ? "/conversations" : "/login", request.url));
  }
  if (!authed && pathname !== "/login") {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (authed && pathname === "/login") {
    return NextResponse.redirect(new URL("/conversations", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api|webhooks|health).*)"],
};
