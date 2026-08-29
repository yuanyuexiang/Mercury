"use client";
// 知识库（技术方案 §10）：上传/URL 导入、启停、重建索引、删除。
import {
  Button,
  Card,
  Form,
  Input,
  message as antdMessage,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";

interface Doc {
  id: number;
  title: string;
  source_type: string;
  source_url: string | null;
  status: string;
  version: number;
  updated_at: string;
}

const STATUS_COLORS: Record<string, string> = {
  active: "green",
  indexing: "blue",
  pending: "orange",
  disabled: "default",
  failed: "red",
};

export default function KnowledgePage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [urlModalOpen, setUrlModalOpen] = useState(false);
  const [urlForm] = Form.useForm();

  const load = useCallback(async () => {
    const data = await api.get<{ items: Doc[] }>("/api/knowledge/documents");
    setDocs(data.items);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000); // 索引状态轮询
    return () => clearInterval(timer);
  }, [load]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      antdMessage.success(ok);
      await load();
    } catch (e) {
      antdMessage.error(e instanceof ApiError ? e.message : "操作失败");
    }
  };

  return (
    <div>
      <Typography.Title level={4}>知识库</Typography.Title>
      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Upload
            accept=".md,.markdown,.txt,.pdf"
            showUploadList={false}
            customRequest={({ file, onSuccess, onError }) => {
              const formData = new FormData();
              formData.append("file", file as File);
              api
                .upload("/api/knowledge/documents", formData)
                .then(() => {
                  antdMessage.success("已上传，索引中");
                  load();
                  onSuccess?.(null);
                })
                .catch((e) => {
                  antdMessage.error(e instanceof ApiError ? e.message : "上传失败");
                  onError?.(e);
                });
            }}
          >
            <Button type="primary">上传文档（md/txt/pdf）</Button>
          </Upload>
          <Button onClick={() => setUrlModalOpen(true)}>导入网页 URL</Button>
        </Space>
        <Table<Doc>
          rowKey="id"
          dataSource={docs}
          pagination={false}
          columns={[
            { title: "ID", dataIndex: "id", width: 60 },
            { title: "标题", dataIndex: "title" },
            { title: "类型", dataIndex: "source_type", width: 100 },
            {
              title: "状态",
              dataIndex: "status",
              width: 100,
              render: (s: string) => <Tag color={STATUS_COLORS[s]}>{s}</Tag>,
            },
            { title: "版本", dataIndex: "version", width: 70 },
            { title: "更新时间", dataIndex: "updated_at", width: 200 },
            {
              title: "操作",
              width: 260,
              render: (_, doc) => (
                <Space>
                  {doc.status === "active" ? (
                    <Button
                      size="small"
                      onClick={() =>
                        run(
                          () =>
                            api.patch(`/api/knowledge/documents/${doc.id}`, {
                              status: "disabled",
                            }),
                          "已停用",
                        )
                      }
                    >
                      停用
                    </Button>
                  ) : (
                    <Button
                      size="small"
                      onClick={() =>
                        run(
                          () =>
                            api.patch(`/api/knowledge/documents/${doc.id}`, {
                              status: "active",
                            }),
                          "已启用",
                        )
                      }
                    >
                      启用
                    </Button>
                  )}
                  <Button
                    size="small"
                    onClick={() =>
                      run(
                        () => api.post(`/api/knowledge/documents/${doc.id}/reindex`),
                        "已加入索引队列",
                      )
                    }
                  >
                    重建索引
                  </Button>
                  <Popconfirm
                    title="确认删除该文档及其全部索引？"
                    onConfirm={() =>
                      run(() => api.del(`/api/knowledge/documents/${doc.id}`), "已删除")
                    }
                  >
                    <Button size="small" danger>
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
        title="导入网页 URL"
        open={urlModalOpen}
        onCancel={() => setUrlModalOpen(false)}
        onOk={() => urlForm.submit()}
      >
        <Form
          form={urlForm}
          layout="vertical"
          onFinish={(values) =>
            run(() => api.post("/api/knowledge/documents/url", values), "已导入，索引中").then(
              () => {
                setUrlModalOpen(false);
                urlForm.resetFields();
              },
            )
          }
        >
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="url" label="URL" rules={[{ required: true, type: "url" }]}>
            <Input placeholder="https://…" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
