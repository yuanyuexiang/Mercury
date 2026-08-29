"use client";
// 线索详情（技术方案 §10）：人工修正字段 → 自动重算评分；手动同步。
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  message as antdMessage,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";

interface LeadDetail {
  id: number;
  conversation_id: number;
  score: number;
  grade: string;
  score_reasons: string[];
  status: string;
  version: number;
  external_crm_id: string | null;
  [key: string]: unknown;
}

const FIELDS: Array<[string, string]> = [
  ["name", "姓名"],
  ["company", "公司"],
  ["country", "国家"],
  ["business_email", "工作邮箱"],
  ["requirement", "需求"],
  ["team_size", "团队规模"],
  ["budget_range", "预算"],
  ["purchase_timeline", "采购时间"],
  ["notes", "备注"],
];

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>();
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
      antdMessage.success(`已保存，评分 ${data.score}（${data.grade}）`);
    } catch (e) {
      antdMessage.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const manualSync = async () => {
    try {
      await api.post(`/api/leads/${id}/sync`);
      antdMessage.success("已触发同步");
    } catch (e) {
      antdMessage.error(e instanceof ApiError ? e.message : "同步失败");
    }
  };

  if (!lead) return null;

  return (
    <Row gutter={16}>
      <Col span={14}>
        <Card
          title={`线索 #${lead.id}`}
          extra={
            <Space>
              <Link href={`/conversations/${lead.conversation_id}`}>查看会话</Link>
              <Button onClick={manualSync}>同步到 CRM</Button>
            </Space>
          }
        >
          <Form form={form} layout="vertical" onFinish={save}>
            <Row gutter={12}>
              {FIELDS.map(([key, label]) => (
                <Col span={12} key={key}>
                  <Form.Item name={key} label={label}>
                    <Input />
                  </Form.Item>
                </Col>
              ))}
              <Col span={12}>
                <Form.Item name="status" label="状态">
                  <Select
                    options={["open", "synced", "won", "lost"].map((v) => ({
                      value: v,
                      label: v,
                    }))}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存（自动重算评分）
            </Button>
          </Form>
        </Card>
      </Col>
      <Col span={10}>
        <Card title="评分" size="small">
          <Typography.Title level={2} style={{ marginTop: 0 }}>
            {lead.score}
            <Tag style={{ marginLeft: 12 }} color={lead.grade === "high" ? "red" : undefined}>
              {lead.grade}
            </Tag>
          </Typography.Title>
          <div>
            {lead.score_reasons.map((r) => (
              <Tag key={r}>{r}</Tag>
            ))}
          </div>
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
            版本 v{lead.version} · CRM：{lead.external_crm_id ?? "未同步"}
          </Typography.Paragraph>
        </Card>
      </Col>
    </Row>
  );
}
