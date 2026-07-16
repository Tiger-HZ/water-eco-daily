"""
每日资讯 HTML 报告生成器
========================
将聚合后的结构化数据（Aggregator.aggregate() 输出）渲染为独立 HTML 文件，
内嵌 CSS / JS，无任何外部依赖，可直接用浏览器打开。

布局结构：
    1. 顶部标题区（渐变背景 + 生成时间 + 概览数字）
    2. 统计概览（总文档数、近7天新增、分类分布条形图、质量分布）
    3. 分类 Tab 切换（7 个分类，显示各分类文档数）
    4. 时段筛选（8 个时段 + "全部"，显示各时段文档数）
    5. 内容卡片列表（标题 / 摘要 / 来源 / 日期 / 质量标签 / 原文链接）

响应式设计，支持手机浏览。
"""
import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _esc(text: Any) -> str:
    """HTML 转义，None / 空值返回空串。"""
    if text is None:
        return ""
    return html.escape(str(text))


def _quality_class(level: str) -> str:
    """根据质量等级返回 CSS 类名。"""
    if not level:
        return "q-low"
    if "高" in level:
        return "q-high"
    if "中" in level:
        return "q-mid"
    return "q-low"


class DigestGenerator:
    """生成每日资讯 HTML 报告。"""

    def __init__(
        self, output_dir: str = "/workspace/water-eco-kb/output/digests"
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def generate(
        self,
        aggregated_data: Dict[str, Any],
        output_path: str = None,
    ) -> str:
        """生成 HTML 报告，返回输出文件绝对路径。

        :param aggregated_data: Aggregator.aggregate() 返回的结构化数据
        :param output_path: 输出路径，None 时自动按时间戳命名
        """
        if not aggregated_data:
            raise ValueError("aggregated_data 不能为空")

        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(self.output_dir / f"digest_{ts}.html")

        html_content = self._render(aggregated_data)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(
            "HTML 报告已生成: %s (%.2f KB)",
            output_path,
            len(html_content.encode("utf-8")) / 1024,
        )
        return output_path

    # ------------------------------------------------------------------ #
    # 渲染主流程
    # ------------------------------------------------------------------ #
    def _render(self, data: Dict[str, Any]) -> str:
        stats: Dict[str, Any] = data.get("stats", {}) or {}
        segments: List[Dict[str, Any]] = data.get("time_segments", []) or []
        categories: List[Dict[str, Any]] = data.get("categories", []) or []
        generated_at = data.get("generated_at", datetime.now().isoformat())
        total_items = data.get("total_items", 0)

        parts: List[str] = []
        parts.append("<!DOCTYPE html>")
        parts.append('<html lang="zh-CN">')
        parts.append("<head>")
        parts.append('<meta charset="UTF-8">')
        parts.append(
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        )
        parts.append(
            f"<title>水生态环境知识日报 - {_esc(datetime.now().strftime('%Y-%m-%d'))}</title>"
        )
        parts.append(f"<style>{self._css()}</style>")
        parts.append("</head>")
        parts.append("<body>")
        parts.append(self._render_header(generated_at, stats, total_items))
        parts.append(self._render_stats_overview(stats, categories))
        parts.append(self._render_category_tabs(categories))
        parts.append(self._render_segment_filters(segments))
        parts.append(self._render_content(categories, segments))
        parts.append(self._render_footer())
        parts.append(f"<script>{self._js()}</script>")
        parts.append("</body>")
        parts.append("</html>")
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # 各区域渲染
    # ------------------------------------------------------------------ #
    def _render_header(
        self, generated_at: str, stats: Dict[str, Any], total_items: int
    ) -> str:
        total = stats.get("total", 0)
        recent = stats.get("recent_7d", 0)
        return f"""
        <header class="hero">
            <div class="hero-inner">
                <h1>水生态环境知识日报</h1>
                <p class="hero-sub">每日自动聚合 · 政策 / 文献 / 讲话 / 技术 / 案例 / 专家 / 机构</p>
                <div class="hero-meta">
                    <span>生成时间：{_esc(generated_at)}</span>
                    <span class="dot">·</span>
                    <span>总文档 <b>{total}</b></span>
                    <span class="dot">·</span>
                    <span>近7天新增 <b>{recent}</b></span>
                    <span class="dot">·</span>
                    <span>本次收录 <b>{total_items}</b></span>
                </div>
            </div>
        </header>
        """

    def _render_stats_overview(
        self, stats: Dict[str, Any], categories: List[Dict[str, Any]]
    ) -> str:
        total = stats.get("total", 0)
        recent = stats.get("recent_7d", 0)
        by_category: Dict[str, int] = stats.get("by_category", {}) or {}
        by_source: Dict[str, int] = stats.get("by_source", {}) or {}
        quality_dist: Dict[str, int] = stats.get("quality_dist", {}) or {}

        # 4 个概览卡片
        cards = f"""
        <div class="stat-cards">
            <div class="stat-card sc1"><div class="sc-num">{total}</div><div class="sc-label">总文档数</div></div>
            <div class="stat-card sc2"><div class="sc-num">{recent}</div><div class="sc-label">近7天新增</div></div>
            <div class="stat-card sc3"><div class="sc-num">{len(by_category)}</div><div class="sc-label">覆盖分类</div></div>
            <div class="stat-card sc4"><div class="sc-num">{len(by_source)}</div><div class="sc-label">来源类型</div></div>
        </div>
        """

        # 分类分布条形图
        cat_bars = ""
        max_cat = max(by_category.values()) if by_category else 1
        for cat in [
            "01_政策法规标准", "02_研究文献", "03_领导讲话", "04_技术产品",
            "05_实践案例", "06_专家团队", "07_科研院所与企业",
        ]:
            cnt = by_category.get(cat, 0)
            label = cat.split("_", 1)[-1] if "_" in cat else cat
            pct = (cnt / max_cat * 100) if max_cat else 0
            cat_bars += (
                f'<div class="bar-row"><span class="bar-label">{_esc(label)}</span>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>'
                f'<span class="bar-val">{cnt}</span></div>'
            )
        cat_section = f"""
        <div class="panel">
            <h2 class="panel-title">分类分布</h2>
            <div class="bar-list">{cat_bars}</div>
        </div>
        """

        # 质量分布
        q_items = ""
        q_colors = {"高质量": "#16a34a", "中等": "#2563eb", "一般": "#9ca3af"}
        q_total = sum(quality_dist.values()) or 1
        for lvl in ["高质量", "中等", "一般"]:
            cnt = quality_dist.get(lvl, 0)
            pct = cnt / q_total * 100
            color = q_colors.get(lvl, "#9ca3af")
            q_items += (
                f'<div class="q-row"><span class="q-name">{_esc(lvl)}</span>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
                f'<span class="bar-val">{cnt}</span></div>'
            )
        q_section = f"""
        <div class="panel">
            <h2 class="panel-title">质量分布</h2>
            <div class="bar-list">{q_items}</div>
        </div>
        """

        return f'<section class="overview">{cards}<div class="panels-grid">{cat_section}{q_section}</div></section>'

    def _render_category_tabs(self, categories: List[Dict[str, Any]]) -> str:
        if not categories:
            return '<nav class="cat-tabs" id="catTabs"><span class="empty">暂无分类数据</span></nav>'
        buttons = ""
        for i, cat in enumerate(categories):
            active = "active" if i == 0 else ""
            buttons += (
                f'<button class="cat-tab {active}" data-cat="{_esc(cat["key"])}">'
                f'<span class="ct-label">{_esc(cat["label"])}</span>'
                f'<span class="ct-count">{cat.get("doc_count", 0)}</span></button>'
            )
        return f'<nav class="cat-tabs" id="catTabs">{buttons}</nav>'

    def _render_segment_filters(self, segments: List[Dict[str, Any]]) -> str:
        if not segments:
            return '<nav class="seg-filters" id="segFilters"></nav>'
        buttons = '<button class="seg-btn active" data-seg="all">全部</button>'
        for seg in segments:
            cnt = seg.get("doc_count", 0)
            buttons += (
                f'<button class="seg-btn" data-seg="{_esc(seg["key"])}">'
                f'{_esc(seg["label"])} <em>({cnt})</em></button>'
            )
        return f'<nav class="seg-filters" id="segFilters">{buttons}</nav>'

    def _render_content(
        self,
        categories: List[Dict[str, Any]],
        segments: List[Dict[str, Any]],
    ) -> str:
        if not categories:
            return '<main class="content"><p class="empty">暂无内容，请先执行采集流程。</p></main>'

        panels = ""
        for i, cat in enumerate(categories):
            active = "active" if i == 0 else ""
            cards_html = ""
            segs: Dict[str, List[Dict[str, Any]]] = cat.get("segments", {}) or {}
            for seg_key, docs in segs.items():
                if not docs:
                    continue
                for doc in docs:
                    cards_html += self._render_card(doc, seg_key)
            if not cards_html:
                cards_html = '<p class="empty">该分类暂无内容。</p>'
            panels += (
                f'<section class="cat-panel {active}" data-cat="{_esc(cat["key"])}">'
                f'<h2 class="panel-cat-title">{_esc(cat["label"])} '
                f'<em>({cat.get("doc_count", 0)} 条)</em></h2>'
                f'<div class="card-grid">{cards_html}</div>'
                f"</section>"
            )
        return f'<main class="content" id="content">{panels}</main>'

    def _render_card(self, doc: Dict[str, Any], seg_key: str) -> str:
        title = _esc(doc.get("title", "无标题"))
        summary = _esc(doc.get("summary", "") or "暂无摘要。")
        source = _esc(doc.get("source", "") or "未知来源")
        source_type = _esc(doc.get("source_type", "") or "")
        pub_date = _esc(doc.get("publish_date", "") or "未知日期")
        geo = _esc(doc.get("geo_scope", "") or "")
        url = doc.get("url", "") or ""
        quality_level = doc.get("quality_level", "中等") or "中等"
        quality_score = doc.get("quality_score", 0.0)
        try:
            score_txt = f"{float(quality_score):.2f}"
        except (TypeError, ValueError):
            score_txt = str(quality_score)

        qcls = _quality_class(quality_level)
        link_html = (
            f'<a class="card-link" href="{_esc(url)}" target="_blank" rel="noopener">查看原文 →</a>'
            if url
            else '<span class="card-link disabled">无原文链接</span>'
        )

        geo_html = f'<span class="meta-geo">📍 {_esc(geo)}</span>' if geo else ""

        return f"""
        <article class="card" data-seg="{_esc(seg_key)}">
            <div class="card-top">
                <span class="q-badge {qcls}">{_esc(quality_level)}</span>
                <span class="q-score">质量 {score_txt}</span>
                <span class="card-date">📅 {_esc(pub_date)}</span>
            </div>
            <h3 class="card-title">{title}</h3>
            <p class="card-summary">{summary}</p>
            <div class="card-meta">
                <span class="meta-source">来源：{_esc(source)}</span>
                {f'<span class="meta-type">· {_esc(source_type)}</span>' if source_type else ''}
                {geo_html}
            </div>
            <div class="card-foot">{link_html}</div>
        </article>
        """

    def _render_footer(self) -> str:
        return f"""
        <footer class="footer">
            <p>水生态环境知识管理系统 · 自动生成于 {_esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</p>
            <p class="footer-sub">由 Aggregator + DigestGenerator 自动聚合渲染</p>
        </footer>
        """

    # ------------------------------------------------------------------ #
    # CSS / JS（纯字符串，避免 f-string 大括号问题）
    # ------------------------------------------------------------------ #
    def _css(self) -> str:
        return """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    background:#f5f7fa;color:#1f2937;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}

/* 顶部标题区 */
.hero{background:linear-gradient(135deg,#0ea5e9 0%,#06b6d4 50%,#10b981 100%);
    color:#fff;padding:48px 20px 40px;box-shadow:0 4px 20px rgba(14,165,233,.25)}
.hero-inner{max-width:1200px;margin:0 auto;text-align:center}
.hero h1{font-size:32px;font-weight:700;letter-spacing:1px;margin-bottom:8px}
.hero-sub{opacity:.92;font-size:14px;margin-bottom:14px}
.hero-meta{font-size:13px;opacity:.95;display:flex;justify-content:center;flex-wrap:wrap;gap:6px}
.hero-meta b{font-weight:700}
.hero-meta .dot{opacity:.6}

/* 概览区 */
.overview{max-width:1200px;margin:-24px auto 0;padding:0 16px;position:relative;z-index:2}
.stat-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
.stat-card{border-radius:14px;padding:20px;color:#fff;box-shadow:0 6px 18px rgba(0,0,0,.08)}
.sc1{background:linear-gradient(135deg,#3b82f6,#2563eb)}
.sc2{background:linear-gradient(135deg,#10b981,#059669)}
.sc3{background:linear-gradient(135deg,#f59e0b,#d97706)}
.sc4{background:linear-gradient(135deg,#8b5cf6,#7c3aed)}
.sc-num{font-size:30px;font-weight:700}
.sc-label{font-size:13px;opacity:.92;margin-top:4px}

.panels-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:18px}
.panel{background:#fff;border-radius:14px;padding:18px 20px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
.panel-title{font-size:15px;font-weight:600;color:#374151;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #f1f5f9}

/* 条形图 */
.bar-list{display:flex;flex-direction:column;gap:9px}
.bar-row,.q-row{display:flex;align-items:center;gap:10px;font-size:13px}
.bar-label{width:96px;color:#4b5563;flex-shrink:0;text-align:right}
.bar-track{flex:1;height:9px;background:#eef2f6;border-radius:5px;overflow:hidden}
.bar-fill{height:100%;background:linear-gradient(90deg,#06b6d4,#3b82f6);border-radius:5px;transition:width .4s}
.bar-val{width:42px;text-align:right;color:#6b7280;font-variant-numeric:tabular-nums}
.q-name{width:64px;text-align:right;color:#4b5563}

/* 分类 Tab */
.cat-tabs{max-width:1200px;margin:18px auto 0;padding:0 16px;display:flex;flex-wrap:wrap;gap:8px}
.cat-tab{display:inline-flex;align-items:center;gap:6px;border:1px solid #e2e8f0;background:#fff;
    color:#475569;padding:8px 16px;border-radius:20px;font-size:13px;cursor:pointer;transition:all .2s}
.cat-tab:hover{border-color:#06b6d4;color:#0891b2}
.cat-tab.active{background:linear-gradient(135deg,#06b6d4,#3b82f6);color:#fff;border-color:transparent;box-shadow:0 3px 10px rgba(6,182,212,.3)}
.ct-count{background:rgba(0,0,0,.08);border-radius:10px;padding:1px 8px;font-size:11px;font-weight:600}
.cat-tab.active .ct-count{background:rgba(255,255,255,.25)}

/* 时段筛选 */
.seg-filters{max-width:1200px;margin:14px auto 0;padding:0 16px;display:flex;flex-wrap:wrap;gap:8px}
.seg-btn{border:1px solid #e2e8f0;background:#fff;color:#64748b;padding:6px 14px;border-radius:16px;
    font-size:12px;cursor:pointer;transition:all .2s}
.seg-btn em{font-style:normal;color:#94a3b8;margin-left:2px}
.seg-btn:hover{border-color:#0ea5e9;color:#0ea5e9}
.seg-btn.active{background:#0ea5e9;color:#fff;border-color:transparent}
.seg-btn.active em{color:rgba(255,255,255,.85)}

/* 内容区 */
.content{max-width:1200px;margin:16px auto 40px;padding:0 16px}
.cat-panel{display:none}
.cat-panel.active{display:block}
.panel-cat-title{font-size:18px;font-weight:600;color:#1e293b;margin-bottom:14px;padding-left:10px;border-left:4px solid #06b6d4}
.panel-cat-title em{font-size:13px;color:#94a3b8;font-style:normal;font-weight:400}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}

.card{background:#fff;border-radius:12px;padding:16px 18px;box-shadow:0 2px 8px rgba(0,0,0,.06);
    border:1px solid #f1f5f9;display:flex;flex-direction:column;transition:transform .15s,box-shadow .15s}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(0,0,0,.1)}
.card-top{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:12px}
.q-badge{padding:2px 9px;border-radius:10px;font-weight:600;font-size:11px;color:#fff}
.q-high{background:#16a34a}.q-mid{background:#2563eb}.q-low{background:#9ca3af}
.q-score{color:#6b7280}.card-date{margin-left:auto;color:#94a3b8}
.card-title{font-size:15px;font-weight:600;color:#1e293b;line-height:1.4;margin-bottom:6px}
.card-summary{font-size:13px;color:#64748b;flex:1;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.card-meta{font-size:12px;color:#94a3b8;margin-top:10px;display:flex;flex-wrap:wrap;gap:6px}
.meta-type,.meta-geo{color:#0ea5e9}
.card-foot{margin-top:10px;padding-top:10px;border-top:1px dashed #eef2f6}
.card-link{color:#2563eb;font-size:13px;font-weight:500}
.card-link:hover{text-decoration:underline}
.card-link.disabled{color:#cbd5e1;cursor:default}

.empty{grid-column:1/-1;text-align:center;color:#94a3b8;padding:30px;font-size:14px}

/* 页脚 */
.footer{text-align:center;color:#94a3b8;font-size:12px;padding:24px 16px;border-top:1px solid #eef2f6;margin-top:20px}
.footer-sub{margin-top:4px;font-size:11px;color:#cbd5e1}

/* 响应式 */
@media (max-width:768px){
    .hero{padding:32px 16px 28px}
    .hero h1{font-size:24px}
    .stat-cards{grid-template-columns:repeat(2,1fr)}
    .panels-grid{grid-template-columns:1fr}
    .card-grid{grid-template-columns:1fr}
    .bar-label{width:72px;font-size:12px}
}
@media (max-width:420px){
    .hero-meta{font-size:12px;flex-direction:column;gap:2px}
    .hero-meta .dot{display:none}
    .card{padding:14px}
    .cat-tab{padding:6px 12px;font-size:12px}
}
"""

    def _js(self) -> str:
        return """
(function(){
    function selectCategory(key){
        document.querySelectorAll('.cat-panel').forEach(function(p){
            p.classList.toggle('active', p.dataset.cat===key);
        });
        document.querySelectorAll('.cat-tab').forEach(function(t){
            t.classList.toggle('active', t.dataset.cat===key);
        });
        setSegment('all');
    }
    function setSegment(seg){
        document.querySelectorAll('.seg-btn').forEach(function(b){
            b.classList.toggle('active', b.dataset.seg===seg);
        });
        var active = document.querySelector('.cat-panel.active');
        if(!active) return;
        var cards = active.querySelectorAll('.card');
        var visible = 0;
        cards.forEach(function(c){
            var show = (seg==='all' || c.dataset.seg===seg);
            c.style.display = show ? '' : 'none';
            if(show) visible++;
        });
        var note = active.querySelector('.seg-note');
        if(!note){
            note = document.createElement('p');
            note.className = 'empty seg-note';
            active.appendChild(note);
        }
        if(cards.length>0 && visible===0){
            note.style.display='';
            note.textContent = '该时段暂无内容，可切换其他时段查看。';
        } else {
            note.style.display='none';
        }
    }
    document.querySelectorAll('.cat-tab').forEach(function(t){
        t.addEventListener('click', function(){ selectCategory(t.dataset.cat); });
    });
    document.querySelectorAll('.seg-btn').forEach(function(b){
        b.addEventListener('click', function(){ setSegment(b.dataset.seg); });
    });
    // 初始化：默认选中第一个分类 + 全部时段
    var firstTab = document.querySelector('.cat-tab');
    if(firstTab){ selectCategory(firstTab.dataset.cat); }
})();
"""


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    gen = DigestGenerator()
    # 演示用空数据结构（实际应传入 Aggregator.aggregate() 结果）
    demo = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": {
            "total": 0, "recent_7d": 0,
            "by_category": {}, "by_geo": {}, "by_source": {}, "quality_dist": {},
        },
        "time_segments": [
            {"key": "7d", "label": "近7天", "doc_count": 0},
        ],
        "categories": [
            {"key": "01_政策法规标准", "label": "政策法规标准", "doc_count": 0, "segments": {"7d": []}},
        ],
        "total_items": 0,
    }
    path = gen.generate(demo)
    print(f"演示报告已生成: {path}")
