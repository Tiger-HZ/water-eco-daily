"""
定时调度模块
============
提供两个入口函数：

- ``run_daily()``        ：完整流程 采集 → 处理 → 索引 → 聚合 → 生成 HTML
- ``run_digest_only()``  ：仅执行 聚合 → 生成 HTML（资讯推送）

每个阶段都有日志输出和统计信息，最终汇总打印。
可由 cron / systemd timer 定时调用，也可直接 ``python -m src.push.scheduler`` 运行。
"""
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage.metadata_db import MetadataDB  # noqa: E402
from src.push.aggregator import Aggregator  # noqa: E402
from src.push.digest_generator import DigestGenerator  # noqa: E402

logger = logging.getLogger(__name__)

CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"

# 采集器 → source_type 映射（用于 collection_log 记录）
_COLLECTOR_SPECS = [
    ("gov_collector", "GovCollector", "政府机构"),
    ("academic_collector", "AcademicCollector", "学术期刊"),
    ("news_collector", "NewsCollector", "主流媒体"),
    ("wechat_collector", "WeChatCollector", "微信公众号"),
]


# ---------------------------------------------------------------------- #
# 工具函数
# ---------------------------------------------------------------------- #
def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        logger.error("配置文件不存在: %s", CONFIG_PATH)
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


# ---------------------------------------------------------------------- #
# 各阶段实现
# ---------------------------------------------------------------------- #
def _step_collect(config: Dict[str, Any], db: MetadataDB) -> Dict[str, Any]:
    """采集阶段：运行各采集器，结果 upsert 到 MetadataDB。

    元数据提取与质量评估已在各采集器内部完成（见 collectors/*）。
    """
    from src.collectors.gov_collector import GovCollector
    from src.collectors.academic_collector import AcademicCollector
    from src.collectors.news_collector import NewsCollector
    from src.collectors.wechat_collector import WeChatCollector

    collection_cfg = config.get("collection", {})
    collector_map = {
        "GovCollector": ("政府机构", GovCollector),
        "AcademicCollector": ("学术期刊", AcademicCollector),
        "NewsCollector": ("主流媒体", NewsCollector),
        "WeChatCollector": ("微信公众号", WeChatCollector),
    }

    total_collected = 0
    total_new = 0
    failed: List[str] = []

    for cls_name, (source_type, cls) in collector_map.items():
        t0 = time.time()
        try:
            collector = cls(collection_cfg)
            docs = collector.collect()
            new = 0
            for doc in docs:
                try:
                    _, is_new = db.upsert_document(doc)
                    if is_new:
                        new += 1
                except Exception as e:
                    logger.warning("upsert 文档失败 [%s]: %s", doc.get("title", "")[:40], e)
            db.log_collection(
                source_name=cls_name, source_type=source_type,
                items_collected=len(docs), items_new=new,
                status="success", error="",
            )
            elapsed = time.time() - t0
            logger.info(
                "[采集] %-20s 采集 %4d 条, 新增 %4d 条, 耗时 %s",
                cls_name, len(docs), new, _fmt_duration(elapsed),
            )
            total_collected += len(docs)
            total_new += new
        except Exception as e:
            failed.append(cls_name)
            logger.error("[采集] %s 失败: %s", cls_name, e)
            logger.debug(traceback.format_exc())
            db.log_collection(
                source_name=cls_name, source_type=source_type,
                items_collected=0, items_new=0,
                status="failed", error=str(e),
            )

    return {
        "collected": total_collected,
        "new": total_new,
        "failed": failed,
    }


def _step_process(config: Dict[str, Any], db: MetadataDB) -> Dict[str, Any]:
    """处理阶段：数据质量巡检。

    采集器内部已完成解析 / 元数据提取 / 质量评估，
    此处对库中近 7 天文档做质量巡检，统计缺失摘要或关键词的文档数，
    并按需补全空字段（保留已有数据，仅填充缺失）。
    """
    try:
        recent_docs = db.query_documents(date_from=None, date_to=None, limit=1000)
    except Exception as e:
        logger.error("[处理] 获取文档失败: %s", e)
        return {"checked": 0, "missing_summary": 0, "missing_keywords": 0}

    missing_summary = 0
    missing_keywords = 0
    for d in recent_docs:
        if not (d.get("summary") or "").strip():
            missing_summary += 1
        if not (d.get("keywords") or "").strip() or d.get("keywords") == "[]":
            missing_keywords += 1

    logger.info(
        "[处理] 巡检 %d 条文档: 缺摘要 %d 条, 缺关键词 %d 条",
        len(recent_docs), missing_summary, missing_keywords,
    )
    return {
        "checked": len(recent_docs),
        "missing_summary": missing_summary,
        "missing_keywords": missing_keywords,
    }


