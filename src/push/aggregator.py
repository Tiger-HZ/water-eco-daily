"""
内容聚合模块
================
从 metadata.db 查询文档，按 7 个知识分类和 8 个时间段聚合，
每个「分类 × 时段」最多保留 max_items_per_segment 条，按质量分降序排列。

时间段配置来自 config/settings.yaml 的 push.time_segments：
    近7天 / 近1个月 / 近3个月 / 近半年 / 本年度 / 去年 / 近3年 / 更早

为保证每个文档只归属一个时段，时段之间做互斥处理：
按时段起始下界降序排列，每个时段的上界 = 前一个（更近）时段的下界，
从而形成连续且不重叠的时间窗口。

聚合后的结构化数据供 DigestGenerator 生成每日资讯 HTML 报告。
"""
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# 确保项目根目录在 sys.path 中，便于直接运行
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage.metadata_db import MetadataDB  # noqa: E402

logger = logging.getLogger(__name__)

# 7 大知识分类（结合杭州水生态环境处职责）
CATEGORIES: List[str] = [
    "01_政策法规与规划",
    "02_水环境质量与监测",
    "03_水污染防治与监管",
    "04_水生态保护与修复",
    "05_饮用水水源保护",
    "06_流域综合管理",
    "07_科研文献与技术",
    "08_管理实践与动态",
]

DEFAULT_CONFIG_PATH = str(_PROJECT_ROOT / "config" / "settings.yaml")
DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "metadata.db")


