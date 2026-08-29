"use client";
// 登录态布局（技术方案 §3）：AntD 侧边导航 + 登出。
import { Button, Layout, Menu } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { api } from "@/lib/api";

const MENU = [
  { key: "/dashboard", label: <Link href="/dashboard">概览</Link> },
  { key: "/conversations", label: <Link href="/conversations">会话</Link> },
  { key: "/leads", label: <Link href="/leads">线索</Link> },
  { key: "/knowledge", label: <Link href="/knowledge">知识库</Link> },
  { key: "/settings", label: <Link href="/settings">模型配置</Link> },
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
      <Layout.Sider theme="dark" width={200}>
        <div style={{ color: "#fff", fontWeight: 700, fontSize: 18, padding: "16px 24px" }}>
          Mercury
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={MENU} />
        <div style={{ padding: 16, position: "absolute", bottom: 0, width: "100%" }}>
          <Button size="small" block onClick={logout}>
            退出登录
          </Button>
        </div>
      </Layout.Sider>
      <Layout.Content style={{ padding: 24, background: "#f5f5f5" }}>{children}</Layout.Content>
    </Layout>
  );
}
