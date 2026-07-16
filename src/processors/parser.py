"""
文档解析模块 - 将PDF/HTML/DOCX等格式解析为结构化文本
"""
import re
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentParser:
    """多格式文档解析器"""

    @staticmethod
    def parse(file_path: str, url: str = "", content_type: str = "") -> Dict[str, Any]:
        """根据文件类型自动选择解析器"""
        path = Path(file_path)
        ext = path.suffix.lower() if path.suffix else content_type

        if ext in (".pdf", "application/pdf"):
            return DocumentParser.parse_pdf(file_path)
        elif ext in (".html", ".htm", "text/html"):
            return DocumentParser.parse_html_file(file_path)
        elif ext in (".docx",):
            return DocumentParser.parse_docx(file_path)
        elif ext in (".txt", "text/plain"):
            return DocumentParser.parse_text(file_path)
        else:
            # 默认当文本处理
            return DocumentParser.parse_text(file_path)

    @staticmethod
    def parse_html_content(html: str, url: str = "") -> Dict[str, Any]:
        """解析HTML字符串，提取正文"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # 移除脚本、样式、导航等
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        # 尝试常见正文容器
        content_selectors = [
            "article", ".article-content", ".content", ".TRS_Editor",
            ".article", ".news_content", "#zoom", ".pages_content",
            ".con_text", ".article-body", ".main-content", ".text",
        ]
        content_soup = None
        for sel in content_selectors:
            content_soup = soup.select_one(sel)
            if content_soup and len(content_soup.get_text(strip=True)) > 200:
                break
            content_soup = None

        if not content_soup:
            content_soup = soup.find("body") or soup

        # 提取标题
        title = ""
        if soup.find("title"):
            title = soup.find("title").get_text(strip=True)
        h1 = content_soup.find("h1") if content_soup else None
        if h1:
            title = h1.get_text(strip=True)

        # 提取正文
        text = content_soup.get_text(separator="\n", strip=True) if content_soup else ""
        # 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        # 提取发布日期
        publish_date = DocumentParser._extract_date(html)

        # 提取作者/来源
        source = ""
        for sel in [".source", ".origin", ".author", ".info", ".article-info"]:
            el = soup.select_one(sel)
            if el:
                source = el.get_text(strip=True)
                break

        return {
            "title": title,
            "content": text,
            "publish_date": publish_date,
            "source": source,
            "raw_html": html[:5000],  # 保留前5000字符
        }

    @staticmethod
    def parse_html_file(file_path: str) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        return DocumentParser.parse_html_content(html)

    @staticmethod
    def parse_pdf(file_path: str) -> Dict[str, Any]:
        import pdfplumber

        text_parts = []
        title = ""
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text:
                    text_parts.append(page_text)
                # 第一页尝试提取标题
                if i == 0 and not title:
                    lines = [l.strip() for l in (page.extract_text() or "").split("\n") if l.strip()]
                    if lines:
                        # 取前几行中最长的作为标题
                        title = max(lines[:5], key=len) if lines else ""

        content = "\n\n".join(text_parts)
        publish_date = DocumentParser._extract_date(content)

        return {
            "title": title,
            "content": content,
            "publish_date": publish_date,
            "source": "",
            "raw_html": "",
        }

    @staticmethod
    def parse_docx(file_path: str) -> Dict[str, Any]:
        from docx import Document

        doc = Document(file_path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        content = "\n\n".join(paragraphs)
        title = paragraphs[0] if paragraphs else Path(file_path).stem

        return {
            "title": title,
            "content": content,
            "publish_date": DocumentParser._extract_date(content),
            "source": "",
            "raw_html": "",
        }

    @staticmethod
    def parse_text(file_path: str) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        lines = content.strip().split("\n")
        title = lines[0] if lines else Path(file_path).stem

        return {
            "title": title,
            "content": content,
            "publish_date": DocumentParser._extract_date(content),
            "source": "",
            "raw_html": "",
        }

    @staticmethod
    def _extract_date(text: str) -> str:
        """从文本中提取日期"""
        patterns = [
            r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}年\d{1,2}月\d{1,2}日)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                # 统一格式为 YYYY-MM-DD
                date_str = re.sub(r"[年月]", "-", date_str)
                date_str = date_str.replace("/", "-")
                parts = date_str.split("-")
                if len(parts) == 3:
                    try:
                        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                    except ValueError:
                        pass
                return date_str
        return ""
