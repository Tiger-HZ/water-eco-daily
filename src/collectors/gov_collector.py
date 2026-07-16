"""
政务网站爬虫 - 采集生态环境部、水利部、省市生态环境厅局等政务网站内容
"""
import re
import logging
from typing import List, Dict, Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import yaml

from .base import BaseCollector
from ..processors.parser import DocumentParser
from ..processors.metadata import MetadataExtractor
from ..processors.quality import QualityAssessor

logger = logging.getLogger(__name__)


class GovCollector(BaseCollector):
    """政务网站采集器"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.sources_path = "/workspace/water-eco-kb/config/sources.yaml"
        with open(self.sources_path, "r", encoding="utf-8") as f:
            self.sources_config = yaml.safe_load(f)
        self.gov_sources = self.sources_config.get("gov_sources", [])
        self.parser = DocumentParser()
        self.metadata_extractor = MetadataExtractor()
        self.quality_assessor = QualityAssessor()

    def collect(self) -> List[Dict[str, Any]]:
        """采集所有政务网站"""
        all_docs = []
        for source in self.gov_sources:
            try:
                logger.info(f"开始采集: {source['name']}")
                docs = self._collect_source(source)
                all_docs.extend(docs)
                logger.info(f"  {source['name']}: 采集到 {len(docs)} 条")
            except Exception as e:
                logger.error(f"采集 {source['name']} 失败: {e}")

        return all_docs

    def _collect_source(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集单个数据源"""
        docs = []
        html = self.fetch_url(source["url"])
        if not html:
            logger.warning(f"无法获取列表页: {source['url']}")
            return docs

        soup = BeautifulSoup(html, "lxml")
        base_url = source.get("base_url", source["url"])

        # 提取文章链接
        links = self._extract_article_links(soup, source, base_url)

        for link_url, title in links[:30]:  # 每个源最多采集30篇
            if not title or len(title) < 5:
                continue

            article_html = self.fetch_url(link_url)
            if not article_html:
                continue

            parsed = self.parser.parse_html_content(article_html, link_url)
            if not parsed["content"] or len(parsed["content"]) < 100:
                continue

            doc = self.make_doc(
                title=parsed["title"] or title,
                content=parsed["content"],
                url=link_url,
                source=source["name"],
                source_type="政府机构",
                category=source.get("category", "01_政策法规标准"),
                geo_scope=source.get("geo_scope", "全国"),
                publish_date=parsed.get("publish_date", ""),
                extra_metadata={
                    "source_url": source["url"],
                    "source_name": source["name"],
                },
            )

            # 元数据提取与质量评估
            doc = self.metadata_extractor.extract(doc)
            quality = self.quality_assessor.assess(doc)
            doc["quality_score"] = quality["quality_score"]
            doc["quality_level"] = quality["quality_level"]

            docs.append(doc)

        return docs

    def _extract_article_links(self, soup: BeautifulSoup, source: Dict[str, Any],
                                base_url: str) -> List[tuple]:
        """从列表页提取文章链接和标题"""
        links = []
        seen = set()

        # 尝试多种选择器
        selectors = [
            source.get("list_selector", ""),
            "ul.list li a", "ul li a", ".list li a",
            ".news-list li a", ".content-list li a",
            "table tr a", ".article-list a",
            "a[href*='art/']", "a[href*='content/']", "a[href*='news/']",
            "a[href*='.html']", "a[href*='.htm']",
        ]

        for selector in selectors:
            if not selector:
                continue
            elements = soup.select(selector)
            if elements:
                for el in elements:
                    href = el.get("href", "")
                    title = el.get_text(strip=True)
                    if href and title and len(title) > 5:
                        full_url = urljoin(base_url, href)
                        if full_url not in seen and self._is_article_url(full_url, source):
                            seen.add(full_url)
                            links.append((full_url, title))
                if len(links) >= 10:
                    break

        return links

    @staticmethod
    def _is_article_url(url: str, source: Dict[str, Any]) -> bool:
        """判断URL是否为文章页"""
        # 排除列表页和导航页
        exclude_patterns = ["index.html", "index.htm", "list.html", "/col/", "javascript:"]
        for pattern in exclude_patterns:
            if pattern in url:
                return False
        # 包含文章特征
        article_patterns = ["art/", "content/", "news/", "article/", "detail/",
                           ".html", ".htm", ".shtml"]
        return any(p in url for p in article_patterns)
