"use client";
// 会话工作台：三栏收件箱布局（列表 / 聊天流 / 客户画像+线索），一屏完成 扫→判断→接管→回复。
// URL 同步 ?id= 与 ?status=（可分享、可从概览直达）；列表 15s / 当前会话 5s 轮询。
import {
  FileTextOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  App,
  Avatar,
  Button,
  Collapse,
  Descriptions,
  Empty,
  Input,
  Popconfirm,
  Progress,
  Spin,
  Tag,
  Timeline,
  Typography,
} from "antd";
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

// ---------- 类型 ----------

interface ConvRow {
  id: number;
  status: string;
  user: { username: string | null; first_name: string | null; telegram_user_id: number };
  lead_grade: string | null;
  lead_score: number | null;
  last_message: string | null;
  last_message_at: string | null;
}

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

const STATUS_CHIPS: Array<[string | undefined, string]> = [
  [undefined, "全部"],
  ["handoff_pending", "待接管"],
  ["ai_active", "AI 接待"],
  ["human_active", "人工"],
  ["closed", "已关闭"],
];

const STATUS_DOT: Record<string, string> = {
  ai_active: "#52C41A",
  handoff_pending: "#FAAD14",
  human_active: "#1677FF",
  closed: "#d9d9d9",
};

// ---------- 聊天气泡（原详情页迁入） ----------

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

// ---------- 页面 ----------

