"""
ChromaDB向量存储 - 管理文档向量索引和检索
"""
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class VectorDB:
    """ChromaDB向量数据库管理"""

    def __init__(
        self,
        persist_path: str = "/workspace/water-eco-kb/data/chroma",
        collection_name: str = "water_eco_knowledge"
    ):
        self.persist_path = persist_path
        self.collection_name = collection_name
        Path(persist_path).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"VectorDB初始化完成: {persist_path}, 集合: {collection_name}, 当前文档数: {self.collection.count()}")

    def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> List[str]:
        """批量添加文档向量，返回vector_id列表"""
        if not ids:
            return []

        # ChromaDB metadata值不能为None，需处理
        clean_metas = []
        for m in metadatas:
            clean = {}
            for k, v in m.items():
                if v is None:
                    clean[k] = ""
                elif isinstance(v, (str, int, float, bool)):
                    clean[k] = v
                else:
                    clean[k] = str(v)
            clean_metas.append(clean)

        # 分批处理，每批最多100条
        vector_ids = []
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_embs = embeddings[i:i + batch_size]
            batch_docs = documents[i:i + batch_size]
            batch_metas = clean_metas[i:i + batch_size]

            self.collection.upsert(
                ids=batch_ids,
                embeddings=batch_embs,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            vector_ids.extend(batch_ids)

        logger.info(f"添加 {len(ids)} 条文档向量到ChromaDB")
        return vector_ids

    def search_by_vector(
        self,
        query_embedding: List[float],
        top_k: int = 20,
        where: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """向量相似度搜索"""
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        docs = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                docs.append({
                    "id": doc_id,
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                    "score": 1 - results["distances"][0][i] if results["distances"] else 0,
                })
        return docs

    def search_by_keyword(
        self,
        query: str,
        top_k: int = 20,
        where: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """ChromaDB内置关键词搜索（基于文档内容）"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        docs = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                docs.append({
                    "id": doc_id,
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                    "score": 1 - results["distances"][0][i] if results["distances"] else 0,
                })
        return docs

    def build_where_filter(
        self,
        category: Optional[str] = None,
        geo_scope: Optional[str] = None,
        source_type: Optional[str] = None,
        min_quality: Optional[float] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Optional[Dict]:
        """构建ChromaDB元数据过滤条件"""
        conditions = []
        if category:
            conditions.append({"category": category})
        if geo_scope:
            conditions.append({"geo_scope": geo_scope})
        if source_type:
            conditions.append({"source_type": source_type})

        if min_quality is not None:
            conditions.append({"quality_score": {"$gte": min_quality}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def count(self) -> int:
        return self.collection.count()

    def delete_by_ids(self, ids: List[str]):
        if ids:
            self.collection.delete(ids=ids)
            logger.info(f"从ChromaDB删除 {len(ids)} 条向量")

    def get_all_ids(self) -> List[str]:
        """获取所有已存储的vector_id"""
        result = self.collection.get(include=[])
        return result.get("ids", [])
