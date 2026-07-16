"""
执行索引构建 - 对采集的文档进行解析、分块、嵌入、向量存储和知识图谱构建

用法:
    python3 scripts/run_indexing.py [--limit 100]
"""
import sys
import os
import logging
import yaml

sys.path.insert(0, "/workspace/water-eco-kb")

from src.storage.metadata_db import MetadataDB
from src.storage.vector_db import VectorDB
from src.storage.graph_store import GraphStore
from src.processors.chunker import TextChunker
from src.processors.embedder import Embedder
from src.processors.graph_builder import GraphBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="知识索引构建")
    parser.add_argument("--limit", type=int, default=200, help="单次处理文档上限")
    args = parser.parse_args()

    # 加载配置
    with open("/workspace/water-eco-kb/config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    db = MetadataDB(config["metadata_db"]["path"])
    vector_db = VectorDB(
        persist_path=config["vector_db"]["persist_path"],
        collection_name=config["vector_db"]["collection_name"],
    )
    embedder = Embedder(
        model_name=config["embedding"]["model_name"],
        device=config["embedding"]["device"],
        cache_dir=config["embedding"]["cache_dir"],
    )
    chunker = TextChunker(chunk_size=512, chunk_overlap=100)

    # 获取未向量化的文档
    docs = db.get_all_documents_for_indexing(limit=args.limit)
    logger.info(f"待索引文档: {len(docs)} 条")

    if not docs:
        logger.info("没有需要索引的新文档")
        return

    # 1. 分块
    logger.info("阶段1: 文本分块")
    all_chunks = []
    for doc in docs:
        # 构建用于嵌入的内容
        embed_content = doc.get("content", "")
        if not embed_content:
            embed_content = doc.get("summary", "") or doc.get("title", "")
        doc["content"] = embed_content
        chunks = chunker.chunk_document(doc)
        all_chunks.extend(chunks)
    logger.info(f"  分块完成: {len(all_chunks)} 个chunk")

    if not all_chunks:
        logger.warning("无有效内容可嵌入")
        return

    # 2. 嵌入
    logger.info("阶段2: 向量嵌入")
    texts = [chunk["content"] for chunk in all_chunks]
    try:
        embeddings = embedder.embed_texts(texts, batch_size=config["embedding"]["batch_size"])
        logger.info(f"  嵌入完成: {len(embeddings)} 个向量, 维度: {len(embeddings[0]) if embeddings else 0}")
    except Exception as e:
        logger.error(f"嵌入失败: {e}")
        return

    # 3. 存入ChromaDB
    logger.info("阶段3: 向量存储")
    ids = [chunk["chunk_id"] for chunk in all_chunks]
    metadatas = [chunk["metadata"] for chunk in all_chunks]
    # 添加doc_id到metadata
    for chunk, meta in zip(all_chunks, metadatas):
        meta["doc_id"] = chunk["doc_id"]

    vector_ids = vector_db.add_documents(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    logger.info(f"  向量存储完成: {len(vector_ids)} 条")

    # 4. 更新元数据库
    logger.info("阶段4: 更新元数据")
    for chunk in all_chunks:
        db.update_vector_id(chunk["doc_id"], chunk["chunk_id"])

    # 5. 知识图谱构建
    logger.info("阶段5: 知识图谱构建")
    try:
        graph_store = GraphStore(config["knowledge_graph"]["graph_path"])
        graph_builder = GraphBuilder(graph_store)
        graph_builder.build_from_documents(docs)
        logger.info(f"  知识图谱: {graph_store.get_stats()}")
    except Exception as e:
        logger.error(f"知识图谱构建失败: {e}")

    logger.info("=" * 60)
    logger.info(f"索引构建完成: {len(docs)} 篇文档 → {len(all_chunks)} 个chunk → {len(vector_ids)} 个向量")
    logger.info(f"向量库总量: {vector_db.count()}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
