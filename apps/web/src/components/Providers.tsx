"use client";
// 全局主题（品牌主色/圆角/中文语言包）+ AntD App 上下文（message/notification）。
import "@ant-design/v5-patch-for-react-19";

import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#2F54EB",
          colorInfo: "#2F54EB",
          borderRadius: 8,
          colorBgLayout: "#f5f7fa",
          fontSize: 14,
        },
        components: {
          Layout: { siderBg: "#0f172a" },
          Menu: {
            darkItemBg: "#0f172a",
            darkItemSelectedBg: "#2F54EB",
            darkItemColor: "rgba(255,255,255,0.72)",
            darkItemHoverColor: "#fff",
          },
          Card: { boxShadowTertiary: "0 1px 2px rgba(15,23,42,0.04)" },
        },
      }}
    >
      <AntApp>{children}</AntApp>
    </ConfigProvider>
  );
}
