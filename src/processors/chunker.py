"""
文本分块模块 - 将长文档切分为适合嵌入的文本块
"""
import re
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class TextChunker:
    """文本分块器"""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_document(self, doc: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将文档分块，每个chunk保留文档元数据上下文"""
        content = doc.get("content", "")
        title = doc.get("title", "")
        doc_id = doc.get("id", "")

        if not content or len(content) < self.min_chunk_size:
            # 短文档整体作为一个chunk
            return [{
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}_0",
                "content": f"{title}\n{content}".strip(),
                "chunk_index": 0,
                "metadata": {
                    "title": title,
                    "category": doc.get("category", ""),
                    "geo_scope": doc.get("geo_scope", ""),
                    "source": doc.get("source", ""),
                    "source_type": doc.get("source_type", ""),
                    "publish_date": doc.get("publish_date", ""),
                    "quality_score": doc.get("quality_score", 0.5),
                    "url": doc.get("url", ""),
                },
            }]

        # 按段落分割
        paragraphs = self._split_paragraphs(content)
        chunks = []
        current_chunk = ""
        chunk_index = 0

        for para in paragraphs:
            if len(current_chunk) + len(para) > self.chunk_size and current_chunk:
                # 保存当前chunk
                chunks.append(self._make_chunk(
                    doc_id, title, current_chunk.strip(), chunk_index, doc
                ))
                chunk_index += 1
                # 保留重叠部分
                overlap = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else ""
                current_chunk = overlap + "\n" + para
            else:
                current_chunk = current_chunk + "\n" + para if current_chunk else para

        # 最后一个chunk
        if current_chunk.strip():
            chunks.append(self._make_chunk(
                doc_id, title, current_chunk.strip(), chunk_index, doc
            ))

        logger.debug(f"文档 {doc_id} 分为 {len(chunks)} 个chunk")
        return chunks

    def _split_paragraphs(self, text: str) -> List[str]:
        """按段落/标题分割文本"""
        # 先按双换行分段
        paragraphs = re.split(r"\n\s*\n", text)
        # 如果段落太长，进一步按单换行分割
        result = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) > self.chunk_size * 2:
                # 长段落按句子分割
                sentences = re.split(r"(?<=[。！？；.!?;])\s*", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) > self.chunk_size and current:
                        result.append(current.strip())
                        current = sent
                    else:
                        current = current + sent if current else sent
                if current:
                    result.append(current.strip())
            else:
                result.append(para)
        return result

    def _make_chunk(
        self, doc_id: str, title: str, content: str,
        chunk_index: int, doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建带上下文的chunk"""
        # 在chunk前加上标题作为上下文
        full_content = f"【{title}】\n{content}" if title else content
        return {
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}_{chunk_index}",
            "content": full_content,
            "chunk_index": chunk_index,
            "metadata": {
                "title": title,
                "category": doc.get("category", ""),
                "geo_scope": doc.get("geo_scope", ""),
                "source": doc.get("source", ""),
                "source_type": doc.get("source_type", ""),
                "publish_date": doc.get("publish_date", ""),
                "quality_score": doc.get("quality_score", 0.5),
                "url": doc.get("url", ""),
            },
        }
