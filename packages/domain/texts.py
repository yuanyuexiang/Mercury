"""机器人固定文案（非 LLM 提示词——那些在 packages/llm/prompts.py）。中英双语后续按需扩展。"""


def welcome(brand_name: str = "") -> str:
    """欢迎语（/start）：品牌名按客户实例配置（§20）。"""
    who = f"{brand_name}客服助手" if brand_name else "客服助手"
    return (
        f"你好！我是{who}，可以回答关于我们产品的问题。\n"
        "隐私说明：对话内容仅用于客服与销售跟进，输入 /human 可随时转人工。"
    )


def revive_follow_up(brand_name: str = "") -> str:
    """沉睡唤醒（确定性模板，不走 LLM——绝不编造承诺）。"""
    who = f"{brand_name}的" if brand_name else "我们的"
    return (
        f"您好，之前的咨询如果还有想了解的，随时告诉我；"
        f"也可以直接说「约演示」或「要报价」，{who}同事会尽快联系您。\n"
        "Hi again — happy to pick up where we left off. "
        'Ask me anything, or just say "demo" or "quote" and our team will reach out.'
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
