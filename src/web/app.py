"""
Gradio Web 应用
================
水生态环境知识管理系统的 Web 交互界面，包含 5 个功能 Tab：

    1. 知识检索  ：关键词 / 分类 / 地理 / 质量阈值 → 卡片列表
    2. RAG 问答  ：基于向量检索 + LLM（可选）的问答对话
    3. 资讯看板  ：查看最新每日资讯 HTML 报告，并支持手动生成
    4. 知识图谱  ：基于 pyvis 的实体网络图（从 data/graph.json 读取）
    5. 知识管理  ：MetadataDB.get_stats() 统计数据可视化

启动：``python -m src.web.app`` 或直接运行本文件。
监听 ``0.0.0.0:7860``。
"""
import html as _html
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
import yaml

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage.metadata_db import MetadataDB  # noqa: E402

logger = logging.getLogger(__name__)

CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"
DIGEST_DIR = _PROJECT_ROOT / "output" / "digests"
GRAPH_PATH = _PROJECT_ROOT / "data" / "graph.json"


# ---------------------------------------------------------------------- #
# 配置与全局对象
# ---------------------------------------------------------------------- #
def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = _load_config()
_DB_PATH = CONFIG.get("metadata_db", {}).get("path", str(_PROJECT_ROOT / "data" / "metadata.db"))

# 7 大知识分类（下拉选项）
CATEGORY_CHOICES = ["全部", "01_政策法规标准", "02_研究文献", "03_领导讲话",
                    "04_技术产品", "05_实践案例", "06_专家团队", "07_科研院所与企业"]
CATEGORY_LABELS = {c: (c.split("_", 1)[-1] if "_" in c else c) for c in CATEGORY_CHOICES[1:]}

# 地理范围（从配置的 geo_weights 取键，补充通用值）
_GEO_WEIGHTS = CONFIG.get("geo_weights", {})
GEO_CHOICES = ["全部"] + list(_GEO_WEIGHTS.keys())
for _g in ["杭州", "浙江", "长三角", "全国", "国际"]:
    if _g not in GEO_CHOICES:
        GEO_CHOICES.append(_g)


def _get_db() -> MetadataDB:
    return MetadataDB(_DB_PATH)


def _esc(text: Any) -> str:
    if text is None:
        return ""
    return _html.escape(str(text))


# ====================================================================== #
# Tab1：知识检索
# ====================================================================== #
def search_knowledge(
    keyword: str, category: str, geo_scope: str, min_quality: float
) -> str:
    """执行检索并返回卡片 HTML。"""
    try:
        db = _get_db()
        cat = None if category in ("", "全部") else category
        geo = None if geo_scope in ("", "全部") else geo_scope
        kw = keyword.strip() or None

        docs = db.query_documents(
            category=cat, geo_scope=geo, min_quality=float(min_quality),
            keyword=kw, limit=60, offset=0,
        )
    except Exception as e:
        logger.error("检索失败: %s", e)
        return f'<div class="err">检索失败: {_esc(e)}</div>'

    if not docs:
        return '<div class="empty-hint">未找到匹配的文档，请调整检索条件。</div>'

    cards = []
    for d in docs:
        title = _esc(d.get("title", "无标题"))
        summary = _esc(d.get("summary", "") or "暂无摘要。")
        source = _esc(d.get("source", "") or "未知来源")
        source_type = _esc(d.get("source_type", "") or "")
        pub_date = _esc(d.get("publish_date", "") or "未知日期")
        geo = _esc(d.get("geo_scope", "") or "")
        url = d.get("url", "") or ""
        ql = d.get("quality_level", "中等") or "中等"
        try:
            score_txt = f"{float(d.get('quality_score', 0) or 0):.2f}"
        except (TypeError, ValueError):
            score_txt = str(d.get("quality_score", 0))
        qcls = "q-high" if "高" in ql else ("q-mid" if "中" in ql else "q-low")

        link = (
            f'<a class="card-link" href="{_esc(url)}" target="_blank" rel="noopener">查看原文 →</a>'
            if url else '<span class="card-link disabled">无原文链接</span>'
        )
        geo_html = f'<span class="m-geo">📍 {_esc(geo)}</span>' if geo else ""
        cards.append(f"""
        <div class="kcard">
            <div class="ktop"><span class="qb {qcls}">{_esc(ql)}</span>
                <span class="qs">质量 {score_txt}</span>
                <span class="kd">📅 {_esc(pub_date)}</span></div>
            <div class="ktitle">{title}</div>
            <div class="ksummary">{summary}</div>
            <div class="kmeta"><span>来源：{source}</span>
                {f'<span class="m-type">· {source_type}</span>' if source_type else ''}{geo_html}</div>
            <div class="kfoot">{link}</div>
        </div>""")

    head = f'<div class="result-count">共找到 <b>{len(docs)}</b> 条结果</div>'
    return f'<div class="kgrid">{head}{"".join(cards)}</div>'


