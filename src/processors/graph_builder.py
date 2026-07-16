"""
知识图谱构建模块 - 从文档中抽取实体和关系构建知识图谱
"""
import re
import logging
from typing import List, Dict, Any
from pathlib import Path

from ..storage.graph_store import GraphStore

logger = logging.getLogger(__name__)


class GraphBuilder:
    """知识图谱构建器"""

    # 水生态环境领域实体词典
    ENTITY_DICT = {
        "水体": [
            "长江", "黄河", "珠江", "淮河", "海河", "松花江", "辽河", "钱塘江",
            "太湖", "巢湖", "滇池", "鄱阳湖", "洞庭湖", "洪泽湖", "西湖", "千岛湖",
            "富春江", "瓯江", "椒江", "曹娥江", "京杭运河", "黑臭水体",
            "渤海", "黄海", "东海", "南海", "杭州湾", "长江口",
        ],
        "污染物": [
            "COD", "BOD", "氨氮", "总磷", "总氮", "溶解氧", "重金属",
            "铅", "汞", "镉", "铬", "砷", "氰化物", "石油类",
            "挥发性酚", "硝酸盐", "亚硝酸盐", "多环芳烃", "内分泌干扰物",
            "微塑料", "抗生素", "全氟化合物",
        ],
        "机构": [
            "生态环境部", "水利部", "自然资源部", "住房和城乡建设部",
            "浙江省生态环境厅", "杭州市生态环境局", "太湖流域管理局",
            "中国环境科学研究院", "中国科学院", "清华大学", "浙江大学",
            "同济大学", "河海大学", "中国环境监测总站",
        ],
        "技术": [
            "活性污泥法", "生物膜法", "膜生物反应器", "MBR", "人工湿地",
            "生态浮床", "生物修复", "化学絮凝", "高级氧化", "膜分离",
            "反渗透", "超滤", "纳滤", "消毒", "脱氮除磷",
            "雨污分流", "海绵城市", "智慧水务", "遥感监测", "在线监测",
        ],
        "政策法规": [
            "水污染防治法", "长江保护法", "黄河保护法", "水法",
            "水十条", "河长制", "湖长制", "排污许可制",
            "饮用水水源保护", "水环境质量标准", "地表水环境质量标准",
            "城镇污水处理厂污染物排放标准",
        ],
    }

    # 关系模式（实体类型对 → 关系类型）
    RELATION_PATTERNS = [
        # (主语类型, 客语类型, 关系, 模式关键词列表)
        ("机构", "水体", "管辖", ["管辖", "管理", "负责", "监管"]),
        ("机构", "政策法规", "发布", ["发布", "印发", "出台", "制定"]),
        ("机构", "技术", "研发", ["研发", "开发", "研究", "创新"]),
        ("污染物", "水体", "污染", ["污染", "超标", "排放", "排入"]),
        ("技术", "污染物", "去除", ["去除", "处理", "降解", "净化", "消除"]),
        ("技术", "水体", "修复", ["修复", "治理", "改善", "恢复"]),
        ("政策法规", "水体", "保护", ["保护", "治理", "管理"]),
        ("政策法规", "污染物", "限制", ["限制", "管控", "禁止", "标准"]),
    ]

    def __init__(self, graph_store: GraphStore = None):
        self.graph_store = graph_store or GraphStore()
        self._nlp = None

    def _get_nlp(self):
        """懒加载spaCy模型"""
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("zh_core_web_sm")
                logger.info("spaCy中文模型加载完成")
            except Exception as e:
                logger.warning(f"spaCy模型加载失败: {e}")
        return self._nlp

    def build_from_documents(self, documents: List[Dict[str, Any]]):
        """从文档列表构建知识图谱"""
        for doc in documents:
            try:
                self._process_document(doc)
            except Exception as e:
                logger.debug(f"处理文档 {doc.get('id', '')} 失败: {e}")

        self.graph_store.save()
        logger.info(f"知识图谱构建完成: {self.graph_store.graph.number_of_nodes()} 节点, "
                    f"{self.graph_store.graph.number_of_edges()} 边")

    def _process_document(self, doc: Dict[str, Any]):
        """处理单个文档，提取实体和关系"""
        doc_id = doc.get("id", "")
        content = doc.get("content", "") + " " + doc.get("title", "")

        # 1. 基于词典的实体识别
        entities = self._extract_entities_by_dict(content)

        # 2. spaCy NER补充
        nlp = self._get_nlp()
        if nlp:
            spacy_entities = self._extract_entities_by_spacy(content, nlp)
            entities.extend(spacy_entities)
            # 去重
            seen = {(e["text"], e["type"]) for e in entities}
            entities = [e for e in entities if (e["text"], e["type"]) not in seen or seen.discard((e["text"], e["type"]))]

        # 添加实体到图
        for ent in entities:
            self.graph_store.add_entity(ent["text"], ent["type"], doc_id)

        # 3. 基于模式的关系抽取
        relations = self._extract_relations(content, entities)
        for rel in relations:
            self.graph_store.add_relation(
                rel["source"], rel["target"], rel["relation"], doc_id
            )

    def _extract_entities_by_dict(self, content: str) -> List[Dict[str, str]]:
        """基于领域词典的实体识别"""
        entities = []
        for entity_type, terms in self.ENTITY_DICT.items():
            for term in terms:
                if term in content:
                    entities.append({"text": term, "type": entity_type})
        return entities

    def _extract_entities_by_spacy(self, content: str, nlp) -> List[Dict[str, str]]:
        """使用spaCy进行NER"""
        entities = []
        # 截取前5000字符避免处理过慢
        doc = nlp(content[:5000])
        type_map = {
            "PERSON": "专家", "ORG": "机构", "GPE": "地理位置",
            "LOC": "地理位置", "LAW": "政策法规",
        }
        for ent in doc.ents:
            if ent.text and len(ent.text) >= 2:
                ent_type = type_map.get(ent.label_, "")
                if ent_type:
                    entities.append({"text": ent.text.strip(), "type": ent_type})
        return entities

    def _extract_relations(self, content: str, entities: List[Dict]) -> List[Dict]:
        """基于模式的关系抽取"""
        relations = []
        # 按类型分组
        by_type = {}
        for e in entities:
            by_type.setdefault(e["type"], []).append(e["text"])

        for subj_type, obj_type, relation, patterns in self.RELATION_PATTERNS:
            subjects = by_type.get(subj_type, [])
            objects = by_type.get(obj_type, [])
            if not subjects or not objects:
                continue

            for subj in subjects:
                for obj in objects:
                    if subj == obj:
                        continue
                    # 检查是否有关系模式关键词在两者之间
                    for pattern in patterns:
                        # 查找 "主语...模式...客语" 或 "客语...模式...主语"
                        regex1 = f"{re.escape(subj)}[^。]{{0,50}}{re.escape(pattern)}[^。]{{0,30}}{re.escape(obj)}"
                        regex2 = f"{re.escape(obj)}[^。]{{0,50}}{re.escape(pattern)}[^。]{{0,30}}{re.escape(subj)}"
                        if re.search(regex1, content) or re.search(regex2, content):
                            relations.append({
                                "source": subj,
                                "target": obj,
                                "relation": relation,
                            })
                            break  # 一个关系模式匹配即可
                    else:
                        continue
                    break  # 已找到关系，不再检查其他模式

        return relations
