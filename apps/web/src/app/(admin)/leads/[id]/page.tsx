"use client";
// 线索详情：编辑（自动重算评分）+ 评分仪表盘 + 手动同步。
import { ArrowLeftOutlined, CloudSyncOutlined, MessageOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api, ApiError } from "@/lib/api";
import { fmtFull, GRADE, LEAD_STATUS, SCORE_REASON } from "@/lib/ui";

interface LeadDetail {
  id: number;
  conversation_id: number;
  score: number;
  grade: string;
  score_reasons: string[];
  status: string;
  version: number;
  external_crm_id: string | null;
  updated_at: string;
  [key: string]: unknown;
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

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { message } = App.useApp();
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const data = await api.get<LeadDetail>(`/api/leads/${id}`);
    setLead(data);
    form.setFieldsValue(data);
  }, [id, form]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      const data = await api.patch<LeadDetail>(`/api/leads/${id}`, values);
      setLead(data);
      form.setFieldsValue(data);
      message.success(`已保存，评分更新为 ${data.score}（${GRADE[data.grade]?.label}）`);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const manualSync = async () => {
    try {
      await api.post(`/api/leads/${id}/sync`);
      message.success("已触发同步任务");
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "同步失败");
    }
  };

  if (!lead) return null;
  const grade = lead.grade;

  return (
    <div>
      <PageHeader
        title={
          <Space>
            <Link href="/leads">
              <Button icon={<ArrowLeftOutlined />} type="text" />
            </Link>
            {String(lead.company ?? `线索 #${lead.id}`)}
            <Tag color={GRADE[grade]?.color}>{GRADE[grade]?.label}</Tag>
          </Space>
        }
        subtitle={`最后更新 ${fmtFull(lead.updated_at)} · 版本 v${lead.version}`}
        extra={
          <Space>
            <Link href={`/conversations/${lead.conversation_id}`}>
              <Button icon={<MessageOutlined />}>查看对话</Button>
            </Link>
            <Button icon={<CloudSyncOutlined />} onClick={manualSync}>
              同步到 CRM
            </Button>
          </Space>
        }
      />
      <Row gutter={16}>
        <Col xs={24} lg={15}>
          <Card title="线索资料" extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>保存后自动重算评分并触发同步</Typography.Text>}>
            <Form form={form} layout="vertical" onFinish={save}>
              <Row gutter={14}>
                {FIELDS.map(([key, label, hint]) => (
                  <Col span={12} key={key}>
                    <Form.Item name={key} label={label} tooltip={hint}>
                      <Input placeholder="—" />
                    </Form.Item>
                  </Col>
                ))}
                <Col span={12}>
                  <Form.Item name="status" label="跟进状态">
                    <Select
                      options={Object.entries(LEAD_STATUS).map(([value, s]) => ({
                        value,
                        label: s.label,
                      }))}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" htmlType="submit" loading={saving}>
                保存修改
              </Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card title="评分明细">
            <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
              <Progress
                type="dashboard"
                size={120}
                percent={Math.min(100, Math.max(0, lead.score))}
                format={() => <span style={{ fontSize: 28, fontWeight: 700 }}>{lead.score}</span>}
                strokeColor={grade === "high" ? "#F5222D" : grade === "medium" ? "#FA8C16" : "#94a3b8"}
              />
              <div style={{ fontSize: 12.5, color: "#64748b", lineHeight: 1.9 }}>
                <div>0–29 低意向</div>
                <div>30–59 中意向</div>
                <div>≥60 高意向</div>
              </div>
            </div>
            <div style={{ marginTop: 14 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                命中规则（确定性评分，非模型打分）：
              </Typography.Text>
              <div style={{ marginTop: 8 }}>
                {lead.score_reasons.length === 0 ? (
                  <Typography.Text type="secondary">暂无命中规则</Typography.Text>
                ) : (
                  lead.score_reasons.map((r) => (
                    <Tag key={r} color="blue" style={{ marginBottom: 6 }}>
                      {SCORE_REASON[r] ?? r}
                    </Tag>
                  ))
                )}
              </div>
            </div>
            <Typography.Paragraph type="secondary" style={{ marginTop: 14, marginBottom: 0, fontSize: 12 }}>
              CRM：{lead.external_crm_id ?? "未同步"}
            </Typography.Paragraph>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
