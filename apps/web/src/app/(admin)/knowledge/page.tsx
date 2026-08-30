"use client";
// 知识库：拖拽上传 / URL 导入、启停、重建索引、删除；索引状态 5s 轮询。
import {
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  InboxOutlined,
  LinkOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Upload,
} from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api, ApiError } from "@/lib/api";
import { DOC_STATUS, fromNow } from "@/lib/ui";

interface Doc {
  id: number;
  title: string;
  source_type: string;
  source_url: string | null;
  status: string;
  version: number;
  updated_at: string;
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  markdown: <FileMarkdownOutlined style={{ color: "#2F54EB" }} />,
  txt: <FileTextOutlined style={{ color: "#64748b" }} />,
  pdf: <FilePdfOutlined style={{ color: "#F5222D" }} />,
  url: <LinkOutlined style={{ color: "#13C2C2" }} />,
};

export default function KnowledgePage() {
  const { message } = App.useApp();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [urlModalOpen, setUrlModalOpen] = useState(false);
  const [embeddingReady, setEmbeddingReady] = useState(true);
  const [urlForm] = Form.useForm();

  useEffect(() => {
    api
      .get<{ embedding_ready: boolean }>("/api/settings/setup-status")
      .then((d) => setEmbeddingReady(d.embedding_ready))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    const data = await api.get<{ items: Doc[] }>("/api/knowledge/documents");
    setDocs(data.items);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      message.success(ok);
      await load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : "操作失败");
      throw e;
    }
  };

  return (
    <div>
      <PageHeader
        title="知识库"
        subtitle="机器人只依据这里已启用的文档回答业务问题——资料越全，自动解决率越高"
        extra={
          <Button icon={<LinkOutlined />} onClick={() => setUrlModalOpen(true)}>
            导入网页 URL
          </Button>
        }
      />

      {!embeddingReady && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="知识库暂时无法生效：当前 AI 服务商缺少「知识库检索模型」"
          description={
            <span>
              上传的文档会一直停在「待索引/索引失败」。请到
              <Link href="/settings">「模型配置」</Link>
              给当前服务商补一个知识库检索模型（最简单：新增 OpenAI 服务商并填
              text-embedding-3-small），配好后点文档的「重建索引」即可恢复。
            </span>
          }
        />
      )}

      <Upload.Dragger
        accept=".md,.markdown,.txt,.pdf"
        showUploadList={false}
        multiple
        style={{ marginBottom: 16 }}
        customRequest={({ file, onSuccess, onError }) => {
          const formData = new FormData();
          formData.append("file", file as File);
          api
            .upload("/api/knowledge/documents", formData)
            .then(() => {
              message.success("已上传，开始索引");
              load();
              onSuccess?.(null);
            })
            .catch((e) => {
              message.error(e instanceof ApiError ? e.message : "上传失败");
              onError?.(e as Error);
            });
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
        <p className="ant-upload-hint">支持 Markdown / TXT / PDF，单文件不超过 20MB</p>
      </Upload.Dragger>

      <Card styles={{ body: { paddingTop: 8 } }}>
        <Table<Doc>
          rowKey="id"
          dataSource={docs}
          pagination={false}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="还没有文档——上传产品资料、FAQ、价格说明，机器人即可开始回答"
              />
            ),
          }}
          columns={[
            {
              title: "文档",
              render: (_, doc) => (
                <Space>
                  <span style={{ fontSize: 18 }}>{TYPE_ICON[doc.source_type]}</span>
                  <div style={{ lineHeight: 1.3 }}>
                    <div style={{ fontWeight: 550 }}>{doc.title}</div>
                    {doc.source_url && (
                      <div style={{ fontSize: 12, color: "#94a3b8" }}>{doc.source_url}</div>
                    )}
                  </div>
                </Space>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 110,
              render: (s: string) => (
                <Tag
                  color={DOC_STATUS[s]?.color}
                  icon={s === "indexing" ? <SyncOutlined spin /> : undefined}
                >
                  {DOC_STATUS[s]?.label ?? s}
                </Tag>
              ),
            },
            { title: "版本", dataIndex: "version", width: 70, render: (v: number) => `v${v}` },
            { title: "更新时间", dataIndex: "updated_at", width: 120, render: fromNow },
            {
              title: "启用",
              width: 80,
              render: (_, doc) => (
                <Switch
                  size="small"
                  checked={doc.status === "active"}
                  disabled={doc.status === "indexing" || doc.status === "pending"}
                  onChange={(checked) =>
                    run(
                      () =>
                        api.patch(`/api/knowledge/documents/${doc.id}`, {
                          status: checked ? "active" : "disabled",
                        }),
                      checked ? "已启用" : "已停用",
                    )
                  }
                />
              ),
            },
            {
              title: "操作",
              width: 170,
              render: (_, doc) => (
                <Space>
                  <Button
                    size="small"
                    type="text"
                    onClick={() =>
                      run(() => api.post(`/api/knowledge/documents/${doc.id}/reindex`), "已加入索引队列")
                    }
                  >
                    重建索引
                  </Button>
                  <Popconfirm
                    title="删除该文档及其全部索引与原始文件？"
                    onConfirm={() => run(() => api.del(`/api/knowledge/documents/${doc.id}`), "已删除")}
                  >
                    <Button size="small" type="text" danger>
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
        okText="导入"
      >
        <Form
          form={urlForm}
          layout="vertical"
          onFinish={(values) =>
            run(() => api.post("/api/knowledge/documents/url", values), "已导入，开始索引").then(
              () => {
                setUrlModalOpen(false);
                urlForm.resetFields();
              },
              () => undefined,
            )
          }
        >
          <Form.Item name="title" label="标题" rules={[{ required: true, message: "请输入标题" }]}>
            <Input placeholder="如：产品定价说明" />
          </Form.Item>
          <Form.Item
            name="url"
            label="URL"
            rules={[{ required: true, type: "url", message: "请输入合法的 http(s) 地址" }]}
          >
            <Input placeholder="https://…" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
