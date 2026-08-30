"use client";
// 会话列表：头像 + 中文状态 + 相对时间 + 搜索筛选。
import { Avatar, Input, Select, Space, Table, Tag } from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import { avatarColor, CONV_STATUS, displayName, fromNow, GRADE, initialOf } from "@/lib/ui";

interface ConvRow {
  id: number;
  status: string;
  user: { username: string | null; first_name: string | null; telegram_user_id: number };
  lead_grade: string | null;
  lead_score: number | null;
  last_message: string | null;
  last_message_at: string | null;
}

export default function ConversationsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<ConvRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page) });
      if (status) params.set("status", status);
      if (q) params.set("q", q);
      const data = await api.get<{ items: ConvRow[]; total: number }>(`/api/conversations?${params}`);
      setRows(data.items);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  }, [page, status, q]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="会话"
        subtitle="点击任意一行进入对话详情，可随时接管"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="全部状态"
              style={{ width: 150 }}
              value={status}
              onChange={(v) => {
                setPage(1);
                setStatus(v);
              }}
              options={Object.entries(CONV_STATUS).map(([value, s]) => ({ value, label: s.label }))}
            />
            <Input.Search
              placeholder="搜索用户名 / 消息内容"
              style={{ width: 240 }}
              onSearch={(value) => {
                setPage(1);
                setQ(value);
              }}
              allowClear
            />
          </Space>
        }
      />
      <Table<ConvRow>
        rowKey="id"
        dataSource={rows}
        loading={loading}
        onRow={(row) => ({
          onClick: () => router.push(`/conversations/${row.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: setPage,
          showTotal: (t) => `共 ${t} 个会话`,
        }}
        columns={[
          {
            title: "用户",
            width: 220,
            render: (_, row) => {
              const name = displayName(row.user);
              return (
                <Space>
                  <Avatar style={{ background: avatarColor(row.user.telegram_user_id) }}>
                    {initialOf(name)}
                  </Avatar>
                  <div style={{ lineHeight: 1.3 }}>
                    <div style={{ fontWeight: 550 }}>{name}</div>
                    <div style={{ fontSize: 12, color: "#94a3b8" }}>#{row.id}</div>
                  </div>
                </Space>
              );
            },
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 130,
            render: (s: string) => (
              <Tag color={CONV_STATUS[s]?.color}>{CONV_STATUS[s]?.label ?? s}</Tag>
            ),
          },
          {
            title: "线索",
            width: 130,
            render: (_, row) =>
              row.lead_grade ? (
                <Tag color={GRADE[row.lead_grade]?.color}>
                  {GRADE[row.lead_grade]?.label}（{row.lead_score}）
                </Tag>
              ) : (
                <span style={{ color: "#cbd5e1" }}>—</span>
              ),
          },
          {
            title: "最后消息",
            dataIndex: "last_message",
            ellipsis: true,
            render: (v: string | null) => v ?? <span style={{ color: "#cbd5e1" }}>—</span>,
          },
          {
            title: "活跃时间",
            dataIndex: "last_message_at",
            width: 120,
            render: fromNow,
          },
        ]}
      />
    </div>
  );
}
