"use client";
// 会话详情：聊天式消息流 + RAG 来源引用 + 线索评分面板 + 接管操作，5s 自动刷新。
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  RobotOutlined,
  SendOutlined,
  SyncOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  App,
  Avatar,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Input,
  Popconfirm,
  Progress,
  Row,
  Space,
  Tag,
  Timeline,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  avatarColor,
  CONV_STATUS,
  displayName,
  fmtTime,
  fromNow,
  GRADE,
  HANDOFF_REASON,
  initialOf,
  SCORE_REASON,
} from "@/lib/ui";

interface SourceChunk {
  id: number;
  content: string;
}

interface Msg {
  id: number;
  direction: string;
  sender_type: string;
  content: string;
  answer_status: string | null;
  delivery_status: string | null;
  model_name: string | null;
  latency_ms: number | null;
  source_chunks: SourceChunk[];
  created_at: string;
}

interface Detail {
  conversation: { id: number; status: string; telegram_chat_id: number };
  user: { username: string | null; first_name: string | null; telegram_user_id: number };
  lead: Record<string, unknown> | null;
  messages: Msg[];
  handoffs: Array<{
    id: number;
    reason: string;
    requested_at: string;
    accepted_at: string | null;
    resolved_at: string | null;
  }>;
}

const LEAD_FIELDS: Array<[string, string]> = [
  ["company", "公司"],
  ["name", "姓名"],
  ["business_email", "邮箱"],
  ["requirement", "需求"],
  ["team_size", "团队规模"],
  ["budget_range", "预算"],
  ["purchase_timeline", "采购时间"],
  ["country", "国家"],
];

