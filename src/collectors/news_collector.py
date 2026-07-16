"""
新闻资讯采集器 - 采集中国环境报等新闻媒体内容
"""
import logging
import re
from typing import List, Dict, Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import yaml

from .base import BaseCollector
from ..processors.parser import DocumentParser
from ..processors.metadata import MetadataExtractor
from ..processors.quality import QualityAssessor

logger = logging.getLogger(__name__)


class NewsCollector(BaseCollector):
    """新闻资讯采集器"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.sources_path = "/workspace/water-eco-kb/config/sources.yaml"
        with open(self.sources_path, "r", encoding="utf-8") as f:
            self.sources_config = yaml.safe_load(f)
        self.news_sources = self.sources_config.get("news_sources", [])
        self.parser = DocumentParser()
        self.metadata_extractor = MetadataExtractor()
        self.quality_assessor = QualityAssessor()

    def collect(self) -> List[Dict[str, Any]]:
        """采集所有新闻源"""
        all_docs = []
        for source in self.news_sources:
            try:
                logger.info(f"开始采集新闻: {source['name']}")
                docs = self._collect_source(source)
                all_docs.extend(docs)
                logger.info(f"  {source['name']}: 采集到 {len(docs)} 条")
            except Exception as e:
                logger.error(f"采集 {source['name']} 失败: {e}")
        return all_docs

    def _collect_source(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集单个新闻源"""
        docs = []
        html = self.fetch_url(source["url"])
        if not html:
            return docs

        soup = BeautifulSoup(html, "lxml")
        base_url = source.get("base_url", source["url"])

        # 提取新闻链接
        links = []
        seen = set()
        selectors = [
            source.get("list_selector", ""),
            ".news-list li a", "ul.list li a", ".list a",
            "a[href*='news/']", "a[href*='article/']", "a[href*='.html']",
            ".content a", ".main a",
        ]

        for selector in selectors:
            if not selector:
                continue
            elements = soup.select(selector)
            if elements:
                for el in elements:
                    href = el.get("href", "")
                    title = el.get_text(strip=True)
                    if href and title and len(title) > 8 and href not in seen:
                        full_url = urljoin(base_url, href)
                        if "javascript:" not in full_url and "#" not in href:
                            seen.add(full_url)
                            links.append((full_url, title))
                if len(links) >= 15:
                    break

        for link_url, title in links[:20]:
            article_html = self.fetch_url(link_url)
            if not article_html:
                continue

            parsed = self.parser.parse_html_content(article_html, link_url)
            if not parsed["content"] or len(parsed["content"]) < 200:
                continue

            doc = self.make_doc(
                title=parsed["title"] or title,
                content=parsed["content"],
                url=link_url,
                source=source["name"],
                source_type="主流媒体",
                category=source.get("category", "02_研究文献"),
                geo_scope=source.get("geo_scope", "全国"),
                publish_date=parsed.get("publish_date", ""),
                extra_metadata={"source_url": source["url"]},
            )

            doc = self.metadata_extractor.extract(doc)
            quality = self.quality_assessor.assess(doc)
            doc["quality_score"] = quality["quality_score"]
            doc["quality_level"] = quality["quality_level"]

            docs.append(doc)

        return docs