export default function ConversationsWorkbench() {
  const { message } = App.useApp();
  const [rows, setRows] = useState<ConvRow[]>([]);
  const [total, setTotal] = useState(0);
  const [pagesLoaded, setPagesLoaded] = useState(1);
  const [listLoading, setListLoading] = useState(true);
  const [status, setStatus] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastMsgCount = useRef(0);
  const initialized = useRef(false);

  // 初始：从 URL 读 ?id= 与 ?status=
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    const st = params.get("status");
    if (id) setSelectedId(Number(id));
    if (st) setStatus(st);
    initialized.current = true;
  }, []);

  const syncUrl = (id: number | null, st: string | undefined) => {
    const params = new URLSearchParams();
    if (id) params.set("id", String(id));
    if (st) params.set("status", st);
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/conversations?${qs}` : "/conversations");
  };

  // 列表加载：page 1..pagesLoaded 合并（轮询保持已加载深度）
  const loadList = useCallback(
    async (silent = false) => {
      if (!silent) setListLoading(true);
      try {
        const all: ConvRow[] = [];
        let totalCount = 0;
        for (let p = 1; p <= pagesLoaded; p++) {
          const params = new URLSearchParams({ page: String(p) });
          if (status) params.set("status", status);
          if (q) params.set("q", q);
          const data = await api.get<{ items: ConvRow[]; total: number }>(
            `/api/conversations?${params}`,
          );
          totalCount = data.total;
          all.push(...data.items);
          if (data.items.length < 20) break;
        }
        setRows(all);
        setTotal(totalCount);
      } finally {
        if (!silent) setListLoading(false);
      }
    },
    [pagesLoaded, status, q],
  );

  useEffect(() => {
    if (!initialized.current) return;
    loadList();
    const timer = setInterval(() => loadList(true), 15_000);
    return () => clearInterval(timer);
  }, [loadList]);

  // 详情加载 + 5s 轮询
  const loadDetail = useCallback(async () => {
    if (selectedId == null) return;
    const data = await api.get<Detail>(`/api/conversations/${selectedId}`);
    setDetail(data);
  }, [selectedId]);

  useEffect(() => {
    setDetail(null);
    lastMsgCount.current = 0;
    if (selectedId == null) return;
    loadDetail();
    const timer = setInterval(loadDetail, 5_000);
    return () => clearInterval(timer);
  }, [selectedId, loadDetail]);

  // 新消息到达时滚到底部
  useEffect(() => {
    const count = detail?.messages.length ?? 0;
    if (count > 0 && count !== lastMsgCount.current) {
      lastMsgCount.current = count;
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 60);
    }
  }, [detail]);

  const select = (id: number) => {
    setSelectedId(id);
    syncUrl(id, status);
  };

  const changeStatus = (st: string | undefined) => {
    setStatus(st);
    setPagesLoaded(1);
    syncUrl(selectedId, st);
  };

  const action = async (path: string, ok: string) => {
    try {
      await api.post(path);
      message.success(ok);
      await Promise.all([loadDetail(), loadList(true)]);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "操作失败");
    }
  };

  const send = async () => {
    if (!text.trim() || selectedId == null) return;
    setSending(true);
    try {
      await api.post(`/api/conversations/${selectedId}/messages`, { text });
      setText("");
      await loadDetail();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "发送失败");
    } finally {
      setSending(false);
    }
  };

  const conv = detail?.conversation;
  const userName = detail ? displayName(detail.user) : "";
  const userColor = detail ? avatarColor(detail.user.telegram_user_id) : "#ccc";
  const lead = detail?.lead;
  const score = Number(lead?.score ?? 0);
  const grade = String(lead?.grade ?? "low");

  const panelBorder = "1px solid #e2e8f0";

  return (
    <div
      style={{
        display: "flex",
        height: "calc(100vh - 90px)",
        background: "#fff",
        border: panelBorder,
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: "0 1px 3px rgba(15,23,42,0.05)",
      }}
    >
      {/* ---------- 左栏：会话列表 ---------- */}
      <div
        style={{
          width: 296,
          flexShrink: 0,
          borderRight: panelBorder,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <div style={{ padding: "12px 12px 8px", borderBottom: panelBorder }}>
          <Input.Search
            placeholder="搜索用户 / 消息内容"
            allowClear
            size="small"
            onSearch={(v) => {
              setQ(v);
              setPagesLoaded(1);
            }}
          />
          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
            {STATUS_CHIPS.map(([value, label]) => (
              <Tag.CheckableTag
                key={label}
                checked={status === value}
                onChange={() => changeStatus(value)}
                style={{ fontSize: 12, userSelect: "none" }}
              >
                {label}
              </Tag.CheckableTag>
            ))}
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {listLoading && rows.length === 0 ? (
            <div style={{ textAlign: "center", paddingTop: 60 }}>
              <Spin />
            </div>
          ) : rows.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无会话"
              style={{ marginTop: 60 }}
            />
          ) : (
            rows.map((row) => {
              const name = displayName(row.user);
              const active = row.id === selectedId;
              return (
                <div
                  key={row.id}
                  onClick={() => select(row.id)}
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "10px 12px",
                    cursor: "pointer",
                    background: active ? "#EEF2FF" : undefined,
                    borderLeft: active ? "3px solid #2F54EB" : "3px solid transparent",
                    borderBottom: "1px solid #f8fafc",
                  }}
                >
                  <div style={{ position: "relative", flexShrink: 0 }}>
                    <Avatar size={38} style={{ background: avatarColor(row.user.telegram_user_id) }}>
                      {initialOf(name)}
                    </Avatar>
                    <span
                      style={{
                        position: "absolute",
                        right: -1,
                        bottom: -1,
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background: STATUS_DOT[row.status] ?? "#d9d9d9",
                        border: "2px solid #fff",
                      }}
                    />
                  </div>
                  <div style={{ flex: 1, minWidth: 0, lineHeight: 1.4 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                      <span
                        style={{
                          fontWeight: 570,
                          fontSize: 13,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {name}
                      </span>
                      <span style={{ fontSize: 11, color: "#cbd5e1", flexShrink: 0 }}>
                        {fromNow(row.last_message_at)}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: row.status === "handoff_pending" ? "#D46B08" : "#94a3b8",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {row.status === "handoff_pending" && "⚠ 等待接管 · "}
                      {row.last_message ?? "—"}
                    </div>
                    {row.lead_grade && (
                      <Tag
                        color={GRADE[row.lead_grade]?.color}
                        style={{ fontSize: 11, lineHeight: "16px", marginTop: 2 }}
                      >
                        {GRADE[row.lead_grade]?.label} {row.lead_score}
                      </Tag>
                    )}
                  </div>
                </div>
              );
            })
          )}
          {rows.length < total && (
            <div style={{ textAlign: "center", padding: 10 }}>
              <Button size="small" type="text" onClick={() => setPagesLoaded((p) => p + 1)}>
                加载更多（共 {total} 个）
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* ---------- 中栏：聊天 ---------- */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        {selectedId == null ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="从左侧选择一个会话" />
          </div>
        ) : detail == null ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Spin />
          </div>
        ) : (
          <>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "10px 16px",
                borderBottom: panelBorder,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <Avatar size={34} style={{ background: userColor }}>
                  {initialOf(userName)}
                </Avatar>
                <div style={{ lineHeight: 1.25, minWidth: 0 }}>
                  <Typography.Text strong style={{ fontSize: 14.5 }}>
                    {userName}
                  </Typography.Text>
                  <div style={{ fontSize: 11.5, color: "#94a3b8" }}>
                    会话 #{conv!.id} · Telegram {detail.user.telegram_user_id}
                  </div>
                </div>
                <Tag color={CONV_STATUS[conv!.status]?.color} style={{ marginLeft: 4 }}>
                  {CONV_STATUS[conv!.status]?.label ?? conv!.status}
                </Tag>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                {conv!.status !== "human_active" && conv!.status !== "closed" && (
                  <Popconfirm
                    title="接管后 AI 将停止自动回复，由你直接对话"
                    onConfirm={() =>
                      action(`/api/conversations/${selectedId}/handoff`, "已接管，AI 已静默")
                    }
                  >
                    <Button type="primary" size="small">
                      接管会话
                    </Button>
                  </Popconfirm>
                )}
                {(conv!.status === "human_active" || conv!.status === "handoff_pending") && (
                  <Button
                    size="small"
                    onClick={() =>
                      action(`/api/conversations/${selectedId}/resume-ai`, "已恢复 AI 接待")
                    }
                  >
                    恢复 AI
                  </Button>
                )}
              </div>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "18px 18px 6px", background: "#f8fafc" }}>
              {detail.messages.length === 0 ? (
                <Empty description="暂无消息" style={{ marginTop: 80 }} />
              ) : (
                detail.messages.map((m) => (
                  <Bubble key={m.id} m={m} userName={userName} userColor={userColor} />
                ))
              )}
              <div ref={bottomRef} />
            </div>
            <div style={{ padding: 12, borderTop: panelBorder }}>
              <div style={{ display: "flex", gap: 10 }}>
                <Input.TextArea
                  autoSize={{ minRows: 2, maxRows: 5 }}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    conv!.status === "human_active"
                      ? "以人工客服身份回复用户…"
                      : "发送将以人工客服身份送达（建议先接管，避免与 AI 同时回复）"
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
              <div style={{ fontSize: 11, color: "#cbd5e1", marginTop: 5 }}>
                Enter 发送 · Shift + Enter 换行 · 每 5 秒自动刷新
              </div>
            </div>
          </>
        )}
      </div>

      {/* ---------- 右栏：线索 + 接管记录 ---------- */}
      {detail && (
        <div
          style={{
            width: 304,
            flexShrink: 0,
            borderLeft: panelBorder,
            overflowY: "auto",
            padding: 16,
          }}
        >
          <Typography.Text strong style={{ fontSize: 13 }}>
            线索评分
          </Typography.Text>
          {lead ? (
            <div style={{ marginTop: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <Progress
                  type="dashboard"
                  size={84}
                  percent={Math.min(100, Math.max(0, score))}
                  format={() => <span style={{ fontSize: 20, fontWeight: 700 }}>{score}</span>}
                  strokeColor={
                    grade === "high" ? "#F5222D" : grade === "medium" ? "#FA8C16" : "#94a3b8"
                  }
                />
                <div>
                  <Tag color={GRADE[grade]?.color} style={{ fontSize: 12.5, padding: "1px 8px" }}>
                    {GRADE[grade]?.label}
                  </Tag>
                  <div style={{ fontSize: 11.5, color: "#94a3b8", marginTop: 6 }}>
                    <a href={`/leads/${lead.id}`} style={{ fontSize: 12 }}>
                      编辑线索 →
                    </a>
                  </div>
                </div>
              </div>
              {Array.isArray(lead.score_reasons) && lead.score_reasons.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  {(lead.score_reasons as string[]).map((r) => (
                    <Tag key={r} style={{ marginBottom: 5, fontSize: 11.5 }}>
                      {SCORE_REASON[r] ?? r}
                    </Tag>
                  ))}
                </div>
              )}
              <Descriptions
                column={1}
                size="small"
                style={{ marginTop: 6 }}
                colon={false}
                labelStyle={{ width: 72, color: "#94a3b8", fontSize: 12.5 }}
                contentStyle={{ fontSize: 12.5 }}
              >
                {LEAD_FIELDS.map(([key, label]) => (
                  <Descriptions.Item key={key} label={label}>
                    {lead[key] ? String(lead[key]) : <span style={{ color: "#e2e8f0" }}>—</span>}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </div>
          ) : (
            <div style={{ fontSize: 12.5, color: "#94a3b8", marginTop: 8 }}>
              对话中出现购买意图后自动生成
            </div>
          )}

          <div style={{ borderTop: "1px solid #f1f5f9", margin: "14px 0" }} />
          <Typography.Text strong style={{ fontSize: 13 }}>
            接管记录
          </Typography.Text>
          <div style={{ marginTop: 10 }}>
            {detail.handoffs.length === 0 ? (
              <div style={{ fontSize: 12.5, color: "#94a3b8" }}>暂无记录</div>
            ) : (
              <Timeline
                items={detail.handoffs.map((h) => ({
                  color: h.resolved_at ? "gray" : h.accepted_at ? "blue" : "orange",
                  children: (
                    <div style={{ fontSize: 12 }}>
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
          </div>
        </div>
      )}
    </div>
  );
}
