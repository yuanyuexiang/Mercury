"""机器人固定文案（非 LLM 提示词——那些在 packages/llm/prompts.py）。中英双语后续按需扩展。"""

WELCOME = (
    "你好！我是客服助手，可以回答关于我们产品的问题。\n"
    "隐私说明：对话内容仅用于客服与销售跟进，输入 /human 可随时转人工。"
)

RESET_DONE = "会话已重新开始。请问有什么可以帮您？"

HUMAN_ACK = "已通知人工客服，稍后会有同事跟进。"

HUMAN_ALREADY = (
    "人工客服已收到通知，正在赶来，请稍候。\n"
    "The team has already been notified — someone will be with you shortly."
)

NON_TEXT_UNSUPPORTED = "目前仅支持文字消息，请用文字描述您的问题。"

FALLBACK_ERROR = "系统繁忙，已通知人工客服跟进，抱歉给您带来不便。"

REFUSED_NO_ANSWER = (
    "抱歉，我暂时无法从官方资料中确认这一点，已通知人工同事跟进。\n"
    "Sorry, I can't confirm this from our official materials — a teammate will follow up."
)

SENSITIVE_TO_HUMAN = (
    "这个问题需要人工同事处理，已为您转接，请稍候。\n"
    "This needs a human colleague — transferring you now, one moment."
)

SMALLTALK = (
    "您好！我是产品客服助手，欢迎咨询产品功能、部署方式与价格。\n"
    "Hi! I'm the product assistant — feel free to ask about features, deployment, or pricing."
)

LLM_NOT_CONFIGURED = (
    "系统暂未就绪，已通知人工同事尽快回复您。\n"
    "The assistant is not ready yet — a teammate will get back to you shortly."
)
