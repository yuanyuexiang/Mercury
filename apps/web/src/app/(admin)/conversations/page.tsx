"use client";
// 会话列表（技术方案 §10）：状态筛选、搜索、分页。
import { Input, Select, Space, Table, Tag, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

interface ConvRow {
  id: number;
  status: string;
  user: { username: string | null; first_name: string | null; telegram_user_id: number };
  lead_grade: string | null;
  lead_score: number | null;
  last_message: string | null;
  last_message_at: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  ai_active: "green",
  handoff_pending: "orange",
  human_active: "red",
  closed: "default",
};

export default function ConversationsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<ConvRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string | undefined>();
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page) });
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    const data = await api.get<{ items: ConvRow[]; total: number }>(
      `/api/conversations?${params}`,
    );
    setRows(data.items);
    setTotal(data.total);
  }, [page, status, q]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <Typography.Title level={4}>会话</Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="状态筛选"
          style={{ width: 160 }}
          value={status}
          onChange={setStatus}
          options={[
            { value: "ai_active", label: "AI 接待中" },
            { value: "handoff_pending", label: "待人工接管" },
            { value: "human_active", label: "人工接待中" },
            { value: "closed", label: "已关闭" },
          ]}
        />
        <Input.Search
          placeholder="搜索用户名/消息内容"
          style={{ width: 260 }}
          onSearch={(value) => {
            setPage(1);
            setQ(value);
          }}
          allowClear
        />
      </Space>
      <Table<ConvRow>
        rowKey="id"
        dataSource={rows}
        onRow={(row) => ({
          onClick: () => router.push(`/conversations/${row.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: setPage,
          showTotal: (t) => `共 ${t} 条`,
        }}
        columns={[
          { title: "ID", dataIndex: "id", width: 70 },
          {
            title: "用户",
            render: (_, row) =>
              row.user.username
                ? `@${row.user.username}`
                : (row.user.first_name ?? row.user.telegram_user_id),
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 130,
            render: (s: string) => <Tag color={STATUS_COLORS[s]}>{s}</Tag>,
          },
          {
            title: "线索",
            width: 110,
            render: (_, row) =>
              row.lead_grade ? `${row.lead_grade}（${row.lead_score}）` : "-",
          },
          { title: "最后消息", dataIndex: "last_message", ellipsis: true },
          { title: "时间", dataIndex: "last_message_at", width: 180 },
        ]}
      />
    </div>
  );
}
