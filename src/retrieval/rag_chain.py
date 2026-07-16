"""
RAG问答链 - LangChain RAG链 + LLM生成 + 引用标注
"""
import os
import logging
from typing import List, Dict, Any, Optional

from ..storage.vector_db import VectorDB
from ..storage.metadata_db import MetadataDB
from ..processors.embedder import Embedder
from .hybrid_retriever import HybridRetriever

logger = logging.getLogger(__name__)

# 系统Prompt - 水生态环境领域专家角色
SYSTEM_PROMPT = """你是一位水生态环境领域的资深专家，专注于水环境保护、水生态修复、水污染治理等领域的研究与管理。

请基于以下检索到的知识资料回答用户问题。回答要求：
1. 优先依据提供的资料作答，每个重要观点后标注来源编号[1][2]等
2. 如果资料不足以完全回答，说明"根据现有资料"并补充专业建议
3. 如果资料中没有相关信息，明确说明"当前知识库未提供相关内容"
4. 回答结构清晰：先给结论，再展开说明，最后给出建议或注意事项
5. 涉及政策法规的内容，注意标注发布机关和时效性
6. 关注浙江省和杭州市的本地化信息

检索到的知识资料：
{context}

请基于以上资料回答用户的问题。"""


class RAGChain:
    """RAG问答链"""

    def __init__(
        self,
        vector_db: VectorDB,
        embedder: Embedder,
        metadata_db: MetadataDB,
        config: Dict[str, Any] = None,
    ):
        self.config = config or {}
        self.retriever = HybridRetriever(vector_db, embedder, metadata_db, self.config)

        # LLM配置
        self.llm_config = self.config.get("llm", {})
        self.api_key = self.llm_config.get("api_key", "") or os.environ.get("LLM_API_KEY", "")
        self.base_url = self.llm_config.get("base_url", "https://api.deepseek.com/v1")
        self.model = self.llm_config.get("model", "deepseek-chat")
        self.temperature = self.llm_config.get("temperature", 0.3)

        self._llm = None

    def _get_llm(self):
        """懒加载LLM"""
        if self._llm is not None:
            return self._llm

        if not self.api_key:
            logger.warning("LLM API Key未配置，RAG问答功能将受限")
            return None

        try:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.llm_config.get("max_tokens", 4096),
            )
            logger.info(f"LLM加载完成: {self.model} @ {self.base_url}")
            return self._llm
        except Exception as e:
            logger.error(f"LLM加载失败: {e}")
            return None

    def query(self, question: str, **filters) -> Dict[str, Any]:
        """
        RAG问答：检索 → 构建Prompt → LLM生成 → 引用标注
        返回 {answer, sources, retrieval_details}
        """
        # 1. 检索相关知识
        retrieved = self.retriever.retrieve(question, **filters)

        if not retrieved:
            return {
                "answer": "当前知识库中未找到与您问题相关的资料。建议：\n1. 尝试用不同关键词重新搜索\n2. 将该问题整理后补充到知识库\n3. 联系相关领域专家确认",
                "sources": [],
                "retrieval_details": {"total_found": 0},
            }

        # 2. 构建上下文
        context_parts = []
        sources = []
        for i, item in enumerate(retrieved, 1):
            metadata = item.get("metadata", {})
            doc_meta = item.get("doc_metadata", {})
            content = item.get("content", "")[:800]  # 每条最多800字

            source_info = {
                "index": i,
                "title": metadata.get("title", doc_meta.get("title", "")),
                "source": metadata.get("source", doc_meta.get("source", "")),
                "url": metadata.get("url", doc_meta.get("url", "")),
                "date": metadata.get("publish_date", doc_meta.get("publish_date", "")),
                "category": metadata.get("category", doc_meta.get("category", "")),
                "geo_scope": metadata.get("geo_scope", doc_meta.get("geo_scope", "")),
                "quality_score": metadata.get("quality_score", doc_meta.get("quality_score", 0)),
                "content_snippet": content[:200],
            }
            sources.append(source_info)

            context_parts.append(
                f"[{i}] 标题：{source_info['title']}\n"
                f"来源：{source_info['source']} ({source_info['date']})\n"
                f"分类：{source_info['category']} | 地区：{source_info['geo_scope']}\n"
                f"内容：{content}\n"
            )

        context = "\n---\n".join(context_parts)

        # 3. LLM生成
        llm = self._get_llm()
        if llm:
            try:
                prompt = SYSTEM_PROMPT.format(context=context)
                response = llm.invoke([
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": question},
                ])
                answer = response.content if hasattr(response, "content") else str(response)
            except Exception as e:
                logger.error(f"LLM生成失败: {e}")
                answer = self._fallback_answer(question, retrieved)
        else:
            # 无LLM时，返回检索结果摘要
            answer = self._fallback_answer(question, retrieved)

        # 4. 添加引用来源
        answer += "\n\n---\n**参考来源：**\n"
        for src in sources:
            answer += f"[{src['index']}] {src['title']} - {src['source']} ({src['date']})\n"
            if src["url"]:
                answer += f"    链接：{src['url']}\n"

        return {
            "answer": answer,
            "sources": sources,
            "retrieval_details": {
                "total_found": len(retrieved),
                "categories": list(set(s["category"] for s in sources if s["category"])),
                "geo_scopes": list(set(s["geo_scope"] for s in sources if s["geo_scope"])),
            },
        }

    def _fallback_answer(self, question: str, retrieved: List[Dict]) -> str:
        """无LLM时的降级回答：返回检索结果摘要"""
        lines = [f"根据知识库检索到 {len(retrieved)} 条相关资料，以下是主要内容摘要：\n"]

        for i, item in enumerate(retrieved[:5], 1):
            metadata = item.get("metadata", {})
            doc_meta = item.get("doc_metadata", {})
            title = metadata.get("title", doc_meta.get("title", "未知标题"))
            source = metadata.get("source", doc_meta.get("source", ""))
            content = item.get("content", "")[:300]

            lines.append(f"**[{i}] {title}**\n")
            lines.append(f"来源：{source}\n")
            lines.append(f"摘要：{content}...\n")

        lines.append("\n*注：当前未配置LLM API，以上为检索结果摘要。配置API Key后可获得智能问答。*")
        return "\n".join(lines)