function Bubble({ m, userName, userColor }: { m: Msg; userName: string; userColor: string }) {
  const isUser = m.direction === "inbound";
  const isOperator = m.sender_type === "operator";
  const bubbleBg = isUser ? "#ffffff" : isOperator ? "#FFF7E6" : "#EEF2FF";
  const avatar = isUser ? (
    <Avatar size={32} style={{ background: userColor, flexShrink: 0 }}>
      {initialOf(userName)}
    </Avatar>
  ) : isOperator ? (
    <Avatar size={32} style={{ background: "#FA8C16", flexShrink: 0 }} icon={<UserOutlined />} />
  ) : (
    <Avatar size={32} style={{ background: "#2F54EB", flexShrink: 0 }} icon={<RobotOutlined />} />
  );

  return (
    <div
      style={{
        display: "flex",
        flexDirection: isUser ? "row" : "row-reverse",
        gap: 10,
        marginBottom: 14,
      }}
    >
      {avatar}
      <div style={{ maxWidth: "72%" }}>
        <div
          style={{
            fontSize: 11.5,
            color: "#94a3b8",
            marginBottom: 3,
            textAlign: isUser ? "left" : "right",
          }}
        >
          {isUser ? userName : isOperator ? "人工客服" : "AI 助手"} · {fmtTime(m.created_at)}
          {m.model_name && ` · ${m.model_name}${m.latency_ms != null ? ` ${m.latency_ms}ms` : ""}`}
        </div>
        <div
          style={{
            background: bubbleBg,
            border: "1px solid rgba(15,23,42,0.06)",
            borderRadius: isUser ? "4px 12px 12px 12px" : "12px 4px 12px 12px",
            padding: "10px 14px",
            whiteSpace: "pre-wrap",
            fontSize: 14,
            lineHeight: 1.65,
            color: "#1e293b",
            boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
          }}
        >
          {m.content}
        </div>
        <div style={{ marginTop: 4, textAlign: isUser ? "left" : "right" }}>
          {m.answer_status === "refused" && <Tag color="warning">安全拒答</Tag>}
          {m.answer_status === "handoff" && <Tag color="orange">已转人工</Tag>}
          {m.delivery_status === "uncertain" && <Tag color="red">投递结果不明</Tag>}
          {m.delivery_status === "failed" && <Tag color="red">发送失败</Tag>}
        </div>
        {m.source_chunks.length > 0 && (
          <Collapse
            ghost
            size="small"
            items={[
              {
                key: "sources",
                label: (
                  <span style={{ fontSize: 12, color: "#64748b" }}>
                    <FileTextOutlined /> 回答依据（{m.source_chunks.length} 段资料）
                  </span>
                ),
                children: m.source_chunks.map((c) => (
                  <div
                    key={c.id}
                    style={{
                      borderLeft: "3px solid #2F54EB",
                      background: "#f8fafc",
                      padding: "8px 12px",
                      marginBottom: 8,
                      fontSize: 12.5,
                      color: "#475569",
                      borderRadius: "0 6px 6px 0",
                    }}
                  >
                    {c.content}
                  </div>
                )),
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}

export default function ConversationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { message } = App.useApp();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const firstLoad = useRef(true);

  const load = useCallback(async () => {
    const data = await api.get<Detail>(`/api/conversations/${id}`);
    setDetail(data);
    if (firstLoad.current) {
      firstLoad.current = false;
      setTimeout(() => bottomRef.current?.scrollIntoView(), 50);
    }
  }, [id]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const action = async (path: string, ok: string) => {
    try {
      await api.post(path);
      message.success(ok);
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "操作失败");
    }
  };

  const send = async () => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await api.post(`/api/conversations/${id}/messages`, { text });
      setText("");
      await load();
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "发送失败");
    } finally {
      setSending(false);
    }
  };

  if (!detail) return null;
  const { conversation, user, lead } = detail;
  const userName = displayName(user);
  const userColor = avatarColor(user.telegram_user_id);
  const status = CONV_STATUS[conversation.status];
  const score = Number(lead?.score ?? 0);
  const grade = String(lead?.grade ?? "low");

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
        <Space size="middle">
          <Link href="/conversations">
            <Button icon={<ArrowLeftOutlined />} type="text">
              返回
            </Button>
          </Link>
          <Avatar size={40} style={{ background: userColor }}>
            {initialOf(userName)}
          </Avatar>
          <div style={{ lineHeight: 1.3 }}>
            <Typography.Text strong style={{ fontSize: 16 }}>
              {userName}
            </Typography.Text>
            <div style={{ fontSize: 12, color: "#94a3b8" }}>
              Telegram ID {user.telegram_user_id} · 会话 #{conversation.id}
            </div>
          </div>
          <Tag color={status?.color} style={{ fontSize: 13, padding: "2px 10px" }}>
            {status?.label ?? conversation.status}
          </Tag>
        </Space>
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            <SyncOutlined spin style={{ marginRight: 4 }} />
            每 5 秒自动刷新
          </Typography.Text>
          {conversation.status !== "human_active" && conversation.status !== "closed" && (
            <Popconfirm
              title="接管后 AI 将停止自动回复，由你直接对话"
              onConfirm={() => action(`/api/conversations/${id}/handoff`, "已接管，AI 已静默")}
            >
              <Button type="primary">接管会话</Button>
            </Popconfirm>
          )}
          {(conversation.status === "human_active" || conversation.status === "handoff_pending") && (
            <Button onClick={() => action(`/api/conversations/${id}/resume-ai`, "已恢复 AI 接待")}>
              恢复 AI
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={16}>
        <Col xs={24} lg={16}>
          <Card styles={{ body: { padding: 0 } }}>
            <div style={{ height: "58vh", overflowY: "auto", padding: "20px 20px 8px", background: "#f8fafc" }}>
              {detail.messages.length === 0 ? (
                <Empty description="暂无消息" style={{ marginTop: 80 }} />
              ) : (
                detail.messages.map((m) => (
                  <Bubble key={m.id} m={m} userName={userName} userColor={userColor} />
                ))
              )}
              <div ref={bottomRef} />
            </div>
            <div style={{ padding: 14, borderTop: "1px solid #f1f5f9" }}>
              <div style={{ display: "flex", gap: 10 }}>
                <Input.TextArea
                  autoSize={{ minRows: 2, maxRows: 5 }}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    conversation.status === "human_active"
                      ? "以人工客服身份回复用户…"
                      : "发送消息将以人工客服身份送达（建议先接管，避免与 AI 同时回复）"
                  }
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                />
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  loading={sending}
                  onClick={send}
                  style={{ height: "auto" }}
                >
                  发送
                </Button>
              </div>
              <div style={{ fontSize: 11.5, color: "#cbd5e1", marginTop: 6 }}>
                Enter 发送 · Shift + Enter 换行
              </div>
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card
            title="线索评分"
            size="small"
            extra={
              lead && (
                <Link href={`/leads/${lead.id}`} style={{ fontSize: 12 }}>
                  编辑线索
                </Link>
              )
            }
          >
            {lead ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <Progress
                    type="dashboard"
                    size={92}
                    percent={Math.min(100, Math.max(0, score))}
                    format={() => <span style={{ fontSize: 22, fontWeight: 700 }}>{score}</span>}
                    strokeColor={grade === "high" ? "#F5222D" : grade === "medium" ? "#FA8C16" : "#94a3b8"}
                  />
                  <div>
                    <Tag color={GRADE[grade]?.color} style={{ fontSize: 13, padding: "2px 10px" }}>
                      {GRADE[grade]?.label}
                    </Tag>
                    <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>
                      60 分及以上为高意向
                    </div>
                  </div>
                </div>
                {Array.isArray(lead.score_reasons) && lead.score_reasons.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    {(lead.score_reasons as string[]).map((r) => (
                      <Tag key={r} style={{ marginBottom: 6 }}>
                        {SCORE_REASON[r] ?? r}
                      </Tag>
                    ))}
                  </div>
                )}
                <Descriptions column={1} size="small" style={{ marginTop: 8 }} colon={false}
                  labelStyle={{ width: 76, color: "#94a3b8" }}>
                  {LEAD_FIELDS.map(([key, label]) => (
                    <Descriptions.Item key={key} label={label}>
                      {lead[key] ? String(lead[key]) : <span style={{ color: "#e2e8f0" }}>—</span>}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="对话中出现购买意图后自动生成" />
            )}
          </Card>

          <Card title="接管记录" size="small" style={{ marginTop: 16 }}>
            {detail.handoffs.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无记录" />
            ) : (
              <Timeline
                items={detail.handoffs.map((h) => ({
                  color: h.resolved_at ? "gray" : h.accepted_at ? "blue" : "orange",
                  children: (
                    <div style={{ fontSize: 12.5 }}>
                      <div style={{ fontWeight: 550 }}>{HANDOFF_REASON[h.reason] ?? h.reason}</div>
                      <div style={{ color: "#94a3b8" }}>
                        {fromNow(h.requested_at)}
                        {h.resolved_at ? " · 已处理" : h.accepted_at ? " · 接管中" : " · 待接管"}
                      </div>
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
