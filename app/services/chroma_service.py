"""基于 Chroma 的向量存储与混合检索实现。"""

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import chromadb

from app.core.config import Settings
from app.models.api import KnowledgeDocumentIn
from app.models.domain import KnowledgeChunk
from app.services.openai_service import OpenAIService


class ChromaService:
    """负责 Chroma 集合的文档入库与混合检索。"""

    def __init__(self, settings: Settings, openai_service: OpenAIService) -> None:
        self.settings = settings
        self.openai_service = openai_service
        os.makedirs(self.settings.chroma_path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.settings.chroma_path)
        self.collection = self.client.get_or_create_collection(
            name=self.settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

    async def collection_count(self) -> int:
        """返回当前知识集合中的片段数量。"""
        return int(await asyncio.to_thread(self.collection.count))

    async def upsert_documents(self, documents: List[KnowledgeDocumentIn]) -> int:
        """生成向量后把文档写入或更新到 Chroma。"""
        embeddings = await self.openai_service.embed_texts([item.content for item in documents])
        ids = [item.document_id for item in documents]
        metadatas: List[Dict[str, Any]] = []
        for item in documents:
            # Chroma 的 metadata 结构更适合扁平字段，这里把 tags 序列化成逗号分隔字符串。
            metadata = dict(item.metadata)
            metadata.update(
                {
                    "title": item.title,
                    "source": item.source,
                    "section": item.section,
                    "tags": ",".join(item.tags),
                }
            )
            metadatas.append(metadata)

        await asyncio.to_thread(
            self.collection.upsert,
            ids=ids,
            documents=[item.content for item in documents],
            metadatas=metadatas,
            embeddings=embeddings,
        )
        return len(documents)

    async def hybrid_search(self, query: str, top_k: Optional[int] = None) -> List[KnowledgeChunk]:
        """组合向量检索与关键词检索，并在本地完成重排。"""
        target_top_k = top_k or self.settings.rag_top_k
        query_embedding = (await self.openai_service.embed_texts([query]))[0]
        keywords = self._extract_keywords(query)

        # 混合检索分成一次向量召回和一次关键词召回，最后在本地做轻量融合打分。
        vector_task = asyncio.to_thread(
            self.collection.query,
            query_embeddings=[query_embedding],
            n_results=max(target_top_k, self.settings.rag_vector_k),
            include=["documents", "metadatas", "distances"],
        )
        keyword_task = asyncio.to_thread(
            self._keyword_search_sync,
            keywords,
            self.settings.rag_keyword_limit_per_term,
        )
        vector_result, keyword_matches = await asyncio.gather(vector_task, keyword_task)

        candidates: Dict[str, Dict[str, Any]] = {}

        ids = vector_result.get("ids", [[]])[0]
        documents = vector_result.get("documents", [[]])[0]
        metadatas = vector_result.get("metadatas", [[]])[0]
        distances = vector_result.get("distances", [[]])[0]

        for rank, chunk_id in enumerate(ids):
            # 把 Chroma 的余弦距离转换成可参与融合的相似度分数。
            distance = float(distances[rank]) if rank < len(distances) else 1.0
            similarity = max(0.0, 1.0 - distance)
            candidates[chunk_id] = {
                "chunk_id": chunk_id,
                "content": documents[rank],
                "metadata": metadatas[rank] or {},
                "vector_score": similarity,
                "keyword_score": 0.0,
                "rank_score": 1.0 / (rank + 1),
            }

        keyword_divisor = float(max(len(keywords), 1))
        for item in keyword_matches:
            # 同一片段命中多个关键词时采用累加，而不是覆盖已有分数。
            chunk_id = item["chunk_id"]
            entry = candidates.setdefault(
                chunk_id,
                {
                    "chunk_id": chunk_id,
                    "content": item["content"],
                    "metadata": item["metadata"],
                    "vector_score": 0.0,
                    "keyword_score": 0.0,
                    "rank_score": 0.0,
                },
            )
            entry["keyword_score"] += 1.0 / keyword_divisor

        results: List[KnowledgeChunk] = []
        for item in candidates.values():
            metadata = item["metadata"] or {}
            rerank_score = round(
                item["vector_score"] * 0.65 + item["keyword_score"] * 0.25 + item["rank_score"] * 0.10,
                4,
            )
            results.append(
                KnowledgeChunk(
                    chunk_id=item["chunk_id"],
                    content=item["content"],
                    title=metadata.get("title"),
                    source=metadata.get("source"),
                    section=metadata.get("section"),
                    vector_score=round(item["vector_score"], 4),
                    keyword_score=round(item["keyword_score"], 4),
                    rerank_score=rerank_score,
                    metadata=metadata,
                )
            )

        results.sort(key=lambda chunk: chunk.rerank_score, reverse=True)
        return results[:target_top_k]

    def _keyword_search_sync(self, keywords: List[str], limit_per_term: int) -> List[Dict[str, Any]]:
        """对提取出的高价值关键词执行同步 Chroma 检索。"""
        matches: List[Dict[str, Any]] = []
        for keyword in keywords[: self.settings.rag_keyword_k]:
            # 关键词过滤交给 Chroma，本地只负责在结果返回后做融合评分。
            result = self.collection.get(
                where_document={"$contains": keyword},
                limit=limit_per_term,
                include=["documents", "metadatas"],
            )
            ids = result.get("ids", [])
            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            for index, chunk_id in enumerate(ids):
                matches.append(
                    {
                        "chunk_id": chunk_id,
                        "content": documents[index],
                        "metadata": metadatas[index] or {},
                    }
                )
        return matches

    @staticmethod
    def _extract_keywords(query: str) -> List[str]:
        """提取英文 token 与中文 n-gram，供轻量关键词检索使用。"""
        normalized = re.sub(r"\s+", " ", query.strip().lower())
        keywords = set()
        for token in re.findall(r"[a-z0-9_]{2,}", normalized):
            keywords.add(token)
        for block in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
            keywords.add(block)
            if len(block) > 2:
                for index in range(len(block) - 1):
                    keywords.add(block[index : index + 2])
            if len(block) > 3:
                for index in range(len(block) - 2):
                    keywords.add(block[index : index + 3])
        keywords.add(normalized)
        return sorted(keywords, key=len, reverse=True)
