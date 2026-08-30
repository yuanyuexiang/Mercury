"use client";
// 登录态布局：品牌区 + 图标导航 + 底部用户区。
import {
  BookOutlined,
  DashboardOutlined,
  FunnelPlotOutlined,
  LogoutOutlined,
  MessageOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Tooltip } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { api } from "@/lib/api";

const MENU = [
  { key: "/dashboard", icon: <DashboardOutlined />, label: <Link href="/dashboard">概览</Link> },
  { key: "/conversations", icon: <MessageOutlined />, label: <Link href="/conversations">会话</Link> },
  { key: "/leads", icon: <FunnelPlotOutlined />, label: <Link href="/leads">线索</Link> },
  { key: "/knowledge", icon: <BookOutlined />, label: <Link href="/knowledge">知识库</Link> },
  { key: "/settings", icon: <SettingOutlined />, label: <Link href="/settings">模型配置</Link> },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const selected = MENU.find((m) => pathname.startsWith(m.key))?.key ?? "/conversations";

  const logout = async () => {
    await api.post("/api/auth/logout");
    router.push("/login");
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider width={216} style={{ position: "sticky", top: 0, height: "100vh" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "18px 20px 14px",
          }}
        >
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "linear-gradient(135deg,#2F54EB,#13C2C2)",
              color: "#fff",
              fontWeight: 700,
              fontSize: 17,
              flexShrink: 0,
            }}
          >
            M
          </div>
          <div style={{ lineHeight: 1.2 }}>
            <div style={{ color: "#fff", fontWeight: 650, fontSize: 16 }}>Mercury</div>
            <div style={{ color: "rgba(255,255,255,0.45)", fontSize: 11 }}>询盘转化系统</div>
          </div>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={MENU} />
        <div
          style={{
            position: "absolute",
            bottom: 0,
            width: "100%",
            padding: "14px 16px",
            borderTop: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ color: "rgba(255,255,255,0.65)", fontSize: 13 }}>admin</span>
          <Tooltip title="退出登录">
            <Button
              type="text"
              size="small"
              icon={<LogoutOutlined style={{ color: "rgba(255,255,255,0.65)" }} />}
              onClick={logout}
            />
          </Tooltip>
        </div>
      </Layout.Sider>
      <Layout.Content>
        <div style={{ padding: "24px 28px 40px", maxWidth: 1280, margin: "0 auto" }}>
          {children}
        </div>
      </Layout.Content>
    </Layout>
  );
}
