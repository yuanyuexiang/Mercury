"use client";
// 模型配置工作台：微信式两栏（加全局侧边栏共三栏）——左=服务商列表（置顶「当前生效」），右=内容区。
// 自动化三层：拉取模型列表自动分类（对话/检索分流下拉）→ 添加后自动预填推荐模型 → 保存自动实测（检索含 1536 维校验）。
import {
  CheckCircleFilled,
  CloseCircleFilled,
  MessageOutlined,
  PlusOutlined,
  SearchOutlined,
  SettingOutlined,
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
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  classifyModels,
  type ClassifiedModels,
  PROVIDER_PRESETS,
  type ProviderPreset,
} from "@/lib/providers";
import { avatarColor, fromNow, initialOf } from "@/lib/ui";

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

const panelBorder = "1px solid #e2e8f0";

const presetFor = (p?: Provider | null): ProviderPreset | undefined =>
  p ? PROVIDER_PRESETS.find((x) => x.base_url === p.base_url) : undefined;

function TestStatus({ p }: { p: Provider }) {
  if (!p.last_test_at)
    return <span style={{ color: "#cbd5e1", fontSize: 12.5 }}>未测试</span>;
  return p.last_test_ok ? (
    <span style={{ color: "#52C41A", fontSize: 12.5 }}>
      <CheckCircleFilled /> 连接正常 · {fromNow(p.last_test_at)}
    </span>
  ) : (
    <span style={{ color: "#F5222D", fontSize: 12.5 }}>
      <CloseCircleFilled /> 连接失败 · {fromNow(p.last_test_at)}
    </span>
  );
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
    <Card title="模型用量（Token / 日，近 14 天）" size="small" style={{ marginTop: 16 }}>
      {days.length === 0 ? (
        <Typography.Text type="secondary">暂无调用记录</Typography.Text>
      ) : (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 100 }}>
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

// ---------- 内容区：当前生效总览 ----------
function OverviewPanel({
  providers,
  onSelect,
  onAdd,
}: {
  providers: Provider[];
  onSelect: (id: number) => void;
  onAdd: () => void;
}) {
  const chatHolder = providers.find((p) => p.is_active);
  const embedHolder = providers.find((p) => p.is_embed_active);

  const slotCard = (
    icon: React.ReactNode,
    title: string,
    subtitle: string,
    holder: Provider | undefined,
    model: string,
  ) => (
    <Card size="small" styles={{ body: { minHeight: 118 } }}>
      <Space size={8} style={{ marginBottom: 8 }}>
        {icon}
        <span style={{ fontWeight: 600 }}>{title}</span>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {subtitle}
        </Typography.Text>
      </Space>
      {holder ? (
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
            {holder.name} · {model}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <TestStatus p={holder} />
            <Button size="small" onClick={() => onSelect(holder.id)}>
              调整
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <Typography.Text type="warning">未配置</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {providers.length ? (
              <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>
                在左侧点一家服务商进行配置
              </Typography.Text>
            ) : (
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={onAdd}>
                添加服务商
              </Button>
            )}
          </div>
        </div>
      )}
    </Card>
  );

  return (
    <div>
      <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 4 }}>
        当前生效
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12.5, marginBottom: 16 }}>
        机器人现在用谁干活。对话和检索可以来自不同服务商——在左侧选一家进行配置。
      </Typography.Paragraph>
      <Row gutter={12}>
        <Col xs={24} xl={12} style={{ marginBottom: 12 }}>
          {slotCard(
            <MessageOutlined style={{ color: "#2F54EB" }} />,
            "对话模型",
            "回答客户的消息",
            chatHolder,
            chatHolder?.chat_model ?? "",
          )}
        </Col>
        <Col xs={24} xl={12} style={{ marginBottom: 12 }}>
          {slotCard(
            <SearchOutlined style={{ color: "#722ED1" }} />,
            "知识库检索模型",
            "搜索知识库（embedding）",
            embedHolder,
            embedHolder?.embed_model ?? "",
          )}
        </Col>
      </Row>
      <UsageCard />
    </div>
  );
}

