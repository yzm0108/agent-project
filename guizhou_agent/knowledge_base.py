"""
knowledge_base.py — 知识库管理
功能：加载 JSON 知识库 → 生成 Embedding → 存入 ChromaDB → 支持分类过滤搜索
"""

import json
import math
import os
import chromadb
from openai import OpenAI


class KnowledgeBase:
    """贵州知识库：加载、向量化、分类检索"""

    def __init__(self, data_path="data/guizhou_kb.json", db_path="./chroma_db"):
        self.ollama = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
        self.chroma = chromadb.PersistentClient(path=db_path)
        self.collection = self.chroma.get_or_create_collection(name="guizhou_kb")
        self.data_path = data_path
        self.documents = []  # 内存中保存原文，方便溯源

        # 如果是首次运行，初始化
        if self.collection.count() == 0:
            self._load_and_index()
        else:
            self._load_documents()

    def _load_and_index(self):
        """首次运行：从 JSON 文件加载知识库并建立向量索引"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(base_dir, self.data_path)

        with open(full_path, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

        print(f"正在为 {len(self.documents)} 条知识建立向量索引...")

        for doc in self.documents:
            emb = self._embed(doc["content"])
            self.collection.add(
                ids=[doc["id"]],
                documents=[doc["content"]],
                embeddings=[emb],
                metadatas=[{"category": doc["category"]}],
            )

        print(f"知识库初始化完成，{self.collection.count()} 条，覆盖 {self._all_categories()} 个分类")

    def _load_documents(self):
        """非首次运行：从 JSON 加载原文档列表（用于溯源）"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(base_dir, self.data_path)
        with open(full_path, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def _embed(self, text):
        """文字 → 向量（调用 Ollama BGE 模型）"""
        resp = self.ollama.embeddings.create(model="bge-embed", input=text)
        return resp.data[0].embedding

    def search(self, query, top_k=3, category=None):
        """
        语义搜索知识库。
        - query: 搜索关键词
        - category: 如果指定（如 '美食'），只搜该分类；None 则全库搜索
        返回: [(相似度, 内容, 文档ID, 分类), ...]
        """
        q_emb = self._embed(query)

        # 构建过滤条件
        where = None
        if category:
            where = {"category": category}

        results = self.collection.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            include=["documents", "distances", "metadatas"],
            where=where,
        )

        docs = []
        for content, dist, meta in zip(
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        ):
            similarity = round(1.0 - dist, 4)
            # 找到对应的文档 ID（用于溯源）
            doc_id = ""
            for d in self.documents:
                if d["content"] == content:
                    doc_id = d["id"]
                    break
            docs.append((similarity, content, doc_id, meta.get("category", "")))

        return docs

    def _all_categories(self):
        return list(set(d["category"] for d in self.documents))

    @property
    def categories(self):
        return sorted(self._all_categories())

    def get_by_category(self):
        """返回每个分类各有多少条"""
        cats = {}
        for d in self.documents:
            c = d["category"]
            cats[c] = cats.get(c, 0) + 1
        return cats

    def get_doc_by_id(self, doc_id):
        """根据 ID 查原文（用于溯源）"""
        for d in self.documents:
            if d["id"] == doc_id:
                return d
        return None
