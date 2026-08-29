// 未登录重定向 /login（技术方案 §3）。M8 实现；当前直通。
import { NextResponse } from "next/server";

export function middleware() {
  return NextResponse.next();
}
