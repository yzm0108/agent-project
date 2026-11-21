"""Knowledge base backed by ChromaDB."""

import json
import os
import re
import uuid

import chromadb
from openai import OpenAI


class KnowledgeBase:
    def __init__(self, data_path="data/guizhou_kb.json", db_path=None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.getenv("CHROMA_DB_PATH", os.path.join(project_root, "chroma_db"))
        self.ollama = OpenAI(
            api_key="ollama",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        )
        self.chroma = chromadb.PersistentClient(path=db_path)
        self.collection = self.chroma.get_or_create_collection(
            name="guizhou_kb",
            metadata={"hnsw:space": "cosine"},
        )
        self.data_path = data_path

        if self.collection.count() == 0:
            self._load_and_index()

    def _load_and_index(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(base_dir, self.data_path)

        with open(full_path, "r", encoding="utf-8") as file:
            documents = json.load(file)

        ids = [document["id"] for document in documents]
        contents = [document["content"] for document in documents]
        metadatas = [{"category": document["category"]} for document in documents]
        embeddings = [self._embed(content) for content in contents]

        self.collection.add(
            ids=ids,
            documents=contents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def _embed(self, text):
        response = self.ollama.embeddings.create(model="bge-embed", input=text)
        return response.data[0].embedding

    def add_document(self, content, category, doc_id=None):
        content = content.strip()
        category = category.strip()
        if not content:
            raise ValueError("Document content cannot be empty.")
        if not category:
            raise ValueError("Document category cannot be empty.")

        doc_id = doc_id or f"user_{uuid.uuid4().hex[:10]}"
        embedding = self._embed(content)
        self.collection.add(
            ids=[doc_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[{"category": category}],
        )
        return doc_id

    # ===== 批量增量导入 =====

    BATCH_SIZE = 200          # 每批处理条目数，超过自动分批循环
    MIN_ENTRY_CHARS = 10      # 少于该字符数的条目视为无检索价值，过滤

    @staticmethod
    def _clean_text(text: str) -> str:
        """基础清洗：去 BOM、规范换行、去全角/不间断空格、折叠连续空格与空行"""
        if not text:
            return ""
        text = text.replace("﻿", "")                    # UTF-8 BOM
        text = text.replace("\r\n", "\n").replace("\r", "\n")    # 换行归一
        text = text.replace("　", " ").replace(" ", " ")  # fullwidth/nbsp -> space
        lines = []
        for line in text.split("\n"):
            line = re.sub(r"[ \t]{2,}", " ", line)               # 折叠连续空格（保留单个）
            lines.append(line.strip())                           # 去行首尾
        text = "\n".join(lines)
        text = re.sub(r"\n{2,}", "\n\n", text)                   # 连续空行 → 一个
        return text.strip()

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """剥离常见 Markdown 语法符号，保留文字内容"""
        text = re.sub(r"```\w*[^\n]*\n?", "", text)              # 代码块围栏行（保留内部文本）
        lines = []
        for line in text.split("\n"):
            line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)        # 标题
            line = re.sub(r"^\s*>\s?", "", line)                 # 引用
            line = re.sub(r"^\s*[-*+]\s+", "", line)             # 无序列表
            line = re.sub(r"^\s*\d+[.、)】]\s*", "", line)       # 有序列表
            line = re.sub(r"^\s*([-*_])\1{2,}\s*$", "", line)    # 分隔线 --- / *** / ___
            line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", line)  # 图片 → alt 文字
            line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)   # 链接 → 显示文字
            line = re.sub(r"`([^`]*)`", r"\1", line)             # 行内代码 → 文字
            line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)       # 加粗
            line = re.sub(r"__([^_]+)__", r"\1", line)           # 加粗（下划线）
            line = re.sub(r"\*([^*]+)\*", r"\1", line)           # 斜体
            line = re.sub(r"\s*\|\s*", " ", line)                # 表格竖线 → 空格
            lines.append(line)
        return "\n".join(lines)

    def _split_entries(self, text: str) -> tuple[list[str], int]:
        """按空行切分成独立条目（一条=一段，空行数量随意，不兜底不猜）"""
        entries = []
        short = 0
        for part in text.split("\n\n"):
            entry = part.strip()
            if not entry:
                continue
            if len(entry) < self.MIN_ENTRY_CHARS:
                short += 1
                continue
            entries.append(entry)
        return entries, short

    def _existing_documents(self) -> set[str]:
        """拉取库中全部已入库文本（规范化后），用于精确去重"""
        result = self.collection.get(include=["documents"])
        return {doc.strip() for doc in result["documents"] if doc}

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量 embedding；Ollama 批量接口失败时降级为逐条"""
        try:
            resp = self.ollama.embeddings.create(model="bge-embed", input=texts)
            return [item.embedding for item in resp.data]
        except Exception:
            return [self._embed(t) for t in texts]

    def import_texts(self, raw_text: str, category: str, batch_size: int = BATCH_SIZE) -> dict:
        """
        批量增量导入：清洗 → 剥离 Markdown → 按空行切分 → 精确去重 → 批量向量化 → 写库。

        category 整批统一（调用方保证一个文件为单一类型）。超过 batch_size 自动分批循环。
        两阶段写入：全部向量化成功后才开始写库，embedding 失败整体中断，不留残缺数据。

        返回: {
            "imported": 入库条数,
            "skipped_duplicate": 重复跳过条数,
            "skipped_short": 过短过滤条数,
            "total_entries": 切分后总条目数,
            "ids": 成功写入的 id 列表,
        }
        """
        category = category.strip()
        if not category:
            raise ValueError("category 不能为空")

        if not raw_text or not raw_text.strip():
            return {"imported": 0, "skipped_duplicate": 0, "skipped_short": 0,
                    "total_entries": 0, "ids": []}

        cleaned = self._strip_markdown(self._clean_text(raw_text))
        entries, short = self._split_entries(cleaned)
        if not entries:
            return {"imported": 0, "skipped_duplicate": 0, "skipped_short": short,
                    "total_entries": 0, "ids": []}

        # 精确去重：与库中已有文本比对（规范化后）
        existing = self._existing_documents()
        fresh = [e for e in entries if e not in existing]
        dup = len(entries) - len(fresh)
        if not fresh:
            return {"imported": 0, "skipped_duplicate": dup, "skipped_short": short,
                    "total_entries": len(entries), "ids": []}

        # 阶段一：全部向量化（分批 embed，失败即中断）
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        for i in range(0, len(fresh), batch_size):
            chunk = fresh[i:i + batch_size]
            chunk_ids = [f"user_{uuid.uuid4().hex[:10]}" for _ in chunk]
            chunk_embeddings = self._embed_batch(chunk)
            ids.extend(chunk_ids)
            documents.extend(chunk)
            embeddings.extend(chunk_embeddings)

        # 阶段二：批量写库
        for i in range(0, len(ids), batch_size):
            chunk_ids = ids[i:i + batch_size]
            self.collection.add(
                ids=chunk_ids,
                documents=documents[i:i + batch_size],
                embeddings=embeddings[i:i + batch_size],
                metadatas=[{"category": category}] * len(chunk_ids),
            )

        return {
            "imported": len(ids),
            "skipped_duplicate": dup,
            "skipped_short": short,
            "total_entries": len(entries),
            "ids": ids,
        }

    def search(self, query, top_k=3, category=None):
        """语义搜索知识库。

        返回结构化结果 list[dict]，每项含:
        {"id", "content", "score", "category"}（score 为相似度，越高越相关）
        """
        query = query.strip()
        if not query:
            return []
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        where = {"category": category} if category else None
        available = self.collection.get(where=where, include=["metadatas"])
        if not available["ids"]:
            return []

        query_embedding = self._embed(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, len(available["ids"])),
            include=["documents", "distances", "metadatas"],
            where=where,
        )

        documents = []
        for doc_id, content, distance, metadata in zip(
            results["ids"][0],
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        ):
            documents.append({
                "id": doc_id,
                "content": content,
                "score": round(1.0 - distance, 4),
                "category": (metadata or {}).get("category", ""),
            })
        return documents

    def all_documents(self):
        result = self.collection.get(include=["documents", "metadatas"])
        documents = []
        for doc_id, content, metadata in zip(
            result["ids"], result["documents"], result["metadatas"]
        ):
            documents.append(
                {
                    "id": doc_id,
                    "category": (metadata or {}).get("category", ""),
                    "content": content,
                }
            )
        return sorted(documents, key=lambda document: document["id"])

    def get_doc_by_id(self, doc_id):
        result = self.collection.get(
            ids=[doc_id], include=["documents", "metadatas"]
        )
        if not result["ids"]:
            return None

        metadata = result["metadatas"][0] or {}
        return {
            "id": result["ids"][0],
            "content": result["documents"][0],
            "category": metadata.get("category", ""),
        }

    @property
    def categories(self):
        result = self.collection.get(include=["metadatas"])
        return sorted(
            {
                metadata["category"]
                for metadata in result["metadatas"]
                if metadata and metadata.get("category")
            }
        )

    def get_by_category(self):
        result = self.collection.get(include=["metadatas"])
        counts = {}
        for metadata in result["metadatas"]:
            if metadata and metadata.get("category"):
                category = metadata["category"]
                counts[category] = counts.get(category, 0) + 1
        return counts
