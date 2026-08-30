"use client";
// 统一页头：标题 + 副标题 + 右侧操作区。
import { Space, Typography } from "antd";

export default function PageHeader({
  title,
  subtitle,
  extra,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  extra?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-end",
        marginBottom: 20,
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div>
        <Typography.Title level={3} style={{ margin: 0, fontWeight: 650 }}>
          {title}
        </Typography.Title>
        {subtitle && (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {subtitle}
          </Typography.Text>
        )}
      </div>
      {extra && <Space wrap>{extra}</Space>}
    </div>
  );
}
