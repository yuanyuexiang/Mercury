"use client";
// 概览 = 获客驾驶舱：今日大数字 → 转化漏斗 → 趋势 → 最新高意向 → 知识库缺口。
// token 用量图在「模型配置」页（成本视角，不属于获客叙事）。
import {
  FireOutlined,
  FunnelPlotOutlined,
  MessageOutlined,
  RightOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Card, Col, Empty, Row, Table, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import { avatarColor, fromNow, initialOf, SCORE_REASON } from "@/lib/ui";

interface Overview {
  window_days: number;
  auto_replies: number;
  refused: number;
  leads_high: number;
  pending_handoffs: number;
  funnel: {
    conversations: number;
    leads: number;
    leads_high: number;
    leads_synced: number;
    leads_won: number;
  };
  channels: Array<{
    channel: string | null;
    conversations: number;
    leads: number;
    leads_high: number;
  }>;
  today: { conversations: number; leads: number };
  trend: Array<{ day: string; conversations: number; leads: number }>;
}

interface Gap {
  question: string | null;
  conversation_id: number;
  refused_at: string;
}

interface SetupStatus {
  telegram: boolean;
  operator: boolean;
  llm: boolean;
  knowledge: boolean;
}

const SETUP_ITEMS: Array<[keyof SetupStatus, string, string]> = [
  ["telegram", "连接 Telegram 机器人", "/system"],
  ["operator", "设置通知接收人", "/system"],
  ["llm", "配置 AI 模型", "/settings"],
  ["knowledge", "上传知识库文档", "/knowledge"],
];

function SetupCard({ status }: { status: SetupStatus }) {
  const doneCount = SETUP_ITEMS.filter(([key]) => status[key]).length;
  return (
    <Card
      style={{ marginBottom: 16, borderColor: "#ADC6FF", background: "#F0F5FF" }}
      styles={{ body: { padding: "16px 20px" } }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <Typography.Text strong style={{ fontSize: 15 }}>
          🚀 快速开始（{doneCount}/{SETUP_ITEMS.length}）
        </Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          完成四步，机器人即可开始接待客户
        </Typography.Text>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "10px 28px", marginTop: 12 }}>
        {SETUP_ITEMS.map(([key, label, href], i) => (
          <Link
            key={key}
            href={href}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13.5,
              color: status[key] ? "#52C41A" : "#1e293b",
              textDecoration: "none",
            }}
          >
            <span
              style={{
                width: 22,
                height: 22,
                borderRadius: "50%",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                fontWeight: 600,
                background: status[key] ? "#52C41A" : "#fff",
                color: status[key] ? "#fff" : "#2F54EB",
                border: status[key] ? "none" : "1.5px solid #2F54EB",
              }}
            >
              {status[key] ? "✓" : i + 1}
            </span>
            <span style={{ textDecoration: status[key] ? "line-through" : "none" }}>{label}</span>
            {!status[key] && <RightOutlined style={{ fontSize: 10, color: "#94a3b8" }} />}
          </Link>
        ))}
      </div>
    </Card>
  );
}

interface HotLead {
  id: number;
  company: string | null;
  name: string | null;
  score: number;
  grade: string;
  score_reasons: string[];
  requirement: string | null;
  updated_at: string;
  user: { username: string | null; telegram_user_id: number } | null;
}

function BigStat({
  icon,
  color,
  title,
  value,
  href,
  alert,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  value: number | undefined;
  href?: string;
  alert?: boolean;
}) {
  const router = useRouter();
  return (
    <Card
      hoverable={!!href}
      onClick={href ? () => router.push(href) : undefined}
      styles={{ body: { padding: "18px 20px" } }}
      style={alert ? { borderColor: "#FF4D4F", background: "#FFF1F0" } : undefined}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 20,
            color,
            background: `${color}14`,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div style={{ lineHeight: 1.25, flex: 1 }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: alert ? "#CF1322" : "#0f172a" }}>
            {value ?? "—"}
          </div>
          <div style={{ fontSize: 12.5, color: "#64748b" }}>{title}</div>
        </div>
        {href && <RightOutlined style={{ color: "#cbd5e1", fontSize: 12 }} />}
      </div>
    </Card>
  );
}

const FUNNEL_STAGES: Array<[keyof Overview["funnel"], string, string]> = [
  ["conversations", "会话", "#2F54EB"],
  ["leads", "产生线索", "#722ED1"],
  ["leads_high", "高意向", "#F5222D"],
  ["leads_synced", "已同步 CRM", "#52C41A"],
  ["leads_won", "已成交", "#237804"],
];

