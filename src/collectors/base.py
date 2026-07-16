"""
采集器基类 - 定义统一的采集接口和数据结构
"""
import hashlib
import time
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """采集器基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.get("user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        })
        self.timeout = config.get("request_timeout", 30)
        self.delay = config.get("request_delay", 1.0)
        self.max_retries = config.get("max_retries", 3)

    @abstractmethod
    def collect(self) -> List[Dict[str, Any]]:
        """执行采集，返回标准化文档列表"""
        pass

    def fetch_url(self, url: str, encoding: str = "utf-8") -> Optional[str]:
        """带重试和延迟的URL获取"""
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.delay)
                resp = self.session.get(url, timeout=self.timeout, verify=False)
                if encoding:
                    resp.encoding = encoding
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                logger.warning(f"获取 {url} 失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        return None

    def fetch_binary(self, url: str) -> Optional[bytes]:
        """获取二进制内容"""
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.delay)
                resp = self.session.get(url, timeout=self.timeout, verify=False)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as e:
                logger.warning(f"获取 {url} 失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        return None

    @staticmethod
    def make_doc(
        title: str,
        content: str,
        url: str,
        source: str,
        source_type: str,
        category: str = "",
        geo_scope: str = "",
        publish_date: str = "",
        extra_metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """创建标准化文档对象"""
        return {
            "title": title.strip(),
            "content": content.strip(),
            "url": url.strip(),
            "source": source.strip(),
            "source_type": source_type,
            "category": category,
            "geo_scope": geo_scope,
            "publish_date": publish_date,
            "summary": "",
            "keywords": [],
            "quality_score": 0.5,
            "quality_level": "中等",
            "extra_metadata": extra_metadata or {},
            "collected_at": datetime.now().isoformat(),
            "status": "active",
        }
