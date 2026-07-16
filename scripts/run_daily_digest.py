"""
生成每日资讯推送 - 聚合知识库内容，生成分类分时段的HTML资讯报告

用法:
    python3 scripts/run_daily_digest.py [--date 2026-07-16]
"""
import sys
import os
import logging
import yaml
from datetime import datetime

sys.path.insert(0, "/workspace/water-eco-kb")

from src.storage.metadata_db import MetadataDB
from src.push.aggregator import Aggregator
from src.push.digest_generator import DigestGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="生成每日资讯推送")
    parser.add_argument("--date", default=None, help="指定日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    digest_date = args.date or datetime.now().strftime("%Y-%m-%d")
    logger.info(f"生成 {digest_date} 的每日资讯推送")

    # 加载配置
    with open("/workspace/water-eco-kb/config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    db = MetadataDB(config["metadata_db"]["path"])

    # 检查知识库是否有内容
    stats = db.get_stats()
    if stats["total"] == 0:
        logger.warning("知识库为空，请先运行采集和索引")
        return

    logger.info(f"知识库状态: {stats['total']} 篇文档, 近7天 {stats['recent_7d']} 篇新增")

    # 聚合内容
    logger.info("阶���1: 内容聚合")
    aggregator = Aggregator(
        db_path=config["metadata_db"]["path"],
        config_path="/workspace/water-eco-kb/config/settings.yaml",
    )
    aggregated_data = aggregator.aggregate()
    logger.info(f"  聚合完成: {aggregated_data['total_items']} 条内容")

    # 生成HTML
    logger.info("阶段2: 生成HTML报告")
    generator = DigestGenerator(
        output_dir=config["push"]["output_dir"],
    )
    output_dir = config["push"]["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{digest_date}_digest.html")

    html_path = generator.generate(aggregated_data, output_path)
    logger.info(f"  HTML报告已生成: {html_path}")

    # 记录推送历史
    categories_json = str(aggregated_data.get("segment_stats", {}))
    db.add_digest_history(
        digest_date=digest_date,
        file_path=html_path,
        tdrive_file_id="",  # 上传tdrive后更新
        total_items=aggregated_data["total_items"],
        categories=categories_json,
    )

    logger.info("=" * 60)
    logger.info(f"每日资讯推送完成!")
    logger.info(f"  日期: {digest_date}")
    logger.info(f"  总内容数: {aggregated_data['total_items']}")
    logger.info(f"  HTML路径: {html_path}")
    logger.info(f"  可在浏览器中打开查看")
    logger.info("=" * 60)

    return html_path


if __name__ == "__main__":
    main()