# ====================================================================== #
# Tab2：RAG 问答
# ====================================================================== #
def _rag_retrieve(question: str, top_k: int = 5) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """向量检索相关文档，返回 (结果列表, 错误信息)。"""
    try:
        from src.processors.embedder import Embedder
        from src.storage.vector_db import VectorDB

        emb_cfg = CONFIG.get("embedding", {})
        vdb_cfg = CONFIG.get("vector_db", {})
        embedder = Embedder(
            model_name=emb_cfg.get("model_name", "BAAI/bge-large-zh-v1.5"),
            device=emb_cfg.get("device", "cpu"),
            cache_dir=emb_cfg.get("cache_dir", str(_PROJECT_ROOT / "data" / "cache")),
        )
        vdb = VectorDB(
            persist_path=vdb_cfg.get("persist_path", str(_PROJECT_ROOT / "data" / "chroma")),
            collection_name=vdb_cfg.get("collection_name", "water_eco_knowledge"),
        )
        qvec = embedder.embed_query(question)
        results = vdb.search_by_vector(qvec, top_k=top_k)
        return results, None
    except Exception as e:
        return [], str(e)


def _rag_answer(question: str, history: List[List[str]]) -> Tuple[List[List[str]], str]:
    """RAG 问答：检索 + LLM 生成（API Key 未配置时仅返回检索片段）。"""
    question = (question or "").strip()
    if not question:
        return history, "请输入问题。"

    history = history or []

    # 尝试调用 retrieval 模块（可能未配置 / 未实现）
    try:
        from src.retrieval.rag import RAGEngine  # type: ignore
        engine = RAGEngine()
        answer = engine.answer(question)
        history.append([question, answer])
        return history, ""
    except Exception:
        pass  # 回退到内置检索

    results, err = _rag_retrieve(question, top_k=5)
    if err:
        history.append(
            [question, f"⚠️ 向量检索不可用：{_esc(err)}\n\n请确认嵌入模型与向量库已就绪。"]
        )
        return history, ""

    if not results:
        history.append([question, "未检索到相关文档，无法回答。"])
        return history, ""

    context_parts = []
    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {}) or {}
        content = (r.get("content", "") or "").strip()
        context_parts.append(
            f"[{i}] 《{_esc(meta.get('title', '未知'))}》\n{_esc(content[:400])}"
        )
    context = "\n\n".join(context_parts)

    llm_cfg = CONFIG.get("llm", {})
    api_key = llm_cfg.get("api_key", "") or ""
    if not api_key:
        msg = (
            "⚠️ 未配置 LLM API Key（config/settings.yaml → llm.api_key），"
            "以下为检索到的相关文档，供参考：\n\n" + context
        )
        history.append([question, msg])
        return history, ""

    # 调用 OpenAI 兼容 LLM
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=llm_cfg.get("base_url", ""))
        prompt = (
            f"你是一个水生态环境知识助手。请根据以下检索到的资料回答问题。\n\n"
            f"【资料】\n{context}\n\n"
            f"【问题】{question}\n\n请基于资料作答，若资料不足请说明。"
        )
        resp = client.chat.completions.create(
            model=llm_cfg.get("model", "deepseek-chat"),
            messages=[{"role": "user", "content": prompt}],
            temperature=float(llm_cfg.get("temperature", 0.3)),
            max_tokens=int(llm_cfg.get("max_tokens", 4096)),
        )
        answer = resp.choices[0].message.content.strip()
        history.append([question, answer + "\n\n---\n📎 参考文档：\n" + context])
    except Exception as e:
        history.append(
            [question, f"⚠️ LLM 调用失败：{_esc(e)}\n\n参考文档：\n" + context]
        )
    return history, ""


