// 品牌白标（§20 配置面）：从免认证的 /api/meta 读 BRAND_NAME，会话内缓存。
// 空品牌 = 未配置，回落到产品名 Mercury。

let cached: string | null = null;

export async function fetchBrandName(): Promise<string> {
  if (cached !== null) return cached;
  try {
    const res = await fetch("/api/meta");
    const data = (await res.json()) as { brand_name?: string };
    cached = data.brand_name?.trim() ?? "";
  } catch {
    cached = "";
  }
  return cached;
}

export const brandTitle = (brand: string): string => brand || "Mercury";
