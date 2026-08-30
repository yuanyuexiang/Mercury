"use client";
// 概览：图标统计卡 + Token 用量迷你图 + 知识库缺口。
import {
  FireOutlined,
  FunnelPlotOutlined,
  MessageOutlined,
  RobotOutlined,
  StopOutlined,
  TeamOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Card, Col, Empty, Row, Table, Tooltip, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import { fromNow } from "@/lib/ui";

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

interface CostRow {
  day: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
}

function StatCard({
  icon,
  color,
  title,
  value,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  value: number | undefined;
}) {
  return (
    <Card styles={{ body: { padding: "18px 20px" } }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 42,
            height: 42,
            borderRadius: 11,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 19,
            color,
            background: `${color}14`,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div style={{ lineHeight: 1.25 }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#0f172a" }}>{value ?? "—"}</div>
          <div style={{ fontSize: 12.5, color: "#64748b" }}>{title}</div>
        </div>
      </div>
    </Card>
  );
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [costs, setCosts] = useState<CostRow[]>([]);

  useEffect(() => {
    api.get<Overview>("/api/metrics/overview").then(setOverview);
    api.get<{ items: Gap[] }>("/api/metrics/knowledge-gaps").then((d) => setGaps(d.items));
    api.get<{ items: CostRow[] }>("/api/metrics/costs").then((d) => setCosts(d.items));
  }, []);

  // 按日聚合 token 总量，渲染纯 CSS 迷你柱状图
  const byDay = new Map<string, number>();
  for (const row of costs) {
    byDay.set(row.day, (byDay.get(row.day) ?? 0) + row.prompt_tokens + row.completion_tokens);
  }
  const days = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-14);
  const maxTokens = Math.max(1, ...days.map(([, v]) => v));

  return (
    <div>
      <PageHeader
        title="概览"
        subtitle={`近 ${overview?.window_days ?? 14} 天数据`}
      />
      <Row gutter={[16, 16]}>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<MessageOutlined />} color="#2F54EB" title="消息数" value={overview?.messages} />
        </Col>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<TeamOutlined />} color="#13C2C2" title="会话数" value={overview?.conversations} />
        </Col>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<RobotOutlined />} color="#52C41A" title="AI 自动回复" value={overview?.auto_replies} />
        </Col>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<StopOutlined />} color="#FAAD14" title="安全拒答" value={overview?.refused} />
        </Col>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<UserSwitchOutlined />} color="#FA541C" title="人工接管" value={overview?.handoffs} />
        </Col>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<FunnelPlotOutlined />} color="#722ED1" title="线索总数" value={overview?.leads_total} />
        </Col>
        <Col xs={12} md={8} xl={6}>
          <StatCard icon={<FireOutlined />} color="#F5222D" title="高意向线索" value={overview?.leads_high} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={10}>
          <Card title="模型用量（Token / 日）" styles={{ body: { paddingTop: 12 } }}>
            {days.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无调用记录" />
            ) : (
              <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 120 }}>
                {days.map(([day, tokens]) => (
                  <Tooltip key={day} title={`${day}：${tokens.toLocaleString()} tokens`}>
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}>
                      <div
                        style={{
                          height: `${Math.max(6, (tokens / maxTokens) * 100)}%`,
                          background: "linear-gradient(180deg,#597EF7,#2F54EB)",
                          borderRadius: 4,
                        }}
                      />
                      <div style={{ fontSize: 10, color: "#94a3b8", textAlign: "center", marginTop: 4 }}>
                        {day.slice(5)}
                      </div>
                    </div>
                  </Tooltip>
                ))}
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card
            title="知识库缺口"
            extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>最近被拒答的用户问题——补充对应文档可提高自动解决率</Typography.Text>}
          >
            <Table<Gap>
              rowKey={(g) => `${g.conversation_id}-${g.refused_at}`}
              dataSource={gaps}
              size="small"
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无拒答记录" /> }}
              columns={[
                {
                  title: "用户问题",
                  dataIndex: "question",
                  render: (q: string | null, row) => (
                    <Link href={`/conversations/${row.conversation_id}`}>{q ?? "（未知）"}</Link>
                  ),
                },
                { title: "时间", dataIndex: "refused_at", width: 120, render: fromNow },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
