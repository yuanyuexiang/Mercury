"use client";
// 推广获客：渠道深链生成器（链接 + 二维码 + 可复制话术）+ 各渠道效果统计。
// Mercury 是转化引擎——这页帮客户把机器人链接铺到自己的引流触点上，并看清哪个触点值钱。
import { CheckOutlined, CopyOutlined, DownloadOutlined } from "@ant-design/icons";
import { Alert, App, Card, Col, Empty, Input, QRCode, Row, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import { brandTitle, fetchBrandName } from "@/lib/brand";

interface ChannelRow {
  channel: string | null;
  conversations: number;
  leads: number;
  leads_high: number;
}

// 常见引流触点：渠道标识 + 放置建议
const SPOTS: Array<{ key: string; label: string; hint: string }> = [
  { key: "tg_bio", label: "Telegram 简介", hint: "个人/频道简介里挂链接，最零成本的入口" },
  { key: "tg_group", label: "Telegram 群", hint: "在相关群里回答问题后，附一句「详情问我的机器人」" },
  { key: "yt", label: "YouTube", hint: "视频描述区第一行放链接" },
  { key: "tw", label: "Twitter / X", hint: "个人简介 + 置顶推文" },
  { key: "ig", label: "Instagram", hint: "Bio 链接（也可用 Linktree 聚合）" },
  { key: "web", label: "官网 / 落地页", hint: "「在线咨询」按钮直接指向机器人" },
  { key: "wechat", label: "微信 / 朋友圈", hint: "发二维码图片，扫码直达机器人" },
  { key: "offline", label: "线下 / 名片", hint: "名片、易拉宝印二维码" },
];

export default function PromotionPage() {
  const { message } = App.useApp();
  const [botUsername, setBotUsername] = useState("");
  const [brand, setBrand] = useState("");
  const [channels, setChannels] = useState<ChannelRow[]>([]);
  const [spot, setSpot] = useState(SPOTS[0]);
  const [customChannel, setCustomChannel] = useState("");
  const [copied, setCopied] = useState("");
  const qrWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .get<{ bot_username: string }>("/api/settings/setup-status")
      .then((d) => setBotUsername(d.bot_username))
      .catch(() => {});
    api
      .get<{ channels: ChannelRow[] }>("/api/metrics/overview")
      .then((d) => setChannels(d.channels))
      .catch(() => {});
    fetchBrandName().then(setBrand);
  }, []);

  const channelKey = (customChannel.trim() || spot.key).replace(/[^A-Za-z0-9_-]/g, "");
  const link = botUsername ? `https://t.me/${botUsername}?start=${channelKey}` : "";
  const brandName = brandTitle(brand);

  const copy = async (text: string, tag: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(tag);
      message.success("已复制");
      setTimeout(() => setCopied(""), 2000);
    } catch {
      message.error("复制失败，请手动选择复制");
    }
  };

  const downloadQr = () => {
    const canvas = qrWrapRef.current?.querySelector("canvas");
    if (!canvas) return;
    const a = document.createElement("a");
    a.download = `${channelKey}-qrcode.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  };

  const scripts = [
    `我们的 AI 客服 24 小时在线，产品功能、价格、方案都能直接问：${link}`,
    `想了解 ${brandName} 的话，点这里直接和我们的智能客服聊：${link}`,
    `有问题随时问 👉 ${link}（AI 秒回，复杂问题会转人工）`,
  ];

  return (
    <div>
      <PageHeader
        title="推广获客"
        subtitle="把机器人链接铺到你的引流触点——每个触点用不同链接，系统自动统计哪个触点值钱"
      />

      {!botUsername && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="还没有连接 Telegram 机器人"
          description={
            <span>
              先到<Link href="/system">「系统设置」</Link>完成机器人接入，这里才能生成推广链接。
            </span>
          }
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="第一步：选择你要推广的位置">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {SPOTS.map((s) => (
                <Tag.CheckableTag
                  key={s.key}
                  checked={spot.key === s.key && !customChannel}
                  onChange={() => {
                    setSpot(s);
                    setCustomChannel("");
                  }}
                  style={{ fontSize: 13, padding: "3px 10px", userSelect: "none" }}
                >
                  {s.label}
                </Tag.CheckableTag>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 12.5, color: "#64748b" }}>💡 {spot.hint}</div>
            <Input
              style={{ marginTop: 10, maxWidth: 320 }}
              size="small"
              placeholder="或自定义渠道名（字母数字，如 douyin、campaign1）"
              value={customChannel}
              onChange={(e) => setCustomChannel(e.target.value)}
            />
          </Card>

          <Card title="第二步：复制链接或话术，贴出去" style={{ marginTop: 16 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Input value={link} readOnly style={{ fontFamily: "monospace" }} />
              <Typography.Link onClick={() => copy(link, "link")} style={{ flexShrink: 0 }}>
                {copied === "link" ? <CheckOutlined /> : <CopyOutlined />} 复制
              </Typography.Link>
            </div>
            <div style={{ marginTop: 14 }}>
              {scripts.map((text, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "flex-start",
                    padding: "8px 12px",
                    background: "#f8fafc",
                    borderRadius: 8,
                    marginBottom: 8,
                    fontSize: 13,
                    lineHeight: 1.6,
                  }}
                >
                  <span style={{ flex: 1, wordBreak: "break-all" }}>{text}</span>
                  <Typography.Link onClick={() => copy(text, `s${i}`)} style={{ flexShrink: 0 }}>
                    {copied === `s${i}` ? <CheckOutlined /> : <CopyOutlined />}
                  </Typography.Link>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card
            title="二维码（微信 / 朋友圈 / 线下用）"
            extra={
              botUsername && (
                <Typography.Link onClick={downloadQr} style={{ fontSize: 12 }}>
                  <DownloadOutlined /> 下载 PNG
                </Typography.Link>
              )
            }
          >
            <div ref={qrWrapRef} style={{ textAlign: "center", padding: "8px 0" }}>
              {botUsername ? (
                <>
                  <QRCode value={link} size={180} style={{ margin: "0 auto" }} />
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 10 }}>
                    扫码直达 @{botUsername} · 渠道标记：{channelKey}
                  </div>
                </>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="连接机器人后生成" />
              )}
            </div>
          </Card>

          <Card title="各触点效果（近 14 天）" style={{ marginTop: 16 }}>
            {channels.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="链接撒出去后，这里会告诉你哪个触点在出线索"
              />
            ) : (
              <Table
                rowKey={(r) => r.channel ?? "__direct__"}
                dataSource={channels}
                size="small"
                pagination={false}
                columns={[
                  {
                    title: "渠道",
                    dataIndex: "channel",
                    render: (c: string | null) =>
                      c ?? <span style={{ color: "#94a3b8" }}>直接进入</span>,
                  },
                  { title: "会话", dataIndex: "conversations", width: 64, align: "right" },
                  { title: "线索", dataIndex: "leads", width: 64, align: "right" },
                  {
                    title: "高意向",
                    dataIndex: "leads_high",
                    width: 72,
                    align: "right",
                    render: (v: number) =>
                      v > 0 ? <span style={{ color: "#F5222D", fontWeight: 600 }}>{v}</span> : v,
                  },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