def _step_index(config: Dict[str, Any], db: MetadataDB) -> Dict[str, Any]:
    """索引阶段：为未向量化的文档生成向量并写入 VectorDB。

    注意：documents 表不存储全文 content（仅 content_hash），
    此处用 title + summary + keywords 拼接作为嵌入文本。
    """
    try:
        pending = db.get_all_documents_for_indexing(limit=500)
    except Exception as e:
        logger.error("[索引] 获取待索引文档失败: %s", e)
        return {"indexed": 0, "pending": 0, "error": str(e)}

    if not pending:
        logger.info("[索引] 无待向量化的文档")
        return {"indexed": 0, "pending": 0}

    embedder_cfg = config.get("embedding", {})
    vdb_cfg = config.get("vector_db", {})
    collection_cfg = config.get("collection", {})

    try:
        from src.processors.embedder import Embedder
        from src.storage.vector_db import VectorDB

        embedder = Embedder(
            model_name=embedder_cfg.get("model_name", "BAAI/bge-large-zh-v1.5"),
            device=embedder_cfg.get("device", "cpu"),
            cache_dir=embedder_cfg.get("cache_dir", str(_PROJECT_ROOT / "data" / "cache")),
        )
        vdb = VectorDB(
            persist_path=vdb_cfg.get("persist_path", str(_PROJECT_ROOT / "data" / "chroma")),
            collection_name=vdb_cfg.get("collection_name", "water_eco_knowledge"),
        )
    except Exception as e:
        logger.error("[索引] 初始化嵌入/向量库失败（可能依赖未安装）: %s", e)
        return {"indexed": 0, "pending": len(pending), "error": str(e)}

    # 拼接嵌入文本
    texts = []
    for d in pending:
        parts = [d.get("title", "")]
        summary = d.get("summary", "")
        if summary:
            parts.append(summary)
        keywords = d.get("keywords", "")
        if keywords and keywords != "[]":
            parts.append(keywords)
        texts.append("\n".join(parts))

    batch_size = int(embedder_cfg.get("batch_size", 32))
    t0 = time.time()
    try:
        embeddings = embedder.embed_texts(texts, batch_size=batch_size)
    except Exception as e:
        logger.error("[索引] 向量生成失败: %s", e)
        return {"indexed": 0, "pending": len(pending), "error": str(e)}

    ids = [d["id"] for d in pending]
    metadatas = [
        {
            "title": d.get("title", ""),
            "category": d.get("category", ""),
            "geo_scope": d.get("geo_scope", ""),
            "source_type": d.get("source_type", ""),
            "publish_date": d.get("publish_date", ""),
            "quality_score": d.get("quality_score", 0.5),
            "doc_id": d["id"],
        }
        for d in pending
    ]

    try:
        vector_ids = vdb.add_documents(
            ids=ids, embeddings=embeddings,
            documents=texts, metadatas=metadatas,
        )
    except Exception as e:
        logger.error("[索引] 写入向量库失败: %s", e)
        return {"indexed": 0, "pending": len(pending), "error": str(e)}

    # 回写 vector_id
    written = 0
    for doc_id, vid in zip(ids, vector_ids):
        try:
            db.update_vector_id(doc_id, vid)
            written += 1
        except Exception as e:
            logger.warning("[索引] 回写 vector_id 失败 %s: %s", doc_id, e)

    elapsed = time.time() - t0
    logger.info(
        "[索引] 向量化 %d / %d 条, 耗时 %s",
        written, len(pending), _fmt_duration(elapsed),
    )
    return {"indexed": written, "pending": len(pending)}


def _step_aggregate_and_publish(
    config: Dict[str, Any], db: MetadataDB, db_path: str
) -> Dict[str, Any]:
    """聚合 + 生成 HTML，并记录 digest 历史。"""
    push_cfg = config.get("push", {})
    output_dir = push_cfg.get("output_dir", str(_PROJECT_ROOT / "output" / "digests"))

    aggregator = Aggregator(db_path=db_path, config_path=str(CONFIG_PATH))
    aggregated = aggregator.aggregate()

    generator = DigestGenerator(output_dir=output_dir)
    html_path = generator.generate(aggregated)

    # 记录推送历史
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        categories_str = ",".join(c["key"] for c in aggregated.get("categories", []))
        db.add_digest_history(
            digest_date=today,
            file_path=html_path,
            tdrive_file_id="",
            total_items=aggregated.get("total_items", 0),
            categories=categories_str,
        )
    except Exception as e:
        logger.warning("记录 digest 历史失败: %s", e)

    return {
        "html_path": html_path,
        "total_items": aggregated.get("total_items", 0),
        "segment_stats": aggregated.get("segment_stats", {}),
    }


