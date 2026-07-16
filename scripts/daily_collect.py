"""
每日资讯综合采集脚本（增量模式）
================================
- 不清空数据库，增量采集
- 学术文献：Semantic Scholar + OpenAlex，15+关键词×30条
- 微信公众号：wechat-article-search技能
- 日期过滤：2023-2026
- 自动去重：URL+标题哈希 + 标题相似度
- 主题相关度过滤：排除非水生态环境内容
"""
import sys
import os
import json
import time
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.metadata_db import MetadataDB
from src.processors.metadata import MetadataExtractor
from src.processors.quality import QualityAssessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

WECHAT_SEARCH_SCRIPT = "/root/.codebuddy/skills/skill_2053083784548929536/scripts/search_wechat.js"

# Semantic Scholar 关键词（扩展到15个）
S2_KEYWORDS = [
    "water ecology restoration", "aquatic ecosystem management",
    "water quality monitoring", "lake eutrophication control",
    "constructed wetland wastewater", "ecological flow river",
    "water pollution control", "drinking water protection",
    "river restoration ecology", "sewage treatment technology",
    "water environmental management", "black odorous water remediation",
    "nonpoint source pollution water", "reservoir water quality",
    "urban stormwater management",
]

# OpenAlex 关键词（扩展到15个）
OA_KEYWORDS = [
    "水生态环境", "水环境治理", "水生态修复", "黑臭水体治理",
    "饮用水安全", "湖泊富营养化", "蓝藻水华",
    "入河排污口", "污水处理", "流域生态管理",
    "水质监测评价", "人工湿地", "面源污染控制",
    "钱塘江水环境", "太湖水生态",
]

# 微信搜索关键词
WECHAT_KEYWORDS = [
    "水生态环境", "水环境治理", "水生态修复", "黑臭水体",
    "饮用水水源", "入河排污口", "污水处理", "流域治理",
    "水质监测", "水污染防治",
]

# 水生态核心词（用于标题预筛）
WATER_TITLE_KEYWORDS = [
    "water", "lake", "river", "aquatic", "wetland", "watershed",
    "sewage", "wastewater", "eutrophication", "drinking water",
    "水生", "水环境", "水质", "水污染", "水处理", "水源",
    "污水", "废水", "饮用水", "河流", "湖泊", "水库",
    "流域", "湿地", "黑臭", "富营养化", "蓝藻", "排污",
    "水生态", "水功能", "断面", "水环境质量", "生态流量",
    "钱塘江", "太湖", "西湖", "千岛湖", "运河",
]


