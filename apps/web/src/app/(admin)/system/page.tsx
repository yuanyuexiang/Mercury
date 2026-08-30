"use client";
// 系统设置：Telegram 对接（token 加密存库、保存自动验证并注册 webhook）+ 品牌文案。
// 全部 DB 优先 env 兜底，保存即生效（无需重启）。
import { SendOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Form, Input, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api, ApiError } from "@/lib/api";

interface TelegramConf {
  bot_token_masked: string;
  bot_token_source: string;
  operator_chat_id: string;
  webhook_configured: boolean;
}

interface GeneralConf {
  brand_name: string;
  bot_tone_hint: string;
}

const SOURCE_LABEL: Record<string, { label: string; color: string }> = {
  db: { label: "后台配置", color: "success" },
  env: { label: "环境变量兜底", color: "default" },
  none: { label: "未配置", color: "warning" },
};

export default function SystemSettingsPage() {
  const { message } = App.useApp();
  const [tg, setTg] = useState<TelegramConf | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [tgForm] = Form.useForm();
  const [generalForm] = Form.useForm();

  const load = useCallback(async () => {
    const [t, g] = await Promise.all([
      api.get<TelegramConf>("/api/settings/telegram"),
      api.get<GeneralConf>("/api/settings/general"),
    ]);
    setTg(t);
    tgForm.setFieldsValue({ operator_chat_id: t.operator_chat_id });
    generalForm.setFieldsValue(g);
  }, [tgForm, generalForm]);

  useEffect(() => {
    load();
  }, [load]);

  const saveTelegram = async (values: { bot_token?: string; operator_chat_id?: string }) => {
    const body: Record<string, string> = {};
    if (values.bot_token?.trim()) body.bot_token = values.bot_token.trim();
    if (values.operator_chat_id !== undefined)
      body.operator_chat_id = values.operator_chat_id.trim();
    if (Object.keys(body).length === 0) {
      message.info("没有要保存的内容");
      return;
    }
    setSaving(true);
    try {
      const res = await api.put<{ bot_username: string; webhook: string }>(
        "/api/settings/telegram",
        body,
      );
      const webhookText =
        res.webhook === "registered"
          ? "，webhook 已自动注册"
          : res.webhook === "failed"
            ? "，但 webhook 注册失败（可稍后重试）"
            : res.webhook === "skipped"
              ? "，webhook 未注册（服务器未配置公网地址）"
              : "";
      message.success(
        (res.bot_username ? `已连接 @${res.bot_username}` : "已保存") + webhookText,
        6,
      );
      tgForm.setFieldValue("bot_token", "");
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async () => {
    setTesting(true);
    try {
      await api.post("/api/settings/telegram/test");
      message.success("测试通知已发送，请查看 Telegram");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "发送失败");
    } finally {
      setTesting(false);
    }
  };

  const saveGeneral = async (values: GeneralConf) => {
    setSavingGeneral(true);
    try {
      await api.put("/api/settings/general", values);
      message.success("已保存，机器人回复与后台品牌即刻生效");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSavingGeneral(false);
    }
  };

  const source = SOURCE_LABEL[tg?.bot_token_source ?? "none"];

  return (
    <div>
      <PageHeader title="系统设置" subtitle="Telegram 对接与品牌配置——保存即生效，无需重启" />

      <Card
        title="Telegram 对接"
        extra={
          tg && (
            <Space size={8}>
              <Tag color={source.color}>{source.label}</Tag>
              {tg.bot_token_masked && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  当前 Token：{tg.bot_token_masked}
                </Typography.Text>
              )}
            </Space>
          )
        }
      >
        {tg && !tg.webhook_configured && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="服务器未配置公网地址（PUBLIC_BASE_URL / TELEGRAM_WEBHOOK_SECRET），保存 Token 后无法自动注册 webhook"
          />
        )}
        <Form form={tgForm} layout="vertical" onFinish={saveTelegram} style={{ maxWidth: 560 }}>
          <Form.Item
            name="bot_token"
            label="Bot Token"
            extra="在 Telegram 搜索 @BotFather → /newbot 创建机器人后获得。留空表示不修改；保存时自动验证有效性并注册 webhook。"
          >
            <Input.Password placeholder={tg?.bot_token_masked ? "已配置（输入新值以更换）" : "123456789:ABC-…"} />
          </Form.Item>
          <Form.Item
            name="operator_chat_id"
            label="通知接收 Chat ID"
            extra="高意向线索、转人工请求会推送到这个 Telegram 账号/群。个人 ID 获取：给 @userinfobot 发条消息即可看到。"
          >
            <Input placeholder="如 123456789（群为负数）" />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存并验证
            </Button>
            <Button icon={<SendOutlined />} loading={testing} onClick={sendTest}>
              发送测试通知
            </Button>
          </Space>
        </Form>
      </Card>

      <Card title="品牌与语气" style={{ marginTop: 16 }}>
        <Form form={generalForm} layout="vertical" onFinish={saveGeneral} style={{ maxWidth: 560 }}>
          <Form.Item
            name="brand_name"
            label="品牌名称"
            extra="用于机器人欢迎语、AI 回答的身份设定，以及本后台的登录页与侧边栏。"
          >
            <Input placeholder="如 Acme" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="bot_tone_hint"
            label="回复语气（可选，英文效果更稳定）"
            extra="附加到 AI 回答的风格提示，例如：Friendly and concise, use simple language."
          >
            <Input.TextArea rows={2} maxLength={500} placeholder="留空使用默认专业语气" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={savingGeneral}>
            保存
          </Button>
        </Form>
      </Card>
    </div>
  );
}
