"""切分与假向量单元测试（无外部依赖）。"""

from llm.chunking import CHUNK_SIZE_CHARS, checksum_of, split_text
from llm.client import DeterministicFakeEmbedder

MD_SAMPLE = """# 产品手册

## 部署

支持私有化部署，最低 4 张 GPU。

### 云端

默认 SaaS 多租户。

## 定价

团队版每席位每月 29 美元。
"""


def test_markdown_headers_become_metadata() -> None:
    chunks = split_text(MD_SAMPLE, "markdown")
    assert chunks, "应产出至少一个 chunk"
    by_content = {c.content: c.metadata for c in chunks}
    deploy = next(m for content, m in by_content.items() if "私有化" in content)
    assert deploy.get("h1") == "产品手册" and deploy.get("h2") == "部署"
    cloud = next(m for content, m in by_content.items() if "多租户" in content)
    assert cloud.get("h3") == "云端"
    pricing = next(m for content, m in by_content.items() if "29 美元" in content)
    assert pricing.get("h2") == "定价"


def test_long_text_is_split_with_size_cap() -> None:
    long_text = "这是一段很长的产品说明。" * 400  # 远超单块上限
    chunks = split_text(long_text, "txt")
    assert len(chunks) > 1
    assert all(len(c.content) <= CHUNK_SIZE_CHARS for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_checksum_stable() -> None:
    assert checksum_of("abc") == checksum_of("abc")
    assert checksum_of("abc") != checksum_of("abd")


async def test_fake_embedder_deterministic_unit_vectors() -> None:
    embedder = DeterministicFakeEmbedder()
    [v1] = await embedder.embed(["hello"])
    [v2] = await embedder.embed(["hello"])
    [v3] = await embedder.embed(["world"])
    assert v1 == v2 and v1 != v3
    assert len(v1) == 1536
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6
    # 不同文本的随机单位向量在高维空间近似正交
    dot = sum(a * b for a, b in zip(v1, v3, strict=True))
    assert abs(dot) < 0.15
