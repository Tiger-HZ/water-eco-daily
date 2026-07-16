"""
嵌入向量生成模块 - 使用BGE中文嵌入模型生成文档向量
"""
import logging
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class Embedder:
    """嵌入向量生成器"""

    _model = None

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-zh-v1.5",
        device: str = "cpu",
        cache_dir: str = "/workspace/water-eco-kb/data/cache",
    ):
        self.model_name = model_name
        self.device = device
        self.cache_dir = cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    def _get_model(self):
        """懒加载嵌入模型（单例）"""
        if Embedder._model is None:
            logger.info(f"正在加载嵌入模型: {self.model_name} (device={self.device})")
            from sentence_transformers import SentenceTransformer
            import os
            os.environ["HF_HOME"] = self.cache_dir
            os.environ["TRANSFORMERS_CACHE"] = self.cache_dir

            Embedder._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                cache_folder=self.cache_dir,
            )
            logger.info(f"嵌入模型加载完成，向量维度: {Embedder._model.get_sentence_embedding_dimension()}")
        return Embedder._model

    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """批量生成文本嵌入向量"""
        if not texts:
            return []

        model = self._get_model()

        # BGE模型建议使用query前缀（对于检索场景）
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 50,
            normalize_embeddings=True,  # 归一化，方便余弦相似度计算
            convert_to_numpy=True,
        )

        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        """生成查询向量（BGE模型对query需要加前缀）"""
        model = self._get_model()

        # BGE模型建议对查询添加 "为这个句子生成表示以用于检索相关文章："
        prefix = "为这个句子生成表示以用于检索相关文章："
        query_text = prefix + query

        embedding = model.encode(
            [query_text],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embedding[0].tolist()

    def embed_documents(self, documents: List[dict], batch_size: int = 32) -> List[dict]:
        """为文档列表生成嵌入，返回带向量的文档"""
        texts = [doc["content"] for doc in documents]
        embeddings = self.embed_texts(texts, batch_size)

        for doc, emb in zip(documents, embeddings):
            doc["embedding"] = emb

        return documents

    @property
    def dimension(self) -> int:
        model = self._get_model()
        return model.get_sentence_embedding_dimension()
