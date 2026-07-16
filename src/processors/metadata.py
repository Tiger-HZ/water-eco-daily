"""
元数据提取与标注模块 - 自动提取文档元数据，推断分类和地理标签
"""
import re
import yaml
from typing import Dict, Any, List
from urllib.parse import urlparse


class MetadataExtractor:
    """元数据提取器"""

    def __init__(self, config_path: str = "/workspace/water-eco-kb/config/categories.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.category_keywords = self.config.get("category_keywords", {})
        self.geo_keywords = self.config.get("geo_keywords", {})

    def extract(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """提取并标注元数据"""
        content = doc.get("content", "") + " " + doc.get("title", "")

        # 推断分类
        if not doc.get("category"):
            doc["category"] = self._infer_category(content)

        # 推断地理范围
        if not doc.get("geo_scope"):
            doc["geo_scope"] = self._infer_geo_scope(content)

        # 提取关键词
        if not doc.get("keywords"):
            doc["keywords"] = self._extract_keywords(doc.get("content", ""), doc.get("title", ""))

        # 生成摘要（取前200字）
        if not doc.get("summary"):
            content_text = doc.get("content", "")
            doc["summary"] = content_text[:200].replace("\n", " ").strip() + ("..." if len(content_text) > 200 else "")

        # 从URL提取来源类型
        if not doc.get("source_type"):
            doc["source_type"] = self._infer_source_type(doc.get("url", ""), doc.get("source", ""))

        return doc

    def _infer_category(self, content: str) -> str:
        """基于关键词推断分类"""
        scores = {}
        for cat, keywords in self.category_keywords.items():
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                scores[cat] = score

        if scores:
            return max(scores, key=scores.get)
        return "02_研究文献"  # 默认分类

    def _infer_geo_scope(self, content: str) -> str:
        """基于地理关键词推断地理范围"""
        geo_found = {}
        for geo, keywords in self.geo_keywords.items():
            count = sum(1 for kw in keywords if kw in content)
            if count > 0:
                geo_found[geo] = count

        if geo_found:
            # 优先返回更具体的地理标签（杭州 > 浙江 > 长三角）
            priority = ["杭州", "浙江", "长三角", "全国", "国际"]
            for g in priority:
                if g in geo_found:
                    return g
        return "全国"

    def _extract_keywords(self, content: str, title: str = "") -> List[str]:
        """简单关键词提取（基于频率和位置）"""
        # 预定义水生态环境领域关键词
        domain_keywords = [
            "水生态环境", "水环境", "水生态", "水质", "水污染", "水污染防治",
            "污水处理", "废水处理", "黑臭水体", "富营养化", "蓝藻", "水华",
            "生态修复", "人工湿地", "生态流量", "饮用水水源", "水源地保护",
            "入河排污口", "排污许可", "流域治理", "河湖长制", "断面水质",
            "地表水", "地下水", "海洋生态", "近岸海域", "水生生物",
            "生物多样性", "生态廊道", "湿地保护", "长江保护", "黄河保护",
            "太湖", "巢湖", "滇池", "钱塘江", "西湖", "千岛湖",
            "COD", "氨氮", "总磷", "总氮", "BOD", "溶解氧",
            "断面考核", "水功能区", "水环境容量", "纳污能力",
            "海绵城市", "雨污分流", "管网改造", "提标改造",
            "智慧水务", "在线监测", "遥感监测", "水质自动站",
        ]

        found = []
        text = (title + " " + content).lower()
        for kw in domain_keywords:
            if kw.lower() in text:
                found.append(kw)

        # 如果找到的关键词太少，从标题中提取
        if len(found) < 3 and title:
            # 提取标题中的中文词组
            words = re.findall(r"[\u4e00-\u9fa5]{2,6}", title)
            found.extend(words[:5])

        return list(dict.fromkeys(found))[:15]  # 去重，最多15个

    def _infer_source_type(self, url: str, source: str) -> str:
        """从URL或来源名称推断来源类型"""
        if not url and not source:
            return "其他"

        text = (url + " " + source).lower()

        gov_domains = [".gov.cn", "mee.gov", "mwr.gov", "tba.gov", "gov.cn"]
        if any(d in text for d in gov_domains):
            return "政府机构"

        if "mp.weixin.qq.com" in text or "微信" in source:
            return "微信公众号"

        academic_domains = ["semanticscholar", "openalex", "doi.org", "springer", "elsevier", "wiley"]
        if any(d in text for d in academic_domains):
            return "学术期刊"

        media_domains = ["cenews", "news", "news.cn", "people.com"]
        if any(d in text for d in media_domains):
            return "主流媒体"

        if any(d in text for d in ["e20", "水网", "行业"]):
            return "行业媒体"

        return "其他"
