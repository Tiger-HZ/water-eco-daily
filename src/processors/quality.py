"""
质量评估模块 - 对采集的知识进行质量评分与筛选
包含主题相关度过滤，排除与水生态环境无关的内容
"""
import re
import yaml
from typing import Dict, Any, List
from pathlib import Path


# 水生态环境核心关键词词典（用于主题相关度判断）
WATER_ECO_KEYWORDS = {
    # 中文核心词
    "zh_strong": [
        "水生态", "水环境", "水质", "水污染", "水处理", "水资源",
        "污水处理", "废水处理", "饮用水", "水源地", "水源保护",
        "河流", "湖泊", "水库", "流域", "湿地", "运河",
        "黑臭水体", "富营养化", "蓝藻", "水华",
        "排污口", "排污许可", "污水处理厂", "雨污分流",
        "水生生物", "生态流量", "水功能区", "断面水质",
        "水环境质量", "水环境容量", "纳污能力", "水质达标",
        "海绵城市", "管网改造", "提标改造",
        "河长制", "湖长制", "水十条", "碧水保卫战",
        "生态修复", "人工湿地", "生态浮床", "水生态修复",
        "面源污染", "农业面源", "非点源污染",
        "地表水", "地下水", "近岸海域", "入海河流",
        "水环境监测", "水质监测", "在线监测", "水质自动站",
        "钱塘江", "西湖", "太湖", "千岛湖", "富春江", "苕溪",
        "长江保护", "黄河保护", "入河排污",
        "排水许可", "城镇污水", "工业园区污水",
        "水生植被", "岸线修复", "生态护岸", "水生态恢复",
        "断面考核", "水环境承载力", "水生态状况评价",
        "再生水", "中水回用", "污水���源化",
        "溢流污染", "合流制", "分流制",
        # 常用水环境政策术语（新增）
        "水体", "河湖", "碧水", "治水", "水治理", "水环境保护",
        "水体治理", "群众身边水体", "美丽河湖", "水环境治理",
        "水生态保护", "水生态状况", "水环境状况",
        "集中式饮用水", "水源安全", "水污染物",
        "排放标准", "水环境标准", "工业园区水",
        "畜禽养殖污染", "入海排污口",
        "国考断面", "省考断面", "水生态调查",
        "水生态评价", "城镇排水", "水环境监管",
    ],
    "zh_medium": [
        "水", "河流", "湖", "水体的", "水系",
        "污染", "环境", "生态", "监测", "治理",
        "保护区", "达标", "排放", "净化",
    ],
    # 英文核心词
    "en_strong": [
        "water quality", "water pollution", "water treatment",
        "wastewater", "sewage", "drinking water",
        "river", "lake", "reservoir", "watershed", "wetland",
        "eutrophication", "cyanobacteria", "algal bloom",
        "aquatic ecosystem", "aquatic ecology",
        "water environment", "water monitoring",
        "constructed wetland", "ecological restoration",
        "nonpoint source", "diffuse pollution",
        "black odorous", "black water",
        "discharge outfall", "sewage treatment",
        "water function zone", "ecological flow",
        "surface water", "groundwater", "coastal water",
        "COD", "ammonia nitrogen", "total phosphorus",
        "BOD", "dissolved oxygen", "nutrient loading",
        "stormwater", "combined sewer", "separate sewer",
        "water restoration", "stream restoration",
        "bioretention", "rain garden", "green infrastructure",
        "water security", "water safety",
    ],
    "en_medium": [
        "water", "river", "lake", "aquatic", "hydro",
        "pollution", "environment", "ecology", "monitor",
    ],
}


