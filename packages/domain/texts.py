"""机器人固定文案（非 LLM 提示词——那些在 packages/llm/prompts.py）。

所有客户可见文案按客户语言输出：lang 提示可为 Telegram language_code（zh-hans/en/…）
或 triage 识别结果（zh/en/auto）；"auto"/空默认中文，非中文一律英文。
文案纪律：对客户绝不暴露内部概念（知识库/资料/系统架构）；拒答语气是"接住"
（帮您找专人确认，欢迎继续问别的）而非"推开"（我不知道）。
"""


def _is_zh(lang: str) -> bool:
    lowered = (lang or "").strip().lower()
    if lowered in ("", "auto"):
        return True
    return lowered.startswith("zh") or "chinese" in lowered or "中文" in lowered


def welcome(brand_name: str = "", lang: str = "") -> str:
    """欢迎语（/start）：品牌名按客户实例配置（§20）。"""
    if _is_zh(lang):
        who = f"{brand_name}客服助手" if brand_name else "客服助手"
        return (
            f"你好！我是{who}，可以回答关于我们产品的问题。\n"
            "隐私说明：对话内容仅用于客服与销售跟进，输入 /human 可随时转人工。"
        )
    who = f"the {brand_name} assistant" if brand_name else "the support assistant"
    return (
        f"Hi! I'm {who} — ask me anything about our product.\n"
        "Privacy note: this chat is used for support and sales follow-up. "
        "Send /human anytime to reach a person."
    )


def revive_follow_up(brand_name: str = "") -> str:
    """沉睡唤醒（确定性模板，不走 LLM——绝不编造承诺）。刻意双语：沉睡客户语言不确定。"""
    who = f"{brand_name}的" if brand_name else "我们的"
    return (
        f"您好，之前的咨询如果还有想了解的，随时告诉我；"
        f"也可以直接说「约演示」或「要报价」，{who}同事会尽快联系您。\n"
        "Hi again — happy to pick up where we left off. "
        'Ask me anything, or just say "demo" or "quote" and our team will reach out.'
    )


def reset_done(lang: str = "") -> str:
    if _is_zh(lang):
        return "会话已重新开始。请问有什么可以帮您？"
    return "Conversation restarted. How can I help?"


def human_ack(lang: str = "") -> str:
    if _is_zh(lang):
        return "好的，已通知人工同事，很快来接待您。"
    return "Got it — a teammate has been notified and will be with you shortly."


def human_already(lang: str = "") -> str:
    if _is_zh(lang):
        return "人工同事已经在赶来的路上了，请稍候。"
    return "The team is already on the way — one moment please."


def sensitive_to_human(lang: str = "") -> str:
    if _is_zh(lang):
        return "这个问题由人工同事为您处理更稳妥，已为您转接，请稍候。"
    return "This is best handled by a human colleague — connecting you now, one moment."


def refused_no_answer(lang: str = "") -> str:
    if _is_zh(lang):
        return (
            "这个问题我帮您请同事来确认，以免给您不准确的信息——他们会尽快回复您。"
            "产品、价格、交付方面的问题，欢迎继续问我。"
        )
    return (
        "I'd rather have a teammate confirm this for you than guess — "
        "they've been notified and will follow up shortly. "
        "Meanwhile, happy to answer anything about the product, pricing or delivery."
    )


def purchase_ack(lang: str = "") -> str:
    """购买意向表态（非提问）的接单确认：只确认不追问——
    信息收集让给 extract_lead 的追问，避免两条消息抢话。"""
    if _is_zh(lang):
        return "收到！我已经把您的需求转给同事，会尽快联系您对接。"
    return "Great — I've passed your request to our team and they'll reach out shortly."


def purchase_reassure(lang: str = "") -> str:
    """已有线索的客户再次催促购买：安抚推进，与首次接单确认措辞区分开。"""
    if _is_zh(lang):
        return "收到，同事正在安排对接，会尽快联系您！"
    return "On it — our team is arranging the follow-up and will contact you very soon."


def casual_ack(lang: str = "") -> str:
    """已有线索会话里的短消息（"好的/不需要/谢谢"）：轻确认，不自我介绍、不打扰运营。"""
    if _is_zh(lang):
        return "好的！有其他问题随时找我。"
    return "Got it — I'm here if you need anything else."


def smalltalk(lang: str = "") -> str:
    if _is_zh(lang):
        return "您好！我是产品客服助手，产品功能、价格、部署方式都可以问我。"
    return "Hi! Ask me anything about the product — features, pricing, or how to get set up."


def non_text_unsupported(lang: str = "") -> str:
    if _is_zh(lang):
        return "目前仅支持文字消息，请用文字描述您的问题。"
    return "I can only read text for now — please type your question."


def fallback_error(lang: str = "") -> str:
    if _is_zh(lang):
        return "不好意思，系统开小差了，已通知人工同事跟进。"
    return "Something went wrong on our side — a teammate has been notified. Sorry about that!"


def llm_not_configured(lang: str = "") -> str:
    if _is_zh(lang):
        return "系统正在维护，已通知人工同事尽快回复您。"
    return "We're doing a bit of maintenance — a teammate will get back to you shortly."