// ---------- 内容区：服务商详情（密钥 + 两个用途配置块） ----------
function RoleBlock({
  role,
  provider,
  classified,
  onSaved,
}: {
  role: "chat" | "embed";
  provider: Provider;
  classified: ClassifiedModels | null;
  onSaved: () => Promise<void>;
}) {
  const { message } = App.useApp();
  const holds = role === "chat" ? provider.is_active : provider.is_embed_active;
  const heldModel = (role === "chat" ? provider.chat_model : provider.embed_model) ?? "";
  const preset = presetFor(provider);
  const recommended = (role === "chat" ? preset?.chat_model : preset?.embed_model) ?? "";

  const [model, setModel] = useState<string>(heldModel || recommended);
  const [saving, setSaving] = useState(false);

  // 自动预填：分类结果就绪后，空输入自动填（推荐优先，其次分类命中的第一个）
  useEffect(() => {
    if (model || !classified) return;
    const pool = role === "chat" ? classified.chat : classified.embed;
    if (recommended) setModel(recommended);
    else if (pool.length) setModel(pool[0]);
  }, [classified, model, recommended, role]);

  const options: { label: string; options: { value: string }[] }[] = [];
  if (classified) {
    const pool = role === "chat" ? classified.chat : classified.embed;
    if (recommended && !pool.includes(recommended))
      options.push({ label: "推荐", options: [{ value: recommended }] });
    if (pool.length)
      options.push({
        label: role === "chat" ? "对话模型" : "检索模型（embedding）",
        options: pool.map((m) => ({
          value: m,
          ...(m === recommended ? { label: `${m}（推荐）` } : {}),
        })),
      });
    if (classified.other.length)
      options.push({ label: "其他", options: classified.other.map((m) => ({ value: m })) });
  } else if (recommended) {
    options.push({ label: "推荐", options: [{ value: recommended }] });
  }

  const inEffect = holds && model.trim() === heldModel;

  const save = async () => {
    if (!model.trim()) {
      message.info("请先选择模型");
      return;
    }
    setSaving(true);
    try {
      await api.put(`/api/settings/llm-providers/roles/${role}`, {
        provider_id: provider.id,
        model: model.trim(),
      });
      const test = await api.post<{ ok: boolean; error: string | null }>(
        `/api/settings/llm-providers/${provider.id}/test`,
        {},
      );
      if (test.ok) message.success("已生效，连接正常");
      else message.warning(`已生效，但连接测试失败：${test.error ?? "未知错误"}`, 8);
      await onSaved();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        border: panelBorder,
        borderRadius: 10,
        padding: "14px 16px",
        marginBottom: 12,
        background: holds ? "#F6FFED" : undefined,
        borderColor: holds ? "#B7EB8F" : undefined,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <Space size={8}>
          {role === "chat" ? (
            <MessageOutlined style={{ color: "#2F54EB" }} />
          ) : (
            <SearchOutlined style={{ color: "#722ED1" }} />
          )}
          <span style={{ fontWeight: 600 }}>
            {role === "chat" ? "对话模型" : "知识库检索模型"}
          </span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {role === "chat" ? "回答客户的消息" : "搜索知识库（embedding）"}
          </Typography.Text>
        </Space>
        {holds && <Tag color="green">这家正在承担此用途</Tag>}
      </div>
      <Space.Compact style={{ width: "100%" }}>
        <AutoComplete
          style={{ flex: 1 }}
          value={model}
          onChange={setModel}
          options={options}
          placeholder={
            classified
              ? role === "chat"
                ? "选择或输入对话模型"
                : "选择或输入检索模型"
              : "正在拉取模型列表…也可直接输入"
          }
          filterOption={(input, option) =>
            String((option as { value?: string } | undefined)?.value ?? "")
              .toLowerCase()
              .includes(input.toLowerCase())
          }
        />
        <Button
          type={inEffect ? "default" : "primary"}
          icon={<ThunderboltOutlined />}
          loading={saving}
          disabled={inEffect || !model.trim()}
          onClick={save}
        >
          {inEffect ? "当前生效" : holds ? "保存变更" : "设为" + (role === "chat" ? "对话" : "检索")}
        </Button>
      </Space.Compact>
      {role === "embed" && (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 8 }}>
          保存时自动校验能否输出 1536 维；更换检索模型后需到「知识库」重建索引（首次配置不用管）。
        </Typography.Text>
      )}
    </div>
  );
}