class QualityAssessor:
    """知识质量评估器（含水生态主题相关度过滤）"""

    def __init__(self, config_path: str = "/workspace/water-eco-kb/config/settings.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.source_authority = self.config.get("source_authority", {})
        self.geo_weights = self.config.get("geo_weights", {})
        self.categories_path = "/workspace/water-eco-kb/config/categories.yaml"
        with open(self.categories_path, "r", encoding="utf-8") as f:
            self.categories_config = yaml.safe_load(f)
        self.geo_keywords = self.categories_config.get("geo_keywords", {})

    def assess(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        评估文档质量，返回评分和等级
        综合质量分 = 来源权威度(25%) + 内容深度(20%) + 地理相关性(15%) + 时效性(10%) + 主题相关度(30%)
        """
        # 主题相关度（最高优先级）
        relevance_score = self._score_topical_relevance(doc)

        # 相关度极低的直接拒绝
        if relevance_score < 0.15:
            return {
                "quality_score": 0.0,
                "quality_level": "低质量",
                "rejected": True,
                "reject_reason": "主题相关度过低，与水生态环境无关",
                "details": {"relevance": round(relevance_score, 3)},
            }

        source_score = self._score_source(doc)
        depth_score = self._score_content_depth(doc)
        geo_score = self._score_geo_relevance(doc)
        time_score = self._score_timeliness(doc)

        # 微信特殊评估
        wechat_bonus = 0.0
        if doc.get("source_type") == "微信公众号":
            wechat_bonus = self._score_wechat(doc)

        total = (
            source_score * 0.25
            + depth_score * 0.20
            + geo_score * 0.15
            + time_score * 0.10
            + relevance_score * 0.30
            + wechat_bonus
        )
        total = max(0.0, min(1.0, total))

        level = self._score_to_level(total)

        return {
            "quality_score": round(total, 3),
            "quality_level": level,
            "rejected": False,
            "details": {
                "source": round(source_score, 3),
                "depth": round(depth_score, 3),
                "geo": round(geo_score, 3),
                "timeliness": round(time_score, 3),
                "relevance": round(relevance_score, 3),
                "wechat_bonus": round(wechat_bonus, 3),
            },
        }

    def _score_topical_relevance(self, doc: Dict[str, Any]) -> float:
        """
        评估文档与水生态环境的主题相关度
        基于核心关键词在标题和内容/摘要中的命中情况
        """
        title = doc.get("title", "").lower()
        # 数据库中可能没有content字段，用summary补充
        content_parts = [doc.get("content", ""), doc.get("summary", "")]
        content = " ".join(str(p) for p in content_parts if p).lower()
        text = title + " " + content

        score = 0.0

        # 1. 标题中包含强核心词（权重最高）
        strong_hits_in_title = 0
        for kw in WATER_ECO_KEYWORDS["zh_strong"]:
            if kw in title:
                strong_hits_in_title += 1
        for kw in WATER_ECO_KEYWORDS["en_strong"]:
            if kw in title:
                strong_hits_in_title += 1

        if strong_hits_in_title >= 2:
            score += 0.6
        elif strong_hits_in_title == 1:
            score += 0.4

        # 2. 内容中包含强核心词
        strong_hits_in_content = 0
        for kw in WATER_ECO_KEYWORDS["zh_strong"]:
            if kw in content:
                strong_hits_in_content += 1
        for kw in WATER_ECO_KEYWORDS["en_strong"]:
            if kw in content:
                strong_hits_in_content += 1

        if strong_hits_in_content >= 5:
            score += 0.3
        elif strong_hits_in_content >= 3:
            score += 0.2
        elif strong_hits_in_content >= 1:
            score += 0.1

        # 3. 中等关键词补充
        medium_hits = 0
        for kw in WATER_ECO_KEYWORDS["zh_medium"]:
            if kw in text:
                medium_hits += 1
        for kw in WATER_ECO_KEYWORDS["en_medium"]:
            if kw in text:
                medium_hits += 1

        if medium_hits >= 3 and score < 0.3:
            score += 0.1  # 只有在分数较低时才补充

        # 4. 排除词检查（如果包含明显无关领域的强信号，降低分数）
        exclude_signals = [
            "糖尿病", "动脉硬化", "冠心病", "肿瘤", "癌症", "临床试验",
            "胰岛素", "血糖", "胆固醇", "血压",
            "稀土", "矿物", "采矿", "冶金",
            "大气化学", "PM2.5", "臭氧氧化", "挥发性有机物",
            "土壤重金属", "农田土壤", "土壤酸化",
            "社交媒体", " populist", "pipeline opposition",
            "climate migration", "migration climate",
        ]
        for excl in exclude_signals:
            if excl in text:
                score *= 0.3  # 大幅降低分数
                break

        return max(0.0, min(1.0, score))

    def _score_source(self, doc: Dict[str, Any]) -> float:
        source_type = doc.get("source_type", "其他")
        score = self.source_authority.get(source_type, 0.3)

        source = doc.get("source", "")
        authority_sources = {
            "生态环境部": 0.95, "水利部": 0.95, "国务院": 0.95,
            "浙江省生态环境厅": 0.90, "杭州市生态环境局": 0.90,
            "生态环境部办公厅": 0.90, "太湖流域管理局": 0.85,
        }
        for name, s in authority_sources.items():
            if name in source:
                score = max(score, s)
                break

        return score

    def _score_content_depth(self, doc: Dict[str, Any]) -> float:
        content = doc.get("content", "")
        if not content:
            return 0.1

        score = 0.0
        length = len(content)

        if length > 5000:
            score += 0.4
        elif length > 2000:
            score += 0.3
        elif length > 500:
            score += 0.2
        elif length > 100:
            score += 0.1

        if re.search(r"^#{1,3}\s", content, re.MULTILINE):
            score += 0.1
        if re.search(r"[一二三四五六七八九十]、", content):
            score += 0.1
        if "附件" in content or "附表" in content:
            score += 0.05

        citation_count = doc.get("extra_metadata", {}).get("citationCount", 0)
        if citation_count:
            if citation_count > 100:
                score += 0.2
            elif citation_count > 20:
                score += 0.15
            elif citation_count > 5:
                score += 0.1

        return min(1.0, score)

    def _score_geo_relevance(self, doc: Dict[str, Any]) -> float:
        geo_scope = doc.get("geo_scope", "全国")
        base = self.geo_weights.get(geo_scope, 0.0)

        content = (doc.get("content", "") + doc.get("title", "")).lower()
        for geo, keywords in self.geo_keywords.items():
            for kw in keywords:
                if kw in content:
                    base = max(base, self.geo_weights.get(geo, 0.0))
                    break

        return 0.5 + base

    def _score_timeliness(self, doc: Dict[str, Any]) -> float:
        publish_date = doc.get("publish_date", "")
        if not publish_date:
            return 0.5

        try:
            from datetime import datetime
            if len(publish_date) >= 4:
                year = int(publish_date[:4])
                current_year = datetime.now().year
                diff = current_year - year
                if diff <= 0:
                    return 1.0
                elif diff <= 1:
                    return 0.9
                elif diff <= 3:
                    return 0.7
                elif diff <= 5:
                    return 0.5
                else:
                    return 0.3
        except (ValueError, TypeError):
            pass
        return 0.5

    def _score_wechat(self, doc: Dict[str, Any]) -> float:
        bonus = 0.0
        extra = doc.get("extra_metadata", {})

        read_count = extra.get("read_count", 0)
        if read_count:
            if read_count > 10000:
                bonus += 0.15
            elif read_count > 5000:
                bonus += 0.10
            elif read_count > 1000:
                bonus += 0.05

        account = extra.get("account_name", "")
        whitelist = {
            "中国环境报": 0.1, "水利部": 0.1, "浙江生态环境": 0.08,
            "杭州生态环境": 0.08, "E20水网固废网": 0.05,
        }
        for name, b in whitelist.items():
            if name in account:
                bonus += b
                break

        return bonus

    @staticmethod
    def _score_to_level(score: float) -> str:
        if score >= 0.60:
            return "高质量"
        elif score >= 0.50:
            return "中等"
        elif score >= 0.40:
            return "一般"
        else:
            return "低质量"