def is_water_related(title, content=""):
    """标题预筛：必须包含水相关关键词"""
    text = (title + " " + content).lower()
    for kw in WATER_TITLE_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def collect_via_academic(db, meta, qa):
    """学术文献采集（增量，不清空DB）"""
    import requests as req
    docs = []

    # Semantic Scholar
    for kw in S2_KEYWORDS:
        try:
            logger.info(f"  S2: {kw}")
            url = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
            params = {
                "query": kw,
                "fields": "title,year,abstract,citationCount,openAccessPdf,authors,venue,externalIds",
                "sort": "citationCount:desc",
            }
            time.sleep(1.1)
            resp = req.get(url, params=params, timeout=20)
            if resp.status_code != 200:
                continue
            papers = resp.json().get("data", [])
            for p in papers[:25]:  # 每词25条
                abstract = p.get("abstract", "")
                title = p.get("title", "")
                if not abstract or len(abstract) < 100:
                    continue
                if not is_water_related(title, abstract):
                    continue
                year = p.get("year", 0)
                if year and (year < 2020 or year > 2026):
                    continue
                authors = [a.get("name", "") for a in p.get("authors", [])[:3]]
                venue = p.get("venue", "")
                doi = p.get("externalIds", {}).get("DOI", "")
                cited = p.get("citationCount", 0)

                doc = {
                    "title": title, "content": abstract,
                    "url": f"https://doi.org/{doi}" if doi else "",
                    "source": f"Semantic Scholar ({venue})" if venue else "Semantic Scholar",
                    "source_type": "学术期刊", "category": "06_科研技术与实践案例",
                    "geo_scope": "国际" if not any(g in title for g in ["China", "Chinese", "Lake Tai", "Lake Cha", "Lake Dong"]) else "全国",
                    "publish_date": f"{year}-01-01" if year else "",
                    "summary": "", "keywords": [],
                    "quality_score": 0.8 if cited > 20 else 0.6,
                    "quality_level": "高质量" if cited > 20 else "中等",
                    "extra_metadata": {"doi": doi, "authors": authors, "citationCount": cited, "year": year},
                    "collected_at": datetime.now().isoformat(), "status": "active",
                }
                docs.append(doc)
        except Exception as e:
            logger.warning(f"  S2 '{kw}' 失败: {e}")

    # OpenAlex
    for kw in OA_KEYWORDS:
        try:
            logger.info(f"  OpenAlex: {kw}")
            url = "https://api.openalex.org/works"
            params = {
                "search": kw, "per_page": 25,
                "sort": "cited_by_count:desc",
                "filter": "cited_by_count:>3,from_publication_date:2020-01-01",
            }
            time.sleep(0.5)
            resp = req.get(url, params=params, timeout=20)
            if resp.status_code != 200:
                continue
            works = resp.json().get("results", [])
            for w in works[:25]:
                abs_idx = w.get("abstract_inverted_index", {})
                if not abs_idx:
                    continue
                positions = [(i, word) for word, idxs in abs_idx.items() for i in idxs]
                positions.sort()
                abstract = " ".join(w for _, w in positions)
                if len(abstract) < 100:
                    continue
                title = w.get("title", w.get("display_name", ""))
                if not is_water_related(title, abstract):
                    continue
                year = w.get("publication_year", 0)
                if year and (year < 2020 or year > 2026):
                    continue
                doi = w.get("doi", "")
                cited = w.get("cited_by_count", 0)
                venue = ""
                if w.get("primary_location") and w["primary_location"].get("source"):
                    venue = w["primary_location"]["source"].get("display_name", "")

                doc = {
                    "title": title, "content": abstract,
                    "url": doi or "",
                    "source": f"OpenAlex ({venue})" if venue else "OpenAlex",
                    "source_type": "学术期刊", "category": "06_科研技术与实践案例",
                    "geo_scope": "全国",
                    "publish_date": f"{year}-01-01" if year else "",
                    "summary": "", "keywords": [],
                    "quality_score": 0.8 if cited > 20 else 0.6,
                    "quality_level": "高质量" if cited > 20 else "中等",
                    "extra_metadata": {"doi": doi, "citationCount": cited, "year": year},
                    "collected_at": datetime.now().isoformat(), "status": "active",
                }
                docs.append(doc)
        except Exception as e:
            logger.warning(f"  OpenAlex '{kw}' 失败: {e}")

    logger.info(f"学术文献采集: {len(docs)} 条")
    return docs


def collect_via_wechat(db, meta, qa):
    """微信公众号文章采集"""
    docs = []
    node_path = os.popen("npm root -g").read().strip()
    env = os.environ.copy()
    env["NODE_PATH"] = node_path

    for kw in WECHAT_KEYWORDS:
        try:
            logger.info(f"  微信: {kw}")
            output_file = f"/tmp/wechat_{abs(hash(kw))}.json"
            result = subprocess.run(
                ["node", WECHAT_SEARCH_SCRIPT, kw, "-n", "10", "-o", output_file],
                capture_output=True, text=True, timeout=30, env=env
            )
            if result.returncode == 0 and os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as f:
                    raw = f.read()
                # 尝试解析JSON
                try:
                    articles = json.loads(raw)
                    if isinstance(articles, dict):
                        articles = articles.get("data", articles.get("results", [articles]))
                except json.JSONDecodeError:
                    # 可能是JSON Lines格式
                    articles = []
                    for line in raw.strip().split("\n"):
                        try:
                            articles.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

                for art in articles:
                    if not isinstance(art, dict):
                        continue
                    title = art.get("title", "")
                    url = art.get("url", art.get("link", ""))
                    summary = art.get("summary", art.get("snippet", art.get("abstract", "")))
                    pub_time = art.get("pubTime", art.get("publish_time", art.get("date", "")))
                    account = art.get("account", art.get("source", art.get("author", "")))
                    if len(title) < 5 or not is_water_related(title, summary):
                        continue

                    doc = {
                        "title": title, "content": summary or title,
                        "url": url,
                        "source": f"微信公众号-{account}" if account else "微信公众号",
                        "source_type": "微信公众号", "category": "",
                        "geo_scope": "", "publish_date": pub_time[:10] if pub_time else "",
                        "summary": "", "keywords": [],
                        "quality_score": 0.4, "quality_level": "一般",
                        "extra_metadata": {"account_name": account, "search_keyword": kw},
                        "collected_at": datetime.now().isoformat(), "status": "active",
                    }
                    docs.append(doc)
                os.remove(output_file)
            time.sleep(1.5)
        except Exception as e:
            logger.warning(f"  微信 '{kw}' 失败: {e}")

    logger.info(f"微信采集: {len(docs)} 条")
    return docs


