"use client";
// 线索工作台：三栏布局（列表 / 详情编辑 / 对话上下文）——看线索时直接看到聊天记录。
// ?id= 深链可分享；编辑保存自动重算评分并触发同步。
import {
  CloudSyncOutlined,
  DownloadOutlined,
  MessageOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Progress,
  Select,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { fmtTime, fromNow, GRADE, LEAD_STATUS, SCORE_REASON } from "@/lib/ui";

interface LeadRow {
  id: number;
  conversation_id: number;
  company: string | null;
  name: string | null;
  business_email: string | null;
  requirement: string | null;
  score: number;
  grade: string;
  status: string;
  source_channel: string | null;
  user: { username: string | null; telegram_user_id: number } | null;
  updated_at: string;
}

interface LeadDetail extends LeadRow {
  score_reasons: string[];
  version: number;
  external_crm_id: string | null;
  [key: string]: unknown;
}

interface ConvMsg {
  id: number;
  direction: string;
  sender_type: string;
  content: string;
  created_at: string;
}

const FIELDS: Array<[string, string, string?]> = [
  ["company", "公司"],
  ["name", "姓名"],
  ["business_email", "工作邮箱", "评分依据：企业邮箱 +15"],
  ["requirement", "需求", "评分依据：明确需求 +20"],
  ["team_size", "团队规模", "评分依据：达标 +15"],
  ["budget_range", "预算", "评分依据：提供预算 +15"],
  ["purchase_timeline", "采购时间", "评分依据：30 天内 +20"],
  ["country", "国家"],
  ["notes", "备注"],
];

const GRADE_CHIPS: Array<[string | undefined, string]> = [
  [undefined, "全部"],
  ["high", "高意向"],
  ["medium", "中意向"],
  ["low", "低意向"],
];

const displayOf = (l: LeadRow): string =>
  l.company ?? l.name ?? (l.user?.username ? `@${l.user.username}` : `线索 #${l.id}`);

const scoreColor = (grade: string): string =>
  grade === "high" ? "#F5222D" : grade === "medium" ? "#FA8C16" : "#94a3b8";

export default function LeadsWorkbench() {
  const { message } = App.useApp();
  const [rows, setRows] = useState<LeadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [pagesLoaded, setPagesLoaded] = useState(1);
  const [listLoading, setListLoading] = useState(true);
  const [grade, setGrade] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [messages, setMessages] = useState<ConvMsg[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const initialized = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    const g = params.get("grade");
    if (id) setSelectedId(Number(id));
    if (g && GRADE[g]) setGrade(g);
    initialized.current = true;
  }, []);

  const syncUrl = (id: number | null, g: string | undefined) => {
    const params = new URLSearchParams();
    if (id) params.set("id", String(id));
    if (g) params.set("grade", g);
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/leads?${qs}` : "/leads");
  };

  const loadList = useCallback(
    async (silent = false) => {
      if (!silent) setListLoading(true);
      try {
        const all: LeadRow[] = [];
        let totalCount = 0;
        for (let p = 1; p <= pagesLoaded; p++) {
          const params = new URLSearchParams({ page: String(p) });
          if (grade) params.set("grade", grade);
          if (status) params.set("status", status);
          const data = await api.get<{ items: LeadRow[]; total: number }>(`/api/leads?${params}`);
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
    [pagesLoaded, grade, status],
  );

  useEffect(() => {
    if (!initialized.current) return;
    loadList();
  }, [loadList]);

  const loadDetail = useCallback(async () => {
    if (selectedId == null) return;
    const data = await api.get<LeadDetail>(`/api/leads/${selectedId}`);
    setDetail(data);
    form.setFieldsValue(data);
    api
      .get<{ messages: ConvMsg[] }>(`/api/conversations/${data.conversation_id}`)
      .then((d) => setMessages(d.messages.slice(-15)))
      .catch(() => setMessages([]));
  }, [selectedId, form]);

  useEffect(() => {
    setDetail(null);
    setMessages(null);
    if (selectedId != null) loadDetail();
  }, [selectedId, loadDetail]);

  const select = (id: number) => {
    setSelectedId(id);
    syncUrl(id, grade);
  };

  const changeGrade = (g: string | undefined) => {
    setGrade(g);
    setPagesLoaded(1);
    syncUrl(selectedId, g);
  };

  const save = async (values: Record<string, unknown>) => {
    if (selectedId == null) return;
    setSaving(true);
    try {
      const data = await api.patch<LeadDetail>(`/api/leads/${selectedId}`, values);
      setDetail(data);
      form.setFieldsValue(data);
      message.success(`已保存，评分更新为 ${data.score}（${GRADE[data.grade]?.label}）`);
      await loadList(true);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const manualSync = async () => {
    if (selectedId == null) return;
    try {
      await api.post(`/api/leads/${selectedId}/sync`);
      message.success("已触发同步任务");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "同步失败");
    }
  };

  const exportCsv = () => {
    const params = new URLSearchParams();
    if (grade) params.set("grade", grade);
    if (status) params.set("status", status);
    const qs = params.toString();
    window.open(`/api/leads/export${qs ? `?${qs}` : ""}`, "_blank");
  };

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
      {/* ---------- 左栏：线索列表 ---------- */}
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
        <div style={{ padding: "10px 12px 8px", borderBottom: panelBorder }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {GRADE_CHIPS.map(([value, label]) => (
              <Tag.CheckableTag
                key={label}
                checked={grade === value}
                onChange={() => changeGrade(value)}
                style={{ fontSize: 12, userSelect: "none" }}
              >
                {label}
              </Tag.CheckableTag>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <Select
              allowClear
              size="small"
              placeholder="全部同步状态"
              style={{ flex: 1 }}
              value={status}
              onChange={(v) => {
                setStatus(v);
                setPagesLoaded(1);
              }}
              options={Object.entries(LEAD_STATUS).map(([value, s]) => ({
                value,
                label: s.label,
              }))}
            />
            <Button size="small" icon={<DownloadOutlined />} onClick={exportCsv} title="导出 CSV" />
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
              description="暂无线索——对话中出现购买意图后自动生成"
              style={{ marginTop: 60 }}
            />
          ) : (
            rows.map((row) => {
              const active = row.id === selectedId;
              return (
                <div
                  key={row.id}
                  onClick={() => select(row.id)}
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "center",
                    padding: "10px 12px",
                    cursor: "pointer",
                    background: active ? "#EEF2FF" : undefined,
                    borderLeft: active ? "3px solid #2F54EB" : "3px solid transparent",
                    borderBottom: "1px solid #f8fafc",
                  }}
                >
                  <div
                    style={{
                      width: 40,
                      textAlign: "center",
                      fontWeight: 700,
                      fontSize: 17,
                      color: scoreColor(row.grade),
                      flexShrink: 0,
                    }}
                  >
                    {row.score}
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
                        {displayOf(row)}
                      </span>
                      <span style={{ fontSize: 11, color: "#cbd5e1", flexShrink: 0 }}>
                        {fromNow(row.updated_at)}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "#94a3b8",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {row.requirement ?? row.business_email ?? "—"}
                    </div>
                    <div style={{ marginTop: 2 }}>
                      <Tag color={GRADE[row.grade]?.color} style={{ fontSize: 11, lineHeight: "16px" }}>
                        {GRADE[row.grade]?.label}
                      </Tag>
                      <Tag color={LEAD_STATUS[row.status]?.color} style={{ fontSize: 11, lineHeight: "16px" }}>
                        {LEAD_STATUS[row.status]?.label ?? row.status}
                      </Tag>
                    </div>
                  </div>
                </div>
              );
            })
          )}
          {rows.length < total && (
            <div style={{ textAlign: "center", padding: 10 }}>
              <Button size="small" type="text" onClick={() => setPagesLoaded((p) => p + 1)}>
                加载更多（共 {total} 条）
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* ---------- 中栏：详情编辑 ---------- */}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
        {selectedId == null ? (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="从左侧选择一条线索" />
          </div>
        ) : detail == null ? (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Spin />
          </div>
        ) : (
          <div style={{ padding: "16px 20px 24px" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 10,
                marginBottom: 14,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Typography.Text strong style={{ fontSize: 16 }}>
                  {displayOf(detail)}
                </Typography.Text>
                <Tag color={GRADE[detail.grade]?.color}>{GRADE[detail.grade]?.label}</Tag>
                {detail.source_channel && (
                  <Tag color="geekblue" style={{ fontSize: 11.5 }}>
                    渠道 {detail.source_channel}
                  </Tag>
                )}
              </div>
              <Button size="small" icon={<CloudSyncOutlined />} onClick={manualSync}>
                同步到表格
              </Button>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 6 }}>
              <Progress
                type="dashboard"
                size={96}
                percent={Math.min(100, Math.max(0, detail.score))}
                format={() => (
                  <span style={{ fontSize: 24, fontWeight: 700 }}>{detail.score}</span>
                )}
                strokeColor={scoreColor(detail.grade)}
              />
              <div style={{ flex: 1 }}>
                <div>
                  {detail.score_reasons.length === 0 ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>
                      暂无命中规则（确定性评分，非模型打分）
                    </Typography.Text>
                  ) : (
                    detail.score_reasons.map((r) => (
                      <Tag key={r} color="blue" style={{ marginBottom: 5, fontSize: 11.5 }}>
                        {SCORE_REASON[r] ?? r}
                      </Tag>
                    ))
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
                  表格：{detail.external_crm_id ? "已同步" : "未同步"} · v{detail.version} · 更新于{" "}
                  {fromNow(detail.updated_at)}
                </div>
              </div>
            </div>

            <Form form={form} layout="vertical" onFinish={save}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                  columnGap: 14,
                }}
              >
                {FIELDS.map(([key, label, hint]) => (
                  <Form.Item key={key} name={key} label={label} tooltip={hint} style={{ marginBottom: 14 }}>
                    <Input placeholder="—" />
                  </Form.Item>
                ))}
                <Form.Item name="status" label="跟进状态" style={{ marginBottom: 14 }}>
                  <Select
                    options={Object.entries(LEAD_STATUS).map(([value, s]) => ({
                      value,
                      label: s.label,
                    }))}
                  />
                </Form.Item>
              </div>
              <Button type="primary" htmlType="submit" loading={saving}>
                保存修改
              </Button>
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 12 }}>
                保存后自动重算评分并触发同步
              </Typography.Text>
            </Form>
          </div>
        )}
      </div>

      {/* ---------- 右栏：对话上下文 ---------- */}
      {detail && (
        <div
          style={{
            width: 320,
            flexShrink: 0,
            borderLeft: panelBorder,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div
            style={{
              padding: "10px 14px",
              borderBottom: panelBorder,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <Typography.Text strong style={{ fontSize: 13 }}>
              对话记录
            </Typography.Text>
            <a href={`/conversations?id=${detail.conversation_id}`}>
              <Button size="small" icon={<MessageOutlined />}>
                打开会话
              </Button>
            </a>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "12px 12px 4px", background: "#f8fafc" }}>
            {messages == null ? (
              <div style={{ textAlign: "center", paddingTop: 40 }}>
                <Spin size="small" />
              </div>
            ) : messages.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消息" style={{ marginTop: 40 }} />
            ) : (
              messages.map((m) => {
                const isUser = m.direction === "inbound";
                return (
                  <div
                    key={m.id}
                    style={{
                      display: "flex",
                      justifyContent: isUser ? "flex-start" : "flex-end",
                      marginBottom: 8,
                    }}
                  >
                    <div style={{ maxWidth: "85%" }}>
                      <div
                        style={{
                          background: isUser ? "#fff" : "#EEF2FF",
                          border: "1px solid rgba(15,23,42,0.06)",
                          borderRadius: 8,
                          padding: "6px 10px",
                          fontSize: 12.5,
                          lineHeight: 1.55,
                          color: "#1e293b",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {!isUser && (
                          <RobotOutlined style={{ fontSize: 11, color: "#2F54EB", marginRight: 4 }} />
                        )}
                        {m.content}
                      </div>
                      <div
                        style={{
                          fontSize: 10.5,
                          color: "#cbd5e1",
                          marginTop: 2,
                          textAlign: isUser ? "left" : "right",
                        }}
                      >
                        {fmtTime(m.created_at)}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
