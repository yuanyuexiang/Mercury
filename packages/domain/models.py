"""SQLAlchemy ORM 模型，与技术方案 §4 的 DDL 一一对应（首个 migration 手写，模型保持同构）。"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1536  # 与 LLM_EMBED_MODEL 维度一致；换维度需重建索引（§1）


class Base(DeclarativeBase):
    pass


class TelegramUpdate(Base):
    """幂等表：update_id 主键是重复推送的最终防线（§4/§5）。"""

    __tablename__ = "telegram_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # 租户边界（§20）：独立实例阶段恒为 1；SaaS 化时 PK 需改 (tenant_id, update_id)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # queued|processing|replied|extracting|done|failed|skipped（§6 管线与兜底扫描器）
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_tenant_telegram", "tenant_id", "telegram_user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(Text)
    # notified|accepted|deleted
    consent_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'notified'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ai_active','handoff_pending','human_active','closed')",
            name="conversations_status_check",
        ),
        # 只约束"未关闭会话唯一"——/reset 关旧建新不会违反唯一键（§4）
        Index(
            "one_open_conversation",
            "tenant_id",
            "telegram_chat_id",
            "user_id",
            unique=True,
            postgresql_where=text("status != 'closed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    # 渠道归因：/start 深链参数（t.me/<bot>?start=xxx），首触后不再覆盖
    source_channel: Mapped[str | None] = mapped_column(Text)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ai_active'"))
    # MVP 单管理员恒为 1（内部 ID）；P1 建 operators 表（§9）
    assigned_operator_id: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        # 任务重试用 ON CONFLICT DO NOTHING，不产生重复 inbound（§6 第 2 步）
        Index(
            "uniq_inbound_message",
            "conversation_id",
            "telegram_message_id",
            unique=True,
            postgresql_where=text("direction = 'inbound'"),
        ),
        # 每个投递意图至多一条 outbound（§6 第 4 步统一投递）
        Index(
            "uniq_outbound_delivery",
            "delivery_key",
            unique=True,
            postgresql_where=text("delivery_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    # 产生该消息的 update（人工/系统消息为 NULL；update 被保留期清理后置 NULL）
    source_update_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("telegram_updates.update_id", ondelete="SET NULL")
    )
    # outbound 投递幂等键：
    # reply:{update_id} | followup:{update_id} | ack:{update_id} | fallback:{update_id}
    delivery_key: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text, nullable=False)  # inbound|outbound
    sender_type: Mapped[str] = mapped_column(Text, nullable=False)  # user|ai|operator|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'text'"))
    delivery_status: Mapped[str | None] = mapped_column(Text)  # sending|sent|failed|uncertain
    answer_status: Mapped[str | None] = mapped_column(Text)  # answered|refused|handoff
    source_chunk_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    model_name: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)  # markdown|txt|pdf|url
    source_url: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(Text)
    # pending|indexing|active|disabled|failed
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        # 重试/并发重索引不产生重复 chunk（§6 RAG 细节）
        UniqueConstraint("document_id", "version", "chunk_index"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    # 对应 documents.version，重索引原子切换用
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # MVP 一个会话至多一条 lead（§4）
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # 渠道归因：创建时继承 conversation.source_channel
    source_channel: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    business_email: Mapped[str | None] = mapped_column(Text)
    requirement: Mapped[str | None] = mapped_column(Text)
    team_size: Mapped[str | None] = mapped_column(Text)
    budget_range: Mapped[str | None] = mapped_column(Text)
    purchase_timeline: Mapped[str | None] = mapped_column(Text)
    integrations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    # 用户拒绝提供的字段，不再追问（§7）
    declined_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # 提取出的事实布尔，供 §8 确定性评分（asked_demo +25 / freebie_only -20）
    asked_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    freebie_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    grade: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'low'"))
    score_reasons: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    # 实质变更 +1，同步幂等键的组成部分（§11）
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    external_crm_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Handoff(Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        # 每会话至多一个未解决的接管请求；通知型记录创建即 resolved（§9）
        Index(
            "one_unresolved_handoff",
            "conversation_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # user_request|low_confidence|sensitive|high_intent|manual
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[int | None] = mapped_column(BigInteger)


class IntegrationJob(Base):
    __tablename__ = "integration_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    integration_type: Mapped[str] = mapped_column(Text, nullable=False)  # google_sheets|...
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # lead
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 版本化幂等键，如 "sheets:lead:42:v3"（§11）
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LlmProvider(Base):
    __tablename__ = "llm_providers"
    __table_args__ = (
        # 全局至多一个激活供应商（§4）
        Index(
            "one_active_provider",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet 密文，绝不存明文
    chat_model: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_model: Mapped[str | None] = mapped_column(Text)
    # embedding 模型（可空 = 用 env 兜底）；必须与向量库维度一致（1536），换维度需全量重索引
    embed_model: Mapped[str | None] = mapped_column(Text)
    supports_json_schema: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)  # admin|system|ai
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AppSetting(Base):
    """系统设置 KV（migration 0007）：后台可配 Telegram 对接与品牌文案，DB 优先 env 兜底。

    敏感值（bot token）Fernet 密文入库（is_encrypted=true），主密钥仅在 env（§12 同机制）。
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
