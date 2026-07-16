"""
手动添加数据脚本
================
允许用户手动添加知识文档到知识库。

使用方式：
  # 命令行添加
  python3 scripts/add_document.py --title "文档标题" --url "https://..." --category "01_政策法规与标准"
  
  # 交互式添加
  python3 scripts/add_document.py
  
  # 从文件添加
  python3 scripts/add_document.py --file /path/to/document.pdf --category "06_科研技术与实践案例"
"""
import sys
import os
import argparse
import logging
from datetime import datetime

sys.path.insert(0, "/workspace/water-eco-kb")

from src.storage.metadata_db import MetadataDB
from src.processors.parser import DocumentParser
from src.processors.metadata import MetadataExtractor
from src.processors.quality import QualityAssessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CATEGORIES = [
    "01_政策法规与标准",
    "02_水环境质量管理",
    "03_水污染防治与监管",
    "04_水生态修复与保护",
    "05_饮用水水源保护",
    "06_科研技术与实践案例",
    "07_动态资讯与综合",
]


def add_from_text(title, content, url, source, category, geo_scope=""):
    """从文本添加文档"""
    db = MetadataDB("/workspace/water-eco-kb/data/metadata.db")
    meta = MetadataExtractor()
    qa = QualityAssessor()

    doc = {
        "title": title,
        "content": content,
        "url": url,
        "source": source or "手动添加",
        "source_type": "其他",
        "category": category,
        "geo_scope": geo_scope,
        "publish_date": datetime.now().strftime("%Y-%m-%d"),
        "summary": "",
        "keywords": [],
        "quality_score": 0.5,
        "quality_level": "中等",
        "extra_metadata": {"added_by": "manual"},
        "collected_at": datetime.now().isoformat(),
        "status": "active",
    }

    doc = meta.extract(doc)
    quality = qa.assess(doc)
    doc["quality_score"] = quality["quality_score"]
    doc["quality_level"] = quality["quality_level"]

    doc_id, is_new = db.upsert_document(doc)
    logger.info(f"文档已{'新增' if is_new else '更新'}: {title} (ID: {doc_id[:8]}...)")
    return doc_id


def add_from_file(file_path, category, source=""):
    """从文件添加文档"""
    parser = DocumentParser()
    parsed = parser.parse(file_path)

    if not parsed["content"]:
        logger.error("无法从文件中提取内容")
        return None

    return add_from_text(
        title=parsed["title"] or os.path.basename(file_path),
        content=parsed["content"],
        url="",
        source=source or f"文件上传-{os.path.basename(file_path)}",
        category=category,
    )


def interactive_add():
    """交互式添加"""
    print("\n" + "=" * 50)
    print("  手动添加知识文档")
    print("=" * 50)

    title = input("\n标题: ").strip()
    if not title:
        print("标题不能为空")
        return

    print("\n内容（输入空行结束）:")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    content = "\n".join(lines)

    url = input("\nURL链接（可选）: ").strip()
    source = input("来源（可选）: ").strip()

    print("\n选择分类:")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"  {i}. {cat}")
    cat_idx = input(f"选择(1-{len(CATEGORIES)}, 默认7): ").strip()
    try:
        idx = int(cat_idx) - 1 if cat_idx else 6
        category = CATEGORIES[idx]
    except (ValueError, IndexError):
        category = CATEGORIES[6]

    geo = input("\n地理范围(杭州/浙江/长三角/全国/国际, 默认全国): ").strip() or "全国"

    add_from_text(title, content, url, source, category, geo)
    print("\n✅ 添加成功！")


def main():
    parser = argparse.ArgumentParser(description="手动添加知识文档")
    parser.add_argument("--title", help="文档标题")
    parser.add_argument("--content", help="文档内容")
    parser.add_argument("--url", help="原文URL")
    parser.add_argument("--source", help="来源")
    parser.add_argument("--category", default="07_动态资讯与综合", help="分类")
    parser.add_argument("--geo", default="全国", help="地理范围")
    parser.add_argument("--file", help="从文件添加（支持PDF/DOCX/TXT/HTML）")
    args = parser.parse_args()

    if args.file:
        if not os.path.exists(args.file):
            print(f"文件不存在: {args.file}")
            return
        add_from_file(args.file, args.category, args.source)
    elif args.title:
        add_from_text(args.title, args.content or args.title, args.url, args.source, args.category, args.geo)
    else:
        interactive_add()


if __name__ == "__main__":
    main()