# ====================================================================== #
# Tab3：资讯看板
# ====================================================================== #
def _list_digests() -> List[str]:
    if not DIGEST_DIR.exists():
        return []
    files = sorted(DIGEST_DIR.glob("digest_*.html"), reverse=True)
    return [f.name for f in files]


def load_digest(file_name: str) -> str:
    """读取指定 digest HTML，通过 iframe 隔离样式展示。"""
    if not file_name:
        return '<div class="empty-hint">暂无资讯报告，请点击"生成今日资讯"。</div>'
    path = DIGEST_DIR / file_name
    if not path.exists():
        return f'<div class="err">文件不存在: {_esc(file_name)}</div>'
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f'<div class="err">读取失败: {_esc(e)}</div>'
    escaped = _esc(content)
    return (
        f'<iframe srcdoc="{escaped}" style="width:100%;height:82vh;border:0;'
        'border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08);"></iframe>'
    )


def generate_digest_now() -> Tuple[str, str]:
    """手动触发生成资讯报告。"""
    try:
        from src.push.scheduler import run_digest_only

        result = run_digest_only()
        pub = result.get("publish", {})
        html_path = pub.get("html_path", "")
        if html_path and Path(html_path).exists():
            files = _list_digests()
            choices = gr.update(choices=files, value=Path(html_path).name)
            msg = f"✅ 生成成功：{Path(html_path).name}（收录 {pub.get('total_items', 0)} 条）"
            return choices, msg
        return gr.update(), f"❌ 生成失败：{pub.get('error', '未知错误')}"
    except Exception as e:
        logger.error("手动生成 digest 失败: %s", e)
        return gr.update(), f"❌ 生成失败：{_esc(e)}"