function Funnel({ data }: { data: Overview["funnel"] }) {
  const base = Math.max(1, data.conversations);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {FUNNEL_STAGES.map(([key, label, color], i) => {
        const value = data[key];
        const prev = i === 0 ? null : data[FUNNEL_STAGES[i - 1][0]];
        const rate = prev ? (prev > 0 ? Math.round((value / prev) * 100) : 0) : null;
        return (
          <div key={key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 84, fontSize: 12.5, color: "#64748b", textAlign: "right" }}>
              {label}
            </div>
            <div style={{ flex: 1, background: "#f1f5f9", borderRadius: 6, height: 26 }}>
              <div
                style={{
                  width: `${Math.max(3, (value / base) * 100)}%`,
                  height: "100%",
                  borderRadius: 6,
                  background: color,
                  opacity: 0.85,
                  display: "flex",
                  alignItems: "center",
                  paddingLeft: 10,
                  color: "#fff",
                  fontSize: 12.5,
                  fontWeight: 600,
                  minWidth: 30,
                }}
              >
                {value}
              </div>
            </div>
            <div style={{ width: 52, fontSize: 11.5, color: "#94a3b8" }}>
              {rate !== null ? `${rate}%` : ""}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Trend({ data }: { data: Overview["trend"] }) {
  const days = data.slice(-14);
  const max = Math.max(1, ...days.map((d) => Math.max(d.conversations, d.leads)));
  if (days.length === 0)
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 110 }}>
        {days.map((d) => (
          <div
            key={d.day}
            title={`${d.day}：${d.conversations} 会话 / ${d.leads} 线索`}
            style={{ flex: 1, display: "flex", alignItems: "flex-end", gap: 2, height: "100%" }}
          >
            <div
              style={{
                flex: 1,
                height: `${Math.max(4, (d.conversations / max) * 100)}%`,
                background: "#ADC6FF",
                borderRadius: 3,
              }}
            />
            <div
              style={{
                flex: 1,
                height: `${Math.max(4, (d.leads / max) * 100)}%`,
                background: "#722ED1",
                borderRadius: 3,
              }}
            />
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        {days.map((d) => (
          <div key={d.day} style={{ flex: 1, fontSize: 10, color: "#94a3b8", textAlign: "center" }}>
            {d.day.slice(5)}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 12, color: "#64748b" }}>
        <span>
          <span style={{ display: "inline-block", width: 10, height: 10, background: "#ADC6FF", borderRadius: 2, marginRight: 5 }} />
          会话
        </span>
        <span>
          <span style={{ display: "inline-block", width: 10, height: 10, background: "#722ED1", borderRadius: 2, marginRight: 5 }} />
          新线索
        </span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [hotLeads, setHotLeads] = useState<HotLead[]>([]);
  const [setup, setSetup] = useState<SetupStatus | null>(null);

  useEffect(() => {
    const tz = -new Date().getTimezoneOffset();
    api.get<Overview>(`/api/metrics/overview?tz_offset_minutes=${tz}`).then(setOverview);
    api.get<{ items: Gap[] }>("/api/metrics/knowledge-gaps").then((d) => setGaps(d.items));
    api.get<SetupStatus>("/api/settings/setup-status").then(setSetup);
    api
      .get<{ items: HotLead[] }>("/api/leads?grade=high&sort=recent")
      .then((d) => setHotLeads(d.items.slice(0, 6)));
  }, []);

  return (
    <div>
      <PageHeader title="概览" subtitle={`获客漏斗与近 ${overview?.window_days ?? 14} 天趋势`} />
      {setup && Object.values(setup).some((v) => !v) && <SetupCard status={setup} />}
      <Row gutter={[16, 16]}>
        <Col xs={12} xl={6}>
          <BigStat
            icon={<MessageOutlined />}
            color="#2F54EB"
            title="今日新会话"
            value={overview?.today.conversations}
            href="/conversations"
          />
        </Col>
        <Col xs={12} xl={6}>
          <BigStat
            icon={<FunnelPlotOutlined />}
            color="#722ED1"
            title="今日新线索"
            value={overview?.today.leads}
            href="/leads"
          />
        </Col>
        <Col xs={12} xl={6}>
          <BigStat
            icon={<FireOutlined />}
            color="#F5222D"
            title={`高意向线索（近 ${overview?.window_days ?? 14} 天）`}
            value={overview?.funnel.leads_high}
            href="/leads?grade=high"
          />
        </Col>
        <Col xs={12} xl={6}>
          <BigStat
            icon={<UserSwitchOutlined />}
            color="#FA541C"
            title="待人工接管"
            value={overview?.pending_handoffs}
            href="/conversations?status=handoff_pending"
            alert={(overview?.pending_handoffs ?? 0) > 0}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card title={`转化漏斗（近 ${overview?.window_days ?? 14} 天）`}>
            {overview ? <Funnel data={overview.funnel} /> : null}
            <div style={{ marginTop: 14, fontSize: 12, color: "#94a3b8" }}>
              AI 自动回复 {overview?.auto_replies ?? "—"} 条 · 安全拒答 {overview?.refused ?? "—"} 条
            </div>
          </Card>
          <Card title="每日 会话 / 新线索" style={{ marginTop: 16 }}>
            {overview ? <Trend data={overview.trend} /> : null}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card
            title="最新高意向线索"
            extra={
              <Link href="/leads?grade=high" style={{ fontSize: 12 }}>
                全部 <RightOutlined style={{ fontSize: 10 }} />
              </Link>
            }
            styles={{ body: { padding: hotLeads.length ? "4px 0" : undefined } }}
          >
            {hotLeads.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无高意向线索——对话中出现购买意图后自动生成"
              />
            ) : (
              hotLeads.map((l) => {
                const name =
                  l.company ?? l.name ?? (l.user?.username ? `@${l.user.username}` : `线索 #${l.id}`);
                return (
                  <div
                    key={l.id}
                    onClick={() => router.push(`/leads?id=${l.id}`)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "10px 20px",
                      cursor: "pointer",
                      borderBottom: "1px solid #f8fafc",
                    }}
                  >
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 10,
                        flexShrink: 0,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#fff",
                        fontWeight: 600,
                        background: avatarColor(l.user?.telegram_user_id ?? l.id),
                      }}
                    >
                      {initialOf(name)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0, lineHeight: 1.35 }}>
                      <div style={{ fontWeight: 570, fontSize: 13.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {name}
                      </div>
                      <div style={{ fontSize: 12, color: "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {(l.score_reasons ?? [])
                          .slice(0, 2)
                          .map((r) => SCORE_REASON[r]?.replace(/\s[+−]\d+$/, "") ?? r)
                          .join(" · ") || l.requirement || "—"}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <div style={{ fontWeight: 700, color: "#F5222D", fontSize: 16 }}>{l.score}</div>
                      <div style={{ fontSize: 11, color: "#cbd5e1" }}>{fromNow(l.updated_at)}</div>
                    </div>
                  </div>
                );
              })
            )}
          </Card>
          <Card
            title="渠道来源"
            extra={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                深链 t.me/机器人?start=渠道名 自动归因
              </Typography.Text>
            }
            style={{ marginTop: 16 }}
          >
            {(overview?.channels ?? []).length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
            ) : (
              <Table
                rowKey={(r) => r.channel ?? "__direct__"}
                dataSource={overview?.channels ?? []}
                size="small"
                pagination={false}
                columns={[
                  {
                    title: "渠道",
                    dataIndex: "channel",
                    render: (c: string | null) =>
                      c ?? <span style={{ color: "#94a3b8" }}>直接进入</span>,
                  },
                  { title: "会话", dataIndex: "conversations", width: 70, align: "right" },
                  { title: "线索", dataIndex: "leads", width: 70, align: "right" },
                  {
                    title: "高意向",
                    dataIndex: "leads_high",
                    width: 80,
                    align: "right",
                    render: (v: number) =>
                      v > 0 ? <span style={{ color: "#F5222D", fontWeight: 600 }}>{v}</span> : v,
                  },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Card
        title="知识库缺口"
        extra={
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            最近被拒答的用户问题——补充对应文档可提高自动解决率
          </Typography.Text>
        }
        style={{ marginTop: 16 }}
      >
        <Table<Gap>
          rowKey={(g) => `${g.conversation_id}-${g.refused_at}`}
          dataSource={gaps}
          size="small"
          pagination={{ pageSize: 8, hideOnSinglePage: true }}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无拒答记录" />,
          }}
          columns={[
            {
              title: "用户问题",
              dataIndex: "question",
              render: (q: string | null, row) => (
                <Link href={`/conversations?id=${row.conversation_id}`}>{q ?? "（未知）"}</Link>
              ),
            },
            { title: "时间", dataIndex: "refused_at", width: 120, render: fromNow },
          ]}
        />
      </Card>
    </div>
  );
}
