"""
执行知识采集 - 从各数据源采集水生态环境知识

用法:
    python3 scripts/run_collection.py [--source gov|academic|news|wechat|all]
"""
import sys
import os
import logging
import yaml
import time

# 添加项目根目录到Python路径
sys.path.insert(0, "/workspace/water-eco-kb")

from src.storage.metadata_db import MetadataDB
from src.collectors.gov_collector import GovCollector
from src.collectors.academic_collector import AcademicCollector
from src.collectors.news_collector import NewsCollector
from src.collectors.wechat_collector import WeChatCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="水生态环境知识采集")
    parser.add_argument("--source", default="all",
                       choices=["gov", "academic", "news", "wechat", "all"],
                       help="采集源")
    args = parser.parse_args()

    # 加载配置
    with open("/workspace/water-eco-kb/config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    collection_config = config.get("collection", {})
    db = MetadataDB(config["metadata_db"]["path"])

    all_docs = []
    source_type = args.source

    if source_type in ("gov", "all"):
        logger.info("=" * 60)
        logger.info("开始采集政务网站")
        logger.info("=" * 60)
        try:
            collector = GovCollector(collection_config)
            docs = collector.collect()
            all_docs.extend(docs)
            db.log_collection("政务网站", "政府机构", len(docs), 0)
        except Exception as e:
            logger.error(f"政务网站采集失败: {e}")
            db.log_collection("政务网站", "政府机构", 0, 0, "failed", str(e))

    if source_type in ("academic", "all"):
        logger.info("=" * 60)
        logger.info("开始采集学术文献")
        logger.info("=" * 60)
        try:
            collector = AcademicCollector(collection_config)
            docs = collector.collect()
            all_docs.extend(docs)
            db.log_collection("学术文献", "学术期刊", len(docs), 0)
        except Exception as e:
            logger.error(f"学术文献采集失败: {e}")
            db.log_collection("学术文献", "学术期刊", 0, 0, "failed", str(e))

    if source_type in ("news", "all"):
        logger.info("=" * 60)
        logger.info("开始采集新闻资讯")
        logger.info("=" * 60)
        try:
            collector = NewsCollector(collection_config)
            docs = collector.collect()
            all_docs.extend(docs)
            db.log_collection("新闻资讯", "主流媒体", len(docs), 0)
        except Exception as e:
            logger.error(f"新闻资讯采集失败: {e}")
            db.log_collection("新闻资讯", "主流媒体", 0, 0, "failed", str(e))

    if source_type in ("wechat", "all"):
        logger.info("=" * 60)
        logger.info("开始采集微信公众号文章")
        logger.info("=" * 60)
        try:
            collector = WeChatCollector(collection_config)
            docs = collector.collect()
            all_docs.extend(docs)
            db.log_collection("微信公众号", "微信公众号", len(docs), 0)
        except Exception as e:
            logger.error(f"微信采集失败: {e}")
            db.log_collection("微信公众号", "微信公众号", 0, 0, "failed", str(e))

    # 存入元数据库
    logger.info("=" * 60)
    logger.info(f"采集完成，共 {len(all_docs)} 条文档，开始入库...")
    logger.info("=" * 60)

    new_count = 0
    for doc in all_docs:
        doc_id, is_new = db.upsert_document(doc)
        if is_new:
            new_count += 1

    logger.info(f"入库完成: 总计 {len(all_docs)} 条，新增 {new_count} 条，更新 {len(all_docs) - new_count} 条")

    # 打印统计
    stats = db.get_stats()
    logger.info(f"知识库当前状态: 总文档数 {stats['total']}, 近7天新增 {stats['recent_7d']}")
    logger.info(f"分类分布: {stats['by_category']}")
    logger.info(f"地理分布: {stats['by_geo']}")

    return all_docs


if __name__ == "__main__":
    main()
