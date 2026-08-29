"use client";
// 概览（技术方案 §10）：基础指标卡片 + 知识缺口。
import { Card, Col, Row, Statistic, Table, Typography } from "antd";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

interface Overview {
  window_days: number;
  messages: number;
  conversations: number;
  auto_replies: number;
  refused: number;
  handoffs: number;
  leads_total: number;
  leads_high: number;
}

interface Gap {
  question: string | null;
  conversation_id: number;
  refused_at: string;
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);

  useEffect(() => {
    api.get<Overview>("/api/metrics/overview").then(setOverview);
    api.get<{ items: Gap[] }>("/api/metrics/knowledge-gaps").then((d) => setGaps(d.items));
  }, []);

  const stats: Array<[string, number | undefined]> = [
    ["消息数", overview?.messages],
    ["会话数", overview?.conversations],
    ["自动回复", overview?.auto_replies],
    ["拒答", overview?.refused],
    ["人工接管", overview?.handoffs],
    ["线索总数", overview?.leads_total],
    ["高意向线索", overview?.leads_high],
  ];

  return (
    <div>
      <Typography.Title level={4}>
        近 {overview?.window_days ?? 14} 天概览
      </Typography.Title>
      <Row gutter={[16, 16]}>
        {stats.map(([title, value]) => (
          <Col key={title} xs={12} md={6}>
            <Card>
              <Statistic title={title} value={value ?? "-"} />
            </Card>
          </Col>
        ))}
      </Row>
      <Card title="知识库缺口（最近拒答的问题）" style={{ marginTop: 24 }}>
        <Table<Gap>
          rowKey={(g) => `${g.conversation_id}-${g.refused_at}`}
          dataSource={gaps}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "用户问题", dataIndex: "question", render: (q) => q ?? "（未知）" },
            { title: "会话", dataIndex: "conversation_id", width: 80 },
            { title: "时间", dataIndex: "refused_at", width: 200 },
          ]}
        />
      </Card>
    </div>
  );
}
