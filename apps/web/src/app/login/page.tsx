"use client";
// 登录页：品牌区 + 表单（POST /api/auth/login → cookie 会话）。
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { brandTitle, fetchBrandName } from "@/lib/brand";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [brand, setBrand] = useState("");

  useEffect(() => {
    fetchBrandName().then((b) => {
      setBrand(b);
      document.title = `${brandTitle(b)} · 登录`;
    });
  }, []);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError(null);
    try {
      await api.post("/api/auth/login", values);
      router.push("/dashboard");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "登录失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background:
          "radial-gradient(1200px 600px at 20% -10%, rgba(47,84,235,0.28), transparent 60%), radial-gradient(900px 500px at 110% 110%, rgba(19,194,194,0.18), transparent 55%), #0f172a",
        padding: 24,
      }}
    >
      <div style={{ width: 400, maxWidth: "100%" }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              margin: "0 auto 14px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "linear-gradient(135deg,#2F54EB,#13C2C2)",
              color: "#fff",
              fontSize: 26,
              fontWeight: 700,
              boxShadow: "0 8px 24px rgba(47,84,235,0.35)",
            }}
          >
            {brandTitle(brand).charAt(0).toUpperCase()}
          </div>
          <Typography.Title level={3} style={{ color: "#fff", margin: 0 }}>
            {brandTitle(brand)}
          </Typography.Title>
          <Typography.Text style={{ color: "rgba(255,255,255,0.65)" }}>
            询盘自动转化系统
          </Typography.Text>
        </div>

        <div
          style={{
            background: "#fff",
            borderRadius: 14,
            padding: "28px 28px 20px",
            boxShadow: "0 20px 60px rgba(2,6,23,0.45)",
          }}
        >
          {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
          <Form layout="vertical" onFinish={onFinish} size="large" requiredMark={false}>
            <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} size="large">
              登 录
            </Button>
          </Form>
        </div>
        <Typography.Paragraph
          style={{ textAlign: "center", color: "rgba(255,255,255,0.4)", marginTop: 20, fontSize: 12 }}
        >
          {brand ? "Powered by Mercury" : "Turn conversations into qualified sales leads"}
        </Typography.Paragraph>
      </div>
    </main>
  );
}
