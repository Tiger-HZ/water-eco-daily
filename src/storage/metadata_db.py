"""
SQLite元数据库 - 存储文档元数据、关键词、实体、采集日志和推送历史
"""
import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


class MetadataDB:
    """SQLite元数据库管理"""

    def __init__(self, db_path: str = "/workspace/water-eco-kb/data/metadata.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT,
                    source TEXT,
                    source_type TEXT,
                    category TEXT,
                    sub_category TEXT,
                    geo_scope TEXT,
                    publish_date TEXT,
                    quality_score REAL DEFAULT 0.5,
                    quality_level TEXT DEFAULT '中等',
                    tdrive_file_id TEXT,
                    vector_id TEXT,
                    content_hash TEXT,
                    content TEXT,
                    summary TEXT,
                    keywords TEXT,
                    extra_metadata TEXT,
                    status TEXT DEFAULT 'active',
                    collected_at TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT,
                    entity_text TEXT,
                    entity_type TEXT,
                    start INTEGER,
                    end INTEGER,
                    FOREIGN KEY (doc_id) REFERENCES documents(id)
                );

                CREATE TABLE IF NOT EXISTS collection_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT,
                    source_type TEXT,
                    items_collected INTEGER DEFAULT 0,
                    items_new INTEGER DEFAULT 0,
                    status TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS digest_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_date TEXT,
                    file_path TEXT,
                    tdrive_file_id TEXT,
                    total_items INTEGER,
                    categories TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
                CREATE INDEX IF NOT EXISTS idx_documents_geo ON documents(geo_scope);
                CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(publish_date);
                CREATE INDEX IF NOT EXISTS idx_documents_quality ON documents(quality_score);
                CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url);
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
            """)

        # 迁移：为旧数据库添加content列
        try:
            with self._get_conn() as conn:
                conn.execute("ALTER TABLE documents ADD COLUMN content TEXT")
                conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在

    @staticmethod
    def _gen_doc_id(url: str, title: str) -> str:
        raw = f"{url}|{title}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def upsert_document(self, doc: Dict[str, Any]) -> tuple:
        """插入或更新文档（含全文），返回 (doc_id, is_new)"""
        doc_id = self._gen_doc_id(doc.get("url", ""), doc.get("title", ""))
        content = doc.get("content", "")
        content_hash = self._content_hash(content) if content else ""

        # 自动生成summary（从content取前300字）
        summary = doc.get("summary", "")
        if not summary and content:
            summary = content[:300].replace("\n", " ").strip()
            if len(content) > 300:
                summary += "..."

        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, content_hash FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()

            is_new = existing is None
            if existing and existing["content_hash"] == content_hash:
                return doc_id, False  # 内容未变，跳过

            keywords = doc.get("keywords", [])
            if isinstance(keywords, list):
                keywords = json.dumps(keywords, ensure_ascii=False)

            extra = doc.get("extra_metadata", {})
            if isinstance(extra, dict):
                extra = json.dumps(extra, ensure_ascii=False)

            conn.execute("""
                INSERT INTO documents (id, title, url, source, source_type, category,
                    sub_category, geo_scope, publish_date, quality_score, quality_level,
                    content_hash, content, summary, keywords, extra_metadata, status, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, url=excluded.url, source=excluded.source,
                    source_type=excluded.source_type, category=excluded.category,
                    sub_category=excluded.sub_category, geo_scope=excluded.geo_scope,
                    publish_date=excluded.publish_date, quality_score=excluded.quality_score,
                    quality_level=excluded.quality_level, content_hash=excluded.content_hash,
                    content=excluded.content, summary=excluded.summary, keywords=excluded.keywords,
                    extra_metadata=excluded.extra_metadata, status=excluded.status,
                    collected_at=excluded.collected_at,
                    updated_at=datetime('now', 'localtime')
            """, (
                doc_id, doc.get("title", ""), doc.get("url", ""),
                doc.get("source", ""), doc.get("source_type", ""),
                doc.get("category", ""), doc.get("sub_category", ""),
                doc.get("geo_scope", ""), doc.get("publish_date", ""),
                doc.get("quality_score", 0.5), doc.get("quality_level", "中等"),
                content_hash, content, summary, keywords, extra,
                doc.get("status", "active"),
                doc.get("collected_at", datetime.now().isoformat())
            ))
            conn.commit()

        return doc_id, is_new

    def update_tdrive_id(self, doc_id: str, tdrive_file_id: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET tdrive_file_id = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (tdrive_file_id, doc_id)
            )
            conn.commit()

    def update_vector_id(self, doc_id: str, vector_id: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET vector_id = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (vector_id, doc_id)
            )
            conn.commit()

    def get_document(self, doc_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def get_document_by_url(self, url: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE url = ?", (url,)).fetchone()
            return dict(row) if row else None

    def query_documents(
        self,
        category: Optional[str] = None,
        geo_scope: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_quality: float = 0.0,
        source_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        sql = "SELECT * FROM documents WHERE status = 'active' AND quality_score >= ?"
        params: list = [min_quality]

        if category:
            sql += " AND category = ?"
            params.append(category)
        if geo_scope:
            sql += " AND geo_scope = ?"
            params.append(geo_scope)
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        if date_from:
            sql += " AND publish_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND publish_date <= ?"
            params.append(date_to)
        if keyword:
            sql += " AND (title LIKE ? OR summary LIKE ? OR keywords LIKE ?)"
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        sql += " ORDER BY publish_date DESC NULLS LAST, quality_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def count_documents(self, category: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) as cnt FROM documents WHERE status = 'active'"
        params: list = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        with self._get_conn() as conn:
            row = conn.execute(sql, params).fetchone()
            return row["cnt"]

    def get_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM documents WHERE status='active'").fetchone()["c"]
            by_category = conn.execute("""
                SELECT category, COUNT(*) as c FROM documents WHERE status='active'
                GROUP BY category ORDER BY c DESC
            """).fetchall()
            by_geo = conn.execute("""
                SELECT geo_scope, COUNT(*) as c FROM documents WHERE status='active'
                GROUP BY geo_scope ORDER BY c DESC
            """).fetchall()
            by_source = conn.execute("""
                SELECT source_type, COUNT(*) as c FROM documents WHERE status='active'
                GROUP BY source_type ORDER BY c DESC
            """).fetchall()
            quality_dist = conn.execute("""
                SELECT quality_level, COUNT(*) as c FROM documents WHERE status='active'
                GROUP BY quality_level
            """).fetchall()
            recent = conn.execute("""
                SELECT COUNT(*) as c FROM documents
                WHERE status='active' AND collected_at >= datetime('now', '-7 days')
            """).fetchone()["c"]

            return {
                "total": total,
                "recent_7d": recent,
                "by_category": {r["category"]: r["c"] for r in by_category},
                "by_geo": {r["geo_scope"]: r["c"] for r in by_geo},
                "by_source": {r["source_type"]: r["c"] for r in by_source},
                "quality_dist": {r["quality_level"]: r["c"] for r in quality_dist},
            }

    def log_collection(self, source_name: str, source_type: str,
                       items_collected: int, items_new: int,
                       status: str = "success", error: str = ""):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO collection_log (source_name, source_type, items_collected,
                    items_new, status, error, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (source_name, source_type, items_collected, items_new,
                  status, error, datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()

    def add_digest_history(self, digest_date: str, file_path: str,
                           tdrive_file_id: str, total_items: int, categories: str):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO digest_history (digest_date, file_path, tdrive_file_id, total_items, categories)
                VALUES (?, ?, ?, ?, ?)
            """, (digest_date, file_path, tdrive_file_id, total_items, categories))
            conn.commit()

    def get_all_documents_for_indexing(self, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """获取未向量化的文档（vector_id为空）"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM documents
                WHERE status = 'active' AND (vector_id IS NULL OR vector_id = '')
                ORDER BY collected_at DESC LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
            return [dict(r) for r in rows]