function ProviderPanel({
  provider,
  onChanged,
  onDeleted,
  onEdit,
}: {
  provider: Provider;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
  onEdit: () => void;
}) {
  const { message } = App.useApp();
  const [classified, setClassified] = useState<ClassifiedModels | null>(null);
  const [testing, setTesting] = useState(false);
  const preset = presetFor(provider);
  const inUse = provider.is_active || provider.is_embed_active;

  // 自动：进入即拉取模型列表并分类（失败不阻塞，可手输）
  useEffect(() => {
    let cancelled = false;
    setClassified(null);
    api
      .post<{ items: string[] }>("/api/settings/llm-providers/models", {
        provider_id: provider.id,
      })
      .then((d) => {
        if (!cancelled) setClassified(classifyModels(d.items));
      })
      .catch(() => {
        if (!cancelled) setClassified({ chat: [], embed: [], other: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [provider.id]);

  const test = async () => {
    setTesting(true);
    try {
      const r = await api.post<{ ok: boolean; error: string | null }>(
        `/api/settings/llm-providers/${provider.id}/test`,
        {},
      );
      if (r.ok) message.success("连接正常");
      else message.error(`测试失败：${r.error ?? "未知错误"}`, 8);
      await onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "测试失败");
    } finally {
      setTesting(false);
    }
  };

  const remove = async () => {
    try {
      await api.del(`/api/settings/llm-providers/${provider.id}`);
      message.success("已删除");
      await onDeleted();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "删除失败");
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 2 }}>
            {provider.name}
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {provider.base_url}
          </Typography.Text>
        </div>
        <Space>
          <Button size="small" loading={testing} onClick={test}>
            测试
          </Button>
          <Button size="small" onClick={onEdit}>
            编辑
          </Button>
          <Popconfirm
            title={inUse ? "该服务商正在担任用途" : "确认删除该服务商？"}
            description={
              inUse
                ? "删除后对应功能（对话/检索）将停用，直到你重新配置。确认删除？"
                : undefined
            }
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={remove}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </div>
      <div style={{ margin: "10px 0 16px", display: "flex", gap: 16, alignItems: "center" }}>
        <span style={{ fontSize: 12.5, color: "#64748b" }}>密钥 {provider.api_key_masked}</span>
        <TestStatus p={provider} />
      </div>
      {preset?.note && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 14 }}>
          💡 {preset.note}
        </Typography.Paragraph>
      )}
      <RoleBlock role="chat" provider={provider} classified={classified} onSaved={onChanged} />
      <RoleBlock role="embed" provider={provider} classified={classified} onSaved={onChanged} />
    </div>
  );
}

