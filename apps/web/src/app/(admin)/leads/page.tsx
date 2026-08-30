"use client";
// 线索列表：等级配色 + 分数条 + 同步状态。
import { Avatar, Select, Space, Table, Tag } from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import { avatarColor, fromNow, GRADE, initialOf, LEAD_STATUS } from "@/lib/ui";

interface LeadRow {
  id: number;
  conversation_id: number;
  company: string | null;
  business_email: string | null;
  requirement: string | null;
  score: number;
  grade: string;
  status: string;
  user: { username: string | null; telegram_user_id: number } | null;
  updated_at: string;
}

export default function LeadsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<LeadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [grade, setGrade] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page) });
      if (grade) params.set("grade", grade);
      const data = await api.get<{ items: LeadRow[]; total: number }>(`/api/leads?${params}`);
      setRows(data.items);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  }, [page, grade]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="线索"
        subtitle="按评分从高到低排序——优先跟进高意向"
        extra={
          <Select
            allowClear
            placeholder="全部等级"
            style={{ width: 140 }}
            value={grade}
            onChange={(v) => {
              setPage(1);
              setGrade(v);
            }}
            options={Object.entries(GRADE).map(([value, g]) => ({ value, label: g.label }))}
          />
        }
      />
      <Table<LeadRow>
        rowKey="id"
        dataSource={rows}
        loading={loading}
        onRow={(row) => ({
          onClick: () => router.push(`/leads/${row.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{ current: page, total, pageSize: 20, onChange: setPage, showTotal: (t) => `共 ${t} 条线索` }}
        columns={[
          {
            title: "客户",
            width: 240,
            render: (_, row) => {
              const name = row.company ?? (row.user?.username ? `@${row.user.username}` : `线索 #${row.id}`);
              return (
                <Space>
                  <Avatar
                    shape="square"
                    style={{ background: avatarColor(row.user?.telegram_user_id ?? row.id), borderRadius: 8 }}
                  >
                    {initialOf(name)}
                  </Avatar>
                  <div style={{ lineHeight: 1.3 }}>
                    <div style={{ fontWeight: 550 }}>{name}</div>
                    <div style={{ fontSize: 12, color: "#94a3b8" }}>
                      {row.business_email ?? (row.user?.username ? `@${row.user.username}` : "—")}
                    </div>
                  </div>
                </Space>
              );
            },
          },
          {
            title: "评分",
            width: 170,
            render: (_, row) => (
              <Space size={8}>
                <span style={{ fontWeight: 700, fontSize: 16, width: 34, display: "inline-block" }}>
                  {row.score}
                </span>
                <Tag color={GRADE[row.grade]?.color}>{GRADE[row.grade]?.label}</Tag>
              </Space>
            ),
          },
          {
            title: "需求",
            dataIndex: "requirement",
            ellipsis: true,
            render: (v: string | null) => v ?? <span style={{ color: "#cbd5e1" }}>—</span>,
          },
          {
            title: "同步状态",
            dataIndex: "status",
            width: 110,
            render: (s: string) => (
              <Tag color={LEAD_STATUS[s]?.color}>{LEAD_STATUS[s]?.label ?? s}</Tag>
            ),
          },
          { title: "更新时间", dataIndex: "updated_at", width: 120, render: fromNow },
        ]}
      />
    </div>
  );
}
