// 常见 OpenAI 兼容供应商预设：选择即自动填 base_url/推荐模型，客户只贴 key。
// embedding 须 1536 维（text-embedding-3-small），非 OpenAI 供应商 embed 留空走 env 兜底。

export interface ProviderPreset {
  label: string;
  base_url: string;
  chat_model: string;
  embed_model: string;
  supports_json_schema: boolean;
  keyUrl: string;
  note: string;
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    label: "DeepSeek",
    base_url: "https://api.deepseek.com/v1",
    chat_model: "deepseek-chat",
    embed_model: "",
    supports_json_schema: false,
    keyUrl: "https://platform.deepseek.com/api_keys",
    note: "性价比高，国内直连；不提供 embedding，需另配 OpenAI 或走 env 兜底",
  },
  {
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    chat_model: "gpt-4o-mini",
    embed_model: "text-embedding-3-small",
    supports_json_schema: true,
    keyUrl: "https://platform.openai.com/api-keys",
    note: "对话 + embedding 一站配齐（唯一自带 1536 维 embedding 的预设）",
  },
  {
    label: "OpenRouter（一个 key 用几百个模型）",
    base_url: "https://openrouter.ai/api/v1",
    chat_model: "openai/gpt-4o-mini",
    embed_model: "",
    supports_json_schema: false,
    keyUrl: "https://openrouter.ai/settings/keys",
    note: "聚合网关：注册一次即可切换各家模型，适合不想到处注册的客户",
  },
  {
    label: "SiliconFlow 硅基流动",
    base_url: "https://api.siliconflow.cn/v1",
    chat_model: "deepseek-ai/DeepSeek-V3",
    embed_model: "",
    supports_json_schema: false,
    keyUrl: "https://cloud.siliconflow.cn/account/ak",
    note: "国内聚合站，开源模型全，国内网络友好",
  },
  {
    label: "Moonshot Kimi",
    base_url: "https://api.moonshot.cn/v1",
    chat_model: "moonshot-v1-8k",
    embed_model: "",
    supports_json_schema: false,
    keyUrl: "https://platform.moonshot.cn/console/api-keys",
    note: "长上下文见长",
  },
  {
    label: "智谱 GLM",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    chat_model: "glm-4-flash",
    embed_model: "",
    supports_json_schema: false,
    keyUrl: "https://open.bigmodel.cn/usercenter/apikeys",
    note: "glm-4-flash 免费额度大，适合试用",
  },
  {
    label: "阿里云通义（DashScope）",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    chat_model: "qwen-plus",
    embed_model: "",
    supports_json_schema: false,
    keyUrl: "https://bailian.console.aliyun.com/?apiKey=1",
    note: "阿里云生态，qwen 系列",
  },
];
