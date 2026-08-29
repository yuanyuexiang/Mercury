"use client";
// 线索列表（技术方案 §10）：按分数排序、等级筛选。
import { Select, Space, Table, Tag, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

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

const GRADE_COLORS: Record<string, string> = { high: "red", medium: "orange", low: "default" };

export default function LeadsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<LeadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [grade, setGrade] = useState<string | undefined>();

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page) });
    if (grade) params.set("grade", grade);
    const data = await api.get<{ items: LeadRow[]; total: number }>(`/api/leads?${params}`);
    setRows(data.items);
    setTotal(data.total);
  }, [page, grade]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <Typography.Title level={4}>线索</Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="等级筛选"
          style={{ width: 140 }}
          value={grade}
          onChange={(v) => {
            setPage(1);
            setGrade(v);
          }}
          options={[
            { value: "high", label: "高意向" },
            { value: "medium", label: "中意向" },
            { value: "low", label: "低意向" },
          ]}
        />
      </Space>
      <Table<LeadRow>
        rowKey="id"
        dataSource={rows}
        onRow={(row) => ({
          onClick: () => router.push(`/leads/${row.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
        columns={[
          { title: "ID", dataIndex: "id", width: 70 },
          {
            title: "等级",
            width: 120,
            render: (_, r) => <Tag color={GRADE_COLORS[r.grade]}>{`${r.grade}（${r.score}）`}</Tag>,
          },
          { title: "公司", dataIndex: "company", render: (v) => v ?? "-" },
          { title: "邮箱", dataIndex: "business_email", render: (v) => v ?? "-" },
          { title: "需求", dataIndex: "requirement", ellipsis: true, render: (v) => v ?? "-" },
          {
            title: "用户",
            render: (_, r) =>
              r.user?.username ? `@${r.user.username}` : (r.user?.telegram_user_id ?? "-"),
          },
          { title: "状态", dataIndex: "status", width: 90 },
          { title: "更新时间", dataIndex: "updated_at", width: 180 },
        ]}
      />
    </div>
  );
}
