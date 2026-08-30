"use client";
// 模型供应商配置（技术方案 §10/§12）：增删改、激活（热切换）、连接测试；key 脱敏展示。
import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  message as antdMessage,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";

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

export default function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
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
    form.resetFields();
    if (provider) form.setFieldsValue({ ...provider, api_key: "" });
    setModalOpen(true);
  };

  const submit = async (values: Record<string, unknown>) => {
    try {
      if (editing) {
        if (!values.api_key) delete values.api_key; // 不传保留原密文（§10）
        await api.patch(`/api/settings/llm-providers/${editing.id}`, values);
      } else {
        await api.post("/api/settings/llm-providers", values);
      }
      antdMessage.success("已保存");
      setModalOpen(false);
      await load();
    } catch (e) {
      antdMessage.error(e instanceof ApiError ? e.message : "保存失败");
    }
  };

  const activate = async (id: number) => {
    try {
      await api.post(`/api/settings/llm-providers/${id}/activate`);
      antdMessage.success("已激活——worker 将即时切换，无需重启");
      await load();
    } catch (e) {
      antdMessage.error(e instanceof ApiError ? e.message : "激活失败");
    }
  };

  const test = async (id: number) => {
    setTesting(id);
    try {
      const result = await api.post<{ ok: boolean; latency_ms: number; error: string | null }>(
        `/api/settings/llm-providers/${id}/test`,
      );
      if (result.ok) antdMessage.success(`连接正常（${result.latency_ms}ms）`);
      else antdMessage.error(`连接失败：${result.error}`);
      await load();
    } finally {
      setTesting(null);
    }
  };

  return (
    <div>
      <Typography.Title level={4}>模型供应商</Typography.Title>
      <Card
        extra={
          <Button type="primary" onClick={() => openModal(null)}>
            新增供应商
          </Button>
        }
      >
        <Typography.Paragraph type="secondary">
          激活的供应商用于对话与 embedding（切换即时生效）。embedding 模型必须是 1536
          维（如 text-embedding-3-small）；更换 embedding 模型后需对所有文档重建索引。
        </Typography.Paragraph>
        <Table<Provider>
          rowKey="id"
          dataSource={providers}
          pagination={false}
          columns={[
            {
              title: "名称",
              render: (_, p) => (
                <Space>
                  {p.name}
                  {p.is_active && <Tag color="green">激活中</Tag>}
                </Space>
              ),
            },
            { title: "Base URL", dataIndex: "base_url", ellipsis: true },
            { title: "对话模型", dataIndex: "chat_model" },
            {
              title: "Embedding",
              dataIndex: "embed_model",
              render: (v: string | null) => v ?? "（env 兜底）",
            },
            { title: "API Key", dataIndex: "api_key_masked", width: 110 },
            {
              title: "连接测试",
              width: 140,
              render: (_, p) =>
                p.last_test_at
                  ? p.last_test_ok
                    ? <Tag color="green">通过</Tag>
                    : <Tag color="red">失败</Tag>
                  : "-",
            },
            {
              title: "操作",
              width: 280,
              render: (_, p) => (
                <Space>
                  {!p.is_active && (
                    <Button size="small" type="primary" onClick={() => activate(p.id)}>
                      激活
                    </Button>
                  )}
                  <Button size="small" loading={testing === p.id} onClick={() => test(p.id)}>
                    测试
                  </Button>
                  <Button size="small" onClick={() => openModal(p)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="确认删除？"
                    onConfirm={async () => {
                      try {
                        await api.del(`/api/settings/llm-providers/${p.id}`);
                        await load();
                      } catch (e) {
                        antdMessage.error(e instanceof ApiError ? e.message : "删除失败");
                      }
                    }}
                  >
                    <Button size="small" danger disabled={p.is_active}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Modal
        title={editing ? `编辑：${editing.name}` : "新增供应商"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如 DeepSeek 官方" />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL（OpenAI 兼容）" rules={[{ required: true }]}>
            <Input placeholder="https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={editing ? "API Key（留空保留原值）" : "API Key"}
            rules={editing ? [] : [{ required: true }]}
          >
            <Input.Password placeholder="sk-…" />
          </Form.Item>
          <Form.Item name="chat_model" label="对话模型" rules={[{ required: true }]}>
            <Input placeholder="deepseek-chat" />
          </Form.Item>
          <Form.Item name="fallback_model" label="Fallback 模型（可选）">
            <Input />
          </Form.Item>
          <Form.Item
            name="embed_model"
            label="Embedding 模型（可选，必须 1536 维；留空用环境变量兜底）"
          >
            <Input placeholder="text-embedding-3-small" />
          </Form.Item>
          <Form.Item name="supports_json_schema" valuePropName="checked" initialValue={true}>
            <Checkbox>支持严格 JSON Schema（structured outputs）</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