# ====================================================================== #
# Tab4：知识图谱
# ====================================================================== #
def render_graph(entity: str) -> str:
    """读取 graph.json 并用 pyvis 渲染网络图。"""
    if not GRAPH_PATH.exists():
        return (
            '<div class="empty-hint">知识图谱数据不存在：'
            f'<code>{_esc(GRAPH_PATH)}</code><br>请先运行图谱构建流程。</div>'
        )
    try:
        with open(GRAPH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f'<div class="err">读取图谱数据失败: {_esc(e)}</div>'

    nodes = data.get("nodes", []) or []
    edges = data.get("edges", []) or []
    if not nodes:
        return '<div class="empty-hint">图谱节点为空。</div>'

    # 实体过滤
    entity = (entity or "").strip().lower()
    if entity:
        matched_ids = set()
        for n in nodes:
            label = str(n.get("label", "") or n.get("id", "")).lower()
            if entity in label:
                matched_ids.add(n.get("id"))
        if not matched_ids:
            return f'<div class="empty-hint">未找到与 "{_esc(entity)}" 相关的实体。</div>'
        # 包含一阶邻居
        keep = set(matched_ids)
        for e in edges:
            s, t = e.get("source", e.get("from")), e.get("target", e.get("to"))
            if s in matched_ids or t in matched_ids:
                keep.add(s)
                keep.add(t)
        nodes = [n for n in nodes if n.get("id") in keep]
        edges = [e for e in edges
                 if e.get("source", e.get("from")) in keep and e.get("target", e.get("to")) in keep]

    try:
        from pyvis.network import Network
    except ImportError:
        return (
            '<div class="err">pyvis 未安装，请运行：<code>pip install pyvis</code></div>'
        )

    try:
        net = Network(height="620px", width="100%", bgcolor="#ffffff",
                      font_color="#333333", cdn_resources="in_line", notebook=False)
        for n in nodes:
            nid = n.get("id")
            label = n.get("label", str(nid))
            title = n.get("title", n.get("group", ""))
            group = n.get("group", "default")
            net.add_node(nid, label=label, title=title or label, group=group)
        for e in edges:
            s = e.get("source", e.get("from"))
            t = e.get("target", e.get("to"))
            w = e.get("weight", e.get("value", 1))
            lbl = e.get("label", "")
            net.add_edge(s, t, value=w, title=lbl)
        out = _PROJECT_ROOT / "output" / "_graph_view.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        net.save_graph(str(out))
        content = out.read_text(encoding="utf-8")
        escaped = _esc(content)
        return (
            f'<iframe srcdoc="{escaped}" style="width:100%;height:640px;border:0;'
            'border-radius:10px;"></iframe>'
            f'<div class="graph-info">节点 {len(nodes)} 个，关系 {len(edges)} 条</div>'
        )
    except Exception as e:
        logger.error("图谱渲染失败: %s", e)
        return f'<div class="err">图谱渲染失败: {_esc(e)}</div>'


# ====================================================================== #
# Tab5：知识管理
# ====================================================================== #
def render_stats() -> str:
    """格式化展示 MetadataDB.get_stats()。"""
    try:
        db = _get_db()
        stats = db.get_stats()
    except Exception as e:
        return f'<div class="err">获取统计失败: {_esc(e)}</div>'

    total = stats.get("total", 0)
    recent = stats.get("recent_7d", 0)
    by_category: Dict[str, int] = stats.get("by_category", {}) or {}
    by_geo: Dict[str, int] = stats.get("by_geo", {}) or {}
    by_source: Dict[str, int] = stats.get("by_source", {}) or {}
    quality_dist: Dict[str, int] = stats.get("quality_dist", {}) or {}

    cards = f"""
    <div class="stat-cards">
        <div class="scard sc1"><div class="sn">{total}</div><div class="sl">总文档数</div></div>
        <div class="scard sc2"><div class="sn">{recent}</div><div class="sl">近7天新增</div></div>
        <div class="scard sc3"><div class="sn">{len(by_category)}</div><div class="sl">分类数</div></div>
        <div class="scard sc4"><div class="sn">{len(by_source)}</div><div class="sl">来源类型</div></div>
    </div>"""

    # 分类分布
    cat_rows = ""
    max_cat = max(by_category.values()) if by_category else 1
    for cat in ["01_政策法规标准", "02_研究文献", "03_领导讲话", "04_技术产品",
                "05_实践案例", "06_专家团队", "07_科研院所与企业"]:
        cnt = by_category.get(cat, 0)
        label = cat.split("_", 1)[-1] if "_" in cat else cat
        pct = cnt / max_cat * 100 if max_cat else 0
        cat_rows += (
            f'<div class="brow"><span class="bl">{_esc(label)}</span>'
            f'<div class="bt"><div class="bf" style="width:{pct:.1f}%"></div></div>'
            f'<span class="bv">{cnt}</span></div>'
        )

    # 来源分布
    src_rows = ""
    max_src = max(by_source.values()) if by_source else 1
    for k, v in sorted(by_source.items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = v / max_src * 100 if max_src else 0
        src_rows += (
            f'<div class="brow"><span class="bl">{_esc(k)}</span>'
            f'<div class="bt"><div class="bf bf2" style="width:{pct:.1f}%"></div></div>'
            f'<span class="bv">{v}</span></div>'
        )

    # 地理分布
    geo_rows = ""
    max_geo = max(by_geo.values()) if by_geo else 1
    for k, v in sorted(by_geo.items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = v / max_geo * 100 if max_geo else 0
        geo_rows += (
            f'<div class="brow"><span class="bl">{_esc(k)}</span>'
            f'<div class="bt"><div class="bf bf3" style="width:{pct:.1f}%"></div></div>'
            f'<span class="bv">{v}</span></div>'
        )

    # 质量分布
    q_rows = ""
    q_colors = {"高质量": "#16a34a", "中等": "#2563eb", "一般": "#9ca3af"}
    q_total = sum(quality_dist.values()) or 1
    for lvl in ["高质量", "中等", "一般"]:
        cnt = quality_dist.get(lvl, 0)
        pct = cnt / q_total * 100
        color = q_colors.get(lvl, "#9ca3af")
        q_rows += (
            f'<div class="brow"><span class="bl">{_esc(lvl)}</span>'
            f'<div class="bt"><div class="bf" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<span class="bv">{cnt}</span></div>'
        )

    return f"""
    <div class="kmgr">
        {cards}
        <div class="panels">
            <div class="panel"><h3>分类分布</h3><div class="bars">{cat_rows}</div></div>
            <div class="panel"><h3>质量分布</h3><div class="bars">{q_rows}</div></div>
            <div class="panel"><h3>来源类型 Top10</h3><div class="bars">{src_rows}</div></div>
            <div class="panel"><h3>地理范围 Top10</h3><div class="bars">{geo_rows}</div></div>
        </div>
    </div>"""


# ====================================================================== #
# 公共样式
# ====================================================================== #
def _common_css() -> str:
    return """
<style>
.kgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.result-count{grid-column:1/-1;color:#64748b;font-size:13px;margin-bottom:4px}
.kcard{background:#fff;border:1px solid #eef2f6;border-radius:10px;padding:14px 16px;
    box-shadow:0 2px 6px rgba(0,0,0,.05);transition:box-shadow .15s}
.kcard:hover{box-shadow:0 6px 18px rgba(0,0,0,.1)}
.ktop{display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:6px}
.qb{padding:2px 8px;border-radius:10px;color:#fff;font-weight:600;font-size:11px}
.q-high{background:#16a34a}.q-mid{background:#2563eb}.q-low{background:#9ca3af}
.qs{color:#6b7280}.kd{margin-left:auto;color:#94a3b8}
.ktitle{font-size:14px;font-weight:600;color:#1e293b;line-height:1.4;margin-bottom:4px}
.ksummary{font-size:12px;color:#64748b;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.kmeta{font-size:11px;color:#94a3b8;margin-top:8px}.m-type,.m-geo{color:#0ea5e9}
.kfoot{margin-top:8px;padding-top:8px;border-top:1px dashed #eef2f6}
.kfoot .card-link{color:#2563eb;font-size:12px;font-weight:500}
.kfoot .card-link:hover{text-decoration:underline}.card-link.disabled{color:#cbd5e1;cursor:default}
.empty-hint{color:#94a3b8;padding:24px;text-align:center;background:#fff;border-radius:10px}
.err{color:#dc2626;padding:16px;background:#fef2f2;border-radius:8px}
.graph-info{margin-top:6px;color:#64748b;font-size:12px;text-align:center}
.stat-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.scard{border-radius:12px;padding:16px;color:#fff;box-shadow:0 4px 12px rgba(0,0,0,.08)}
.sc1{background:linear-gradient(135deg,#3b82f6,#2563eb)}
.sc2{background:linear-gradient(135deg,#10b981,#059669)}
.sc3{background:linear-gradient(135deg,#f59e0b,#d97706)}
.sc4{background:linear-gradient(135deg,#8b5cf6,#7c3aed)}
.sn{font-size:26px;font-weight:700}.sl{font-size:12px;opacity:.92;margin-top:2px}
.panels{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.panel{background:#fff;border-radius:10px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
.panel h3{font-size:14px;color:#374151;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #f1f5f9}
.bars{display:flex;flex-direction:column;gap:7px}
.brow{display:flex;align-items:center;gap:8px;font-size:12px}
.bl{width:84px;text-align:right;color:#4b5563;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bt{flex:1;height:8px;background:#eef2f6;border-radius:4px;overflow:hidden}
.bf{height:100%;background:linear-gradient(90deg,#06b6d4,#3b82f6);border-radius:4px}
.bf2{background:linear-gradient(90deg,#f59e0b,#f97316)}
.bf3{background:linear-gradient(90deg,#8b5cf6,#ec4899)}
.bv{width:38px;text-align:right;color:#6b7280;font-variant-numeric:tabular-nums}
@media(max-width:768px){.stat-cards{grid-template-columns:repeat(2,1fr)}.panels{grid-template-columns:1fr}}
</style>
"""


# ====================================================================== #
# 构建 Gradio 应用
# ====================================================================== #
def build_app() -> gr.Blocks:
    with gr.Blocks(title="水生态环境知识管理系统") as app:
        gr.Markdown("# 💧 水生态环境知识管理系统")
        gr.HTML(_common_css())

        # ---------------- Tab1 知识检索 ----------------
        with gr.Tab("🔍 知识检索"):
            with gr.Row():
                kw_in = gr.Textbox(label="关键词", placeholder="输入标题/摘要/关键词...",
                                   scale=3)
                cat_in = gr.Dropdown(choices=CATEGORY_CHOICES, value="全部", label="分类", scale=1)
                geo_in = gr.Dropdown(choices=GEO_CHOICES, value="全部", label="地理范围", scale=1)
                q_in = gr.Slider(0, 1, value=0.3, step=0.1, label="最低质量分", scale=1)
            btn = gr.Button("🔍 检索", variant="primary")
            out1 = gr.HTML('<div class="empty-hint">输入条件后点击「检索」。</div>')
            btn.click(search_knowledge, inputs=[kw_in, cat_in, geo_in, q_in], outputs=out1)

        # ---------------- Tab2 RAG 问答 ----------------
        with gr.Tab("💬 RAG 问答"):
            gr.Markdown(
                "> 基于向量检索的水生态环境知识问答。若未配置 LLM API Key，将仅返回检索到的相关文档。"
            )
            chat = gr.Chatbot(height=480, label="对话")
            with gr.Row():
                q_in2 = gr.Textbox(label="问题", placeholder="例如：杭州水生态修复有哪些典型案例？",
                                   scale=4)
                sub2 = gr.Button("发送", variant="primary", scale=1)
            warn2 = gr.HTML("")
            sub2.click(_rag_answer, inputs=[q_in2, chat], outputs=[chat, warn2])
            q_in2.submit(_rag_answer, inputs=[q_in2, chat], outputs=[chat, warn2])

        # ---------------- Tab3 资讯看板 ----------------
        with gr.Tab("📊 资讯看板"):
            with gr.Row():
                digest_dd = gr.Dropdown(choices=_list_digests(), label="选择资讯报告",
                                        interactive=True, scale=3)
                load_btn = gr.Button("📂 加载", scale=1)
                gen_btn = gr.Button("⚡ 生成今日资讯", variant="primary", scale=1)
            gen_msg = gr.HTML("")
            out3 = gr.HTML('<div class="empty-hint">选择已有报告或点击「生成今日资讯」。</div>')
            load_btn.click(load_digest, inputs=digest_dd, outputs=out3)
            digest_dd.change(load_digest, inputs=digest_dd, outputs=out3)
            gen_btn.click(generate_digest_now, outputs=[digest_dd, gen_msg])

        # ---------------- Tab4 知识图谱 ----------------
        with gr.Tab("🕸 知识图谱"):
            with gr.Row():
                ent_in = gr.Textbox(label="实体搜索（可选）",
                                    placeholder="输入实体名，如：钱塘江、生态修复", scale=3)
                ent_btn = gr.Button("🔍 查询", variant="primary", scale=1)
            out4 = gr.HTML('<div class="empty-hint">输入实体名或直接查询全部关系。</div>')
            ent_btn.click(render_graph, inputs=ent_in, outputs=out4)

        # ---------------- Tab5 知识管理 ----------------
        with gr.Tab("📈 知识管理"):
            refresh_btn = gr.Button("🔄 刷新统计", variant="primary")
            out5 = gr.HTML("")
            refresh_btn.click(render_stats, outputs=out5)
            app.load(render_stats, outputs=out5)

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = build_app()
    app.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())


if __name__ == "__main__":
    main()