// ---------- 页面 ----------
export default function SettingsPage() {
  const { message } = App.useApp();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selected, setSelected] = useState<"overview" | number>("overview");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [preset, setPreset] = useState<ProviderPreset | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    const data = await api.get<{ items: Provider[] }>("/api/settings/llm-providers");
    setProviders(data.items);
    return data.items;
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (id) setSelected(Number(id));
    load();
  }, [load]);

  const select = (key: "overview" | number) => {
    setSelected(key);
    const qs = key === "overview" ? "" : `?id=${key}`;
    window.history.replaceState(null, "", `/settings${qs}`);
  };

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
        message.success("已保存");
        setModalOpen(false);
        await load();
      } else {
        const created = await api.post<{ id: number }>("/api/settings/llm-providers", values);
        message.success("已添加——已自动拉取模型并填好推荐，确认后点「设为对话/检索」即可");
        setModalOpen(false);
        await load();
        select(created.id); // 自动跳到新服务商，进入自动预填流程
      }
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    }
  };

  const current = typeof selected === "number" ? providers.find((p) => p.id === selected) : null;

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
      {/* ---------- 左栏：服务商列表 ---------- */}
      <div
        style={{
          width: 240,
          flexShrink: 0,
          borderRight: panelBorder,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <div style={{ padding: "14px 14px 10px", borderBottom: panelBorder }}>
          <span style={{ fontWeight: 600, fontSize: 15 }}>模型配置</span>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {/* 置顶：当前生效 */}
          <div
            onClick={() => select("overview")}
            style={{
              display: "flex",
              gap: 10,
              alignItems: "center",
              padding: "12px 14px",
              cursor: "pointer",
              borderBottom: panelBorder,
              background: selected === "overview" ? "#EEF2FF" : undefined,
            }}
          >
            <SettingOutlined style={{ fontSize: 18, color: "#2F54EB" }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>当前生效</div>
              <div style={{ fontSize: 11.5, color: "#94a3b8" }}>机器人现在用谁干活</div>
            </div>
          </div>
          {providers.map((p) => {
            const active = selected === p.id;
            return (
              <div
                key={p.id}
                onClick={() => select(p.id)}
                style={{
                  display: "flex",
                  gap: 10,
                  padding: "11px 14px",
                  cursor: "pointer",
                  background: active ? "#EEF2FF" : undefined,
                  alignItems: "center",
                }}
              >
                <div
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: 8,
                    flexShrink: 0,
                    background: avatarColor(p.id),
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 600,
                  }}
                >
                  {initialOf(p.name)}
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      fontSize: 13.5,
                      fontWeight: 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {p.name}
                  </div>
                  <div style={{ display: "flex", gap: 4, marginTop: 2, alignItems: "center" }}>
                    {p.is_active && (
                      <Tag color="blue" style={{ fontSize: 10, lineHeight: "16px", margin: 0 }}>
                        对话
                      </Tag>
                    )}
                    {p.is_embed_active && (
                      <Tag color="purple" style={{ fontSize: 10, lineHeight: "16px", margin: 0 }}>
                        检索
                      </Tag>
                    )}
                    {!p.is_active && !p.is_embed_active && (
                      <span style={{ fontSize: 11, color: "#cbd5e1" }}>未使用</span>
                    )}
                    {p.last_test_at && (
                      <span
                        style={{
                          width: 7,
                          height: 7,
                          borderRadius: "50%",
                          background: p.last_test_ok ? "#52C41A" : "#F5222D",
                          marginLeft: "auto",
                        }}
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ padding: 10, borderTop: panelBorder }}>
          <Button block icon={<PlusOutlined />} onClick={() => openModal(null)}>
            添加服务商
          </Button>
        </div>
      </div>

      {/* ---------- 内容区 ---------- */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", minWidth: 0 }}>
        {selected === "overview" ? (
          <OverviewPanel providers={providers} onSelect={select} onAdd={() => openModal(null)} />
        ) : current ? (
          <ProviderPanel
            key={current.id}
            provider={current}
            onChanged={async () => {
              await load();
            }}
            onDeleted={async () => {
              await load();
              select("overview");
            }}
            onEdit={() => openModal(current)}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="服务商不存在或已删除"
            style={{ marginTop: 80 }}
          />
        )}
      </div>

      {/* ---------- 添加 / 编辑服务商弹窗 ---------- */}
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
          {!editing && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              保存后自动拉取模型列表、自动分类并填好推荐模型，你只需确认生效。
            </Typography.Text>
          )}

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
