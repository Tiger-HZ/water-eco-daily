#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
水生态环境资讯日报 - HTML报告生成器
====================================
从 SQLite 数据库读取文档数据，按分类和时间段聚合，
生成一个独立、专业、可交互的 HTML 资讯报告。

用法:
    python3 scripts/generate_report.py

输出:
    output/site/index.html
"""

import os
import re
import json
import sqlite3
import html
from datetime import datetime, timedelta

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "metadata.db")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "site")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# 生成日期（今天）
TODAY = datetime.now()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
TODAY_DISPLAY = TODAY.strftime("%Y年%m月%d日")

# 参考日期：用于时间段计算（取今天的 00:00）
REF_DATE = TODAY.replace(hour=0, minute=0, second=0, microsecond=0)

# ============================================================
# 分类定义（顺序即展示顺序）
# ============================================================
CATEGORIES = [
    {"code": "01_政策法规与标准",      "name": "政策法规与标准",   "icon": "📜"},
    {"code": "02_水环境质量管理",      "name": "水环境质量管理",   "icon": "📊"},
    {"code": "03_水污染防治与监管",    "name": "水污染防治与监管", "icon": "🏭"},
    {"code": "04_水生态修复与保护",    "name": "水生态修复与保护", "icon": "🌱"},
    {"code": "05_饮用水水源保护",      "name": "饮用水水源保护",   "icon": "💧"},
    {"code": "06_科研技术与实践案例",  "name": "科研技术与实践案例", "icon": "🔬"},
    {"code": "07_动态资讯与综合",      "name": "动态资讯与综合",   "icon": "📰"},
]

# 分类代码 -> 展示信息 映射
CATEGORY_MAP = {c["code"]: c for c in CATEGORIES}

# ============================================================
# 时间段定义
# ============================================================
# 每个时间段对应一个 key，用于前端筛选与后端标记
TIME_PERIODS = [
    {"key": "7d",   "label": "近7天"},
    {"key": "1m",   "label": "近1个月"},
    {"key": "3m",   "label": "近3个月"},
    {"key": "6m",   "label": "近半年"},
    {"key": "y2026","label": "本年度(2026)"},
    {"key": "y2025","label": "去年(2025)"},
    {"key": "3y",   "label": "近3年"},
    {"key": "older","label": "更早"},
]

# 质量等级配色
QUALITY_STYLE = {
    "高质量": {"cls": "q-high",   "color": "#16a34a", "bg": "#dcfce7"},
    "中等":   {"cls": "q-mid",    "color": "#2563eb", "bg": "#dbeafe"},
    "一般":   {"cls": "q-low",    "color": "#64748b", "bg": "#f1f5f9"},
}

FEEDBACK_EMAIL = "tjhjxhlin@163.com"


# ============================================================
# 数据库读取
# ============================================================
def load_documents():
    """读取所有 active 状态的文档，返回字典列表。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, url, source, source_type, category, sub_category,
               geo_scope, publish_date, quality_score, quality_level,
               summary, keywords, status, collected_at
        FROM documents
        WHERE status = 'active'
        ORDER BY publish_date DESC NULLS LAST, collected_at DESC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def parse_date(date_str):
    """解析日期字符串，返回 datetime 对象；失败返回 None。"""
    if not date_str:
        return None
    # 尝试多种格式
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%Y-%m"):
        try:
            return datetime.strptime(date_str[:len(fmt) + 5 if "T" in fmt else len(fmt)], fmt)
        except ValueError:
            continue
    # 退而求其次：取前 10 位
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None


def compute_time_periods(pub_date):
    """根据发布日期计算该文档所属的时间段 key 列表。"""
    periods = []
    if pub_date is None:
        return periods

    delta_days = (REF_DATE - pub_date).days

    if delta_days <= 7:
        periods.append("7d")
    if delta_days <= 30:
        periods.append("1m")
    if delta_days <= 90:
        periods.append("3m")
    if delta_days <= 180:
        periods.append("6m")
    if pub_date.year == 2026:
        periods.append("y2026")
    if pub_date.year == 2025:
        periods.append("y2025")
    if delta_days <= 1095:  # 约3年
        periods.append("3y")
    if delta_days > 1095 and pub_date.year < 2024:
        periods.append("older")

    # 如果没有任何匹配（例如未来的日期），归到最近的时段
    if not periods:
        if pub_date.year >= 2026:
            periods.append("y2026")
        else:
            periods.append("older")
    return periods


def format_date(date_str):
    """格式化日期为 YYYY-MM-DD 展示。"""
    if not date_str:
        return "未知日期"
    dt = parse_date(date_str)
    if dt:
        return dt.strftime("%Y-%m-%d")
    return date_str[:10] if len(date_str) >= 10 else date_str


