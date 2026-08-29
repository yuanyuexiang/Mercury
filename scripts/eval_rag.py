"""RAG 评测（技术方案 §15）：检索命中率/拒答率报告，是调参 RAG_MIN_SIMILARITY 的依据。

用法（需 DATABASE_URL 指向已跑过 migration 的库）：
  uv run python scripts/eval_rag.py                  # 检索级评测（需 LLM_API_KEY）
  uv run python scripts/eval_rag.py --with-answers   # 加受约束生成评测（M4 验收，需 chat 模型）
  uv run python scripts/eval_rag.py --fake           # 离线冒烟：确定性假向量，命中率无语义意义
  uv run python scripts/eval_rag.py --min-similarity 0.55 --top-k 8

评测集：scripts/eval/evalset.json；判定规则：
  检索级：可答题 → top-k 任一 chunk 含任一期望关键词记命中；不可答题 → 过滤后为空记拒答正确。
  生成级（--with-answers）：可答题 → 实际生成回答且含期望关键词；不可答题 → 走拒答路径。
"""

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from domain import repositories
from domain.config import get_settings
from llm import chunking
from llm.client import DeterministicFakeEmbedder, Embedder, build_embedder
from llm.indexing import run_index_document
from llm.rag import retrieve
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

SCRIPTS_DIR = Path(__file__).parent


class NullLocker:
    """脚本内联执行，无并发竞争：恒获取成功。"""

    @asynccontextmanager
    async def hold(self, entity_id: int):
        yield True


async def ingest(session_factory, embedder: Embedder, doc_spec: dict) -> None:
    path = (SCRIPTS_DIR / doc_spec["path"]).resolve()
    content = path.read_text(encoding="utf-8")
    checksum = chunking.checksum_of(content)
    async with session_factory() as session:
        doc = await repositories.find_document_by_checksum(session, checksum)
        if doc is None:
            doc = await repositories.create_document(
                session,
                title=doc_spec["title"],
                source_type=doc_spec["source_type"],
                storage_path=str(path),
                checksum=checksum,
            )
            await session.commit()
        document_id = doc.id
    outcome = await run_index_document(session_factory, NullLocker(), embedder, document_id)
    if outcome != "indexed":
        raise SystemExit(f"文档索引失败：{doc_spec['title']} → {outcome}")
    print(f"  已索引：{doc_spec['title']}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索评测")
    parser.add_argument("--fake", action="store_true", help="用确定性假向量（离线冒烟）")
    parser.add_argument(
        "--with-answers", action="store_true", help="附加受约束生成评测（需 LLM_CHAT_MODEL）"
    )
    parser.add_argument("--evalset", default=str(SCRIPTS_DIR / "eval" / "evalset.json"))
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-similarity", type=float, default=None)
    args = parser.parse_args()

    settings = get_settings()
    top_k = args.top_k or settings.rag_top_k
    min_similarity = args.min_similarity or settings.rag_min_similarity

    embedder: Embedder | None
    if args.fake:
        embedder = DeterministicFakeEmbedder()
        print("⚠ 使用确定性假向量：命中率不代表真实检索质量，仅验证管线")
    else:
        embedder = build_embedder(settings)
        if embedder is None:
            raise SystemExit("缺少 LLM_API_KEY——配置真实 embedding，或用 --fake 跑离线冒烟")

    evalset = json.loads(Path(args.evalset).read_text(encoding="utf-8"))  # noqa: ASYNC240
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        print(f"评测参数：top_k={top_k} min_similarity={min_similarity}")
        print("导入文档：")
        for doc_spec in evalset["documents"]:
            await ingest(session_factory, embedder, doc_spec)

        answerable_total = answerable_hit = refusal_total = refusal_ok = 0
        print("\n逐题结果：")
        for item in evalset["questions"]:
            async with session_factory() as session:
                results = await retrieve(
                    session, embedder, item["q"], top_k=top_k, min_similarity=min_similarity
                )
            top_sim = f"{results[0].similarity:.3f}" if results else "-"
            if item["answerable"]:
                answerable_total += 1
                hit = any(
                    kw.lower() in chunk.content.lower()
                    for chunk in results
                    for kw in item["expect_keywords"]
                )
                answerable_hit += hit
                mark = "✓" if hit else "✗"
                print(f"  {mark} [可答] {item['q']}  (召回 {len(results)}, top相似度 {top_sim})")
            else:
                refusal_total += 1
                ok = len(results) == 0
                refusal_ok += ok
                mark = "✓" if ok else "✗"
                print(f"  {mark} [应拒] {item['q']}  (召回 {len(results)}, top相似度 {top_sim})")

        print("\n========== 检索级报告 ==========")
        if answerable_total:
            rate = answerable_hit / answerable_total * 100
            print(f"检索命中率：{answerable_hit}/{answerable_total} = {rate:.0f}%  (MVP 目标 ≥85%)")
        if refusal_total:
            rate = refusal_ok / refusal_total * 100
            print(f"安全拒答率：{refusal_ok}/{refusal_total} = {rate:.0f}%  (MVP 目标 ≥95%)")
        if args.fake:
            print("（--fake 模式：以上数字无语义意义）")

        if args.with_answers:
            await eval_answers(session_factory, embedder, evalset, top_k, min_similarity)
    finally:
        await engine.dispose()


async def eval_answers(session_factory, embedder, evalset, top_k, min_similarity) -> None:
    """生成级评测（M4 验收口径）：受约束回答正确率 + 拒答正确率。"""
    from domain.schemas import Deadline
    from llm.client import build_chat_client
    from llm.rag import generate_answer

    settings = get_settings()
    chat = build_chat_client(settings)
    if chat is None:
        print("\n（跳过生成级评测：缺少 LLM_CHAT_MODEL / LLM_API_KEY）")
        return

    ans_total = ans_ok = ref_total = ref_ok = 0
    print("\n生成级逐题结果：")
    for item in evalset["questions"]:
        async with session_factory() as session:
            result = await generate_answer(
                session,
                embedder,
                chat,
                item["q"],
                history=[],
                language="zh",
                deadline=Deadline(settings.reply_deadline_s),
                top_k=top_k,
                min_similarity=min_similarity,
            )
        if item["answerable"]:
            ans_total += 1
            ok = (
                (not result.refused)
                and bool(result.text)
                and (
                    any(kw.lower() in (result.text or "").lower() for kw in item["expect_keywords"])
                )
            )
            ans_ok += ok
            preview = (result.text or "[拒答]").replace("\n", " ")[:60]
            print(f"  {'✓' if ok else '✗'} [可答] {item['q']} → {preview}")
        else:
            ref_total += 1
            ok = result.refused
            ref_ok += ok
            verdict = "拒答" if result.refused else (result.text or "")[:40]
            print(f"  {'✓' if ok else '✗'} [应拒] {item['q']} → {verdict}")

    print("\n========== 生成级报告（M4 验收口径）==========")
    if ans_total:
        print(
            f"有依据正确回答率：{ans_ok}/{ans_total} = {ans_ok / ans_total * 100:.0f}%  (目标 ≥85%)"
        )
    if ref_total:
        print(
            f"无依据安全拒答率：{ref_ok}/{ref_total} = {ref_ok / ref_total * 100:.0f}%  (目标 ≥95%)"
        )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
