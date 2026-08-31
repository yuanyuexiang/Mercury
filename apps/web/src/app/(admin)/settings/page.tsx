"use client";
// 模型配置（§12 双槽位）：①服务商密钥 ②对话槽 ③检索槽。
// 服务商只管 key；「谁来对话」「谁来检索」各自独立选择，可以不同家。
import {
  CheckCircleFilled,
  CloseCircleFilled,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  App,
  AutoComplete,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
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
  is_embed_active: boolean;
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

const presetFor = (p?: Provider): ProviderPreset | undefined =>
  p ? PROVIDER_PRESETS.find((x) => x.base_url === p.base_url) : undefined;

// 用途槽位卡片：选服务商 → 选模型 → 保存并生效（保存后自动做连接测试）
function RoleCard({
  role,
  providers,
  onSaved,
}: {
  role: "chat" | "embed";
  providers: Provider[];
  onSaved: () => Promise<void>;
}) {
  const { message } = App.useApp();
  const current = providers.find((p) => (role === "chat" ? p.is_active : p.is_embed_active));
  const currentModel = (role === "chat" ? current?.chat_model : current?.embed_model) ?? "";

  const [providerId, setProviderId] = useState<number | undefined>(current?.id);
  const [model, setModel] = useState<string>(currentModel);
  const [fallback, setFallback] = useState<string>(current?.fallback_model ?? "");
  const [models, setModels] = useState<string[]>([]);
  const [fetching, setFetching] = useState(false);
  const [saving, setSaving] = useState(false);

  const selected = providers.find((p) => p.id === providerId);
  const dirty =
    providerId !== current?.id ||
    model !== currentModel ||
    (role === "chat" && fallback !== (current?.fallback_model ?? ""));

  const pickProvider = (id: number) => {
    setProviderId(id);
    setModels([]);
    const preset = presetFor(providers.find((p) => p.id === id));
    const recommended = role === "chat" ? preset?.chat_model : preset?.embed_model;
    setModel(recommended || "");
  };

  const fetchModels = async () => {
    if (!providerId) return;
    setFetching(true);
    try {
      const data = await api.post<{ items: string[] }>("/api/settings/llm-providers/models", {
        provider_id: providerId,
      });
      setModels(data.items);
      message.success(`拉取到 ${data.items.length} 个模型，输入框已变为可搜索下拉`);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "拉取失败");
    } finally {
      setFetching(false);
    }
  };

  const save = async () => {
    if (!providerId || !model.trim()) {
      message.info("请先选择服务商和模型");
      return;
    }
    setSaving(true);
    try {
      await api.put(`/api/settings/llm-providers/roles/${role}`, {
        provider_id: providerId,
        model: model.trim(),
        ...(role === "chat" ? { fallback_model: fallback } : {}),
      });
      const test = await api.post<{ ok: boolean; error: string | null }>(
        `/api/settings/llm-providers/${providerId}/test`,
        {},
      );
      if (test.ok) {
        message.success("已保存并生效，连接正常");
      } else {
        message.warning(`已保存，但连接测试失败：${test.error ?? "未知错误"}`, 8);
      }
      await onSaved();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const meta =
    role === "chat"
      ? { step: "第二步", title: "对话模型", subtitle: "谁来回答客户的消息" }
      : { step: "第三步", title: "知识库检索模型", subtitle: "谁来搜索知识库（embedding）" };

  return (
    <Card
      title={
        <Space size={8}>
          <Tag color="blue" style={{ marginRight: 0 }}>
            {meta.step}
          </Tag>
          {meta.title}
          <Typography.Text type="secondary" style={{ fontSize: 12.5, fontWeight: 400 }}>
            {meta.subtitle}
          </Typography.Text>
        </Space>
      }
      styles={{ body: { paddingTop: 16 } }}
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <div>
          <div style={{ fontSize: 13, marginBottom: 6 }}>服务商</div>
          <Select
            style={{ width: "100%" }}
            placeholder={providers.length ? "选择一家服务商" : "请先在上方添加服务商"}
            disabled={!providers.length}
            value={providerId}
            onChange={pickProvider}
            options={providers.map((p) => ({ value: p.id, label: p.name }))}
          />
        </div>
        <div>
          <div style={{ fontSize: 13, marginBottom: 6 }}>
            模型{" "}
            <Button
              size="small"
              type="link"
              loading={fetching}
              disabled={!providerId}
              onClick={fetchModels}
              style={{ padding: 0 }}
            >
              拉取模型列表
            </Button>
          </div>
          <AutoComplete
            style={{ width: "100%" }}
            value={model}
            onChange={setModel}
            options={models.map((m) => ({ value: m }))}
            placeholder={
              role === "chat" ? "如 glm-4.7 / deepseek-chat" : "如 Qwen/Qwen3-Embedding-8B"
            }
            filterOption={(input, option) =>
              (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
            }
          />
        </div>
        {role === "chat" && (
          <Collapse
            ghost
            items={[
              {
                key: "fallback",
                label: (
                  <span style={{ fontSize: 12.5, color: "#64748b" }}>
                    高级：备用模型（主模型故障时顶上）
                  </span>
                ),
                children: (
                  <AutoComplete
                    style={{ width: "100%" }}
                    value={fallback}
                    onChange={setFallback}
                    options={models.map((m) => ({ value: m }))}
                    placeholder="留空 = 不用备用"
                    filterOption={(input, option) =>
                      (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                    }
                  />
                ),
              },
            ]}
          />
        )}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 12.5 }}>
            {!current && !dirty && <Typography.Text type="secondary">尚未配置</Typography.Text>}
            {current && !dirty && current.last_test_ok === true && (
              <span style={{ color: "#52C41A" }}>
                <CheckCircleFilled /> 生效中 · 连接正常 · {fromNow(current.last_test_at)}
              </span>
            )}
            {current && !dirty && current.last_test_ok === false && (
              <span style={{ color: "#F5222D" }}>
                <CloseCircleFilled /> 生效中 · 连接异常 · {fromNow(current.last_test_at)}
              </span>
            )}
            {current && !dirty && current.last_test_ok == null && (
              <Typography.Text type="secondary">生效中 · 未测试</Typography.Text>
            )}
            {dirty && <Typography.Text type="warning">修改未保存</Typography.Text>}
          </span>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={saving}
            disabled={!providerId || !model.trim() || (!dirty && !!current)}
            onClick={save}
          >
            保存并生效
          </Button>
        </div>
        {role === "embed" && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            ⚠ 更换检索模型后，需到「知识库」对所有文档重建索引（首次配置无需操作）。
            保存时会自动校验模型能否输出 1536 维向量，不合适会直接报错。
          </Typography.Text>
        )}
        {role === "chat" && selected && presetFor(selected)?.note && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            💡 {presetFor(selected)?.note}
          </Typography.Text>
        )}
      </Space>
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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [form] = Form.useForm();

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

  const test = async (id: number) => {
    setTesting(id);
    try {
      const r = await api.post<{ ok: boolean; error: string | null }>(
        `/api/settings/llm-providers/${id}/test`,
        {},
      );
      if (r.ok) message.success("连接正常");
      else message.error(`测试失败：${r.error ?? "未知错误"}`, 8);
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "测试失败");
    } finally {
      setTesting(null);
    }
  };

  const chatCurrent = providers.find((p) => p.is_active);
  const embedCurrent = providers.find((p) => p.is_embed_active);

  return (
    <div>
      <PageHeader
        title="模型配置"
        subtitle="三步配完：添加服务商密钥 → 选对话模型 → 选检索模型；对话和检索可以来自不同服务商"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
            添加服务商
          </Button>
        }
      />

      <Card
        title={
          <Space size={8}>
            <Tag color="blue" style={{ marginRight: 0 }}>
              第一步
            </Tag>
            服务商与密钥
            <Typography.Text type="secondary" style={{ fontSize: 12.5, fontWeight: 400 }}>
              把要用的每家服务商的 API Key 存进来
            </Typography.Text>
          </Space>
        }
        styles={{ body: { paddingTop: 8 } }}
      >
        <Table<Provider>
          size="middle"
          rowKey="id"
          dataSource={providers}
          pagination={false}
          locale={{ emptyText: "还没有服务商——点右上角「添加服务商」，选一家、贴上 Key 即可" }}
          columns={[
            {
              title: "服务商",
              render: (_, p) => (
                <div>
                  <div style={{ fontWeight: 600 }}>{p.name}</div>
                  <div style={{ fontSize: 12, color: "#94a3b8" }}>{p.base_url}</div>
                </div>
              ),
            },
            { title: "密钥", dataIndex: "api_key_masked", width: 100 },
            {
              title: "当前用途",
              width: 150,
              render: (_, p) => (
                <Space size={4}>
                  {p.is_active && <Tag color="blue">对话中</Tag>}
                  {p.is_embed_active && <Tag color="purple">检索中</Tag>}
                  {!p.is_active && !p.is_embed_active && (
                    <span style={{ color: "#cbd5e1", fontSize: 12.5 }}>未使用</span>
                  )}
                </Space>
              ),
            },
            {
              title: "连接",
              width: 140,
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
              width: 180,
              render: (_, p) => (
                <Space>
                  <Button size="small" loading={testing === p.id} onClick={() => test(p.id)}>
                    测试
                  </Button>
                  <Button size="small" type="text" onClick={() => openModal(p)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="确认删除该服务商？"
                    onConfirm={async () => {
                      try {
                        await api.del(`/api/settings/llm-providers/${p.id}`);
                        await load();
                      } catch (e) {
                        message.error(e instanceof ApiError ? e.message : "删除失败");
                      }
                    }}
                  >
                    <Button
                      size="small"
                      type="text"
                      danger
                      disabled={p.is_active || p.is_embed_active}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12} style={{ marginBottom: 16 }}>
          <RoleCard
            key={`chat-${chatCurrent?.id ?? 0}-${chatCurrent?.chat_model ?? ""}-${chatCurrent?.fallback_model ?? ""}`}
            role="chat"
            providers={providers}
            onSaved={load}
          />
        </Col>
        <Col xs={24} lg={12} style={{ marginBottom: 16 }}>
          <RoleCard
            key={`embed-${embedCurrent?.id ?? 0}-${embedCurrent?.embed_model ?? ""}`}
            role="embed"
            providers={providers}
            onSaved={load}
          />
        </Col>
      </Row>

      <UsageCard />

      <Modal
        title={editing ? `编辑：${editing.name}` : "添加服务商"}
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
                  form.setFieldsValue({
                    name: p.label.split("（")[0],
                    base_url: p.base_url,
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
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            保存后，到下方「对话模型」「知识库检索模型」里选用这家服务商。
          </Typography.Text>

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
                    <Form.Item
                      name="supports_json_schema"
                      valuePropName="checked"
                      initialValue={true}
                    >
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