# ---------------------------------------------------------------------- #
# 入口函数
# ---------------------------------------------------------------------- #
def run_daily() -> Dict[str, Any]:
    """完整每日流程：采集 → 处理 → 索引 → 聚合 → 生成 HTML。"""
    _setup_logging()
    t_start = time.time()
    logger.info("=" * 64)
    logger.info("水生态环境知识管理 - 每日全流程启动 @ %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("=" * 64)

    config = _load_config()
    if not config:
        logger.error("配置加载失败，流程中止")
        return {"status": "failed", "reason": "config load failed"}

    db_path = config.get("metadata_db", {}).get("path", str(_PROJECT_ROOT / "data" / "metadata.db"))
    db = MetadataDB(db_path)

    results: Dict[str, Any] = {"status": "ok"}

    # 1. 采集
    logger.info("-" * 40 + " [1/5] 采集 " + "-" * 24)
    results["collect"] = _step_collect(config, db)

    # 2. 处理（质量巡检）
    logger.info("-" * 40 + " [2/5] 处理 " + "-" * 24)
    results["process"] = _step_process(config, db)

    # 3. 索引
    logger.info("-" * 40 + " [3/5] 索引 " + "-" * 24)
    results["index"] = _step_index(config, db)

    # 4. 聚合 + 5. 生成 HTML
    logger.info("-" * 40 + " [4/5] 聚合 " + "-" * 24)
    logger.info("-" * 40 + " [5/5] 发布 " + "-" * 24)
    try:
        results["publish"] = _step_aggregate_and_publish(config, db, db_path)
    except Exception as e:
        logger.error("聚合 / 发布失败: %s", e)
        logger.debug(traceback.format_exc())
        results["publish"] = {"error": str(e)}
        results["status"] = "partial"

    # 汇总
    elapsed = time.time() - t_start
    _print_summary(results, elapsed)
    results["elapsed_seconds"] = round(elapsed, 2)
    return results


def run_digest_only() -> Dict[str, Any]:
    """仅执行 聚合 → 生成 HTML（资讯推送）。"""
    _setup_logging()
    t_start = time.time()
    logger.info("=" * 64)
    logger.info("水生态环境知识管理 - 资讯推送 (digest only) @ %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("=" * 64)

    config = _load_config()
    if not config:
        logger.error("配置加载失败，流程中止")
        return {"status": "failed", "reason": "config load failed"}

    db_path = config.get("metadata_db", {}).get("path", str(_PROJECT_ROOT / "data" / "metadata.db"))
    db = MetadataDB(db_path)

    results: Dict[str, Any] = {"status": "ok"}
    try:
        results["publish"] = _step_aggregate_and_publish(config, db, db_path)
    except Exception as e:
        logger.error("聚合 / 发布失败: %s", e)
        logger.debug(traceback.format_exc())
        results["publish"] = {"error": str(e)}
        results["status"] = "failed"

    elapsed = time.time() - t_start
    _print_summary(results, elapsed)
    results["elapsed_seconds"] = round(elapsed, 2)
    return results


def _print_summary(results: Dict[str, Any], elapsed: float) -> None:
    """打印执行汇总。"""
    logger.info("=" * 64)
    logger.info("执行汇总 (耗时 %s):", _fmt_duration(elapsed))

    c = results.get("collect")
    if c:
        logger.info("  采集: 共 %d 条, 新增 %d 条, 失败 %d 个采集器",
                    c.get("collected", 0), c.get("new", 0), len(c.get("failed", [])))

    p = results.get("process")
    if p:
        logger.info("  处理: 巡检 %d 条, 缺摘要 %d, 缺关键词 %d",
                    p.get("checked", 0), p.get("missing_summary", 0), p.get("missing_keywords", 0))

    idx = results.get("index")
    if idx:
        logger.info("  索引: 向量化 %d / %d 条%s",
                    idx.get("indexed", 0), idx.get("pending", 0),
                    f" [错误: {idx['error']}]" if idx.get("error") else "")

    pub = results.get("publish")
    if pub:
        if pub.get("html_path"):
            seg_stats = pub.get("segment_stats", {})
            seg_total = sum(seg_stats.values()) if isinstance(seg_stats, dict) else 0
            logger.info("  发布: HTML -> %s", pub["html_path"])
            logger.info("        本次收录 %d 条, 时段文档总数 %d 条",
                        pub.get("total_items", 0), seg_total)
            if isinstance(seg_stats, dict):
                for k, v in seg_stats.items():
                    logger.info("          %-10s: %d", k, v)
        elif pub.get("error"):
            logger.info("  发布: 失败 - %s", pub["error"])

    logger.info("  状态: %s", results.get("status", "unknown"))
    logger.info("=" * 64)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="水生态环境知识管理 - 调度器")
    parser.add_argument(
        "--digest-only", action="store_true",
        help="仅执行聚合 + 生成 HTML（不采集不索引）",
    )
    args = parser.parse_args()

    if args.digest_only:
        run_digest_only()
    else:
        run_daily()
