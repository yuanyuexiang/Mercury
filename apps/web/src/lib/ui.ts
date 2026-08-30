// 展示层共享：时间格式化、状态/等级/评分理由的中文标签与配色。
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import relativeTime from "dayjs/plugin/relativeTime";

dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

export const fromNow = (iso?: string | null): string => (iso ? dayjs(iso).fromNow() : "—");
export const fmtTime = (iso?: string | null): string =>
  iso ? dayjs(iso).format("MM-DD HH:mm") : "—";
export const fmtFull = (iso?: string | null): string =>
  iso ? dayjs(iso).format("YYYY-MM-DD HH:mm") : "—";

export interface Labeled {
  label: string;
  color: string;
}

export const CONV_STATUS: Record<string, Labeled> = {
  ai_active: { label: "AI 接待中", color: "success" },
  handoff_pending: { label: "待人工接管", color: "warning" },
  human_active: { label: "人工接待中", color: "processing" },
  closed: { label: "已关闭", color: "default" },
};

export const GRADE: Record<string, Labeled> = {
  high: { label: "高意向", color: "red" },
  medium: { label: "中意向", color: "orange" },
  low: { label: "低意向", color: "default" },
};

export const LEAD_STATUS: Record<string, Labeled> = {
  open: { label: "跟进中", color: "processing" },
  synced: { label: "已同步", color: "success" },
  won: { label: "已成交", color: "green" },
  lost: { label: "已流失", color: "default" },
};

export const DOC_STATUS: Record<string, Labeled> = {
  pending: { label: "待索引", color: "default" },
  indexing: { label: "索引中", color: "processing" },
  active: { label: "已启用", color: "success" },
  disabled: { label: "已停用", color: "default" },
  failed: { label: "索引失败", color: "error" },
};

export const SCORE_REASON: Record<string, string> = {
  company_email: "企业邮箱 +15",
  clear_need: "明确需求 +20",
  team_size_fit: "团队规模达标 +15",
  budget_given: "提供预算 +15",
  timeline_30d: "30 天内采购 +20",
  asked_demo: "主动要 Demo/报价 +25",
  freebie_only: "仅求免费资源 −20",
};

export const HANDOFF_REASON: Record<string, string> = {
  user_request: "用户请求人工",
  low_confidence: "知识库无法回答",
  sensitive: "敏感问题",
  high_intent: "高意向线索",
  manual: "管理员发起",
};

const AVATAR_COLORS = ["#2F54EB", "#13C2C2", "#722ED1", "#EB2F96", "#FA8C16", "#52C41A"];

export const avatarColor = (seed: number): string =>
  AVATAR_COLORS[Math.abs(seed) % AVATAR_COLORS.length];

export const displayName = (user: {
  username?: string | null;
  first_name?: string | null;
  telegram_user_id: number;
}): string => (user.username ? `@${user.username}` : (user.first_name ?? String(user.telegram_user_id)));

export const initialOf = (name: string): string =>
  (name.replace("@", "").charAt(0) || "?").toUpperCase();
