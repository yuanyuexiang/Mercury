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
} from "@ant-design/icons";
import { Badge, Layout, Tooltip } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { brandTitle, fetchBrandName } from "@/lib/brand";

const NAV = [
  { key: "/dashboard", icon: <DashboardOutlined />, label: "概览" },
  { key: "/conversations", icon: <MessageOutlined />, label: "会话" },
  { key: "/leads", icon: <FunnelPlotOutlined />, label: "线索" },
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
    <Layout style={{ minHeight: "100vh" }}>
      <div
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
        }}
      >
        <Tooltip title={`${title} · 询盘转化系统${brand ? "，Powered by Mercury" : ""}`} placement="right">
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 11,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "linear-gradient(135deg,#2F54EB,#13C2C2)",
              color: "#fff",
              fontWeight: 700,
              fontSize: 18,
              cursor: "default",
              userSelect: "none",
            }}
          >
            {title.charAt(0).toUpperCase()}
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
            const icon = (
              <span style={{ fontSize: 19, lineHeight: 1 }}>{item.icon}</span>
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
      </div>

      <Layout.Content>
        <div style={{ padding: "20px 24px 36px", maxWidth: 1480, margin: "0 auto" }}>
          {children}
        </div>
      </Layout.Content>
    </Layout>
  );
}
