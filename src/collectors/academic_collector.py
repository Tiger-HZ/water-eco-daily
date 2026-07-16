"""
学术文献采集器 - 通过Semantic Scholar和OpenAlex API采集水生态环境领域文献
"""
import logging
import requests
from typing import List, Dict, Any
import yaml

from .base import BaseCollector

logger = logging.getLogger(__name__)


class AcademicCollector(BaseCollector):
    """学术文献采集器"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.sources_path = "/workspace/water-eco-kb/config/sources.yaml"
        with open(self.sources_path, "r", encoding="utf-8") as f:
            self.sources_config = yaml.safe_load(f)
        self.academic_config = self.sources_config.get("academic_sources", {})

    def collect(self) -> List[Dict[str, Any]]:
        """采集学术文献"""
        docs = []
        docs.extend(self._collect_semantic_scholar())
        docs.extend(self._collect_openalex())
        return docs

    def _collect_semantic_scholar(self) -> List[Dict[str, Any]]:
        """通过Semantic Scholar API采集"""
        config = self.academic_config.get("semantic_scholar", {})
        if not config:
            return []

        base_url = config.get("base_url", "https://api.semanticscholar.org/graph/v1")
        api_key = config.get("api_key", "")
        keywords = config.get("keywords", [])
        fields = config.get("fields", "title,year,abstract,citationCount,openAccessPdf,authors,venue,externalIds")
        min_citations = config.get("min_citations", 5)
        max_results = config.get("max_results", 50)

        headers = {"x-api-key": api_key} if api_key else {}
        docs = []

        for kw in keywords:
            try:
                logger.info(f"Semantic Scholar搜索: {kw}")
                url = f"{base_url}/paper/search/bulk"
                params = {
                    "query": kw,
                    "fields": fields,
                    "sort": "citationCount:desc",
                }

                import time
                time.sleep(1.1)  # 速率限制
                resp = requests.get(url, params=params, headers=headers, timeout=30)
                if resp.status_code != 200:
                    logger.warning(f"Semantic Scholar API返回 {resp.status_code}")
                    continue

                data = resp.json()
                papers = data.get("data", [])

                for paper in papers[:max_results]:
                    if paper.get("citationCount", 0) < min_citations:
                        continue

                    abstract = paper.get("abstract", "")
                    if not abstract or len(abstract) < 100:
                        continue

                    title = paper.get("title", "")
                    year = paper.get("year", "")
                    authors = [a.get("name", "") for a in paper.get("authors", [])[:5]]
                    venue = paper.get("venue", "")
                    doi = paper.get("externalIds", {}).get("DOI", "")
                    pdf_url = paper.get("openAccessPdf", {}).get("url", "") if paper.get("openAccessPdf") else ""

                    doc = self.make_doc(
                        title=title,
                        content=abstract,
                        url=pdf_url or f"https://doi.org/{doi}" if doi else "",
                        source=f"Semantic Scholar ({venue})" if venue else "Semantic Scholar",
                        source_type="学术期刊",
                        category="02_研究文献",
                        geo_scope="国际",
                        publish_date=f"{year}-01-01" if year else "",
                        extra_metadata={
                            "doi": doi,
                            "authors": authors,
                            "venue": venue,
                            "citationCount": paper.get("citationCount", 0),
                            "year": year,
                            "keywords": [kw],
                        },
                    )
                    docs.append(doc)

            except Exception as e:
                logger.error(f"Semantic Scholar采集 '{kw}' 失败: {e}")

        logger.info(f"Semantic Scholar共采集 {len(docs)} 篇文献")
        return docs

    def _collect_openalex(self) -> List[Dict[str, Any]]:
        """通过OpenAlex API采集（补充中文文献）"""
        config = self.academic_config.get("openalex", {})
        if not config:
            return []

        base_url = config.get("base_url", "https://api.openalex.org/works")
        keywords = config.get("keywords", [])
        min_cited = config.get("min_cited_by_count", 3)
        max_results = config.get("max_results", 50)

        docs = []
        for kw in keywords:
            try:
                logger.info(f"OpenAlex搜索: {kw}")
                params = {
                    "search": kw,
                    "per_page": max_results,
                    "sort": "cited_by_count:desc",
                    "filter": f"cited_by_count:>{min_cited}",
                }

                import time
                time.sleep(0.5)
                resp = requests.get(base_url, params=params, timeout=30)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                works = data.get("results", [])

                for work in works[:max_results]:
                    # 提取摘要
                    abstract_inv = work.get("abstract_inverted_index", {})
                    if not abstract_inv:
                        continue
                    # 重建摘要文本
                    positions = []
                    for word, idxs in abstract_inv.items():
                        for idx in idxs:
                            positions.append((idx, word))
                    positions.sort()
                    abstract = " ".join(w for _, w in positions)

                    if len(abstract) < 100:
                        continue

                    title = work.get("title", work.get("display_name", ""))
                    year = work.get("publication_year", "")
                    doi = work.get("doi", "")
                    cited = work.get("cited_by_count", 0)
                    venue = work.get("primary_location", {}).get("source", {}).get("display_name", "") if work.get("primary_location") else ""

                    # 获取作者
                    authorships = work.get("authorships", [])[:5]
                    authors = [a.get("author", {}).get("display_name", "") for a in authorships]

                    doc = self.make_doc(
                        title=title,
                        content=abstract,
                        url=doi or work.get("id", ""),
                        source=f"OpenAlex ({venue})" if venue else "OpenAlex",
                        source_type="学术期刊",
                        category="02_研究文献",
                        geo_scope="全国",
                        publish_date=f"{year}-01-01" if year else "",
                        extra_metadata={
                            "doi": doi.replace("https://doi.org/", "") if doi else "",
                            "authors": authors,
                            "venue": venue,
                            "citationCount": cited,
                            "year": year,
                            "keywords": [kw],
                            "openalex_id": work.get("id", ""),
                        },
                    )
                    docs.append(doc)

            except Exception as e:
                logger.error(f"OpenAlex采集 '{kw}' 失败: {e}")

        logger.info(f"OpenAlex共采集 {len(docs)} 篇文献")
        return docs