def deduplicate_and_store(docs, db, meta, qa):
    """去重入库：URL哈希 + 标题相似度"""
    # 获取现有文档标题
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT id, title, quality_score FROM documents WHERE status='active'").fetchall()
    existing_titles = {r["title"]: r for r in existing}
    conn.close()

    new_count = 0
    dup_count = 0
    rejected_count = 0

    for doc in docs:
        # 元数据提取
        if not doc.get("category"):
            doc = meta.extract(doc)

        # 质量评估（含相关度检查）
        quality = qa.assess(doc)
        doc["quality_score"] = quality["quality_score"]
        doc["quality_level"] = quality["quality_level"]

        if quality.get("rejected"):
            rejected_count += 1
            continue

        # 标题相似度检查
        title = doc["title"]
        is_dup = False
        for existing_title, existing_row in list(existing_titles.items()):
            ratio = SequenceMatcher(None, title.lower(), existing_title.lower()).ratio()
            if ratio > 0.85:
                # 重复：保留质量更高的
                if doc["quality_score"] > existing_row["quality_score"]:
                    # 新文档质量更高，删除旧文档
                    conn = sqlite3.connect(db.db_path)
                    conn.execute("UPDATE documents SET status='replaced' WHERE id=?", (existing_row["id"],))
                    conn.commit()
                    conn.close()
                    del existing_titles[existing_title]
                else:
                    # 旧文档质量更高，跳过新文档
                    is_dup = True
                    dup_count += 1
                    break

        if not is_dup:
            doc_id, is_new = db.upsert_document(doc)
            if is_new:
                new_count += 1
                existing_titles[title] = {"id": doc_id, "quality_score": doc["quality_score"]}

    logger.info(f"入库结果: 新增 {new_count}, 重复跳过 {dup_count}, 相关度排除 {rejected_count}")
    return new_count


def main():
    logger.info("=" * 60)
    logger.info("水生态环境资讯采集（增量模式）")
    logger.info(f"日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 60)

    db = MetadataDB(str(PROJECT_ROOT / "data" / "metadata.db"))
    meta = MetadataExtractor()
    qa = QualityAssessor()

    # 显示当前数据库状态
    stats_before = db.get_stats()
    logger.info(f"当前知识库: {stats_before['total']} 篇")

    all_docs = []

    # 1. 学术文献采集
    logger.info("\n--- 学术文献采集 ---")
    all_docs.extend(collect_via_academic(db, meta, qa))

    # 2. 微信文章采集
    logger.info("\n--- 微信公众号采集 ---")
    all_docs.extend(collect_via_wechat(db, meta, qa))

    # 3. 去重入库
    logger.info(f"\n--- 去重入库（共 {len(all_docs)} 条待处理）---")
    new_count = deduplicate_and_store(all_docs, db, meta, qa)

    # 统计
    stats = db.get_stats()
    logger.info("=" * 60)
    logger.info(f"采集完成")
    logger.info(f"  采集前: {stats_before['total']} 篇")
    logger.info(f"  新增: {new_count} 篇")
    logger.info(f"  当前总量: {stats['total']} 篇")
    logger.info(f"  分类: {stats['by_category']}")
    logger.info(f"  地理: {stats['by_geo']}")
    logger.info(f"  质量: {stats['quality_dist']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
