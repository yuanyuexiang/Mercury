import { AntdRegistry } from "@ant-design/nextjs-registry";

import Providers from "@/components/Providers";

export const metadata = {
  title: "Mercury — Telegram AI 询盘转化",
  description: "把 Telegram 对话自动转化为合格销售线索",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <style>{`
          body{margin:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased;}
          *{box-sizing:border-box}
          ::-webkit-scrollbar{width:6px;height:6px}
          ::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:3px}
        `}</style>
        <AntdRegistry>
          <Providers>{children}</Providers>
        </AntdRegistry>
      </body>
    </html>
  );
}
