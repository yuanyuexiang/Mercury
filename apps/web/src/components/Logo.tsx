"use client";
// 产品标志：渐变底 + 白色对话气泡 + 上升趋势线——"对话变成增长的线索"。
// 抽象图形不依赖品牌首字母，白标到任何客户品牌（含中文名）都成立。
import { useId } from "react";

export default function Logo({ size = 40 }: { size?: number }) {
  const gradientId = useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ display: "block", flexShrink: 0 }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop stopColor="#2F54EB" />
          <stop offset="1" stopColor="#13C2C2" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill={`url(#${gradientId})`} />
      <rect x="10" y="12" width="28" height="20" rx="7" fill="#fff" />
      <path d="M15 30 L13 39 L23 31 Z" fill="#fff" />
      <polyline
        points="16,26 21.5,20 25.5,23.5 31.5,16.5"
        stroke="#2F54EB"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="31.5" cy="16.5" r="2.4" fill="#13C2C2" />
    </svg>
  );
}
