// 同域 /api fetch 封装（技术方案 §3/§14）：cookie 会话、写请求带 CSRF 头、401 跳登录。
import "@ant-design/v5-patch-for-react-19";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, { credentials: "same-origin", ...options });
  if (resp.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new ApiError(401, "未登录");
  }
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(resp.status, (body as { detail?: string }).detail ?? `请求失败（${resp.status}）`);
  }
  return body as T;
}

const writeHeaders = { "X-Requested-With": "fetch", "Content-Type": "application/json" };

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: writeHeaders,
      body: data === undefined ? "{}" : JSON.stringify(data),
    }),
  patch: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PATCH", headers: writeHeaders, body: JSON.stringify(data) }),
  del: <T>(path: string) =>
    request<T>(path, { method: "DELETE", headers: { "X-Requested-With": "fetch" } }),
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, {
      method: "POST",
      headers: { "X-Requested-With": "fetch" },
      body: formData,
    }),
};
