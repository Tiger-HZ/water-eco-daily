"""
微信公众号文章采集器 - 通过搜索引擎和搜狗微信搜索采集文章
"""
import logging
import re
from typing import List, Dict, Any
from urllib.parse import urljoin, quote
from bs4 import BeautifulSoup
import yaml
import requests

from .base import BaseCollector
from ..processors.parser import DocumentParser
from ..processors.metadata import MetadataExtractor
from ..processors.quality import QualityAssessor

logger = logging.getLogger(__name__)


class WeChatCollector(BaseCollector):
    """微信公众号文章采集器"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.sources_path = "/workspace/water-eco-kb/config/sources.yaml"
        with open(self.sources_path, "r", encoding="utf-8") as f:
            self.sources_config = yaml.safe_load(f)
        self.wechat_accounts = self.sources_config.get("wechat_accounts", [])
        self.wechat_keywords = self.sources_config.get("wechat_keywords", [])
        self.parser = DocumentParser()
        self.metadata_extractor = MetadataExtractor()
        self.quality_assessor = QualityAssessor()

        # 构建公众号白名单映射
        self.whitelist = {acc["name"]: acc for acc in self.wechat_accounts}

    def collect(self) -> List[Dict[str, Any]]:
        """采集微信公众号文章"""
        docs = []
        # 通过搜狗微信搜索采集
        docs.extend(self._collect_via_sogou())
        # 通过通用搜索引擎间接获取
        docs.extend(self._collect_via_search())
        return docs

    def _collect_via_sogou(self) -> List[Dict[str, Any]]:
        """通过搜狗微信搜索采集"""
        docs = []
        base_url = "https://weixin.sogou.com/weixin"

        for kw in self.wechat_keywords[:5]:  # 每次最多搜索5个关键词
            try:
                logger.info(f"搜狗微信搜索: {kw}")
                params = {
                    "type": "2",  # 搜索文章
                    "query": kw,
                    "ie": "utf8",
                }

                import time
                time.sleep(2)  # 搜狗反爬较严，增加延迟
                resp = self.session.get(base_url, params=params, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"搜狗微信搜索返回 {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                # 搜狗微信搜索结果
                items = soup.select(".news-list li") or soup.select(".results .news-box")

                for item in items[:10]:
                    try:
                        # 提取标题和链接
                        title_el = item.select_one("h3 a") or item.select_one(".txt-box h3 a")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)

                        # 搜狗的链接是跳转链接
                        link = title_el.get("href", "")
                        if link and not link.startswith("http"):
                            link = urljoin("https://weixin.sogou.com", link)

                        # 提取公众号名称
                        account_el = item.select_one(".account") or item.select_one(".s-p .account")
                        account_name = account_el.get_text(strip=True) if account_el else ""

                        # 提取摘要
                        summary_el = item.select_one(".txt-info") or item.select_one(".s-p .txt-info")
                        summary = summary_el.get_text(strip=True) if summary_el else ""

                        # 提取日期
                        date_el = item.select_one(".s2") or item.select_one(".s-p .s2")
                        date_str = date_el.get_text(strip=True) if date_el else ""

                        if not title or len(title) < 5:
                            continue

                        # 检查是否为白名单公众号
                        in_whitelist = any(name in account_name for name in self.whitelist.keys())

                        doc = self.make_doc(
                            title=title,
                            content=summary or title,
                            url=link,
                            source=f"微信公众号-{account_name}" if account_name else "微信公众号",
                            source_type="微信公众号",
                            category="02_研究文献",
                            geo_scope="全国",
                            publish_date=self._parse_date(date_str),
                            extra_metadata={
                                "account_name": account_name,
                                "in_whitelist": in_whitelist,
                                "search_keyword": kw,
                            },
                        )

                        # 尝试获取文章全文
                        if link:
                            full_html = self.fetch_url(link)
                            if full_html:
                                parsed = self.parser.parse_html_content(full_html, link)
                                if parsed["content"] and len(parsed["content"]) > 200:
                                    doc["content"] = parsed["content"]
                                    doc["publish_date"] = parsed.get("publish_date", doc["publish_date"])

                        doc = self.metadata_extractor.extract(doc)

                        # 微信质量评估（白名单加分）
                        if in_whitelist:
                            doc["extra_metadata"]["read_count"] = 1000  # 预设值

                        quality = self.quality_assessor.assess(doc)
                        doc["quality_score"] = quality["quality_score"]
                        doc["quality_level"] = quality["quality_level"]

                        # 过滤低质量内容
                        if doc["quality_score"] >= 0.3:
                            docs.append(doc)

                    except Exception as e:
                        logger.debug(f"解析微信文章失败: {e}")
                        continue

            except Exception as e:
                logger.error(f"搜狗微信搜索 '{kw}' 失败: {e}")

        logger.info(f"搜狗微信共采集 {len(docs)} 篇文章")
        return docs

    def _collect_via_search(self) -> List[Dict[str, Any]]:
        """通过通用搜索引擎间接获取微信文章链接"""
        docs = []
        # 使用Bing搜索 site:mp.weixin.qq.com
        for kw in self.wechat_keywords[:3]:
            try:
                logger.info(f"搜索引擎搜索微信文章: {kw}")
                search_url = "https://www.bing.com/search"
                params = {
                    "q": f"site:mp.weixin.qq.com {kw}",
                    "count": 10,
                }

                import time
                time.sleep(1.5)
                resp = self.session.get(search_url, params=params, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                results = soup.select(".b_algo h2 a") or soup.select("li.b_algo h2 a")

                for result in results[:5]:
                    link = result.get("href", "")
                    title = result.get_text(strip=True)

                    if "mp.weixin.qq.com" not in link or not title:
                        continue

                    doc = self.make_doc(
                        title=title,
                        content=title,  # 先用标题，后续尝试获取全文
                        url=link,
                        source="微信公众号",
                        source_type="微信公众号",
                        category="02_研究文献",
                        geo_scope="全国",
                        extra_metadata={"search_keyword": kw, "search_engine": "bing"},
                    )

                    # 尝试获取全文
                    full_html = self.fetch_url(link)
                    if full_html:
                        parsed = self.parser.parse_html_content(full_html, link)
                        if parsed["content"] and len(parsed["content"]) > 200:
                            doc["content"] = parsed["content"]
                            doc["title"] = parsed["title"] or title
                            doc["publish_date"] = parsed.get("publish_date", "")

                    if len(doc["content"]) > 100:
                        doc = self.metadata_extractor.extract(doc)
                        quality = self.quality_assessor.assess(doc)
                        doc["quality_score"] = quality["quality_score"]
                        doc["quality_level"] = quality["quality_level"]
                        if doc["quality_score"] >= 0.3:
                            docs.append(doc)

            except Exception as e:
                logger.error(f"搜索引擎微信采集 '{kw}' 失败: {e}")

        logger.info(f"搜索引擎共采集 {len(docs)} 篇微信文章")
        return docs

    @staticmethod
    def _parse_date(date_str: str) -> str:
        """解析搜狗微信的日期格式"""
        if not date_str:
            return ""
        # 格式如 "2026-07-16" 或 "昨天" 或 "3天前"
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        return ""
