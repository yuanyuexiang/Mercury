"use client";
// 会话详情（技术方案 §10）：消息流 + RAG 来源 + 线索面板 + 接管/恢复 + 人工发消息，5s 轮询。
import {
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Input,
  message as antdMessage,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";

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

const LEAD_LABELS: Array<[string, string]> = [
  ["company", "公司"],
  ["name", "姓名"],
  ["country", "国家"],
  ["business_email", "邮箱"],
  ["requirement", "需求"],
  ["team_size", "团队规模"],
  ["budget_range", "预算"],
  ["purchase_timeline", "采购时间"],
];

function Bubble({ m }: { m: Msg }) {
  const mine = m.direction === "outbound";
  const bg = mine ? (m.sender_type === "operator" ? "#fff7e6" : "#e6f4ff") : "#fff";
  return (
    <div style={{ display: "flex", justifyContent: mine ? "flex-end" : "flex-start", marginBottom: 8 }}>
      <div style={{ maxWidth: "75%", background: bg, borderRadius: 8, padding: "8px 12px", border: "1px solid #eee" }}>
        <div style={{ fontSize: 12, color: "#999", marginBottom: 2 }}>
          {m.sender_type}
          {m.answer_status && <Tag style={{ marginLeft: 6 }}>{m.answer_status}</Tag>}
          {m.delivery_status === "uncertain" && <Tag color="red">投递不明</Tag>}
          {m.model_name && (
            <span style={{ marginLeft: 6 }}>
              {m.model_name}
              {m.latency_ms != null && ` · ${m.latency_ms}ms`}
            </span>
          )}
        </div>
        <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
        {m.source_chunks.length > 0 && (
          <Collapse
            ghost
            size="small"
            items={[
              {
                key: "src",
                label: `来源（${m.source_chunks.length} 段）`,
                children: m.source_chunks.map((c) => (
                  <Card key={c.id} size="small" style={{ marginBottom: 8 }}>
                    <Typography.Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                      {c.content}
                    </Typography.Paragraph>
                  </Card>
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
  const [detail, setDetail] = useState<Detail | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setDetail(await api.get<Detail>(`/api/conversations/${id}`));
  }, [id]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000); // MVP 轮询（§10）
    return () => clearInterval(timer);
  }, [load]);

  const action = async (path: string) => {
    try {
      await api.post(path);
      await load();
    } catch (e) {
      antdMessage.error(e instanceof ApiError ? e.message : "操作失败");
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
      antdMessage.error(e instanceof ApiError ? e.message : "发送失败");
    } finally {
      setSending(false);
    }
  };

  if (!detail) return null;
  const { conversation, user, lead } = detail;

  return (
    <Row gutter={16}>
      <Col span={16}>
        <Card
          title={
            <Space>
              会话 #{conversation.id}
              <Tag>{conversation.status}</Tag>
              <span style={{ fontWeight: 400 }}>
                {user.username ? `@${user.username}` : user.first_name}
              </span>
            </Space>
          }
          extra={
            <Space>
              {conversation.status !== "human_active" && conversation.status !== "closed" && (
                <Button type="primary" onClick={() => action(`/api/conversations/${id}/handoff`)}>
                  接管
                </Button>
              )}
              {(conversation.status === "human_active" ||
                conversation.status === "handoff_pending") && (
                <Button onClick={() => action(`/api/conversations/${id}/resume-ai`)}>
                  恢复 AI
                </Button>
              )}
            </Space>
          }
        >
          <div style={{ maxHeight: "60vh", overflowY: "auto", paddingRight: 8 }}>
            {detail.messages.map((m) => (
              <Bubble key={m.id} m={m} />
            ))}
            <div ref={bottomRef} />
          </div>
          <Space.Compact style={{ width: "100%", marginTop: 16 }}>
            <Input.TextArea
              rows={2}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="以人工客服身份发送消息…"
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <Button type="primary" loading={sending} onClick={send} style={{ height: "auto" }}>
              发送
            </Button>
          </Space.Compact>
        </Card>
      </Col>
      <Col span={8}>
        <Card title="线索" size="small">
          {lead ? (
            <>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="评分">
                  {String(lead.score)}（{String(lead.grade)}）
                </Descriptions.Item>
                {LEAD_LABELS.map(([key, label]) => (
                  <Descriptions.Item key={key} label={label}>
                    {lead[key] ? String(lead[key]) : "-"}
                  </Descriptions.Item>
                ))}
              </Descriptions>
              <div style={{ marginTop: 8 }}>
                {(lead.score_reasons as string[] | undefined)?.map((r) => (
                  <Tag key={r}>{r}</Tag>
                ))}
              </div>
            </>
          ) : (
            <Typography.Text type="secondary">暂无线索</Typography.Text>
          )}
        </Card>
        <Card title="接管历史" size="small" style={{ marginTop: 16 }}>
          {detail.handoffs.length === 0 && (
            <Typography.Text type="secondary">无</Typography.Text>
          )}
          {detail.handoffs.map((h) => (
            <div key={h.id} style={{ marginBottom: 8, fontSize: 12 }}>
              <Tag>{h.reason}</Tag>
              {h.requested_at}
              {h.resolved_at ? "（已解决）" : h.accepted_at ? "（接管中）" : "（待接管）"}
            </div>
          ))}
        </Card>
      </Col>
    </Row>
  );
}
