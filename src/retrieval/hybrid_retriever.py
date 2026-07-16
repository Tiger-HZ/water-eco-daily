"""
混合检索引擎 - 向量检索 + BM25关键词检索 + 元数据过滤 + RRF融合
"""
import logging
from typing import List, Dict, Any, Optional

from ..storage.vector_db import VectorDB
from ..storage.metadata_db import MetadataDB
from ..processors.embedder import Embedder

logger = logging.getLogger(__name__)


class HybridRetriever:
    """混合检索引擎"""

    def __init__(
        self,
        vector_db: VectorDB,
        embedder: Embedder,
        metadata_db: MetadataDB,
        config: Dict[str, Any] = None,
    ):
        self.vector_db = vector_db
        self.embedder = embedder
        self.metadata_db = metadata_db
        self.config = config or {}
        self.top_k = self.config.get("top_k", 20)
        self.final_k = self.config.get("final_k", 5)
        self.quality_threshold = self.config.get("quality_threshold", 0.3)
        self.bm25_weight = self.config.get("bm25_weight", 0.4)
        self.vector_weight = self.config.get("vector_weight", 0.6)

        # BM25索引（懒加载）
        self._bm25_index = None
        self._bm25_docs = None

    def retrieve(
        self,
        query: str,
        category: Optional[str] = None,
        geo_scope: Optional[str] = None,
        source_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_quality: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        混合检索：向量 + BM25 + 元数据过滤 + RRF融合
        """
        if min_quality is None:
            min_quality = self.quality_threshold
        if top_k is None:
            top_k = self.final_k

        # 构建元数据过滤条件
        where = self.vector_db.build_where_filter(
            category=category, geo_scope=geo_scope,
            source_type=source_type, min_quality=min_quality,
        )

        # 1. 向量检索
        query_embedding = self.embedder.embed_query(query)
        vector_results = self.vector_db.search_by_vector(
            query_embedding, top_k=self.top_k, where=where
        )
        logger.info(f"向量检索返回 {len(vector_results)} 条")

        # 2. BM25关键词检索
        bm25_results = self._bm25_search(query, top_k=self.top_k, where=where)
        logger.info(f"BM25检索返回 {len(bm25_results)} 条")

        # 3. RRF融合
        fused = self._rrf_fusion(vector_results, bm25_results)
        logger.info(f"RRF融合后 {len(fused)} 条")

        # 4. 补充元数据
        for item in fused:
            doc_id = item.get("metadata", {}).get("doc_id", item.get("id", ""))
            if doc_id:
                doc = self.metadata_db.get_document(doc_id)
                if doc:
                    item["doc_metadata"] = doc

        # 5. 过滤和排序
        filtered = [
            item for item in fused
            if item.get("metadata", {}).get("quality_score", 0) >= min_quality
        ]

        # 地理加权排序
        geo_priority = {"杭州": 0, "浙江": 1, "长三角": 2, "全国": 3, "国际": 4}
        filtered.sort(key=lambda x: (
            -x.get("rrf_score", 0),
            geo_priority.get(x.get("metadata", {}).get("geo_scope", "全国"), 3)
        ))

        return filtered[:top_k]

    def _bm25_search(self, query: str, top_k: int = 20, where: Optional[Dict] = None) -> List[Dict]:
        """BM25关键词检索"""
        try:
            from rank_bm25 import BM25Okapi
            import jieba

            # 获取所有文档（如果索引未构建）
            if self._bm25_index is None or self._bm25_docs is None:
                self._build_bm25_index()

            if self._bm25_index is None or not self._bm25_docs:
                return []

            # 对查询分词
            query_tokens = list(jieba.cut(query))

            # BM25检索
            scores = self._bm25_index.get_scores(query_tokens)

            # 获取top-k结果
            import numpy as np
            top_indices = np.argsort(scores)[::-1][:top_k]

            results = []
            for idx in top_indices:
                if scores[idx] > 0:
                    doc = self._bm25_docs[idx]
                    results.append({
                        "id": doc.get("chunk_id", str(idx)),
                        "content": doc.get("content", ""),
                        "metadata": doc.get("metadata", {}),
                        "bm25_score": float(scores[idx]),
                        "score": float(scores[idx]),
                    })

            return results

        except ImportError:
            logger.warning("rank-bm25或jieba未安装，跳过BM25检索")
            return []
        except Exception as e:
            logger.error(f"BM25检索失败: {e}")
            return []

    def _build_bm25_index(self):
        """从ChromaDB加载所有文档构建BM25索引"""
        try:
            import jieba

            # 从ChromaDB获取所有文档
            all_data = self.vector_db.collection.get(include=["documents", "metadatas"])
            if not all_data or not all_data.get("ids"):
                logger.info("ChromaDB为空，BM25索引无法构建")
                return

            self._bm25_docs = []
            tokenized_docs = []
            for i, doc_id in enumerate(all_data["ids"]):
                content = all_data["documents"][i] if all_data["documents"] else ""
                metadata = all_data["metadatas"][i] if all_data["metadatas"] else {}
                if content:
                    tokens = list(jieba.cut(content))
                    tokenized_docs.append(tokens)
                    self._bm25_docs.append({
                        "chunk_id": doc_id,
                        "content": content,
                        "metadata": metadata,
                    })

            if tokenized_docs:
                from rank_bm25 import BM25Okapi
                self._bm25_index = BM25Okapi(tokenized_docs)
                logger.info(f"BM25索引构建完成: {len(tokenized_docs)} 篇文档")

        except ImportError:
            logger.warning("jieba未安装，BM25索引无法构建。请运行: pip install jieba")
        except Exception as e:
            logger.error(f"BM25索引构建失败: {e}")

    def _rrf_fusion(
        self,
        vector_results: List[Dict],
        bm25_results: List[Dict],
        k: int = 60,
    ) -> List[Dict]:
        """Reciprocal Rank Fusion 融合两路检索结果"""
        scores = {}  # id -> {rrf_score, content, metadata, vector_rank, bm25_rank}

        # 向量检索结果
        for rank, item in enumerate(vector_results):
            item_id = item.get("id", "")
            if item_id not in scores:
                scores[item_id] = {
                    "id": item_id,
                    "content": item.get("content", ""),
                    "metadata": item.get("metadata", {}),
                    "vector_rank": rank,
                    "bm25_rank": None,
                    "rrf_score": 0.0,
                }
            scores[item_id]["rrf_score"] += self.vector_weight / (k + rank + 1)

        # BM25检索结果
        for rank, item in enumerate(bm25_results):
            item_id = item.get("id", "")
            if item_id not in scores:
                scores[item_id] = {
                    "id": item_id,
                    "content": item.get("content", ""),
                    "metadata": item.get("metadata", {}),
                    "vector_rank": None,
                    "bm25_rank": rank,
                    "rrf_score": 0.0,
                }
            scores[item_id]["rrf_score"] += self.bm25_weight / (k + rank + 1)
            scores[item_id]["bm25_rank"] = rank

        # 按RRF分数排序
        result = sorted(scores.values(), key=lambda x: x["rrf_score"], reverse=True)
        return result
