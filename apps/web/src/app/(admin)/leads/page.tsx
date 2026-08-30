"use client";
// 线索列表：等级 Tab + 同步状态筛选 + 评分理由 + CSV 导出——mini-CRM 视角。
import { DownloadOutlined } from "@ant-design/icons";
import { Avatar, Button, Select, Space, Table, Tabs, Tag } from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import { avatarColor, fromNow, GRADE, initialOf, LEAD_STATUS, SCORE_REASON } from "@/lib/ui";

interface LeadRow {
  id: number;
  conversation_id: number;
  company: string | null;
  business_email: string | null;
  requirement: string | null;
  score: number;
  grade: string;
  status: string;
  score_reasons: string[] | null;
  user: { username: string | null; telegram_user_id: number } | null;
  updated_at: string;
}

export default function LeadsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<LeadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [grade, setGrade] = useState<string>("all");
  const [status, setStatus] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);

  // 概览页直达 /leads?grade=high
  useEffect(() => {
    const g = new URLSearchParams(window.location.search).get("grade");
    if (g && GRADE[g]) setGrade(g);
    setReady(true);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page) });
      if (grade !== "all") params.set("grade", grade);
      if (status) params.set("status", status);
      const data = await api.get<{ items: LeadRow[]; total: number }>(`/api/leads?${params}`);
      setRows(data.items);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  }, [page, grade, status]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  const exportCsv = () => {
    const params = new URLSearchParams();
    if (grade !== "all") params.set("grade", grade);
    if (status) params.set("status", status);
    const qs = params.toString();
    window.open(`/api/leads/export${qs ? `?${qs}` : ""}`, "_blank");
  };

  return (
    <div>
      <PageHeader
        title="线索"
        subtitle="按评分从高到低排序——优先跟进高意向"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="全部同步状态"
              style={{ width: 150 }}
              value={status}
              onChange={(v) => {
                setPage(1);
                setStatus(v);
              }}
              options={Object.entries(LEAD_STATUS).map(([value, s]) => ({ value, label: s.label }))}
            />
            <Button icon={<DownloadOutlined />} onClick={exportCsv}>
              导出 CSV
            </Button>
          </Space>
        }
      />
      <Tabs
        activeKey={grade}
        onChange={(k) => {
          setPage(1);
          setGrade(k);
          window.history.replaceState(null, "", k === "all" ? "/leads" : `/leads?grade=${k}`);
        }}
        items={[
          { key: "all", label: "全部" },
          { key: "high", label: "高意向" },
          { key: "medium", label: "中意向" },
          { key: "low", label: "低意向" },
        ]}
        style={{ marginBottom: 4 }}
      />
      <Table<LeadRow>
        rowKey="id"
        dataSource={rows}
        loading={loading}
        onRow={(row) => ({
          onClick: () => router.push(`/leads/${row.id}`),
          style: {
            cursor: "pointer",
            background: row.grade === "high" ? "#FFFBF7" : undefined,
          },
        })}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: setPage,
          showTotal: (t) => `共 ${t} 条线索`,
        }}
        columns={[
          {
            title: "客户",
            width: 240,
            render: (_, row) => {
              const name =
                row.company ?? (row.user?.username ? `@${row.user.username}` : `线索 #${row.id}`);
              return (
                <Space>
                  <Avatar
                    shape="square"
                    style={{
                      background: avatarColor(row.user?.telegram_user_id ?? row.id),
                      borderRadius: 8,
                    }}
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
            width: 150,
            render: (_, row) => (
              <Space size={8}>
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: 16,
                    width: 34,
                    display: "inline-block",
                    color: row.grade === "high" ? "#F5222D" : undefined,
                  }}
                >
                  {row.score}
                </span>
                <Tag color={GRADE[row.grade]?.color}>{GRADE[row.grade]?.label}</Tag>
              </Space>
            ),
          },
          {
            title: "评分理由",
            width: 260,
            render: (_, row) =>
              row.score_reasons?.length ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                  {row.score_reasons.slice(0, 3).map((r) => (
                    <Tag key={r} style={{ fontSize: 11, marginInlineEnd: 0 }}>
                      {SCORE_REASON[r] ?? r}
                    </Tag>
                  ))}
                  {row.score_reasons.length > 3 && (
                    <span style={{ fontSize: 11, color: "#94a3b8" }}>
                      +{row.score_reasons.length - 3}
                    </span>
                  )}
                </div>
              ) : (
                <span style={{ color: "#cbd5e1" }}>—</span>
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
            width: 100,
            render: (s: string) => (
              <Tag color={LEAD_STATUS[s]?.color}>{LEAD_STATUS[s]?.label ?? s}</Tag>
            ),
          },
          { title: "更新时间", dataIndex: "updated_at", width: 110, render: fromNow },
        ]}
      />
    </div>
  );
}
