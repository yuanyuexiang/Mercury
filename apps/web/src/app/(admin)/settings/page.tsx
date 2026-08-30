"use client";
// 模型供应商：增删改、激活（热切换）、连接测试；key 加密存储、脱敏展示。
import {
  ApiOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  App,
  AutoComplete,
  Badge,
  Button,
  Card,
  Checkbox,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api, ApiError } from "@/lib/api";
import { PROVIDER_PRESETS, type ProviderPreset } from "@/lib/providers";
import { fromNow } from "@/lib/ui";

interface Provider {
  id: number;
  name: string;
  base_url: string;
  api_key_masked: string;
  chat_model: string;
  fallback_model: string | null;
  embed_model: string | null;
  supports_json_schema: boolean;
  is_active: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
}

interface CostRow {
  day: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
}

function UsageCard() {
  const [costs, setCosts] = useState<CostRow[]>([]);

  useEffect(() => {
    api.get<{ items: CostRow[] }>("/api/metrics/costs").then((d) => setCosts(d.items));
  }, []);

  const byDay = new Map<string, number>();
  for (const row of costs) {
    byDay.set(row.day, (byDay.get(row.day) ?? 0) + row.prompt_tokens + row.completion_tokens);
  }
  const days = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-14);
  const maxTokens = Math.max(1, ...days.map(([, v]) => v));

  return (
    <Card
      title="模型用量（Token / 日，近 14 天）"
      style={{ marginTop: 16 }}
      styles={{ body: { paddingTop: 12 } }}
    >
      {days.length === 0 ? (
        <Typography.Text type="secondary">暂无调用记录</Typography.Text>
      ) : (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 120 }}>
          {days.map(([day, tokens]) => (
            <div
              key={day}
              title={`${day}：${tokens.toLocaleString()} tokens`}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                justifyContent: "flex-end",
                height: "100%",
              }}
            >
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
          ))}
        </div>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  const { message } = App.useApp();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [preset, setPreset] = useState<ProviderPreset | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchModels = async () => {
    const base_url = form.getFieldValue("base_url");
    const api_key = form.getFieldValue("api_key");
    if (!base_url || (!api_key && !editing)) {
      message.info("请先填写 Base URL 和 API Key");
      return;
    }
    setFetchingModels(true);
    try {
      const body = editing
        ? { provider_id: editing.id, api_key: api_key || undefined }
        : { base_url, api_key };
      const data = await api.post<{ items: string[] }>("/api/settings/llm-providers/models", body);
      setModels(data.items);
      message.success(`拉取到 ${data.items.length} 个模型，输入框已变为可搜索下拉`);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "拉取失败");
    } finally {
      setFetchingModels(false);
    }
  };

  const load = useCallback(async () => {
    const data = await api.get<{ items: Provider[] }>("/api/settings/llm-providers");
    setProviders(data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openModal = (provider: Provider | null) => {
    setEditing(provider);
    setPreset(null);
    setModels([]);
    setAdvancedOpen(false);
    form.resetFields();
    if (provider) form.setFieldsValue({ ...provider, api_key: "" });
    setModalOpen(true);
  };

  const submit = async (values: Record<string, unknown>) => {
    try {
      if (editing) {
        if (!values.api_key) delete values.api_key; // 留空保留原密文
        await api.patch(`/api/settings/llm-providers/${editing.id}`, values);
      } else {
        await api.post("/api/settings/llm-providers", values);
      }
      message.success("已保存");
      setModalOpen(false);
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    }
  };

  const activate = async (id: number) => {
    try {
      await api.post(`/api/settings/llm-providers/${id}/activate`);
      message.success("已激活，即时生效（无需重启）");
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "激活失败");
    }
  };

  const test = async (id: number) => {
    setTesting(id);
    try {
      const result = await api.post<{ ok: boolean; latency_ms: number; error: string | null }>(
        `/api/settings/llm-providers/${id}/test`,
      );
      if (result.ok) message.success(`连接正常，延迟 ${result.latency_ms}ms`);
      else message.error(`连接失败：${result.error}`);
      await load();
    } finally {
      setTesting(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="模型配置"
        subtitle="选择 AI 服务商、粘贴密钥并激活——机器人就用它来回答问题；随时切换、即时生效"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
            新增供应商
          </Button>
        }
      />
      <Card styles={{ body: { paddingTop: 8 } }}>
        <Table<Provider>
          rowKey="id"
          dataSource={providers}
          pagination={false}
          locale={{
            emptyText: (
              <div style={{ padding: "32px 0", textAlign: "center", color: "#94a3b8" }}>
                <ApiOutlined style={{ fontSize: 32, marginBottom: 12, display: "block", margin: "0 auto 12px" }} />
                还没有配置模型供应商——新增并激活后，机器人即可开始回答
              </div>
            ),
          }}
          columns={[
            {
              title: "供应商",
              width: 200,
              render: (_, p) => (
                <Space>
                  {p.is_active ? <Badge status="processing" /> : <Badge status="default" />}
                  <div style={{ lineHeight: 1.3 }}>
                    <div style={{ fontWeight: 550 }}>
                      {p.name}
                      {p.is_active && (
                        <Tag color="green" style={{ marginLeft: 8 }}>
                          使用中
                        </Tag>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: "#94a3b8" }}>{p.base_url}</div>
                  </div>
                </Space>
              ),
            },
            { title: "对话模型", dataIndex: "chat_model", width: 160 },
            {
              title: "知识库检索模型",
              dataIndex: "embed_model",
              width: 180,
              render: (v: string | null) =>
                v ?? <span style={{ color: "#cbd5e1" }}>未配置</span>,
            },
            { title: "密钥", dataIndex: "api_key_masked", width: 90 },
            {
              title: "连接",
              width: 130,
              render: (_, p) =>
                p.last_test_at ? (
                  p.last_test_ok ? (
                    <span style={{ color: "#52C41A", fontSize: 12.5 }}>
                      <CheckCircleFilled /> 正常 · {fromNow(p.last_test_at)}
                    </span>
                  ) : (
                    <span style={{ color: "#F5222D", fontSize: 12.5 }}>
                      <CloseCircleFilled /> 失败 · {fromNow(p.last_test_at)}
                    </span>
                  )
                ) : (
                  <span style={{ color: "#cbd5e1", fontSize: 12.5 }}>未测试</span>
                ),
            },
            {
              title: "操作",
              width: 250,
              render: (_, p) => (
                <Space>
                  {!p.is_active && (
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<ThunderboltOutlined />}
                      onClick={() => activate(p.id)}
                    >
                      激活
                    </Button>
                  )}
                  <Button size="small" loading={testing === p.id} onClick={() => test(p.id)}>
                    测试
                  </Button>
                  <Button size="small" type="text" onClick={() => openModal(p)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="确认删除该供应商？"
                    onConfirm={async () => {
                      try {
                        await api.del(`/api/settings/llm-providers/${p.id}`);
                        await load();
                      } catch (e) {
                        message.error(e instanceof ApiError ? e.message : "删除失败");
                      }
                    }}
                  >
                    <Button size="small" type="text" danger disabled={p.is_active}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 4 }}>
          Embedding 模型须为 1536 维（如 text-embedding-3-small）；更换 Embedding
          模型后需在「知识库」对所有文档重建索引。
        </Typography.Paragraph>
      </Card>

      <UsageCard />

      <Modal
        title={editing ? `编辑：${editing.name}` : "新增供应商"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="保存"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={submit}
          // 必填项（如 Base URL）藏在高级选项里：校验失败时自动展开，避免报错看不见
          onFinishFailed={() => setAdvancedOpen(true)}
        >
          {!editing && (
            <Form.Item label="选择 AI 服务商">
              <Select
                placeholder="选一家，剩下的自动填好——只需再贴 API Key"
                options={PROVIDER_PRESETS.map((p, i) => ({ value: i, label: p.label }))}
                onChange={(i: number) => {
                  const p = PROVIDER_PRESETS[i];
                  setPreset(p);
                  setModels([]);
                  form.setFieldsValue({
                    name: p.label.split("（")[0],
                    base_url: p.base_url,
                    chat_model: p.chat_model,
                    embed_model: p.embed_model,
                    supports_json_schema: p.supports_json_schema,
                  });
                }}
              />
              {preset && (
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 6 }}>
                  {preset.note} ·{" "}
                  <a href={preset.keyUrl} target="_blank" rel="noreferrer">
                    获取 API Key →
                  </a>
                </div>
              )}
            </Form.Item>
          )}
          <Form.Item
            name="api_key"
            label={editing ? "API Key（留空保留原值）" : "API Key"}
            rules={editing ? [] : [{ required: true, message: "请输入 API Key" }]}
          >
            <Input.Password placeholder="sk-…" />
          </Form.Item>
          <Form.Item
            name="chat_model"
            label={
              <Space size={8}>
                对话模型
                <Button
                  size="small"
                  type="link"
                  loading={fetchingModels}
                  onClick={fetchModels}
                  style={{ padding: 0 }}
                >
                  拉取模型列表
                </Button>
              </Space>
            }
            rules={[{ required: true, message: "请输入模型名" }]}
          >
            <AutoComplete
              options={models.map((m) => ({ value: m }))}
              placeholder="选模板已自动填；贴上 Key 后可拉取列表选择"
              filterOption={(input, option) =>
                (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>

          <Collapse
            ghost
            activeKey={advancedOpen ? ["advanced"] : []}
            onChange={(keys) => setAdvancedOpen(keys.includes("advanced"))}
            items={[
              {
                key: "advanced",
                forceRender: true,
                label: (
                  <span style={{ fontSize: 13, color: "#64748b" }}>
                    高级选项（选了服务商模板就不用动）
                  </span>
                ),
                children: (
                  <>
                    <Form.Item
                      name="name"
                      label="显示名称"
                      rules={[{ required: true, message: "请输入名称" }]}
                    >
                      <Input placeholder="如 DeepSeek 官方" />
                    </Form.Item>
                    <Form.Item
                      name="base_url"
                      label="接口地址（OpenAI 兼容 Base URL）"
                      rules={[{ required: true, message: "请输入接口地址" }]}
                    >
                      <Input placeholder="https://api.deepseek.com/v1" />
                    </Form.Item>
                    <Form.Item name="fallback_model" label="备用模型（可选，主模型故障时顶上）">
                      <AutoComplete
                        options={models.map((m) => ({ value: m }))}
                        placeholder="留空 = 不用备用"
                        filterOption={(input, option) =>
                          (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                        }
                      />
                    </Form.Item>
                    <Form.Item
                      name="embed_model"
                      label="知识库检索模型（机器人靠它搜索知识库；OpenAI 填 text-embedding-3-small）"
                    >
                      <AutoComplete
                        options={models.map((m) => ({ value: m }))}
                        placeholder="留空则知识库检索走系统默认配置"
                        filterOption={(input, option) =>
                          (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                        }
                      />
                    </Form.Item>
                    <Form.Item name="supports_json_schema" valuePropName="checked" initialValue={true}>
                      <Checkbox>支持结构化输出（选模板时已自动设置）</Checkbox>
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
    </div>
  );
}