def parse_keywords(kw_str):
    """解析 keywords 字段（可能是 JSON 数组或逗号分隔字符串）。"""
    if not kw_str:
        return []
    kw_str = kw_str.strip()
    if not kw_str or kw_str == "[]":
        return []
    # 尝试 JSON 解析
    try:
        data = json.loads(kw_str)
        if isinstance(data, list):
            return [str(k).strip() for k in data if str(k).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    # 逗号分隔
    return [k.strip() for k in re.split(r"[,，;；]", kw_str) if k.strip()]


def get_summary_fallback(doc):
    """摘要为空时的回退文案。"""
    parts = []
    if doc.get("source_type"):
        parts.append(doc["source_type"])
    if doc.get("geo_scope"):
        parts.append(f"地理范围：{doc['geo_scope']}")
    if doc.get("source"):
        parts.append(f"来源：{doc['source']}")
    base = " · ".join(parts) if parts else "暂无摘要信息"
    return f"本文档暂无结构化摘要。{base}。"


# ============================================================
# 聚合统计
# ============================================================
def aggregate(docs):
    """计算各类统计数据。"""
    total = len(docs)
    by_category = {c["code"]: 0 for c in CATEGORIES}
    by_quality = {"高质量": 0, "中等": 0, "一般": 0}
    new_7d = 0

    for d in docs:
        cat = d.get("category") or "07_动态资讯与综合"
        if cat in by_category:
            by_category[cat] += 1
        else:
            # 未知分类归入综合
            by_category["07_动态资讯与综合"] += 1

        ql = d.get("quality_level") or "中等"
        if ql in by_quality:
            by_quality[ql] += 1

        pub = parse_date(d.get("publish_date"))
        if pub and (REF_DATE - pub).days <= 7:
            new_7d += 1

    active_categories = sum(1 for v in by_category.values() if v > 0)
    return {
        "total": total,
        "by_category": by_category,
        "by_quality": by_quality,
        "new_7d": new_7d,
        "active_categories": active_categories,
        "high_quality": by_quality["高质量"],
    }


# ============================================================
# HTML 生成
# ============================================================
def build_doc_data(docs):
    """构造前端需要的文档数据列表（已转义）。"""
    items = []
    for d in docs:
        pub_dt = parse_date(d.get("publish_date"))
        periods = compute_time_periods(pub_dt)
        cat_code = d.get("category") or "07_动态资讯与综合"
        cat_info = CATEGORY_MAP.get(cat_code, {"name": "综合", "icon": "📰"})
        ql = d.get("quality_level") or "中等"
        score = d.get("quality_score")
        if score is None:
            score = 0.5

        summary_raw = d.get("summary") or ""
        summary_text = summary_raw.strip() if summary_raw else get_summary_fallback(d)
        keywords = parse_keywords(d.get("keywords"))

        geo = d.get("geo_scope") or ""
        is_hz = ("杭州" in geo) or ("杭州" in (d.get("title") or ""))

        # 日期排序值
        sort_date = pub_dt.strftime("%Y%m%d") if pub_dt else "00000000"

        items.append({
            "id": d["id"],
            "title": d.get("title") or "无标题",
            "url": d.get("url") or "",
            "source": d.get("source") or "未知来源",
            "source_type": d.get("source_type") or "",
            "category_code": cat_code,
            "category_name": cat_info["name"],
            "category_icon": cat_info["icon"],
            "geo_scope": geo,
            "publish_date": format_date(d.get("publish_date")),
            "sort_date": sort_date,
            "quality_level": ql,
            "quality_score": round(float(score), 2),
            "summary": summary_text,
            "keywords": keywords,
            "periods": periods,
            "is_hz": is_hz,
        })
    return items


def escape(s):
    """HTML 转义。"""
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def render_category_bars(stats):
    """渲染分类分布水平条形图 HTML。"""
    max_val = max(stats["by_category"].values()) if stats["by_category"] else 1
    if max_val == 0:
        max_val = 1
    bars = []
    for cat in CATEGORIES:
        count = stats["by_category"].get(cat["code"], 0)
        pct = (count / max_val) * 100 if max_val else 0
        bars.append(f"""
        <div class="cat-bar-row" data-cat="{escape(cat['code'])}">
            <div class="cat-bar-label">
                <span class="cat-icon">{cat['icon']}</span>
                <span class="cat-name">{escape(cat['name'])}</span>
            </div>
            <div class="cat-bar-track">
                <div class="cat-bar-fill" style="width:{pct:.1f}%"></div>
            </div>
            <div class="cat-bar-count">{count}</div>
        </div>
        """)
    return "\n".join(bars)


def render_category_tabs(stats):
    """渲染分类 Tab（含文档数标记）。"""
    tabs = [f"""
    <button class="cat-tab active" data-cat="all">
        <span class="cat-tab-icon">🗂️</span>
        <span class="cat-tab-name">全部</span>
        <span class="cat-tab-count">{stats['total']}</span>
    </button>
    """]
    for cat in CATEGORIES:
        count = stats["by_category"].get(cat["code"], 0)
        if count == 0:
            continue
        tabs.append(f"""
        <button class="cat-tab" data-cat="{escape(cat['code'])}">
            <span class="cat-tab-icon">{cat['icon']}</span>
            <span class="cat-tab-name">{escape(cat['name'])}</span>
            <span class="cat-tab-count">{count}</span>
        </button>
        """)
    return "\n".join(tabs)


def render_time_buttons():
    """渲染时间段筛选按钮。"""
    btns = [f'<button class="time-btn active" data-period="all">全部</button>']
    for tp in TIME_PERIODS:
        btns.append(f'<button class="time-btn" data-period="{tp["key"]}">{escape(tp["label"])}</button>')
    return "\n".join(btns)


def build_html(docs):
    """构建完整 HTML 文档。"""
    stats = aggregate(docs)
    items = build_doc_data(docs)

    # 分类条形图、Tab、时间按钮
    cat_bars_html = render_category_bars(stats)
    cat_tabs_html = render_category_tabs(stats)
    time_btns_html = render_time_buttons()

    # 周几
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][TODAY.weekday()]

    # 文档数据 JSON（嵌入到 script 中）
    items_json = json.dumps(items, ensure_ascii=False)

    # 反馈邮件链接
    feedback_subject = f"水生态环境资讯日报 - 意见反馈 ({TODAY_STR})"
    feedback_body = (
        "您好，\n\n"
        "我在使用「水生态环境资讯日报」过程中有以下建议/反馈：\n\n"
        "1. 内容方面：\n"
        "2. 功能方面：\n"
        "3. 其他建议：\n\n"
        "（请在此填写您的具体建议）\n\n"
        "—— 来自水生态环境知识管理系统"
    )
    feedback_href = f"mailto:{FEEDBACK_EMAIL}?subject={escape(feedback_subject)}&body={escape(feedback_body)}"

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>水生态环境资讯日报 · {TODAY_DISPLAY}</title>
<style>
/* ============================================================
   全局变量与重置
   ============================================================ */
