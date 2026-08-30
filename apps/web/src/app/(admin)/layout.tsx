"use client";
// 登录态布局：微信式窄图标侧边栏（64px，纯图标 + Tooltip）——
// 品牌方块在顶、导航图标居中、退出在底；会话图标挂待接管红色 badge。
import {
  ApiOutlined,
  BookOutlined,
  DashboardOutlined,
  FunnelPlotOutlined,
  LogoutOutlined,
  MessageOutlined,
  SettingOutlined,
  ShareAltOutlined,
} from "@ant-design/icons";
import { Badge, Tooltip } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Logo from "@/components/Logo";
import { api } from "@/lib/api";
import { brandTitle, fetchBrandName } from "@/lib/brand";

const NAV = [
  { key: "/dashboard", icon: <DashboardOutlined />, label: "概览" },
  { key: "/conversations", icon: <MessageOutlined />, label: "会话" },
  { key: "/leads", icon: <FunnelPlotOutlined />, label: "线索" },
  { key: "/promotion", icon: <ShareAltOutlined />, label: "推广获客" },
  { key: "/knowledge", icon: <BookOutlined />, label: "知识库" },
  { key: "/settings", icon: <ApiOutlined />, label: "模型配置" },
  { key: "/system", icon: <SettingOutlined />, label: "系统设置" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [brand, setBrand] = useState("");
  const [pending, setPending] = useState(0);

  useEffect(() => {
    fetchBrandName().then((b) => {
      setBrand(b);
      document.title = `${brandTitle(b)} · 询盘转化`;
    });
  }, []);

  // 待接管 badge：30s 轮询，错过接管就是丢单
  useEffect(() => {
    let alive = true;
    const poll = () =>
      api
        .get<{ pending_handoffs: number }>("/api/metrics/pending")
        .then((d) => alive && setPending(d.pending_handoffs))
        .catch(() => {});
    poll();
    const timer = setInterval(poll, 30_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const selected = NAV.find((m) => pathname.startsWith(m.key))?.key ?? "/conversations";

  const logout = async () => {
    await api.post("/api/auth/logout");
    router.push("/login");
  };

  const title = brandTitle(brand);

  return (
    // 显式 flex 横向布局（不用 AntD Layout：它默认纵向，仅识别 Layout.Sider 才变横向）
    <div style={{ display: "flex", minHeight: "100vh", background: "#f5f7fa" }}>
      <aside
        style={{
          width: 64,
          flexShrink: 0,
          background: "#0f172a",
          position: "sticky",
          top: 0,
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          padding: "14px 0 14px",
          zIndex: 10,
        }}
      >
        <Tooltip
          title={`${title} · 询盘转化系统${brand ? "，Powered by Mercury" : ""}`}
          placement="right"
        >
          <div style={{ cursor: "default" }}>
            <Logo size={38} />
          </div>
        </Tooltip>

        <nav
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 6,
            marginTop: 22,
          }}
        >
          {NAV.map((item) => {
            const active = selected === item.key;
            // 颜色写死在最内层：会话图标外面包着 Badge，其 wrapper 自带黑色文字色，
            // 靠 Link 继承会被它截胡（深色栏上图标"消失"的教训）
            const icon = (
              <span
                style={{
                  fontSize: 19,
                  lineHeight: 1,
                  color: active ? "#fff" : "rgba(255,255,255,0.55)",
                }}
              >
                {item.icon}
              </span>
            );
            return (
              <Tooltip key={item.key} title={item.label} placement="right">
                <Link
                  href={item.key}
                  style={{
                    width: 42,
                    height: 42,
                    borderRadius: 10,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: active ? "#fff" : "rgba(255,255,255,0.55)",
                    background: active ? "rgba(255,255,255,0.14)" : "transparent",
                    transition: "background .15s, color .15s",
                  }}
                >
                  {item.key === "/conversations" ? (
                    <Badge count={pending} size="small" offset={[4, -2]} style={{ boxShadow: "none" }}>
                      {icon}
                    </Badge>
                  ) : (
                    icon
                  )}
                </Link>
              </Tooltip>
            );
          })}
        </nav>

        <Tooltip title="admin · 退出登录" placement="right">
          <button
            onClick={logout}
            style={{
              width: 42,
              height: 42,
              borderRadius: 10,
              border: "none",
              background: "transparent",
              color: "rgba(255,255,255,0.55)",
              fontSize: 18,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <LogoutOutlined />
          </button>
        </Tooltip>
      </aside>

      <main style={{ flex: 1, minWidth: 0 }}>
        <div style={{ padding: "20px 24px 36px", maxWidth: 1480, margin: "0 auto" }}>
          {children}
        </div>
      </main>
    </div>
  );
}
