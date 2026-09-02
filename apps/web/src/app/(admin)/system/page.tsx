"use client";
// 系统设置：Telegram 接入向导（三步引导 + Chat ID 自动检测，零命令行）+ 品牌文案。
// 全部 DB 优先 env 兜底，保存即生效（无需重启）。
import { CheckCircleFilled, RadarChartOutlined, SendOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Steps,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api, ApiError } from "@/lib/api";
import { fromNow } from "@/lib/ui";

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

interface ReviveConf {
  enabled: boolean;
  after_days: number;
  max_attempts: number;
}

interface SheetsConf {
  configured: boolean;
  service_account_email: string | null;
  spreadsheet_id: string;
}

interface TuningConf {
  rag_min_similarity: number;
  rag_top_k: number;
  reply_deadline_s: number;
  triage_timeout_s: number;
}

interface Candidate {
  chat_id: number;
  kind: string;
  name: string;
  last_text: string;
  received_at: string;
  is_customer?: boolean;
}

export default function SystemSettingsPage() {
  const { message } = App.useApp();
  const [tg, setTg] = useState<TelegramConf | null>(null);
  const [botUsername, setBotUsername] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [detectOpen, setDetectOpen] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [tokenInput, setTokenInput] = useState("");
  const [generalForm] = Form.useForm();
  const [reviveForm] = Form.useForm();
  const [savingRevive, setSavingRevive] = useState(false);
  const [sheets, setSheets] = useState<SheetsConf | null>(null);
  const [sheetsForm] = Form.useForm();
  const [savingSheets, setSavingSheets] = useState(false);
  const [testingSheets, setTestingSheets] = useState(false);
  const [tuningForm] = Form.useForm();
  const [savingTuning, setSavingTuning] = useState(false);

  const load = useCallback(async () => {
    const [t, g, r, sh, tu] = await Promise.all([
      api.get<TelegramConf>("/api/settings/telegram"),
      api.get<GeneralConf>("/api/settings/general"),
      api.get<ReviveConf>("/api/settings/revive"),
      api.get<SheetsConf>("/api/settings/sheets"),
      api.get<TuningConf>("/api/settings/tuning"),
    ]);
    setTg(t);
    generalForm.setFieldsValue(g);
    reviveForm.setFieldsValue(r);
    setSheets(sh);
    sheetsForm.setFieldsValue({ spreadsheet_id: sh.spreadsheet_id });
    tuningForm.setFieldsValue(tu);
  }, [generalForm, reviveForm, sheetsForm, tuningForm]);

  useEffect(() => {
    load();
  }, [load]);

  const saveToken = async () => {
    if (!tokenInput.trim()) {
      message.info("请粘贴 Bot Token");
      return;
    }
    setSaving(true);
    try {
      const res = await api.put<{ bot_username: string; webhook: string }>(
        "/api/settings/telegram",
        { bot_token: tokenInput.trim() },
      );
      setBotUsername(res.bot_username);
      const webhookText =
        res.webhook === "registered"
          ? "，消息通道已自动接通"
          : res.webhook === "failed"
            ? "，但消息通道注册失败（可重新保存重试）"
            : "";
      message.success(`已连接 @${res.bot_username}${webhookText}`, 6);
      setTokenInput("");
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const detect = async () => {
    setDetecting(true);
    try {
      const data = await api.get<{ items: Candidate[] }>("/api/settings/telegram/candidates");
      setCandidates(data.items);
      setDetectOpen(true);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "检测失败");
    } finally {
      setDetecting(false);
    }
  };

  const pickCandidate = async (c: Candidate) => {
    try {
      await api.put("/api/settings/telegram", { operator_chat_id: String(c.chat_id) });
      setDetectOpen(false);
      message.success(`通知将发送给 ${c.name}`);
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    }
  };

  const sendTest = async () => {
    setTesting(true);
    try {
      await api.post("/api/settings/telegram/test");
      message.success("测试通知已发送，请打开 Telegram 查看");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "发送失败");
    } finally {
      setTesting(false);
    }
  };

  const saveRevive = async (values: ReviveConf) => {
    setSavingRevive(true);
    try {
      await api.put("/api/settings/revive", values);
      message.success("已保存，明天起按新规则执行");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSavingRevive(false);
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

  const saveSheets = async (values: { spreadsheet_id?: string; service_account_json?: string }) => {
    setSavingSheets(true);
    try {
      await api.put("/api/settings/sheets", {
        spreadsheet_id: values.spreadsheet_id,
        service_account_json: values.service_account_json || undefined,
      });
      sheetsForm.setFieldsValue({ service_account_json: "" });
      message.success("已保存——记得把表格共享给下方的 service account 邮箱");
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSavingSheets(false);
    }
  };

  const testSheets = async () => {
    setTestingSheets(true);
    try {
      const r = await api.post<{ spreadsheet_title: string }>("/api/settings/sheets/test");
      message.success(`连接正常，已就绪：《${r.spreadsheet_title}》`);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "测试失败", 8);
    } finally {
      setTestingSheets(false);
    }
  };

  const saveTuning = async (values: TuningConf) => {
    setSavingTuning(true);
    try {
      await api.put("/api/settings/tuning", values);
      message.success("已保存，下一条消息即按新参数处理");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSavingTuning(false);
    }
  };

  const hasToken = !!tg?.bot_token_masked;
  const hasOperator = !!tg?.operator_chat_id;
  const currentStep = !hasToken ? 0 : !hasOperator ? 2 : 3;

  return (
    <div>
      <PageHeader title="系统设置" subtitle="Telegram 接入与品牌配置——保存即生效，无需重启" />

      <Card
        title="Telegram 接入"
        extra={
          hasToken &&
          hasOperator && (
            <Tag icon={<CheckCircleFilled />} color="success">
              接入完成
            </Tag>
          )
        }
      >
        {tg && !tg.webhook_configured && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="服务器未配置公网地址（PUBLIC_BASE_URL / TELEGRAM_WEBHOOK_SECRET），保存 Token 后无法自动接通消息通道"
          />
        )}
        <Steps
          direction="vertical"
          current={currentStep}
          items={[
            {
              title: "创建你的机器人",
              description: (
                <div style={{ fontSize: 13, color: "#64748b", paddingBottom: 8 }}>
                  在 Telegram 打开{" "}
                  <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">
                    @BotFather
                  </a>{" "}
                  → 发送 <Typography.Text code>/newbot</Typography.Text> → 按提示起名字（用户名须以
                  bot 结尾）→ 复制它返回的一长串 Token（形如{" "}
                  <Typography.Text code>123456:ABC-xxx</Typography.Text>）。已有机器人可直接进入下一步。
                </div>
              ),
            },
            {
              title: hasToken ? `已连接机器人${botUsername ? ` @${botUsername}` : ""}` : "粘贴 Token，连接机器人",
              description: (
                <div style={{ paddingBottom: 8, maxWidth: 520 }}>
                  <Space.Compact style={{ width: "100%" }}>
                    <Input.Password
                      value={tokenInput}
                      onChange={(e) => setTokenInput(e.target.value)}
                      placeholder={
                        hasToken ? `已配置（${tg?.bot_token_masked}，输入新值可更换）` : "123456789:ABC-…"
                      }
                    />
                    <Button type="primary" loading={saving} onClick={saveToken}>
                      保存并验证
                    </Button>
                  </Space.Compact>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>
                    保存时自动验证 Token 有效性，并接通 Telegram 消息通道（webhook）。
                  </div>
                </div>
              ),
            },
            {
              title: hasOperator ? `通知接收人已设置（Chat ID ${tg?.operator_chat_id}）` : "设置谁接收通知",
              description: (
                <div style={{ paddingBottom: 8, maxWidth: 520 }}>
                  <div style={{ fontSize: 13, color: "#64748b", marginBottom: 8 }}>
                    高意向线索、转人工请求会推送到这个人（或群）。操作：用<b>你自己的 Telegram</b>{" "}
                    给机器人随便发一句话（群接收则把机器人拉进群后在群里发），然后点检测：
                  </div>
                  <Space>
                    <Button
                      icon={<RadarChartOutlined />}
                      loading={detecting}
                      onClick={detect}
                      disabled={!hasToken}
                    >
                      检测最近联系人
                    </Button>
                    <Button
                      icon={<SendOutlined />}
                      loading={testing}
                      onClick={sendTest}
                      disabled={!hasOperator}
                    >
                      发送测试通知
                    </Button>
                  </Space>
                </div>
              ),
            },
            {
              title: "完成",
              description: (
                <div style={{ fontSize: 13, color: "#64748b" }}>
                  接下来到「模型配置」激活 AI 供应商、「知识库」上传产品资料，机器人就能开始接客了。
                </div>
              ),
            },
          ]}
        />
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

      <Card title="自动跟进（沉睡客户唤醒）" style={{ marginTop: 16 }}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 16 }}>
          客户聊过但几天没动静时，机器人每天上午自动发一条跟进消息（只跟进有购买意向的客户，
          绝不打扰人工接管中的会话；客户一回复就恢复正常接待）。
        </Typography.Paragraph>
        <Form
          form={reviveForm}
          layout="inline"
          onFinish={saveRevive}
          style={{ rowGap: 12 }}
        >
          <Form.Item name="enabled" label="开启" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="after_days" label="安静几天后跟进">
            <InputNumber min={1} max={60} addonAfter="天" style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="max_attempts" label="每位客户最多跟进">
            <InputNumber min={0} max={5} addonAfter="次" style={{ width: 110 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={savingRevive}>
            保存
          </Button>
        </Form>
      </Card>

      <Card title="Google Sheets 线索同步" style={{ marginTop: 16 }}>
        {sheets?.configured ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 16 }}
            message={
              <span>
                已配置。请确认表格已共享给{" "}
                <Typography.Text code copyable>
                  {sheets.service_account_email ?? "（凭据解析失败）"}
                </Typography.Text>{" "}
                （编辑者权限）
              </span>
            }
          />
        ) : (
          <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 16 }}>
            三步开通：① Google Cloud 控制台启用 Sheets API、创建服务账号并下载 JSON 密钥；
            ② 新建一张空表（工作表和表头系统会自动创建）；③ 在下方粘贴 JSON 与表
            ID，保存后把表格共享给显示出的邮箱。每条线索会自动落表，失败自动重试不丢数据。
          </Typography.Paragraph>
        )}
        <Form form={sheetsForm} layout="vertical" onFinish={saveSheets} style={{ maxWidth: 560 }}>
          <Form.Item
            name="spreadsheet_id"
            label="表格 ID"
            extra="表格 URL 中 /d/ 与 /edit 之间的一长串"
          >
            <Input placeholder="1AbCdEf…" />
          </Form.Item>
          <Form.Item
            name="service_account_json"
            label={sheets?.configured ? "服务账号 JSON（留空保留已保存的凭据）" : "服务账号 JSON"}
          >
            <Input.TextArea rows={3} placeholder='粘贴整段密钥文件内容（{"type": "service_account", …}）' />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={savingSheets}>
              保存
            </Button>
            <Button loading={testingSheets} onClick={testSheets} disabled={!sheets?.configured}>
              测试连接
            </Button>
          </Space>
        </Form>
      </Card>

      <Card title="高级调优（一般无需改动）" style={{ marginTop: 16 }}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 16 }}>
          换 AI 服务商或 embedding 模型后才需要调整，保存即生效。经验值参考：OpenAI embedding
          阈值 0.60；Qwen3-Embedding 阈值 0.45、检索条数 10；DeepSeek 意图识别 5 秒。
        </Typography.Paragraph>
        <Form form={tuningForm} layout="inline" onFinish={saveTuning} style={{ rowGap: 12 }}>
          <Form.Item name="rag_min_similarity" label="检索相似度阈值">
            <InputNumber min={0.05} max={0.95} step={0.05} style={{ width: 90 }} />
          </Form.Item>
          <Form.Item name="rag_top_k" label="检索条数">
            <InputNumber min={1} max={20} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item name="reply_deadline_s" label="回复总预算">
            <InputNumber min={3} max={60} addonAfter="秒" style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="triage_timeout_s" label="意图识别上限">
            <InputNumber min={0.5} max={20} step={0.5} addonAfter="秒" style={{ width: 110 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={savingTuning}>
            保存
          </Button>
        </Form>
      </Card>

      <Modal
        title="选择通知接收人"
        open={detectOpen}
        onCancel={() => setDetectOpen(false)}
        footer={null}
      >
        {candidates.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span>
                还没有检测到消息。请先用你的 Telegram 给机器人发一句话
                {botUsername && (
                  <>
                    （
                    <a href={`https://t.me/${botUsername}`} target="_blank" rel="noreferrer">
                      打开 @{botUsername}
                    </a>
                    ）
                  </>
                )}
                ，再点一次检测。
              </span>
            }
          />
        ) : (
          candidates.map((c) => (
            <div
              key={c.chat_id}
              onClick={() => pickCandidate(c)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 12,
                padding: "10px 12px",
                border: "1px solid #f1f5f9",
                borderRadius: 8,
                marginBottom: 8,
                cursor: "pointer",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 570, fontSize: 13.5 }}>
                  {c.name} <Tag style={{ fontSize: 11 }}>{c.kind}</Tag>
                  {c.is_customer && (
                    <Tag color="warning" style={{ fontSize: 11 }}>
                      ⚠ 客户会话——选它会把内部通知发给这个客户
                    </Tag>
                  )}
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
                  {c.last_text || "（非文本消息）"} · {fromNow(c.received_at)}
                </div>
              </div>
              <Button size="small" type="primary">
                选 TA
              </Button>
            </div>
          ))
        )}
      </Modal>
    </div>
  );
}