:root {{
    --c-deep: #0c4a6e;        /* 深蓝 */
    --c-mid:  #0891b2;        /* 青绿 */
    --c-light: #e0f2fe;       /* 浅蓝 */
    --c-accent: #06b6d4;      /* 亮青 */
    --c-bg:    #f0f9ff;       /* 极浅蓝背景 */
    --c-card:  #ffffff;
    --c-text:  #1e293b;
    --c-text-soft: #64748b;
    --c-border: #e2e8f0;
    --c-high: #16a34a;
    --c-high-bg: #dcfce7;
    --c-mid-q: #2563eb;
    --c-mid-bg: #dbeafe;
    --c-low:  #64748b;
    --c-low-bg: #f1f5f9;
    --c-hz: #dc2626;          /* 杭州高亮 */
    --shadow-sm: 0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06);
    --shadow-md: 0 4px 6px -1px rgba(15,23,42,.08), 0 2px 4px -2px rgba(15,23,42,.06);
    --shadow-lg: 0 10px 25px -5px rgba(12,74,110,.15), 0 8px 10px -6px rgba(12,74,110,.10);
    --radius: 14px;
    --radius-sm: 8px;
    --maxw: 1320px;
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
    background: var(--c-bg);
    color: var(--c-text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}
a {{ color: var(--c-mid); text-decoration: none; transition: color .2s; }}
a:hover {{ color: var(--c-deep); }}
button {{ font-family: inherit; cursor: pointer; border: none; background: none; }}

/* ============================================================
   顶部导航栏
   ============================================================ */
.navbar {{
    position: sticky; top: 0; z-index: 100;
    background: rgba(12, 74, 110, .92);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255,255,255,.1);
    color: #fff;
}}
.navbar-inner {{
    max-width: var(--maxw); margin: 0 auto;
    padding: 12px 24px;
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; flex-wrap: wrap;
}}
.navbar-brand {{
    display: flex; align-items: center; gap: 10px;
    font-size: 17px; font-weight: 700; letter-spacing: .5px;
}}
.navbar-brand .logo {{
    width: 32px; height: 32px; border-radius: 8px;
    background: linear-gradient(135deg, var(--c-accent), #67e8f9);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    box-shadow: 0 0 0 2px rgba(255,255,255,.15);
}}
.navbar-actions {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.date-picker {{ color: #cbd5e1; font-size: 13px; }}
.date-picker input {{
    background: rgba(255,255,255,.12);
    border: 1px solid rgba(255,255,255,.18);
    color: #fff; border-radius: 6px;
    padding: 5px 10px; font-size: 13px; font-family: inherit;
}}
.date-picker input::-webkit-calendar-picker-indicator {{ filter: invert(1); }}
.btn-feedback {{
    background: var(--c-accent); color: #fff;
    padding: 7px 16px; border-radius: 20px;
    font-size: 13px; font-weight: 600;
    transition: all .2s;
    box-shadow: 0 2px 8px rgba(6,182,212,.4);
}}
.btn-feedback:hover {{ background: #22d3ee; transform: translateY(-1px); }}

/* ============================================================
   Hero 区
   ============================================================ */
.hero {{
    position: relative;
    background: linear-gradient(135deg, #0c4a6e 0%, #0891b2 60%, #06b6d4 100%);
    color: #fff;
    padding: 64px 24px 72px;
    overflow: hidden;
}}
.hero::before {{
    content: ""; position: absolute; inset: 0;
    background:
        radial-gradient(circle at 15% 20%, rgba(255,255,255,.12) 0, transparent 40%),
        radial-gradient(circle at 85% 80%, rgba(103,232,249,.18) 0, transparent 45%);
    pointer-events: none;
}}
/* 水波纹动画 */
.waves {{
    position: absolute; left: 0; right: 0; bottom: -2px;
    height: 90px; pointer-events: none;
}}
.wave {{
    position: absolute; bottom: 0; left: 0; width: 200%; height: 100%;
    background-repeat: repeat-x; background-position: 0 bottom;
    transform-origin: center bottom;
}}
.wave svg {{ display: block; width: 100%; height: 100%; }}
.wave1 {{ animation: wave-move 12s linear infinite; opacity: .5; }}
.wave2 {{ animation: wave-move 8s linear infinite reverse; opacity: .35; }}
.wave3 {{ animation: wave-move 16s linear infinite; opacity: .25; }}
@keyframes wave-move {{
    0%   {{ transform: translateX(0); }}
    100% {{ transform: translateX(-50%); }}
}}
.hero-inner {{
    position: relative; z-index: 2;
    max-width: var(--maxw); margin: 0 auto;
    text-align: center;
}}
.hero-eyebrow {{
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,.14);
    border: 1px solid rgba(255,255,255,.25);
    padding: 5px 14px; border-radius: 20px;
    font-size: 12.5px; letter-spacing: 1px;
    margin-bottom: 18px;
    backdrop-filter: blur(4px);
}}
.hero-eyebrow .dot {{
    width: 7px; height: 7px; border-radius: 50%;
    background: #4ade80; box-shadow: 0 0 8px #4ade80;
    animation: pulse 2s ease-in-out infinite;
}}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
.hero h1 {{
    font-size: clamp(28px, 4.2vw, 46px);
    font-weight: 800; letter-spacing: 2px;
    margin-bottom: 12px;
    text-shadow: 0 2px 20px rgba(0,0,0,.2);
}}
.hero-sub {{
    font-size: 15px; color: rgba(255,255,255,.85);
    margin-bottom: 36px;
}}
.hero-stats {{
    display: flex; justify-content: center; gap: 14px;
    flex-wrap: wrap;
}}
.hero-stat {{
    background: rgba(255,255,255,.13);
    border: 1px solid rgba(255,255,255,.22);
    border-radius: 12px;
    padding: 14px 26px;
    min-width: 110px;
    backdrop-filter: blur(6px);
    transition: transform .25s, background .25s;
}}
.hero-stat:hover {{ transform: translateY(-3px); background: rgba(255,255,255,.2); }}
.hero-stat .num {{
    font-size: 28px; font-weight: 800; line-height: 1;
    color: #fff;
}}
.hero-stat .lbl {{
    font-size: 12.5px; color: rgba(255,255,255,.8);
    margin-top: 5px;
}}

/* ============================================================
   主体容器
   ============================================================ */
.container {{
    max-width: var(--maxw); margin: 0 auto;
    padding: 0 24px;
}}
.section {{ margin: 40px 0; }}
.section-title {{
    display: flex; align-items: center; gap: 10px;
    font-size: 19px; font-weight: 700; color: var(--c-deep);
    margin-bottom: 18px;
    padding-bottom: 10px;
    border-bottom: 2px solid var(--c-light);
}}
.section-title .bar {{
    width: 4px; height: 20px; border-radius: 2px;
    background: linear-gradient(180deg, var(--c-deep), var(--c-accent));
}}
.section-title .count {{
    margin-left: auto; font-size: 13px; font-weight: 500;
    color: var(--c-text-soft);
    background: var(--c-light); padding: 3px 12px; border-radius: 12px;
}}

/* ============================================================
   统计概览卡片
   ============================================================ */
.stats-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 18px;
}}
.stat-card {{
    background: var(--c-card);
    border-radius: var(--radius);
    padding: 22px;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--c-border);
    position: relative; overflow: hidden;
    transition: transform .25s, box-shadow .25s;
}}
.stat-card::before {{
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
    background: var(--c-accent);
}}
.stat-card.s1::before {{ background: linear-gradient(180deg,#0c4a6e,#0891b2); }}
.stat-card.s2::before {{ background: linear-gradient(180deg,#0891b2,#06b6d4); }}
.stat-card.s3::before {{ background: linear-gradient(180deg,#16a34a,#22c55e); }}
.stat-card.s4::before {{ background: linear-gradient(180deg,#d97706,#f59e0b); }}
.stat-card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow-lg); }}
.stat-card .stat-icon {{
    font-size: 24px; margin-bottom: 8px;
}}
.stat-card .stat-num {{
    font-size: 30px; font-weight: 800; color: var(--c-deep);
    line-height: 1.1;
}}
.stat-card .stat-lbl {{
    font-size: 13.5px; color: var(--c-text-soft);
    margin-top: 4px;
}}
.stat-card .stat-trend {{
    font-size: 12px; color: var(--c-high); margin-top: 6px;
}}

/* ============================================================
   分类分布条形图
   ============================================================ */
.cat-bars {{
    background: var(--c-card);
    border-radius: var(--radius);
    padding: 24px;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--c-border);
}}
.cat-bar-row {{
    display: grid;
    grid-template-columns: 180px 1fr 48px;
    align-items: center; gap: 14px;
    padding: 8px 0;
    cursor: pointer;
    transition: background .2s;
    border-radius: 6px;
    padding-left: 6px; padding-right: 6px;
}}
.cat-bar-row:hover {{ background: var(--c-light); }}
.cat-bar-label {{
    display: flex; align-items: center; gap: 8px;
    font-size: 14px; font-weight: 500;
}}
.cat-bar-label .cat-icon {{ font-size: 16px; }}
.cat-bar-track {{
    height: 14px; border-radius: 7px;
    background: #f1f5f9; overflow: hidden;
}}
.cat-bar-fill {{
    height: 100%; border-radius: 7px;
    background: linear-gradient(90deg, var(--c-deep), var(--c-accent));
    transition: width .8s cubic-bezier(.4,0,.2,1);
}}
.cat-bar-count {{
    text-align: right; font-weight: 700; color: var(--c-deep);
    font-size: 15px;
}}

/* ============================================================
   筛选区
   ============================================================ */
.filter-panel {{
    background: var(--c-card);
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--c-border);
}}
.filter-group {{ margin-bottom: 18px; }}
.filter-group:last-child {{ margin-bottom: 0; }}
.filter-label {{
    font-size: 12.5px; font-weight: 600; color: var(--c-text-soft);
    text-transform: uppercase; letter-spacing: .5px;
    margin-bottom: 10px;
    display: flex; align-items: center; gap: 6px;
}}
.cat-tabs {{
    display: flex; flex-wrap: wrap; gap: 8px;
}}
.cat-tab {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: 20px;
    background: #f1f5f9; color: var(--c-text);
    font-size: 13.5px; font-weight: 500;
    border: 1.5px solid transparent;
    transition: all .2s;
}}
.cat-tab:hover {{ background: var(--c-light); }}
.cat-tab.active {{
    background: var(--c-deep); color: #fff;
    box-shadow: 0 3px 10px rgba(12,74,110,.3);
}}
.cat-tab-icon {{ font-size: 14px; }}
.cat-tab-count {{
    background: rgba(255,255,255,.25); color: inherit;
    padding: 1px 8px; border-radius: 10px;
    font-size: 11.5px; font-weight: 700;
}}
.cat-tab:not(.active) .cat-tab-count {{
    background: #e2e8f0; color: var(--c-text-soft);
}}

.time-buttons {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.time-btn {{
    padding: 6px 14px; border-radius: 6px;
    background: #f1f5f9; color: var(--c-text-soft);
    font-size: 13px; font-weight: 500;
    border: 1.5px solid transparent;
    transition: all .2s;
}}
.time-btn:hover {{ background: var(--c-light); color: var(--c-deep); }}
.time-btn.active {{
    background: var(--c-accent); color: #fff;
    border-color: var(--c-accent);
}}

.search-sort-row {{
    display: flex; gap: 14px; flex-wrap: wrap; align-items: center;
    margin-top: 4px;
}}
.search-box {{
    flex: 1; min-width: 220px; position: relative;
}}
.search-box input {{
    width: 100%; padding: 10px 14px 10px 38px;
    border: 1.5px solid var(--c-border); border-radius: 10px;
    font-size: 14px; font-family: inherit;
    transition: border-color .2s, box-shadow .2s;
    background: #f8fafc;
}}
.search-box input:focus {{
    outline: none; border-color: var(--c-accent);
    box-shadow: 0 0 0 3px rgba(6,182,212,.15);
    background: #fff;
}}
.search-box .search-icon {{
    position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
    color: var(--c-text-soft); font-size: 16px; pointer-events: none;
}}
.sort-group {{
    display: flex; align-items: center; gap: 8px;
}}
.sort-group label {{ font-size: 13px; color: var(--c-text-soft); white-space: nowrap; }}
.sort-select {{
    padding: 8px 12px; border-radius: 8px;
    border: 1.5px solid var(--c-border); background: #f8fafc;
    font-size: 13.5px; font-family: inherit; color: var(--c-text);
    cursor: pointer;
}}
.sort-select:focus {{ outline: none; border-color: var(--c-accent); }}

.result-info {{
    font-size: 13px; color: var(--c-text-soft);
    margin-top: 14px; padding-top: 14px;
    border-top: 1px dashed var(--c-border);
}}
.result-info b {{ color: var(--c-deep); }}

/* ============================================================
   内容列表（卡片网格）
   ============================================================ */
.doc-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 18px;
}}
.doc-card {{
    background: var(--c-card);
    border-radius: var(--radius);
    padding: 20px;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--c-border);
    border-left: 4px solid var(--c-border);
    display: flex; flex-direction: column;
    transition: transform .25s, box-shadow .25s, border-color .25s;
    position: relative;
}}
.doc-card:hover {{
    transform: translateY(-5px);
    box-shadow: var(--shadow-lg);
}}
/* 质量等级左边框配色 */
.doc-card.q-high {{ border-left-color: var(--c-high); }}
.doc-card.q-mid  {{ border-left-color: var(--c-mid-q); }}
.doc-card.q-low  {{ border-left-color: var(--c-low); }}
/* 杭州相关高亮 */
.doc-card.is-hz {{
    border: 1.5px solid var(--c-hz);
    border-left: 4px solid var(--c-hz);
    background: linear-gradient(180deg, #fef2f2 0%, #fff 30%);
}}
.doc-card.is-hz::after {{
    content: "杭州"; position: absolute; top: 12px; right: 12px;
    background: var(--c-hz); color: #fff;
    font-size: 10.5px; font-weight: 700;
    padding: 2px 8px; border-radius: 10px;
    letter-spacing: .5px;
}}
.doc-card-head {{
    display: flex; align-items: flex-start; gap: 10px;
    margin-bottom: 10px;
    padding-right: 48px;
}}
.quality-badge {{
    flex-shrink: 0;
    font-size: 11px; font-weight: 700;
    padding: 3px 9px; border-radius: 10px;
    letter-spacing: .5px;
    white-space: nowrap;
}}
.quality-badge.q-high {{ background: var(--c-high-bg); color: var(--c-high); }}
.quality-badge.q-mid  {{ background: var(--c-mid-bg); color: var(--c-mid-q); }}
.quality-badge.q-low  {{ background: var(--c-low-bg); color: var(--c-low); }}
.doc-cat-tag {{
    flex-shrink: 0; font-size: 11.5px;
    color: var(--c-mid); background: var(--c-light);
    padding: 3px 9px; border-radius: 10px;
    white-space: nowrap;
}}
.doc-title {{
    font-size: 16px; font-weight: 700; color: var(--c-text);
    line-height: 1.45;
    margin-bottom: 10px;
    cursor: pointer;
    transition: color .2s;
}}
.doc-title:hover {{ color: var(--c-deep); }}
.doc-summary {{
    font-size: 13.5px; color: var(--c-text-soft);
    line-height: 1.65;
    margin-bottom: 14px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    transition: -webkit-line-clamp .2s;
}}
.doc-summary.expanded {{
    -webkit-line-clamp: unset;
    display: block;
}}
.doc-summary-toggle {{
    align-self: flex-start;
    color: var(--c-accent); font-size: 12.5px; font-weight: 600;
    margin-bottom: 14px;
    transition: color .2s;
}}
.doc-summary-toggle:hover {{ color: var(--c-deep); }}
.doc-keywords {{
    display: flex; flex-wrap: wrap; gap: 6px;
    margin-bottom: 12px;
}}
.doc-keyword {{
    font-size: 11.5px; color: var(--c-text-soft);
    background: #f1f5f9; padding: 2px 8px; border-radius: 8px;
}}
.doc-meta {{
    display: flex; flex-wrap: wrap; align-items: center;
    gap: 6px 14px;
    margin-top: auto; padding-top: 12px;
    border-top: 1px dashed var(--c-border);
    font-size: 12.5px; color: var(--c-text-soft);
}}
.doc-meta .meta-item {{ display: inline-flex; align-items: center; gap: 5px; }}
.doc-meta .geo-tag {{
    background: var(--c-light); color: var(--c-deep);
    padding: 2px 8px; border-radius: 8px; font-weight: 600;
    font-size: 11.5px;
}}
.doc-meta .geo-tag.hz {{ background: #fee2e2; color: var(--c-hz); }}
.doc-link {{
    margin-left: auto;
    color: var(--c-accent); font-weight: 600; font-size: 12.5px;
    display: inline-flex; align-items: center; gap: 4px;
    transition: color .2s, gap .2s;
}}
.doc-link:hover {{ color: var(--c-deep); gap: 6px; }}

/* 空状态 */
.empty-state {{
    grid-column: 1 / -1;
    text-align: center; padding: 60px 20px;
    color: var(--c-text-soft);
}}
.empty-state .icon {{ font-size: 48px; margin-bottom: 12px; opacity: .5; }}
.empty-state .title {{ font-size: 17px; font-weight: 600; margin-bottom: 6px; color: var(--c-text); }}
.empty-state .desc {{ font-size: 13.5px; }}

/* ============================================================
   底部反馈区
   ============================================================ */
.feedback-section {{
    margin-top: 60px;
    background: linear-gradient(135deg, #0c4a6e 0%, #0891b2 100%);
    border-radius: var(--radius);
    padding: 44px 36px;
    color: #fff;
    text-align: center;
    position: relative;
    overflow: hidden;
}}
.feedback-section::before {{
    content: ""; position: absolute; inset: 0;
    background: radial-gradient(circle at 80% 20%, rgba(103,232,249,.2) 0, transparent 50%);
}}
.feedback-section > * {{ position: relative; z-index: 1; }}
.feedback-section h2 {{
    font-size: 26px; font-weight: 800; margin-bottom: 12px;
    letter-spacing: 1px;
}}
.feedback-section p {{
    font-size: 14.5px; color: rgba(255,255,255,.9);
    max-width: 640px; margin: 0 auto 24px;
    line-height: 1.7;
}}
.feedback-section .email {{ color: #67e8f9; font-weight: 600; }}
.feedback-btn {{
    display: inline-flex; align-items: center; gap: 8px;
    background: #fff; color: var(--c-deep);
    padding: 13px 32px; border-radius: 26px;
    font-size: 15px; font-weight: 700;
    transition: all .25s;
    box-shadow: 0 6px 20px rgba(0,0,0,.2);
}}
.feedback-btn:hover {{
    transform: translateY(-2px);
    box-shadow: 0 10px 28px rgba(0,0,0,.3);
    background: #f0fdff;
}}

/* 页脚 */
.footer {{
    text-align: center; padding: 28px 20px;
    font-size: 12.5px; color: var(--c-text-soft);
    border-top: 1px solid var(--c-border);
    margin-top: 40px;
}}
.footer .sep {{ margin: 0 8px; opacity: .5; }}

/* ============================================================
   响应式
   ============================================================ */
@media (max-width: 1024px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .doc-grid {{ grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }}
}}
@media (max-width: 720px) {{
    .navbar-inner {{ padding: 10px 16px; }}
    .hero {{ padding: 44px 18px 56px; }}
    .container {{ padding: 0 16px; }}
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); gap: 12px; }}
    .stat-card {{ padding: 16px; }}
    .stat-card .stat-num {{ font-size: 24px; }}
    .hero-stat {{ padding: 12px 18px; min-width: 88px; }}
    .hero-stat .num {{ font-size: 22px; }}
    .cat-bar-row {{ grid-template-columns: 130px 1fr 40px; gap: 10px; font-size: 13px; }}
    .doc-grid {{ grid-template-columns: 1fr; }}
    .filter-panel {{ padding: 16px; }}
    .feedback-section {{ padding: 32px 20px; }}
    .feedback-section h2 {{ font-size: 22px; }}
    .search-sort-row {{ flex-direction: column; align-items: stretch; }}
    .sort-group {{ justify-content: space-between; }}
}}
@media (max-width: 480px) {{
    .stats-grid {{ grid-template-columns: 1fr; }}
    .navbar-brand {{ font-size: 15px; }}
}}

/* 回到顶部 */
.back-top {{
    position: fixed; right: 24px; bottom: 24px;
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--c-deep); color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; box-shadow: var(--shadow-lg);
    opacity: 0; visibility: hidden;
    transition: all .3s; z-index: 50;
}}
.back-top.show {{ opacity: 1; visibility: visible; }}
.back-top:hover {{ background: var(--c-accent); transform: translateY(-2px); }}
</style>
</head>
<body>

<!-- ============ 顶部导航栏 ============ -->
<nav class="navbar">
    <div class="navbar-inner">
        <div class="navbar-brand">
            <span class="logo">💧</span>
            <span>水生态环境知识管理系统</span>
        </div>
        <div class="navbar-actions">
            <div class="date-picker">
                <span>📅 查看：</span>
                <input type="date" id="historyDate" value="{TODAY_STR}" max="{TODAY_STR}">
            </div>
            <button class="btn-feedback" onclick="document.getElementById('feedbackSection').scrollIntoView({{behavior:'smooth'}})">
                意见反馈
            </button>
        </div>
    </div>
</nav>

<!-- ============ Hero 区 ============ -->
<header class="hero">
    <div class="hero-inner">
        <div class="hero-eyebrow">
            <span class="dot"></span>
            <span>WATER ECOLOGY INTELLIGENCE</span>
        </div>
        <h1>水生态环境资讯日报</h1>
        <div class="hero-sub">{TODAY_DISPLAY} · {weekday_cn} · 数据截至当日实时更新</div>
        <div class="hero-stats">
            <div class="hero-stat">
                <div class="num">{stats['total']}</div>
                <div class="lbl">收录文献总数</div>
            </div>
            <div class="hero-stat">
                <div class="num">{stats['new_7d']}</div>
                <div class="lbl">近7天新增</div>
            </div>
            <div class="hero-stat">
                <div class="num">{stats['active_categories']}</div>
                <div class="lbl">覆盖分类</div>
            </div>
            <div class="hero-stat">
                <div class="num">{stats['high_quality']}</div>
                <div class="lbl">高质量文献</div>
            </div>
        </div>
    </div>
    <!-- 水波纹动画 -->
    <div class="waves">
        <div class="wave wave1">
            <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0,45 C240,80 480,10 720,45 C960,80 1200,10 1440,45 L1440,90 L0,90 Z" fill="rgba(255,255,255,0.5)"></path>
                <path d="M1440,45 C1680,80 1920,10 2160,45 C2400,80 2640,10 2880,45 L2880,90 L1440,90 Z" fill="rgba(255,255,255,0.5)"></path>
            </svg>
        </div>
        <div class="wave wave2">
            <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0,55 C240,25 480,75 720,55 C960,25 1200,75 1440,55 L1440,90 L0,90 Z" fill="rgba(103,232,249,0.4)"></path>
                <path d="M1440,55 C1680,25 1920,75 2160,55 C2400,25 2640,75 2880,55 L2880,90 L1440,90 Z" fill="rgba(103,232,249,0.4)"></path>
            </svg>
        </div>
        <div class="wave wave3">
            <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0,65 C240,40 480,85 720,65 C960,40 1200,85 1440,65 L1440,90 L0,90 Z" fill="rgba(255,255,255,0.3)"></path>
                <path d="M1440,65 C1680,40 1920,85 2160,65 C2400,40 2640,85 2880,65 L2880,90 L1440,90 Z" fill="rgba(255,255,255,0.3)"></path>
            </svg>
        </div>
    </div>
</header>

<!-- ============ 统计概览 ============ -->
<div class="container">
    <section class="section">
        <div class="section-title">
            <span class="bar"></span>
            <span>统计概览</span>
        </div>
        <div class="stats-grid">
            <div class="stat-card s1">
                <div class="stat-icon">📚</div>
                <div class="stat-num">{stats['total']}</div>
                <div class="stat-lbl">总文档数</div>
            </div>
            <div class="stat-card s2">
                <div class="stat-icon">🆕</div>
                <div class="stat-num">{stats['new_7d']}</div>
                <div class="stat-lbl">近7天新增</div>
            </div>
            <div class="stat-card s3">
                <div class="stat-icon">🗂️</div>
                <div class="stat-num">{stats['active_categories']}<span style="font-size:16px;color:var(--c-text-soft)"> / 7</span></div>
                <div class="stat-lbl">活跃分类数</div>
            </div>
            <div class="stat-card s4">
                <div class="stat-icon">⭐</div>
                <div class="stat-num">{stats['high_quality']}</div>
                <div class="stat-lbl">高质量文献</div>
            </div>
        </div>
    </section>

    <!-- ============ 分类分布 ============ -->
    <section class="section">
        <div class="section-title">
            <span class="bar"></span>
            <span>分类分布</span>
            <span class="count">共 {stats['total']} 篇</span>
        </div>
        <div class="cat-bars">
            {cat_bars_html}
        </div>
    </section>

    <!-- ============ 筛选与内容 ============ -->
    <section class="section">
        <div class="section-title">
            <span class="bar"></span>
            <span>资讯列表</span>
            <span class="count" id="visibleCount">共 {stats['total']} 篇</span>
        </div>

        <div class="filter-panel">
            <!-- 分类 Tab -->
            <div class="filter-group">
                <div class="filter-label">🏷️ 分类筛选</div>
                <div class="cat-tabs" id="catTabs">
                    {cat_tabs_html}
                </div>
            </div>
            <!-- 时间段 -->
            <div class="filter-group">
                <div class="filter-label">🗓️ 时间段</div>
                <div class="time-buttons" id="timeButtons">
                    {time_btns_html}
                </div>
            </div>
            <!-- 搜索与排序 -->
            <div class="filter-group">
                <div class="search-sort-row">
                    <div class="search-box">
                        <span class="search-icon">🔍</span>
                        <input type="text" id="searchInput" placeholder="搜索标题、摘要、关键词...">
                    </div>
                    <div class="sort-group">
                        <label for="sortSelect">排序：</label>
                        <select class="sort-select" id="sortSelect">
                            <option value="date_desc">按时间 新→旧</option>
                            <option value="date_asc">按时间 旧→新</option>
                            <option value="score_desc">按质量 高→低</option>
                        </select>
                    </div>
                </div>
                <div class="result-info" id="resultInfo">
                    显示全部 <b>{stats['total']}</b> 篇文档
                </div>
            </div>
        </div>

        <!-- 文档卡片网格 -->
        <div class="doc-grid" id="docGrid" style="margin-top:22px;">
            <!-- 由 JS 渲染 -->
        </div>
    </section>

    <!-- ============ 底部反馈区 ============ -->
    <section class="feedback-section" id="feedbackSection">
        <h2>📬 意见反馈</h2>
        <p>
            您的建议将帮助持续优化本系统。点击下方反馈按钮，或发送邮件至
            <span class="email">{FEEDBACK_EMAIL}</span>，
            我们将认真倾听每一位领导与专家的意见。
        </p>
        <a href="{feedback_href}" class="feedback-btn">
            <span>✉️</span>
            <span>提交反馈建议</span>
        </a>
    </section>
</div>

<!-- ============ 页脚 ============ -->
<footer class="footer">
    <span>水生态环境知识管理系统</span>
    <span class="sep">|</span>
    <span>资讯日报生成于 {TODAY_DISPLAY} {weekday_cn}</span>
    <span class="sep">|</span>
    <span>数据来源：自动采集与人工整理</span>
</footer>

<!-- 回到顶部 -->
<button class="back-top" id="backTop" title="回到顶部">↑</button>

<script>
// ============================================================
// 文档数据（由 Python 注入）
// ============================================================
const ALL_DOCS = {items_json};

// 当前筛选状态
const state = {{
    category: 'all',     // 当前选中分类
    period: 'all',       // 当前选中时间段
    keyword: '',         // 搜索关键词
    sort: 'date_desc',   // 排序方式
}};

// 分类中文名映射
const CAT_NAMES = {{
    {chr(10).join([f'"{c["code"]}": "{c["name"]}",' for c in CATEGORIES])}
}};

// ============================================================
// 渲染文档卡片
// ============================================================
function renderDocs() {{
    let docs = ALL_DOCS.slice();

    // 1. 分类筛选
    if (state.category !== 'all') {{
        docs = docs.filter(d => d.category_code === state.category);
    }}

    // 2. 时间段筛选
    if (state.period !== 'all') {{
        docs = docs.filter(d => d.periods && d.periods.includes(state.period));
    }}

    // 3. 关键词搜索（匹配标题、摘要、关键词）
    if (state.keyword) {{
        const kw = state.keyword.toLowerCase();
        docs = docs.filter(d => {{
            const title = (d.title || '').toLowerCase();
            const summary = (d.summary || '').toLowerCase();
            const kws = (d.keywords || []).join(' ').toLowerCase();
            const source = (d.source || '').toLowerCase();
            return title.includes(kw) || summary.includes(kw) || kws.includes(kw) || source.includes(kw);
        }});
    }}

    // 4. 排序
    if (state.sort === 'date_desc') {{
        docs.sort((a, b) => b.sort_date.localeCompare(a.sort_date));
    }} else if (state.sort === 'date_asc') {{
        docs.sort((a, b) => a.sort_date.localeCompare(b.sort_date));
    }} else if (state.sort === 'score_desc') {{
        docs.sort((a, b) => b.quality_score - a.quality_score);
    }}

    // 5. 渲染
    const grid = document.getElementById('docGrid');
    const info = document.getElementById('resultInfo');
    const visibleCount = document.getElementById('visibleCount');

    if (docs.length === 0) {{
        grid.innerHTML = `
            <div class="empty-state">
                <div class="icon">🔍</div>
                <div class="title">未找到匹配的文档</div>
                <div class="desc">请尝试调整筛选条件或更换关键词</div>
            </div>
        `;
    }} else {{
        grid.innerHTML = docs.map(d => {{
            const qClass = d.quality_level === '高质量' ? 'q-high' :
                           d.quality_level === '中等' ? 'q-mid' : 'q-low';
            const hzClass = d.is_hz ? 'is-hz' : '';
            const geoTagClass = d.is_hz ? 'hz' : '';
            const keywordsHtml = (d.keywords && d.keywords.length)
                ? `<div class="doc-keywords">${{d.keywords.slice(0,6).map(k => `<span class="doc-keyword">${{escapeHtml(k)}}</span>`).join('')}}</div>`
                : '';
            const linkHtml = d.url
                ? `<a class="doc-link" href="${{escapeAttr(d.url)}}" target="_blank" rel="noopener noreferrer">查看原文 <span>→</span></a>`
                : `<span class="doc-link" style="color:var(--c-text-soft);cursor:default;">暂无链接</span>`;
            const summaryLen = (d.summary || '').length;
            const showToggle = summaryLen > 80;
            const sourceType = d.source_type ? `<span class="meta-item">📌 ${{escapeHtml(d.source_type)}}</span>` : '';

            return `
            <article class="doc-card ${{qClass}} ${{hzClass}}" data-id="${{escapeAttr(d.id)}}">
                <div class="doc-card-head">
                    <span class="quality-badge ${{qClass}}">${{escapeHtml(d.quality_level)}}</span>
                    <span class="doc-cat-tag">${{escapeHtml(d.category_icon)}} ${{escapeHtml(d.category_name)}}</span>
                </div>
                <h3 class="doc-title" onclick="toggleSummary(this)">${{escapeHtml(d.title)}}</h3>
                <div class="doc-summary">${{escapeHtml(d.summary)}}</div>
                ${{showToggle ? `<button class="doc-summary-toggle" onclick="toggleSummary(this)">展开摘要 ▾</button>` : ''}}
                ${{keywordsHtml}}
                <div class="doc-meta">
                    <span class="meta-item">📅 ${{escapeHtml(d.publish_date)}}</span>
                    ${{sourceType}}
                    ${{d.geo_scope ? `<span class="geo-tag ${{geoTagClass}}">📍 ${{escapeHtml(d.geo_scope)}}</span>` : ''}}
                    <span class="meta-item">📚 ${{escapeHtml(d.source)}}</span>
                    ${{linkHtml}}
                </div>
            </article>
            `;
        }}).join('');
    }}

    // 更新结果信息
    const total = ALL_DOCS.length;
    const visible = docs.length;
    info.innerHTML = visible === total
        ? `显示全部 <b>${{total}}</b> 篇文档`
        : `匹配 <b>${{visible}}</b> 篇 / 共 <b>${{total}}</b> 篇文档`;
    visibleCount.textContent = `显示 ${{visible}} 篇`;
}}

// HTML 转义工具
function escapeHtml(s) {{
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, ch => ({{
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }}[ch]));
}}
function escapeAttr(s) {{
    return escapeHtml(s);
}}

// ============================================================
// 卡片摘要展开/收起
// ============================================================
function toggleSummary(el) {{
    let card, toggle, summary;
    if (el.classList.contains('doc-title')) {{
        card = el.closest('.doc-card');
        summary = card.querySelector('.doc-summary');
        toggle = card.querySelector('.doc-summary-toggle');
    }} else {{
        toggle = el;
        card = toggle.closest('.doc-card');
        summary = card.querySelector('.doc-summary');
    }}
    if (!summary) return;
    const expanded = summary.classList.toggle('expanded');
    if (toggle) {{
        toggle.textContent = expanded ? '收起摘要 ▴' : '展开摘要 ▾';
    }}
}}

// ============================================================
// 事件绑定
// ============================================================
// 分类 Tab
document.getElementById('catTabs').addEventListener('click', e => {{
    const btn = e.target.closest('.cat-tab');
    if (!btn) return;
    document.querySelectorAll('.cat-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.category = btn.dataset.cat;
    renderDocs();
}});

// 时间段按钮
document.getElementById('timeButtons').addEventListener('click', e => {{
    const btn = e.target.closest('.time-btn');
    if (!btn) return;
    document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.period = btn.dataset.period;
    renderDocs();
}});

// 搜索框（实时防抖）
let searchTimer = null;
document.getElementById('searchInput').addEventListener('input', e => {{
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {{
        state.keyword = e.target.value.trim();
        renderDocs();
    }}, 200);
}});

// 排序
document.getElementById('sortSelect').addEventListener('change', e => {{
    state.sort = e.target.value;
    renderDocs();
}});

// 分类条形图点击 → 联动分类筛选
document.querySelectorAll('.cat-bar-row').forEach(row => {{
    row.addEventListener('click', () => {{
        const cat = row.dataset.cat;
        const tab = document.querySelector(`.cat-tab[data-cat="${{cat}}"]`);
        if (tab) tab.click();
        document.querySelector('.filter-panel').scrollIntoView({{behavior:'smooth', block:'start'}});
    }});
}});

// 回到顶部
const backTop = document.getElementById('backTop');
window.addEventListener('scroll', () => {{
    if (window.scrollY > 400) backTop.classList.add('show');
    else backTop.classList.remove('show');
}});
backTop.addEventListener('click', () => window.scrollTo({{top:0, behavior:'smooth'}}));

// 日期选择器（仅提示，历史数据需重新生成）
document.getElementById('historyDate').addEventListener('change', e => {{
    const val = e.target.value;
    if (val && val !== '{TODAY_STR}') {{
        showToast(`已选择 ${{val}}，历史日报数据需重新生成后查看`);
    }}
}});

// 简易提示
function showToast(msg) {{
    let t = document.getElementById('toast');
    if (!t) {{
        t = document.createElement('div');
        t.id = 'toast';
        t.style.cssText = 'position:fixed;left:50%;bottom:32px;transform:translateX(-50%);background:rgba(12,74,110,.95);color:#fff;padding:12px 22px;border-radius:24px;font-size:14px;z-index:9999;box-shadow:0 6px 20px rgba(0,0,0,.25);opacity:0;transition:opacity .3s;';
        document.body.appendChild(t);
    }}
    t.textContent = msg;
    t.style.opacity = '1';
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.style.opacity = '0', 2800);
}}

// ============================================================
// 初始渲染
// ============================================================
renderDocs();
</script>

</body>
</html>
"""
    return html_doc


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 60)
    print("  水生态环境资讯日报 - HTML报告生成器")
    print("=" * 60)

    # 1. 检查数据库
    if not os.path.exists(DB_PATH):
        print(f"[错误] 数据库文件不存在: {DB_PATH}")
        return 1
    print(f"[1/4] 数据库路径: {DB_PATH}")

    # 2. 读取文档
    docs = load_documents()
    print(f"[2/4] 读取到 {len(docs)} 篇 active 文档")

    if not docs:
        print("[警告] 数据库中没有 active 文档，仍将生成空报告")

    # 3. 生成 HTML
    html_content = build_html(docs)
    print(f"[3/4] HTML 内容生成完成（{len(html_content):,} 字符）")

    # 4. 写入输出文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[4/4] 报告已写入: {OUTPUT_FILE}")

    # 统计摘要
    stats = aggregate(docs)
    print("\n" + "-" * 40)
    print("  生成报告统计摘要")
    print("-" * 40)
    print(f"  总文档数:    {stats['total']}")
    print(f"  近7天新增:   {stats['new_7d']}")
    print(f"  活跃分类:    {stats['active_categories']} / 7")
    print(f"  高质量文献:  {stats['high_quality']}")
    print(f"  中等质量:    {stats['by_quality']['中等']}")
    print(f"  一般质量:    {stats['by_quality']['一般']}")
    print("-" * 40)
    print(f"  生成日期:    {TODAY_DISPLAY}")
    print(f"  输出文件:    {OUTPUT_FILE}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
