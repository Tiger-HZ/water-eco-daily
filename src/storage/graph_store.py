"""
知识图谱存储模块 - 使用NetworkX管理实体关系图
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import networkx as nx

logger = logging.getLogger(__name__)


class GraphStore:
    """NetworkX知识图谱存储"""

    def __init__(self, graph_path: str = "/workspace/water-eco-kb/data/graph.json"):
        self.graph_path = graph_path
        self.graph = nx.DiGraph()
        self._load()

    def _load(self):
        """从JSON加载图"""
        path = Path(self.graph_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for node in data.get("nodes", []):
                    attrs = node.get("attrs", {})
                    # 将docs列表转回set
                    if "docs" in attrs and isinstance(attrs["docs"], list):
                        attrs["docs"] = set(attrs["docs"])
                    self.graph.add_node(node["id"], **attrs)
                for edge in data.get("edges", []):
                    attrs = edge.get("attrs", {})
                    if "docs" in attrs and isinstance(attrs["docs"], list):
                        attrs["docs"] = set(attrs["docs"])
                    self.graph.add_edge(edge["source"], edge["target"], **attrs)
                logger.info(f"加载知识图谱: {self.graph.number_of_nodes()} 节点, {self.graph.number_of_edges()} 边")
            except Exception as e:
                logger.warning(f"加载图谱失败: {e}")

    def save(self):
        """保存图到JSON"""
        def _serialize_attrs(attrs):
            """将属性中的set转为list，确保JSON可序列化"""
            clean = {}
            for k, v in attrs.items():
                if isinstance(v, set):
                    clean[k] = list(v)
                else:
                    clean[k] = v
            return clean

        data = {
            "nodes": [{"id": n, "attrs": _serialize_attrs(d)} for n, d in self.graph.nodes(data=True)],
            "edges": [{"source": u, "target": v, "attrs": _serialize_attrs(d)} for u, v, d in self.graph.edges(data=True)],
        }
        Path(self.graph_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"保存知识图谱: {self.graph.number_of_nodes()} 节点, {self.graph.number_of_edges()} 边")

    def add_entity(self, entity_text: str, entity_type: str, doc_id: str = "", **extra):
        """添加实体节点"""
        node_id = entity_text
        if not self.graph.has_node(node_id):
            self.graph.add_node(node_id, type=entity_type, docs=set(), **extra)
        # 关联文档
        if doc_id:
            if "docs" not in self.graph.nodes[node_id]:
                self.graph.nodes[node_id]["docs"] = set()
            self.graph.nodes[node_id]["docs"].add(doc_id)

    def add_relation(self, source: str, target: str, relation_type: str, doc_id: str = "", **extra):
        """添加关系边"""
        if not self.graph.has_edge(source, target):
            self.graph.add_edge(source, target, relation=relation_type, docs=set(), **extra)
        if doc_id:
            if "docs" not in self.graph.edges[source, target]:
                self.graph.edges[source, target]["docs"] = set()
            self.graph.edges[source, target]["docs"].add(doc_id)

    def get_entity(self, entity_text: str) -> Optional[Dict]:
        """获取实体信息"""
        if not self.graph.has_node(entity_text):
            return None
        node_data = dict(self.graph.nodes[entity_text])
        if "docs" in node_data:
            node_data["docs"] = list(node_data["docs"])
        node_data["related"] = self.get_related_entities(entity_text)
        return node_data

    def get_related_entities(self, entity_text: str, limit: int = 20) -> List[Dict]:
        """获取与实体相关的其他实体"""
        if not self.graph.has_node(entity_text):
            return []

        related = []
        # 出边
        for _, target, data in self.graph.out_edges(entity_text, data=True):
            if self.graph.has_node(target):
                target_data = self.graph.nodes[target]
                related.append({
                    "entity": target,
                    "type": target_data.get("type", ""),
                    "relation": data.get("relation", ""),
                    "direction": "outgoing",
                })
        # 入边
        for source, _, data in self.graph.in_edges(entity_text, data=True):
            if self.graph.has_node(source):
                source_data = self.graph.nodes[source]
                related.append({
                    "entity": source,
                    "type": source_data.get("type", ""),
                    "relation": data.get("relation", ""),
                    "direction": "incoming",
                })

        return related[:limit]

    def search_entities(self, keyword: str, limit: int = 20) -> List[Dict]:
        """搜索实体"""
        results = []
        for node, data in self.graph.nodes(data=True):
            if keyword.lower() in node.lower():
                results.append({
                    "entity": node,
                    "type": data.get("type", ""),
                    "docs": list(data.get("docs", set()))[:5],
                    "degree": self.graph.degree(node),
                })
                if len(results) >= limit:
                    break
        return results

    def get_subgraph(self, entity: str, depth: int = 2, limit: int = 50) -> Dict:
        """获取以某实体为中心的子图（用于可视化）"""
        if not self.graph.has_node(entity):
            return {"nodes": [], "edges": []}

        # BFS获取邻域
        nodes_set = {entity}
        frontier = {entity}
        for _ in range(depth):
            next_frontier = set()
            for n in frontier:
                for neighbor in self.graph.neighbors(n):
                    if neighbor not in nodes_set:
                        next_frontier.add(neighbor)
                for neighbor in self.graph.predecessors(n):
                    if neighbor not in nodes_set:
                        next_frontier.add(neighbor)
                if len(nodes_set) >= limit:
                    break
            nodes_set.update(next_frontier)
            frontier = next_frontier
            if len(nodes_set) >= limit:
                break

        sub = self.graph.subgraph(nodes_set)
        nodes = []
        for n, d in sub.nodes(data=True):
            nodes.append({
                "id": n,
                "type": d.get("type", ""),
                "label": n,
                "degree": sub.degree(n),
            })
        edges = []
        for u, v, d in sub.edges(data=True):
            edges.append({"source": u, "target": v, "relation": d.get("relation", "")})

        return {"nodes": nodes, "edges": edges}

    def get_stats(self) -> Dict:
        """获取图谱统计信息"""
        type_dist = {}
        for _, data in self.graph.nodes(data=True):
            t = data.get("type", "unknown")
            type_dist[t] = type_dist.get(t, 0) + 1

        relation_dist = {}
        for _, _, data in self.graph.edges(data=True):
            r = data.get("relation", "unknown")
            relation_dist[r] = relation_dist.get(r, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "type_distribution": type_dist,
            "relation_distribution": relation_dist,
        }

    def to_pyvis(self, entity: str = None, depth: int = 2) -> str:
        """生成pyvis可视化HTML"""
        try:
            from pyvis.network import Network
            import tempfile

            if entity:
                sub_data = self.get_subgraph(entity, depth)
                nodes_data = sub_data["nodes"]
                edges_data = sub_data["edges"]
            else:
                nodes_data = [{"id": n, "type": d.get("type", ""), "label": n}
                              for n, d in self.graph.nodes(data=True)]
                edges_data = [{"source": u, "target": v, "relation": d.get("relation", "")}
                              for u, v, d in self.graph.edges(data=True)]

            if not nodes_data:
                return "<p>暂无图谱数据</p>"

            net = Network(height="600px", width="100%", bgcolor="#ffffff", font_color="#333333")

            # 按类型着色
            color_map = {
                "政策法规": "#e74c3c", "水体": "#3498db", "污染物": "#e67e22",
                "机构": "#2ecc71", "专家": "#9b59b6", "技术": "#1abc9c",
                "地理位置": "#f39c12", "": "#95a5a6",
            }

            for node in nodes_data[:100]:  # 限制节点数
                color = color_map.get(node.get("type", ""), "#95a5a6")
                net.add_node(node["id"], label=node.get("label", node["id"]),
                           color=color, title=f"类型: {node.get('type', '未知')}")

            for edge in edges_data[:200]:
                try:
                    net.add_edge(edge["source"], edge["target"],
                               title=edge.get("relation", ""), label=edge.get("relation", ""))
                except Exception:
                    pass

            net.repulsion(node_distance=150, spring_length=100)

            tmp_path = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w")
            net.save_graph(tmp_path.name)
            with open(tmp_path.name, "r", encoding="utf-8") as f:
                html = f.read()
            return html

        except ImportError:
            return "<p>pyvis未安装，无法可视化图谱</p>"
        except Exception as e:
            return f"<p>图谱可视化失败: {e}</p>"
