"""演示数据种子脚本：为管理后台灌入一套可讲故事的假数据（概览/会话/线索/渠道/成本全有内容）。

用法（需 DATABASE_URL 指向已跑过 migration 的库）：
  uv run python scripts/seed_demo.py           # 重建演示数据（先清后插，可重复执行）
  uv run python scripts/seed_demo.py --wipe    # 只清除演示数据，不插入

生产容器内（镜像未含 scripts/ 时先 docker compose cp 拷入）：
  docker compose -f compose.prod.yaml cp scripts/seed_demo.py api:/tmp/seed_demo.py
  docker compose -f compose.prod.yaml exec api python /tmp/seed_demo.py

安全边界：
- 所有演示实体可识别、可整体清除：users.telegram_user_id 落在 990000000–990999999 保留段，
  telegram_updates.update_id 落在 9900000000+ 保留段；--wipe 按此定界删除（FK 级联带走
  conversations/messages/leads/handoffs）。真实数据不受影响。
- 不创建 integration_jobs（假线索绝不会被 worker 推到真实 Google Sheet）。
- 所有演示线索 revive_count=1：默认唤醒上限为 1，沉睡唤醒 cron 不会给假 chat 发消息。
  若后台把唤醒上限调到 >1，请先清掉演示数据再演示唤醒功能。
- 演示内容主题与 docs/knowledge/ 的 Mercury 示例知识库一致，现场追问可无缝衔接真实 RAG。
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from domain import texts
from domain.config import get_settings
from domain.models import (
    Conversation,
    Handoff,
    Lead,
    Message,
    TelegramUpdate,
    User,
)
from domain.scoring import score_lead
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 演示数据保留段（--wipe 按此定界，绝不触碰真实数据）
DEMO_TG_MIN = 990_000_000
DEMO_TG_MAX = 990_999_999
DEMO_UPDATE_BASE = 9_900_000_000

BRAND = "Mercury"

_rng = random.Random(2026)

# 角色：u=用户 inbound；a=AI 回答；r=AI 拒答；h=AI 转人工提示；op=人工回复；w=欢迎语；rev=沉睡唤醒
Turn = tuple[str, str]


def _scenarios() -> list[dict[str, Any]]:
    """18 个会话：14 天增长趋势 + 各渠道 + 各状态 + 11 条分层线索（4 高 6 中 1 低）。"""
    return [
        {
            "user": (1, "amy_crossborder", "Amy", None, "zh-hans"),
            "channel": None,
            "day": 13.6,
            "status": "closed",
            "turns": [
                ("u", "/start"),
                ("w", ""),
                ("u", "你们这个机器人是做什么的？"),
                (
                    "a",
                    "Mercury 是部署在 Telegram 上的 AI 获客助手：用你的产品资料回答客户咨询、"
                    "自动提取和评分销售线索、高意向即时通知你、需要时一键转人工。"
                    "适合用 Telegram 触达客户的外贸、跨境电商和 SaaS 团队。"
                    "想了解接入方式或价格吗？",
                ),
                ("u", "好的谢谢，我先看看"),
                ("a", "好的，随时欢迎回来提问；想看演示直接说「约演示」就可以。"),
            ],
        },
        {
            "user": (2, "rahul_builds", "Rahul", "Mehta", "en"),
            "channel": "tw",
            "day": 12.4,
            "status": "ai_active",
            "turns": [
                ("u", "Hi, does the bot answer in English?"),
                (
                    "a",
                    "Yes — it automatically replies in the customer's language (English, "
                    "Chinese and other major languages), even if your knowledge base is "
                    "written in Chinese.",
                ),
                (
                    "u",
                    "Nice. We're a small SaaS team (8 people), we want to qualify leads coming "
                    "from our Telegram group. Budget is around $100-200/mo.",
                ),
                (
                    "a",
                    "That's exactly the use case. Mercury answers product questions from your own "
                    "docs, extracts and scores each lead, and pings you the moment someone shows "
                    "real buying intent. Current pilot is a one-time $500-1000 setup with 2 weeks "
                    "of support. Would you like a quick demo?",
                ),
                ("rev", ""),
            ],
            "lead": {
                "name": "Rahul Mehta",
                "company": None,
                "country": "India",
                "business_email": None,
                "requirement": "SaaS 团队想对 Telegram 群里进来的咨询做自动答疑和线索筛选",
                "team_size": "8",
                "budget_range": "$100-200/mo",
                "purchase_timeline": None,
                "notes": "预算偏订阅制，与试点一次性报价有差距；已发试点方案，待回复。",
                "status": "open",
                "revived": True,
            },
        },
        {
            "user": (3, "liwei_soho", "李伟", None, "zh-hans"),
            "channel": "wechat",
            "day": 11.3,
            "status": "closed",
            "turns": [
                ("u", "有没有免费版可以用？"),
                (
                    "a",
                    "目前没有免费版。当前是限量试点方案：一次性 $500–1000 包部署、知识库整理、"
                    "评分规则定制和两周试运行支持，7–14 天交付。如果预算有限，可以先聊聊你的场景，"
                    "看看是否值得排进试点名额。",
                ),
                ("u", "那算了，我就想找个免费的玩玩"),
                ("a", "理解！有需要随时回来找我。"),
            ],
            "lead": {
                "name": "李伟",
                "company": None,
                "country": "中国",
                "business_email": None,
                "requirement": "想找免费的 Telegram 客服机器人试玩",
                "team_size": None,
                "budget_range": None,
                "purchase_timeline": None,
                "freebie_only": True,
                "notes": "仅寻找免费方案，无付费意愿，已礼貌收尾。",
                "status": "lost",
            },
        },
        {
            "user": (4, "sophia_bright", "Sophia", "Lane", "en"),
            "channel": "web",
            "day": 10.5,
            "status": "ai_active",
            "turns": [
                ("u", "How much does this cost?"),
                (
                    "a",
                    "The current pilot package is a one-time $500-1000 depending on complexity: "
                    "dedicated deployment, bot setup, knowledge base import, custom lead scoring, "
                    "Google Sheets sync, and 2 weeks of support. Delivery in 7-14 days.",
                ),
                (
                    "u",
                    "We run Telegram channels for 6 clients at our agency — could we resell this "
                    "as part of our service?",
                ),
                (
                    "a",
                    "Each client gets an independent instance with its own database, so an "
                    "agency-reseller setup works naturally. Partner terms would be discussed "
                    "directly with our team — shall I have someone reach out?",
                ),
                (
                    "u",
                    "Yes please, send me a demo. My email is sophia@brightreach.io — budget "
                    "around $800 one-time is fine, we'd want the first client live within 2 weeks.",
                ),
                (
                    "a",
                    "Got it, Sophia — demo and partner details are on the way to "
                    "sophia@brightreach.io. Our team will follow up within one business day.",
                ),
            ],
            "lead": {
                "name": "Sophia Lane",
                "company": "BrightReach Agency",
                "country": "United States",
                "business_email": "sophia@brightreach.io",
                "requirement": "营销代理想为 6 个客户的 Telegram 频道转售 AI 获客机器人",
                "team_size": "6 个客户频道",
                "budget_range": "$800 一次性",
                "purchase_timeline": "2 weeks",
                "asked_demo": True,
                "integrations": ["Google Sheets"],
                "notes": "代理商转售场景，已索取 demo 与合作条款；高优先级跟进。",
                "status": "synced",
                "external_crm_id": "demo-sheet-row-12",
                "version": 3,
            },
            "handoff": ("high_intent", "resolved"),
        },
        {
            "user": (5, "carlos_tienda", "Carlos", None, "es"),
            "channel": "yt",
            "day": 9.4,
            "status": "ai_active",
            "turns": [
                ("u", "Can it handle support for a Shopify store?"),
                (
                    "a",
                    "Yes — upload your store FAQ, shipping and product docs, and the bot answers "
                    "customer questions on Telegram strictly from those materials, escalating to "
                    "you when it's not sure.",
                ),
                ("u", "Do you integrate with WhatsApp?"),
                ("r", ""),
            ],
        },
        {
            "user": (6, "meiling_edu", "王美玲", None, "zh-hans"),
            "channel": "tg_group",
            "day": 8.5,
            "status": "ai_active",
            "turns": [
                ("u", "我们是做在线教育的，20 人团队，想用机器人回答课程咨询，可以吗？"),
                (
                    "a",
                    "完全可以。把课程介绍、价格表、常见问题上传到知识库，机器人就只依据这些资料回答，"
                    "资料里没有的内容会明确说无法确认并转人工，不会乱承诺。同时每个咨询的家长/学员"
                    "会被自动记录成线索并评分，高意向的第一时间通知你们的课程顾问。",
                ),
                ("u", "听起来不错，我跟合伙人商量一下"),
                ("a", "好的，需要演示或报价随时说一声。"),
                ("rev", ""),
            ],
            "lead": {
                "name": "王美玲",
                "company": None,
                "country": "中国",
                "business_email": None,
                "requirement": "在线教育机构想用机器人承接课程咨询并筛选高意向学员",
                "team_size": "20 人团队",
                "budget_range": None,
                "purchase_timeline": None,
                "notes": "决策需与合伙人商量；已自动跟进一次，待回复。",
                "status": "open",
                "revived": True,
            },
        },
        {
            "user": (7, "deniz_nb", "Deniz", "Kaya", "en"),
            "channel": "tg_group",
            "day": 7.3,
            "status": "human_active",
            "turns": [
                (
                    "u",
                    "Hi, I run an IT services company in Istanbul. Does each client of "
                    "ours get their own bot?",
                ),
                (
                    "a",
                    "Yes — every client runs as an independent instance with its own database and "
                    "its own Telegram bot, fully isolated. That makes white-label or reseller "
                    "setups straightforward.",
                ),
                (
                    "u",
                    "I want to discuss partner pricing for 10+ clients. Can I talk to a person?",
                ),
                ("h", texts.HUMAN_ACK),
                (
                    "op",
                    "Hi Deniz, this is Tom from the Mercury team — great to meet you. "
                    "For 10+ instances we can do tiered partner pricing. When works for "
                    "a quick call this week?",
                ),
                ("u", "Thursday afternoon works for me (GMT+3)."),
                ("op", "Perfect, Thursday 3pm GMT+3 it is. Calendar invite coming your way."),
            ],
            "lead": {
                "name": "Deniz Kaya",
                "company": "Nordbridge IT",
                "country": "Türkiye",
                "business_email": None,
                "requirement": "IT 服务商想以合作伙伴身份为 10+ 客户部署白标实例",
                "team_size": None,
                "budget_range": None,
                "purchase_timeline": None,
                "asked_demo": True,
                "notes": "渠道合作线索，已约周四电话谈阶梯报价，人工跟进中。",
                "status": "open",
            },
            "handoff": ("user_request", "accepted"),
        },
        {
            "user": (8, "kenji_tanaka", "田中健", None, "ja"),
            "channel": None,
            "day": 6.6,
            "status": "closed",
            "turns": [
                ("u", "価格を教えてください (please tell me the price)"),
                (
                    "a",
                    "The current pilot is a one-time $500-1000 (scoped by complexity), including "
                    "deployment, knowledge base setup, custom scoring and 2 weeks of support.",
                ),
                ("u", "Thank you, that is above our budget for now."),
                ("a", "Understood — feel free to come back anytime. Good luck with the launch!"),
            ],
        },
        {
            "user": (9, "nina_onchain", "Nina", None, "en"),
            "channel": "tw",
            "day": 5.5,
            "status": "ai_active",
            "turns": [
                ("u", "如果上线后效果不好，能退款吗？"),
                ("h", texts.SENSITIVE_TO_HUMAN),
                (
                    "op",
                    "你好，我是 Mercury 团队的 Tom。退款条款我们在报价单里书面约定："
                    "试运行两周内不满意可退 50%。详细条款我发你邮箱？",
                ),
                ("u", "好的，先不用邮箱，我了解了，谢谢"),
            ],
            "handoff": ("sensitive", "resolved"),
        },
        {
            "user": (10, "omar_gulf", "Omar", "Haddad", "en"),
            "channel": "offline",
            "day": 5.2,
            "status": "closed",
            "turns": [
                (
                    "u",
                    "Hi, I scanned your QR code at the Dubai property expo. We run a real estate "
                    "agency and want a Telegram assistant for listing inquiries.",
                ),
                (
                    "a",
                    "Great to hear from you, Omar! That's a perfect fit — upload your listings and "
                    "FAQ, and the assistant answers buyer questions 24/7, captures each inquiry as "
                    "a scored lead, and hands hot buyers straight to your agents.",
                ),
                ("u", "What's the price?"),
                (
                    "a",
                    "One-time $500-1000 for the pilot: dedicated deployment, bot and knowledge "
                    "base setup, custom lead scoring, Google Sheets sync, 2 weeks of support. "
                    "Delivery in 7-14 days.",
                ),
                (
                    "u",
                    "OK, send the quote to omar@gulfestates.ae. We're a team of 15 agents and "
                    "want to start this month.",
                ),
                (
                    "a",
                    "Done — quote is on its way to omar@gulfestates.ae, and our team will follow "
                    "up to schedule kickoff this month.",
                ),
            ],
            "lead": {
                "name": "Omar Haddad",
                "company": "Gulf Estates",
                "country": "UAE",
                "business_email": "omar@gulfestates.ae",
                "requirement": "地产中介想用 Telegram 助手 7×24 承接房源咨询并分配高意向买家",
                "team_size": "15 agents",
                "budget_range": "$500-1000 一次性",
                "purchase_timeline": "this month",
                "asked_demo": True,
                "integrations": ["Google Sheets"],
                "notes": "迪拜展会扫码进入；报价已确认，项目本月启动——已成交。",
                "status": "won",
                "external_crm_id": "demo-sheet-row-9",
                "version": 4,
            },
            "handoff": ("high_intent", "resolved"),
        },
        {
            "user": (11, "lena_dtc", "Lena", None, "de"),
            "channel": "web",
            "day": 4.4,
            "status": "ai_active",
            "turns": [
                ("u", "How is my customer data stored? We're in the EU."),
                (
                    "a",
                    "Each customer runs a fully isolated deployment with its own database. "
                    "Secrets live only in environment variables, logs are redacted, and you can "
                    "export or delete any end-user's data by their Telegram ID at any time.",
                ),
                ("u", "Do you have case studies with real numbers you can share?"),
                ("r", ""),
            ],
        },
        {
            "user": (12, "zhangtao_saas", "张涛", None, "zh-hans"),
            "channel": "tg_group",
            "day": 3.5,
            "status": "ai_active",
            "turns": [
                (
                    "u",
                    "我们是做项目管理 SaaS 的，想让机器人在 Telegram 群里做售前答疑，"
                    "预算 3000 元内",
                ),
                (
                    "a",
                    "可以的。把产品文档和价格表导入知识库后，机器人只依据这些资料回答售前问题，"
                    "同时把每个咨询者沉淀成带评分的线索。3000 元在试点方案（$500 起）的范围内，"
                    "具体按需求复杂度报价。要不要先看个演示？",
                ),
                ("u", "先发我一份资料吧，我看完再约"),
                ("a", "好的，产品介绍和试点方案说明已整理好，你可以直接在这里继续提问。"),
            ],
            "lead": {
                "name": "张涛",
                "company": None,
                "country": "中国",
                "business_email": None,
                "requirement": "项目管理 SaaS 想在 Telegram 群做售前答疑与线索沉淀",
                "team_size": None,
                "budget_range": "3000 元内",
                "purchase_timeline": None,
                "notes": "已发资料，看完约演示；预算明确。",
                "status": "open",
            },
        },
        {
            "user": (13, "grace_hk", "Grace", "Chan", "zh-hant"),
            "channel": "yt",
            "day": 2.6,
            "status": "ai_active",
            "turns": [
                ("u", "睇咗你哋條片，想問下價錢同埋幾耐可以上線？"),
                (
                    "a",
                    "試點方案一次性 $500–1000（按複雜度報價），包部署、知識庫整理、評分規則定制同"
                    "兩週試運行支持，7–14 日交付，資料齊全一週內可以開始試用。",
                ),
                ("u", "我哋做電商，旺季前想搞掂，預算大概 $600，下個月先開始得唔得？"),
                (
                    "a",
                    "冇問題，$600 喺試點範圍內。下個月開始都得——建議提前一週把產品資料準備好，"
                    "上線就快。需要我同事跟你確認排期嗎？",
                ),
            ],
            "lead": {
                "name": "Grace Chan",
                "company": None,
                "country": "中国香港",
                "business_email": None,
                "requirement": "电商旺季前上线 Telegram 咨询机器人",
                "team_size": None,
                "budget_range": "$600",
                "purchase_timeline": "下个月",
                "notes": "旺季驱动，时间在一个月开外；待确认排期。",
                "status": "open",
            },
        },
        {
            "user": (14, "ivan_builds", "Ivan", None, "ru"),
            "channel": None,
            "day": 2.3,
            "status": "ai_active",
            "turns": [
                ("u", "What LLM do you use under the hood? Can I bring my own API key?"),
                (
                    "a",
                    "Any OpenAI-compatible provider works — OpenAI, DeepSeek and others. You can "
                    "bring your own API key, and the provider/model can be switched in the admin "
                    "panel at any time without redeploying.",
                ),
                ("u", "Good. And if the bot doesn't know an answer?"),
                (
                    "a",
                    "It says so explicitly and escalates to a human — it never invents prices, "
                    "SLAs or policies. Every answer is grounded in your uploaded documents with "
                    "source references you can inspect in the admin panel.",
                ),
            ],
        },
        {
            "user": (15, "sara_meridian", "Sara", "Whitfield", "en"),
            "channel": "web",
            "day": 1.4,
            "status": "ai_active",
            "turns": [
                (
                    "u",
                    "Hello — we're a 12-person consulting firm and we keep missing inbound "
                    "Telegram inquiries outside office hours.",
                ),
                (
                    "a",
                    "That's exactly what Mercury solves: it answers around the clock from your "
                    "own materials, records every inquiry as a scored lead, and notifies your "
                    "team instantly when someone's worth a call.",
                ),
                (
                    "u",
                    "Sounds right. Can we see a demo this week? I'm sara@meridianconsult.com",
                ),
                (
                    "a",
                    "Absolutely — demo details are headed to sara@meridianconsult.com and our "
                    "team will confirm a slot this week. Anything specific you'd like the demo "
                    "to focus on?",
                ),
            ],
            "lead": {
                "name": "Sara Whitfield",
                "company": "Meridian Consulting",
                "country": "United Kingdom",
                "business_email": "sara@meridianconsult.com",
                "requirement": "咨询公司想解决非工作时间 Telegram 咨询漏接问题",
                "team_size": "12",
                "budget_range": None,
                "purchase_timeline": "this week",
                "asked_demo": True,
                "notes": "痛点明确（漏接询盘），本周约演示。",
                "status": "open",
            },
            "handoff": ("high_intent", "resolved"),
        },
        {
            "user": (16, "mark_launchpad", "Mark", None, "en"),
            "channel": "tg_group",
            "day": 0.031,  # 约 45 分钟前
            "status": "handoff_pending",
            "turns": [
                (
                    "u",
                    "We're a SaaS startup, lots of free-trial signups ping us on Telegram. "
                    "Can the bot follow up with them automatically?",
                ),
                (
                    "a",
                    "Yes — it answers their questions from your docs, scores each signup's buying "
                    "intent, and can send a gentle follow-up to quiet conversations so trials "
                    "don't go cold. High-intent users get routed straight to you.",
                ),
                ("u", "/human I'd rather just talk to a person about setup"),
                ("h", texts.HUMAN_ACK),
            ],
            "lead": {
                "name": "Mark",
                "company": None,
                "country": None,
                "business_email": None,
                "requirement": "SaaS 免费试用用户的 Telegram 自动跟进与意向筛选",
                "team_size": None,
                "budget_range": None,
                "purchase_timeline": None,
                "asked_demo": True,
                "notes": "主动要求人工沟通接入细节，待接管。",
                "status": "open",
            },
            "handoff": ("user_request", "pending"),
        },
        {
            "user": (17, "julia_finexa", "Julia", "Moreau", "en"),
            "channel": "web",
            "day": 0.007,  # 约 10 分钟前
            "status": "handoff_pending",
            "turns": [
                (
                    "u",
                    "Hi, we're a 30-person fintech and need this ASAP for compliance-safe "
                    "customer support on Telegram. I'm julia@finexapay.com.",
                ),
                (
                    "a",
                    "Thanks Julia — Mercury only answers from your approved documents and "
                    "escalates anything sensitive to your team, which fits compliance-heavy "
                    "support well. I've noted your contact; our team can walk you through it.",
                ),
                ("u", "Before we share anything: can you sign an NDA and a DPA?"),
                ("h", texts.SENSITIVE_TO_HUMAN),
            ],
            "lead": {
                "name": "Julia Moreau",
                "company": "FinexaPay",
                "country": "France",
                "business_email": "julia@finexapay.com",
                "requirement": "金融科技公司需要合规安全的 Telegram 客服，涉及 NDA/DPA 签署",
                "team_size": "30",
                "budget_range": None,
                "purchase_timeline": "ASAP",
                "integrations": ["HubSpot"],
                "notes": "合规诉求（NDA/DPA）需人工处理；今日新增高意向，待接管。",
                "status": "open",
            },
            "handoff": ("sensitive", "pending"),
        },
        {
            "user": (18, "alexis_dev", "Alexis", None, "en"),
            "channel": "tw",
            "day": 0.0035,  # 约 5 分钟前
            "status": "ai_active",
            "turns": [
                ("u", "/start"),
                ("w", ""),
                ("u", "How long does setup take?"),
                (
                    "a",
                    "Pilot delivery is 7-14 days end to end; with your materials ready, you can "
                    "usually start trying it within a week.",
                ),
            ],
        },
    ]


def _ai_meta(day: float, content: str) -> dict[str, Any]:
    """AI 回复的模型元数据（喂给成本页）：早期与近一周用不同模型，演示后台切换供应商。"""
    model = "gpt-4o-mini" if day >= 7 else "deepseek-chat"
    completion = max(40, len(content) // 2 + _rng.randint(-20, 20))
    return {
        "model_name": model,
        "prompt_tokens": _rng.randint(700, 1500),
        "completion_tokens": completion,
        "latency_ms": _rng.randint(900, 3200),
        "confidence": round(_rng.uniform(0.78, 0.95), 2),
    }


async def wipe(session: AsyncSession) -> None:
    await session.execute(
        sql_text(
            "DELETE FROM integration_jobs WHERE entity_type = 'lead' AND entity_id IN ("
            "  SELECT l.id FROM leads l JOIN users u ON u.id = l.user_id"
            "  WHERE u.telegram_user_id BETWEEN :lo AND :hi)"
        ),
        {"lo": DEMO_TG_MIN, "hi": DEMO_TG_MAX},
    )
    await session.execute(
        sql_text("DELETE FROM users WHERE telegram_user_id BETWEEN :lo AND :hi"),
        {"lo": DEMO_TG_MIN, "hi": DEMO_TG_MAX},
    )
    await session.execute(
        sql_text("DELETE FROM telegram_updates WHERE update_id >= :base"),
        {"base": DEMO_UPDATE_BASE},
    )


async def seed(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    update_seq = DEMO_UPDATE_BASE
    counts = {"users": 0, "conversations": 0, "messages": 0, "leads": 0, "handoffs": 0}

    for scenario in _scenarios():
        offset, username, first, last, lang = scenario["user"]
        day: float = scenario["day"]
        conv_start = now - timedelta(days=day)

        user = User(
            telegram_user_id=DEMO_TG_MIN + offset,
            username=username,
            first_name=first,
            last_name=last,
            language_code=lang,
            created_at=conv_start,
            updated_at=conv_start,
        )
        session.add(user)
        await session.flush()
        counts["users"] += 1

        conv = Conversation(
            telegram_chat_id=DEMO_TG_MIN + offset,
            user_id=user.id,
            status=scenario["status"],
            source_channel=scenario.get("channel"),
            assigned_operator_id=1 if scenario["status"] == "human_active" else None,
            started_at=conv_start,
        )
        session.add(conv)
        await session.flush()
        counts["conversations"] += 1

        # 消息流：每轮间隔 40–150 秒；唤醒消息发生在最后一条消息 3 天后的 02:30 UTC 附近
        t = conv_start
        tg_msg_id = 1000 + offset * 100
        last_update_id: int | None = None
        last_msg_at = conv_start
        revive_at: datetime | None = None
        for role, content in scenario["turns"]:
            if role == "rev":
                revive_at = (t + timedelta(days=3)).replace(hour=2, minute=30 + offset % 10)
                lead_cfg = scenario.get("lead")
                brand = BRAND
                session.add(
                    Message(
                        conversation_id=conv.id,
                        direction="outbound",
                        sender_type="ai",
                        content=texts.revive_follow_up(brand),
                        delivery_key=f"demo:revive:{conv.id}",
                        delivery_status="sent",
                        created_at=revive_at,
                    )
                )
                counts["messages"] += 1
                last_msg_at = revive_at
                if lead_cfg is not None:
                    lead_cfg["_last_revived_at"] = revive_at
                continue

            t = t + timedelta(seconds=_rng.randint(40, 150))
            if role == "u":
                update_seq += 1
                last_update_id = update_seq
                tg_msg_id += 1
                session.add(
                    TelegramUpdate(
                        update_id=update_seq,
                        payload={"demo": True, "update_id": update_seq},
                        status="done",
                        received_at=t,
                        processed_at=t + timedelta(seconds=3),
                    )
                )
                # Message 与 TelegramUpdate 无 ORM relationship，flush 保证 FK 先落库
                await session.flush()
                session.add(
                    Message(
                        conversation_id=conv.id,
                        telegram_message_id=tg_msg_id,
                        source_update_id=update_seq,
                        direction="inbound",
                        sender_type="user",
                        content=content,
                        created_at=t,
                    )
                )
            elif role == "w":
                session.add(
                    Message(
                        conversation_id=conv.id,
                        source_update_id=last_update_id,
                        delivery_key=f"ack:{last_update_id}",
                        direction="outbound",
                        sender_type="ai",
                        content=texts.welcome(BRAND),
                        delivery_status="sent",
                        created_at=t,
                    )
                )
            elif role == "a":
                session.add(
                    Message(
                        conversation_id=conv.id,
                        source_update_id=last_update_id,
                        delivery_key=f"reply:{last_update_id}",
                        direction="outbound",
                        sender_type="ai",
                        content=content,
                        delivery_status="sent",
                        answer_status="answered",
                        created_at=t,
                        **_ai_meta(day, content),
                    )
                )
            elif role == "r":
                session.add(
                    Message(
                        conversation_id=conv.id,
                        source_update_id=last_update_id,
                        delivery_key=f"reply:{last_update_id}",
                        direction="outbound",
                        sender_type="ai",
                        content=texts.REFUSED_NO_ANSWER,
                        delivery_status="sent",
                        answer_status="refused",
                        confidence=round(_rng.uniform(0.18, 0.42), 2),
                        created_at=t,
                    )
                )
            elif role == "h":
                session.add(
                    Message(
                        conversation_id=conv.id,
                        source_update_id=last_update_id,
                        delivery_key=f"reply:{last_update_id}",
                        direction="outbound",
                        sender_type="ai",
                        content=content,
                        delivery_status="sent",
                        answer_status="handoff",
                        created_at=t,
                    )
                )
            elif role == "op":
                session.add(
                    Message(
                        conversation_id=conv.id,
                        direction="outbound",
                        sender_type="operator",
                        content=content,
                        delivery_status="sent",
                        created_at=t,
                    )
                )
            counts["messages"] += 1
            last_msg_at = t

        conv.last_message_at = last_msg_at
        if scenario["status"] == "closed":
            conv.closed_at = last_msg_at + timedelta(hours=2)

        # 线索：评分走 domain.scoring 的真实规则，保证与实例配置口径一致
        lead_cfg = scenario.get("lead")
        if lead_cfg:
            fields = {
                "business_email": lead_cfg.get("business_email"),
                "requirement": lead_cfg.get("requirement"),
                "team_size": lead_cfg.get("team_size"),
                "budget_range": lead_cfg.get("budget_range"),
                "purchase_timeline": lead_cfg.get("purchase_timeline"),
                "asked_demo": lead_cfg.get("asked_demo", False),
                "freebie_only": lead_cfg.get("freebie_only", False),
            }
            result = score_lead(fields)
            lead_created = conv_start + timedelta(minutes=8)
            lead = Lead(
                user_id=user.id,
                conversation_id=conv.id,
                source_channel=scenario.get("channel"),
                name=lead_cfg.get("name"),
                company=lead_cfg.get("company"),
                country=lead_cfg.get("country"),
                business_email=fields["business_email"],
                requirement=fields["requirement"],
                team_size=fields["team_size"],
                budget_range=fields["budget_range"],
                purchase_timeline=fields["purchase_timeline"],
                integrations=lead_cfg.get("integrations", []),
                notes=lead_cfg.get("notes"),
                asked_demo=fields["asked_demo"],
                freebie_only=fields["freebie_only"],
                score=result.score,
                grade=result.grade,
                score_reasons=result.reasons,
                status=lead_cfg.get("status", "open"),
                version=lead_cfg.get("version", 2),
                external_crm_id=lead_cfg.get("external_crm_id"),
                # 防骚扰：唤醒计数占位，默认上限 1 时 cron 绝不触碰假 chat（见文件头注释）
                revive_count=1,
                last_revived_at=lead_cfg.get("_last_revived_at"),
                created_at=lead_created,
                updated_at=(
                    last_msg_at if lead_cfg.get("status") != "won" else now - timedelta(days=2)
                ),
            )
            session.add(lead)
            counts["leads"] += 1

        # 接管：pending 挂在会话末，resolved（高意向通知型）创建即解决，accepted 为人工接待中
        handoff_cfg = scenario.get("handoff")
        if handoff_cfg:
            reason, state = handoff_cfg
            requested = last_msg_at if state != "resolved" else conv_start + timedelta(minutes=9)
            session.add(
                Handoff(
                    conversation_id=conv.id,
                    reason=reason,
                    requested_at=requested,
                    accepted_at=requested + timedelta(minutes=6) if state == "accepted" else None,
                    resolved_at=requested if state == "resolved" else None,
                    operator_id=1 if state == "accepted" else None,
                )
            )
            counts["handoffs"] += 1

    return counts


async def main() -> None:
    parser = argparse.ArgumentParser(description="Mercury 演示数据种子脚本")
    parser.add_argument("--wipe", action="store_true", help="只清除演示数据，不插入")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                await wipe(session)
                if args.wipe:
                    print("演示数据已清除。")
                    return
                counts = await seed(session)
        print(
            "演示数据已重建："
            f"用户 {counts['users']}，会话 {counts['conversations']}，"
            f"消息 {counts['messages']}，线索 {counts['leads']}，接管 {counts['handoffs']}。"
        )
        print("清除：uv run python scripts/seed_demo.py --wipe")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