class Aggregator:
    """按分类 × 时段聚合文档。

    用法::

        agg = Aggregator()
        data = agg.aggregate()
        agg.get_time_segment_stats()
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        config_path: str = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.config = self._load_config(config_path)
        push_cfg = self.config.get("push", {})
        self.time_segments: List[Dict[str, Any]] = push_cfg.get("time_segments", [])
        self.max_items_per_segment: int = int(push_cfg.get("max_items_per_segment", 15))
        self.output_dir = Path(
            push_cfg.get("output_dir", str(_PROJECT_ROOT / "output" / "digests"))
        )

        self.db = MetadataDB(db_path)

        # 预计算互斥时段窗口 [(key, label, date_from, date_to), ...]
        self._ranges: List[Tuple[str, str, Optional[str], Optional[str]]] = (
            self._compute_time_ranges()
        )
        logger.info(
            "Aggregator 初始化完成: %d 个分类, %d 个时段, 每段上限 %d 条",
            len(CATEGORIES),
            len(self._ranges),
            self.max_items_per_segment,
        )

    # ------------------------------------------------------------------ #
    # 初始化辅助
    # ------------------------------------------------------------------ #
    @staticmethod
    def _load_config(config_path: str) -> Dict[str, Any]:
        path = Path(config_path)
        if not path.exists():
            logger.warning("配置文件不存在: %s，使用空配置", config_path)
            return {"push": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error("加载配置失败 %s: %s", config_path, e)
            return {"push": {}}

    def _compute_time_ranges(self) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
        """计算互斥的时段窗口，按时段起始下界降序排列。

        每个时段的上界 = 前一个（更近）时段的下界 - 1 天（保证 <= 比较下不重叠）；
        最近一个时段的上界 = 今天（含当天）。若区间无效（date_from > date_to），
        通过 ``_valid_range`` 在查询时返回空结果。
        """
        today = date.today()
        today_str = today.isoformat()

        # 每个时段的起始下界
        starts: List[Tuple[Dict[str, Any], Optional[str]]] = []
        for seg in self.time_segments:
            key = seg.get("key", "")
            if key == "older":
                starts.append((seg, None))  # 无下界
            elif "year" in seg:
                starts.append((seg, date(int(seg["year"]), 1, 1).isoformat()))
            else:
                days = int(seg.get("days", 0))
                starts.append((seg, (today - timedelta(days=days)).isoformat()))

        # 按起始下界降序（None 视为最小，放最后 → older）
        sorted_starts = sorted(
            starts,
            key=lambda x: x[1] if x[1] else "0000-01-01",
            reverse=True,
        )

        ranges: List[Tuple[str, str, Optional[str], Optional[str]]] = []
        prev_start: Optional[str] = None  # 前一个（更近）时段的下界
        for seg, start in sorted_starts:
            if start is None:  # older：捕获所有早于最近下界的文档
                date_from: Optional[str] = None
                date_to: Optional[str] = self._shift_day(prev_start, -1) if prev_start else None
            elif prev_start is None:
                # 最近一个时段：上界为今天（含当天）
                date_from = start
                date_to = today_str
            else:
                date_from = start
                date_to = self._shift_day(prev_start, -1)
            ranges.append((seg["key"], seg["label"], date_from, date_to))
            prev_start = start
        return ranges

    @staticmethod
    def _valid_range(date_from: Optional[str], date_to: Optional[str]) -> bool:
        """区间是否有效（date_from <= date_to），用于排除年初等重叠导致的空区间。"""
        if date_from and date_to and date_from > date_to:
            return False
        return True

    @staticmethod
    def _shift_day(date_str: Optional[str], delta_days: int) -> Optional[str]:
        """对 YYYY-MM-DD 字符串做天数偏移，失败原样返回。"""
        if not date_str:
            return None
        try:
            d = date.fromisoformat(date_str[:10])
            return (d + timedelta(days=delta_days)).isoformat()
        except ValueError:
            return date_str

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def aggregate(self) -> Dict[str, Any]:
        """聚合全量文档，返回结构化数据供报告生成器使用。"""
        logger.info("开始聚合文档 ...")
        started = datetime.now()

        stats = self._safe_stats()
        segment_stats = self.get_time_segment_stats()

        categories_data: List[Dict[str, Any]] = []
        total_items = 0
        for cat in CATEGORIES:
            cat_label = cat.split("_", 1)[-1] if "_" in cat else cat
            segments_data: Dict[str, List[Dict[str, Any]]] = {}
            cat_count = 0
            for key, label, date_from, date_to in self._ranges:
                docs = self._query_segment(cat, date_from, date_to)
                # 按质量分降序，取前 N 条
                docs.sort(key=lambda d: float(d.get("quality_score") or 0.0), reverse=True)
                docs = docs[: self.max_items_per_segment]
                segments_data[key] = docs
                cat_count += len(docs)
                total_items += len(docs)
            categories_data.append(
                {
                    "key": cat,
                    "label": cat_label,
                    "doc_count": cat_count,
                    "segments": segments_data,
                }
            )

        elapsed = (datetime.now() - started).total_seconds()
        logger.info(
            "聚合完成: %d 个分类, 共 %d 条记录, 耗时 %.2fs",
            len(categories_data),
            total_items,
            elapsed,
        )

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "stats": stats,
            "time_segments": [
                {"key": k, "label": lbl, "doc_count": segment_stats.get(k, 0)}
                for k, lbl, _, _ in self._ranges
            ],
            "segment_stats": segment_stats,
            "categories": categories_data,
            "total_items": total_items,
        }

    def get_time_segment_stats(self) -> Dict[str, int]:
        """返回各时段文档数（互斥统计，不分类别）。"""
        stats: Dict[str, int] = {}
        for key, label, date_from, date_to in self._ranges:
            if not self._valid_range(date_from, date_to):
                stats[key] = 0
                continue
            try:
                docs = self.db.query_documents(
                    date_from=date_from,
                    date_to=date_to,
                    min_quality=0.0,
                    limit=100000,
                )
                stats[key] = len(docs)
            except Exception as e:
                logger.error("时段统计失败 %s: %s", key, e)
                stats[key] = 0
        return stats

    # ------------------------------------------------------------------ #
    # 内部查询
    # ------------------------------------------------------------------ #
    def _query_segment(
        self, category: str, date_from: Optional[str], date_to: Optional[str]
    ) -> List[Dict[str, Any]]:
        if not self._valid_range(date_from, date_to):
            return []
        try:
            return self.db.query_documents(
                category=category,
                date_from=date_from,
                date_to=date_to,
                min_quality=0.0,
                limit=500,  # 取较多再排序截断
            )
        except Exception as e:
            logger.error("查询失败 [%s] %s~%s: %s", category, date_from, date_to, e)
            return []

    def _safe_stats(self) -> Dict[str, Any]:
        try:
            return self.db.get_stats()
        except Exception as e:
            logger.error("获取统计信息失败: %s", e)
            return {
                "total": 0,
                "recent_7d": 0,
                "by_category": {},
                "by_geo": {},
                "by_source": {},
                "quality_dist": {},
            }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    agg = Aggregator()
    data = agg.aggregate()
    print(f"\n聚合完成: 共 {data['total_items']} 条")
    print("时段统计:")
    for seg in data["time_segments"]:
        print(f"  {seg['label']}: {seg['doc_count']} 条")
    print("分类统计:")
    for cat in data["categories"]:
        print(f"  {cat['label']}: {cat['doc_count']} 条")
