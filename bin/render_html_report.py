#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_html_report.py — 把 full-diagnosis.json 渲染成 HTML 报告

读入 full_diagnosis.py 产出的 full-diagnosis.json(含诊断 + 处方章节),
按 references/report-html-template.html 里的样式,生成独立 HTML 文件。

⚠️ 架构陷阱(2026-07-21 教训):
- 整个文件有 2 层 .format(): 内层用 .format() 拼各 section HTML,外层用 .format() 拼最终 HTML 模板
- 如果内层 string 留了 `{0}` `{1}` 占位符没填,会被外层 .format() 触发 IndexError/KeyError 崩
- 防御: 所有内层 string 必须最后调一次 .format() / .replace() 把所有占位符填好再返回
- 推荐: 用下面的 _render() helper 统一用 str.replace (避免 .format() 嵌套)
- 绝对禁止: 留 `template = "...{0}..."` 字面不调 .format()/.replace() 就拼接

输出风格:
- 顶部免责声明(必含)
- 顶部报告卡(病名 + 用户问题)
- 结论卡片(浅绿)
- 5 个关键指标卡(严重程度色块 / 置信度星标 / 候选 / 农技员 / 处方可用)
- 关键视觉特征标签云
- 治疗方案大表格(按候选分类,每行一个方案)
- 现在能做的(列表卡)
- 反馈邀请(5 个 A/B/C/D/E 按钮)

emoji 用量克制:仅保留严重程度色块(🟢🟡🟠) + 候选奖牌(🥇🥈) + 置信度星标(⭐) +
安全警告(⚠️) + 打药时间(⏰) + 复喷(🔁)。其他装饰性 emoji 全部去掉。

用法:
  python render_html_report.py -i full-diagnosis.json -o report.html
  python render_html_report.py full-diagnosis.json > report.html
  python render_html_report.py -i full-diagnosis.json      # 输出到 stdout

兼容:Python 3.5+(避免 f-string)
"""

import argparse
import base64
import json
import mimetypes
import re
import copy
import sys

# Windows GBK 默认不能输出 emoji, 强制 stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass
from pathlib import Path

# P1-40 (2026-07-21 加): 防御层拉齐, 跟 simple/consult 工具共用 _html_shared
from _html_shared import (
    html_escape,                          # wrapper 通过下方的 html_escape 函数代理
    md_inline_to_html,                    # 实际使用 _html_shared 版本 (含 XSS 防护)
    embed_image_as_data_url,              # wrapper 通过下方代理
    check_data_consistency,               # P1-33 入口检查
    check_format_string_leftover,         # P1-18 sanity check (替换本地 re.findall)
    check_markdown_italic_leftover,       # P1-27 sanity check (替换本地 re.finditer)
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_HTML = SKILL_DIR / "references" / "report-html-template.html"


# ===== emoji 减量策略 =====
# 仅保留必要场景:严重程度色块、置信度星标、候选奖牌、安全警告、打药时间、复喷
# 去掉所有装饰性 emoji(段落标题、方案类型、反馈按钮、类别、顶部标签)

SEVERITY_EMOJI = {
    "轻": "🟢 轻",
    "中": "🟡 中",
    "重": "🟠 重",
    "无法判断": "⚪ 无法判断",
}

CONFIDENCE_STARS = {
    "高": "⭐⭐⭐",
    "中": "⭐⭐",
    "低": "⭐",
}


def format_probability(p):
    """把 0-1 浮点数格式化成 'XX.XX%'(用户要求的格式)

    输入: 0.85 → "85.00%"
          None → ""
    """
    if p is None or not isinstance(p, (int, float)):
        return ""
    return "{:.2f}%".format(float(p) * 100)

CANDIDATE_BADGE = {
    1: "🥇 Top 1",
    2: "🥈 Top 2",
    3: "🥉 Top 3",
}

CATEGORY_LABEL = {
    "病害": "病害",
    "虫害": "虫害",
    "缺素": "缺素",
    "药害": "药害",
    "生理障碍": "生理障碍",
}

# CSS 块(从模板里抽出来,实际渲染时直接拼接;保留模板作为完整样例)
CSS_BLOCK = """  :root {
    --bg: #f5f5f3;
    --card: #ffffff;
    --ink: #1f1f1f;
    --ink-soft: #5a5a5a;
    --line: #e8e6e0;
    --green: #4a7c59;
    --green-bg: #e8f1ea;
    --green-border: #b8d4be;
    --amber: #c8821f;
    --amber-bg: #fcf3e3;
    --red: #b94545;
    --red-bg: #f7e4e4;
    --serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
    --sans: -apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  body { font-family: var(--sans); background: var(--bg); color: var(--ink); margin: 0; padding: 32px 16px; line-height: 1.6; font-size: 15px; }
  .wrap { max-width: 920px; margin: 0 auto; }
  .disclaimer { background: #fff7e6; border: 1px solid #f5d491; border-left: 4px solid var(--amber); border-radius: 8px; padding: 14px 18px; font-size: 13.5px; color: #6b4a13; margin-bottom: 18px; }
  .disclaimer strong { color: #8a5a0d; }
  .report-card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 24px 28px; margin-bottom: 18px; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
  .tag { display: inline-block; font-size: 12px; color: var(--green); background: var(--green-bg); padding: 3px 10px; border-radius: 4px; font-weight: 500; margin-bottom: 12px; }
  h1.title { font-family: var(--serif); font-size: 26px; font-weight: 600; margin: 6px 0 12px; color: #2a2a2a; line-height: 1.35; }
  .user-q { font-size: 14.5px; color: var(--ink-soft); margin: 0; }
  .user-q b { color: var(--ink); font-weight: 500; }
  .conclusion { background: var(--green-bg); border: 1px solid var(--green-border); border-left: 4px solid var(--green); border-radius: 8px; padding: 16px 20px; margin-bottom: 28px; font-size: 14.5px; color: #2c3e30; line-height: 1.65; }
  .conclusion strong { color: #1e3a25; }
  .section-title { font-size: 16px; font-weight: 600; margin: 28px 0 12px; color: #2a2a2a; }
  .metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 24px; }
  .metric { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; text-align: left; }
  .metric .lbl { font-size: 12px; color: var(--ink-soft); margin-bottom: 4px; }
  .metric .val { font-size: 22px; font-weight: 600; font-family: var(--serif); color: var(--ink); line-height: 1.2; }
  .metric .sub { font-size: 11.5px; color: var(--ink-soft); margin-top: 6px; line-height: 1.3; }
  .metric.warn .val { color: var(--amber); }
  .metric.danger .val { color: var(--red); }
  .metric.ok .val { color: var(--green); }
  .tags { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 24px; }
  .tag-chip { background: #f4f3ee; color: #4a4a4a; padding: 5px 12px; border-radius: 16px; font-size: 12.5px; border: 1px solid #ece9e1; }
  table.rx { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; font-size: 13.5px; }
  table.rx th { background: #e8f1ea; color: #2c4a35; text-align: left; padding: 11px 14px; font-weight: 500; font-size: 13px; border-bottom: 1px solid var(--green-border); }
  table.rx td { padding: 10px 14px; border-bottom: 1px solid #f0eee8; color: #2a2a2a; vertical-align: top; }
  table.rx tr:last-child td { border-bottom: none; }
  table.rx tr:hover td { background: #fafaf7; }
  .cell-good { color: var(--green); font-weight: 500; }
  .cell-mid { color: var(--amber); font-weight: 500; }
  .cell-bad { color: var(--red); font-weight: 500; }
  .badge-protect, .badge-treat, .badge-mix, .badge-phys { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 12px; white-space: nowrap; width: auto; }
  .badge-protect { background: #e8f1ea; color: #2c4a35; }
  .badge-treat { background: #fcecd6; color: #8a5a0d; }
  .badge-mix { background: #efe1f3; color: #6b2c7c; }
  .badge-phys { background: #e0eaf2; color: #1e3a5c; }
  ol.actions { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 18px 18px 18px 40px; margin: 0 0 24px; }
  ol.actions li { padding: 4px 0; line-height: 1.6; }
  .alert { background: #fff7e6; border: 1px solid #f5d491; border-left: 4px solid var(--amber); border-radius: 8px; padding: 12px 16px; font-size: 13px; color: #6b4a13; margin: 14px 0 0; }
  .alert b { color: #8a5a0d; }
  /* auto-identify 徽章(L2.2: 改 inline style 为 class,便于统一调整) */
  .crop-id-badge { display: inline-block; font-size: 12px; padding: 3px 10px; border-radius: 4px; font-weight: 500; margin-left: 6px; margin-bottom: 12px; }
  .crop-id-badge-auto { color: #3f51b5; background: #e8eaf6; }
  .crop-id-badge-override { color: #e65100; background: #fff3e0; }
  .crop-id-badge-fallback { color: #b94545; background: #fce4e4; }
  .crop-id-badge-script-missing { color: #7a2828; background: #f7e4e4; }
  /* v2.1.1: 矛盾 case 警告框(用户说作物但图片不是) */
  .user-claim-warning { background: #fff3e0; border: 1px solid #f5d491; border-left: 4px solid var(--amber); border-radius: 8px; padding: 12px 16px; font-size: 13.5px; color: #6b4a13; margin-bottom: 18px; }
  .user-claim-warning b { color: #8a5a0d; }
  .user-claim-warning ul { font-size: 13px; }
  /* 用户上传的照片(报告卡里展示) */
  .uploaded-images { margin-top: 14px; }
  .uploaded-images .img-cell { display: inline-block; }
  .uploaded-images .img-cell img { width: 100px; height: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); display: block; }
  .uploaded-images .img-missing { width: 100px; height: 100px; border: 1px dashed var(--line); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; padding: 6px; box-sizing: border-box; }
  .uploaded-images .img-error { font-size: 11px; color: var(--red); text-align: center; line-height: 1.3; }
  /* P1-22 (2026-07-21 修): RAG 库图缩略也用 100x100 + object-fit,跟用户上传图视觉一致 */
  .rag-thumb { width: 100px; height: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); display: block; }
  .feedback { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 12px 0 0; }
  .fb-btn { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px; text-align: center; font-size: 13px; color: var(--ink); cursor: pointer; }
  .footer-note { text-align: center; font-size: 12px; color: var(--ink-soft); margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--line); }
  /* inline code(``code`` → <code>) */
  code { font-family: ui-monospace, "Cascadia Code", Consolas, "Courier New", monospace; font-size: 0.92em; background: #f4f3ee; color: #c2410c; padding: 1px 5px; border-radius: 3px; border: 1px solid #ece9e1; }"""


def parse_diagnosis_section(content):
    """从 prescription.content 里剥出表格行(方案 / 药剂 / 剂量 / 兑水 / 备注)

    跳过:
    - 表头行(cells[0] 是 方案 / 病害 / 方案类型)
    - Markdown 表格分隔行 |---|---|...(整行都是 - : 空格)
    - 全空行 / 无 | 的行
    """
    if not content:
        return []
    rows = []
    # P1-15 (2026-07-21 修): Windows subprocess 返回 \r\n, 直接 split("\n") 留 \r 导致 regex 失败
    # 修法: 先把 \r\n / \r 都规范化成 \n
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    for line in content.split("\n"):
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", line)
        if m:
            cells = [c.strip() for c in m.groups()]
            # 跳表头
            if cells[0] in ("方案", "病害", "方案类型"):
                continue
            # 跳表格分隔行(每个 cell 都是 - 或空)— 例: |---|---|---|...|
            if all(set(c) <= set("-: ") or c == "" for c in cells):
                continue
            rows.append(cells)
    return rows


def parse_prescription_extras(content):
    """从 prescription.content 里提取表格外的辅助信息(复喷节奏 / ⚠️ 警示框等)

    适用: 5 列表格型章节,表格后常带"复喷:..." / "⚠️ 警示" 等非表格文字段
    之前 parse_diagnosis_section 只解析表格,这些"复喷 + 警示"都被丢弃了(P1-26 修)。

    返回: list of (kind, text) — kind 是 "复喷" / "打药时间" / "warning" / "note"
    """
    if not content:
        return []
    items = []
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    for line in content.split("\n"):
        s = line.strip()
        if not s or s.startswith("|") or s.startswith("#") or s.startswith("###"):
            continue
        # ⚠️ 警示
        if s.startswith("⚠") or s.startswith("⚠️"):
            items.append(("warning", s.lstrip("⚠️⚠ ").strip()))
            continue
        # 复喷/打药时间/安全/注意/备注/助剂 等 key: value
        m = re.match(r"^(复喷|打药时间|安全|注意|备注|混配|轮作|采收间隔|停药期)[:：]\s*(.+)$", s)
        if m:
            kind = "复喷" if m.group(1) == "复喷" else ("打药时间" if m.group(1) == "打药时间" else "note")
            items.append((kind, s))
            continue
        # 其它 1-200 字的说明段
        if len(s) > 1 and len(s) < 300 and not s.startswith("**") == False:
            # 普通文字段(不是 ### 标题,不是表格行,不是警示/复喷)
            # 用 md_inline_to_html 在调用方处理 bold/code
            items.append(("note", s))
    return items


def parse_text_list_prescription(content):
    """从 prescription.content 里剥出"无药可治"文字列表(1. 2. 3. 步骤)

    适用: 检疫性病害(猕猴桃溃疡病)/ 系统性病害(玉米丝黑穗病/水稻普通矮缩病)等
    章节,没有 5 列药剂方案,只有 1-N 步骤文字列表。
    返回: list of (kind, text) — kind 是 "head" / "step" / "warn" / "note"
    """
    if not content:
        return []
    items = []
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # 跳 ### 标题
    for line in content.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|---") or s.startswith("|"):
            # 跳标题行 / 分隔行 / 表格行
            continue
        # 数字步骤: "1. **xxx** yyy" 或 "1. xxx"
        m = re.match(r"^(\d+)\.\s+(.+)$", s)
        if m:
            items.append(("step", m.group(2).strip()))
            continue
        # 警示: ⚠️ xxx
        if s.startswith("⚠️") or s.startswith("⚠"):
            items.append(("warn", s.lstrip("⚠️⚠ ").strip()))
            continue
        # 复喷: "复喷:7-10 天一次,连喷 2-3 次。"
        m = re.match(r"^(复喷|打药时间|安全|注意|备注)[:：]\s*(.+)$", s)
        if m:
            items.append(("note", s))
            continue
        # 其他文字段(说明文字, 500 字内)
        if len(s) > 1 and len(s) < 500:
            items.append(("head", s))
    return items


def truncate(s, n):
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + "..."


def embed_image_as_data_url(image_path, max_bytes=4 * 1024 * 1024):
    """detail 特定 wrapper: 默认 4MB (原 detail 报告用, 保留 RAG 缩略大图 + 用户原图)
    P1-37 (2026-07-21 重构): 实现移到 _html_shared.embed_image_as_data_url
    """
    from _html_shared import embed_image_as_data_url as _shared_embed
    return _shared_embed(image_path, max_bytes=max_bytes)


def _render(template, **kwargs):
    """用 str.replace 渲染模板(避免 .format() 嵌套冲突)

    模板里用 __KEY__ 占位符,跟函数 kwargs 配合。
    不要用 .format(),因为外层还有 .format() 模板,内层 .format() 留 {0}{1} 字面会被外层 IndexError。

    用法:
        _render("hello __NAME__", NAME="world")  # -> "hello world"
    """
    result = template
    for k, v in kwargs.items():
        result = result.replace("__" + str(k) + "__", str(v) if v is not None else "")
    return result


def md_inline_to_html(s):
    """P1-37 (2026-07-21 重构): 实现移到 _html_shared.md_inline_to_html
    保留本地函数名为兼容现有调用
    """
    from _html_shared import md_inline_to_html as _shared_md
    return _shared_md(s)


def html_escape(s):
    """P1-37 (2026-07-21 重构): 实现移到 _html_shared.html_escape
    行为升级: 加 `'` -> `&#39;` (跟 simple 工具一致, 防止 attribute XSS)
    """
    from _html_shared import html_escape as _shared_escape
    return _shared_escape(s)


# P1-27 (2026-07-21 加): md_inline_to_html 单元测试 — 防止以后加新 markdown 规则漏掉
# 跑 `python -c "from bin.render_html_report import _test_md_inline; _test_md_inline()"` 验证
_MD_INLINE_TEST_CASES = [
    # (输入, 期望包含, 期望不包含)
    ("**bold**", "<strong>bold</strong>", "**bold**"),
    ("*italic*", "<em>italic</em>", "*italic*"),
    ("`code`", "<code>code</code>", "`code`"),
    ("**bold** and *italic* and `code`", "<strong>bold</strong>", "**bold**"),
    ("complex **bold** with *italic*", "<em>italic</em>", "*italic*"),
    # 学名/病原(P1-27 实际案例)
    ("*Fusarium* 镰刀菌", "<em>Fusarium</em>", "*Fusarium*"),
    ("*Aspergillus* 曲霉", "<em>Aspergillus</em>", "*Aspergillus*"),
    ("*Penicillium* 青霉", "<em>Penicillium</em>", "*Penicillium*"),
    # 粗+斜混合
    ("***both***", "<strong><em>both</em></strong>", "***both***"),
    # 实际处方里的 mixed 用法
    ("**病粒含真菌毒素**(伏马毒素 FB1)", "<strong>病粒含真菌毒素</strong>", "**病粒"),
    ("*Fusarium* 镰刀菌、*Aspergillus* 曲霉", "<em>Fusarium</em>", None),
    # HTML escape
    ("<script>", "&lt;script&gt;", "<script>"),
    # 不该 match 的(单 * 字符)
    ("5*4=20", "5*4=20", None),
]


def _test_md_inline():
    """单元测试:验证 md_inline_to_html 对各种 markdown 语法的渲染"""
    fail = 0
    for input_text, must_contain, must_not_contain in _MD_INLINE_TEST_CASES:
        actual = md_inline_to_html(input_text)
        if must_contain not in actual:
            print(f"  [FAIL] {input_text!r} 期望含 {must_contain!r}, 实际 {actual!r}")
            fail += 1
        if must_not_contain is not None and must_not_contain in actual:
            print(f"  [FAIL] {input_text!r} 不该含 {must_not_contain!r}, 实际 {actual!r}")
            fail += 1
    if fail == 0:
        print("  ✓ md_inline_to_html {0} 个测试用例全过".format(len(_MD_INLINE_TEST_CASES)))
    return fail == 0


def type_to_badge(t):
    t = (t or "").strip()
    if "保护" in t:
        return '<span class="badge-protect">{0}</span>'.format(html_escape(t))
    if "治疗" in t:
        return '<span class="badge-treat">{0}</span>'.format(html_escape(t))
    if "复配" in t or "复" in t:
        return '<span class="badge-mix">{0}</span>'.format(html_escape(t))
    if "物理" in t or "种子" in t or "灌根" in t:
        return '<span class="badge-phys">{0}</span>'.format(html_escape(t))
    return '<span class="badge-treat">{0}</span>'.format(html_escape(t))


def render_full_diagnosis(data):
    """把 full-diagnosis.json 渲染成完整 HTML

    P0-compat (2026-07-20): 自动适配 RAG 流程 schema (data.diagnose)
    - 标准 schema: data.diagnosis.diagnosis[0]
    - RAG schema:    data.diagnose.diagnosis[0]
    两者结构相同, 仅外层键名不同
    """
    # P0-compat: schema normalize (不破坏原 dict, 深拷贝防 metadata 共享引用污染)
    if "diagnose" in data and "diagnosis" not in data:
        data = copy.deepcopy(data)
        data["diagnosis"] = data.pop("diagnose")
        if "inputs" in data and isinstance(data["inputs"], dict) and "image_paths" in data["inputs"]:
            data.setdefault("metadata", {})
            data["metadata"]["images"] = data["inputs"]["image_paths"]
            data["metadata"]["image_count"] = len(data["inputs"]["image_paths"])
    diag = data.get("diagnosis", {})
    diagnosis_list = diag.get("diagnosis", [])
    severity = diag.get("severity", "无法判断")
    cause = diag.get("cause_summary", "")
    immediate = diag.get("immediate_actions", [])
    need_expert = diag.get("need_expert", False)
    expert_reason = diag.get("expert_reason", "")
    uncertainty = diag.get("uncertainty_reason", "")

    top = diagnosis_list[0] if diagnosis_list else {}
    top_name = top.get("name", "?")
    top_category = top.get("category", "病害")
    top_pathogen = top.get("pathogen", "?")
    top_confidence = top.get("confidence", "?")
    top_probability = top.get("probability")  # 0-1 浮点数
    top_reasoning = top.get("reasoning", "")  # P1-13 (2026-07-21 加): LLM 决策推理

    # P1-33 (2026-07-21 加): 数据一致性 sanity check
    # 防御: 防止 prescription 状态自相矛盾, 导致 HTML 渲染出"无意义答案"或"空 table"
    # 之前 P1-32 根因之一: rx_rows 和 rx_text_list_html 同时不为空 → 表格型+文字列表型都渲染
    # 之前 P1-31 根因: rx_avail=True 但 rx_rows=[] → 显示空 table(0 种方案)
    # 修法: 在 render 入口检查, 状态冲突直接 raise 或 warning
    # 规则:
    # 1. rx_avail=True 必须有 rx_content (不能空 content 假装有处方)
    # 2. rx_avail=False 时 rx_rows 和 rx_text_list_html 必须都空 (不能矛盾)
    # 3. rx_rows 和 rx_text_list_html 不能同时非空 (互斥)
    # 4. immediate_actions 不是 list 时 → [] (类型防御)
    rx = data.get("prescription", {}) or {}
    rx_avail_check = rx.get("available", False)
    rx_content_check = rx.get("content", "") or ""
    if rx_avail_check and not rx_content_check.strip():
        # 严重: 标记 available=True 但 content 为空
        # 这会导致 HTML 显示 "0 种方案" 空表 (P1-31 的根因)
        print(
            "[P1-33 warn] prescription.available=True 但 content 为空 — "
            "应改为 available=False 或补详细处方章节。诊断: {0}".format(top_name),
            file=sys.stderr,
        )
    # 类型防御: immediate_actions 必须是 list
    if not isinstance(immediate, list):
        print(
            "[P1-33 warn] immediate_actions 类型错误 ({0}), 应为 list, 强制转 []".format(
                type(immediate).__name__),
            file=sys.stderr,
        )
        immediate = []

    # LLM 决策推理(给 HTML 用户看"为什么选这个病")
    reasoning_html = ""
    if top_reasoning:
        reasoning_html = (
            '\n  <div class="section-title">LLM 决策推理</div>\n'
            '  <div class="reasoning-box" style="background: var(--card); border-left: 3px solid var(--green); padding: 12px 16px; margin: 0 0 16px 0; font-size: 13.5px; color: #2a2a2a; line-height: 1.7;">\n'
            '    {0}\n'
            '  </div>\n'
        ).format(md_inline_to_html(top_reasoning))

    rx = data.get("prescription", {})
    rx_avail = rx.get("available", False)
    rx_content = rx.get("content", "")

    metadata = data.get("metadata", {})
    crop = metadata.get("crop", "?")
    image_count = metadata.get("image_count", 1)

    # auto-identify 信息(可选)— 用于在报告卡显示识别来源
    crop_id_result = data.get("crop_id_result")
    crop_id_method = data.get("crop_id_method") or metadata.get("crop_id_method", "manual")

    # auto-identify 徽章(L2.1: 去 🤖 emoji,贯彻克制原则;L2.2: 用 CSS class 而非 inline style)
    crop_id_badge = ""
    if crop_id_method != "manual" and (crop_id_result or crop_id_method == "script_missing"):
        # 即使 crop_id_result 为空(如 script_missing),也显示徽章说明原因
        primary = (crop_id_result or {}).get("primary_crop") or {}
        id_name = primary.get("name_zh", "?")
        id_prob = format_probability(primary.get("probability"))
        id_conf = primary.get("confidence", "?")
        if crop_id_method == "auto":
            crop_id_badge = (
                '<span class="crop-id-badge crop-id-badge-auto">'
                'AI 识别: {0} · {1} · {2}</span>'
            ).format(html_escape(id_name), html_escape(id_conf), html_escape(id_prob or "—"))
        elif crop_id_method == "overridden":
            crop_id_badge = (
                '<span class="crop-id-badge crop-id-badge-override">'
                '⚠️ AI 识别为 {0} ({1}),手动指定为 {2}</span>'
            ).format(html_escape(id_name), html_escape(id_prob or "—"), html_escape(crop or "?"))
        elif crop_id_method == "fallback":
            crop_id_badge = (
                '<span class="crop-id-badge crop-id-badge-fallback">'
                '⚠️ AI 识别失败/非作物,按 crop={0} 诊断</span>'
            ).format(html_escape(crop or "null"))
        elif crop_id_method == "script_missing":
            # L1.1: 区分"脚本找不到" vs "识别失败"
            crop_id_badge = (
                '<span class="crop-id-badge crop-id-badge-script-missing">'
                '⚠️ AI 识别脚本不可用(未安装),按 crop={0} 诊断</span>'
            ).format(html_escape(crop or "null"))

    # v2.1.1 矛盾 case 警告(L4:用户口述是作物但图片不是)
    # 不管 crop_id_method 是什么,只要 user_claim_mismatch=true 就显示
    user_claim_warning = ""
    if crop_id_result and crop_id_result.get("user_claim_mismatch"):
        user_claim = (crop_id_result.get("user_claim") or "").strip()
        content_desc = crop_id_result.get("content_description") or "图片不是作物"
        uncertainty = crop_id_result.get("uncertainty_reason") or ""
        user_claim_warning = (
            '\n  <div class="user-claim-warning">\n'
            '    <b>⚠️ 提示:图片与您说的作物不一致</b><br>\n'
            '    您说的是 <b>{0}</b>,但 AI 看图识别为 <i>{1}</i>。<br>\n'
            '    可能原因:<br>\n'
            '    <ul style="margin: 6px 0 0 0; padding-left: 20px;">\n'
            '      <li>图片传错了(请重新上传 {0} 照片)</li>\n'
            '      <li>您打错字了(请确认是哪种作物)</li>\n'
            '      <li>我们识别有误(可以反馈给我们)</li>\n'
            '    </ul>\n'
            '    这次无法做病害诊断,等您重传后再继续。\n'
            '  </div>\n'
        ).format(
            html_escape(user_claim or "(未指定)"),
            html_escape(content_desc),
        )
        if uncertainty:
            user_claim_warning = user_claim_warning.replace(
                '\n  <div class="user-claim-warning">\n',
                '\n  <div class="user-claim-warning">\n    <span style="font-size:12px; color:var(--ink-soft);">原因:{0}</span><br>\n'.format(html_escape(uncertainty))
            )

    severity_disp = SEVERITY_EMOJI.get(severity, severity)
    confidence_disp = CONFIDENCE_STARS.get(top_confidence, top_confidence)
    probability_disp = format_probability(top_probability)  # "85.00%"

    rx_rows = parse_diagnosis_section(rx_content)
    visual_clues = top.get("key_visual_clues", [])

    # 顶部标题
    title = "{0} — 作物病害诊断与处置方案".format(top_name)

    # 结论
    cat_label = CATEGORY_LABEL.get(top_category, top_category)
    if need_expert:
        verdict = "<strong>需要联系农技员</strong>"
    else:
        verdict = "<strong>先按方案处理</strong>,扩散或并发再找农技员"
    conclusion_html = (
        "<strong>结论:</strong>{0}({1},{2} 置信度,<strong>{3}</strong>)。"
        "{4}{5}{6}"
    ).format(
        md_inline_to_html(top_name),
        md_inline_to_html(cat_label),
        md_inline_to_html(top_confidence),
        html_escape(probability_disp or "—"),
        md_inline_to_html(truncate(cause, 200)) if cause else "",
        verdict,
        "<br><em>原因:</em>" + md_inline_to_html(truncate(expert_reason, 200)) if expert_reason else "",
    )

    # P1-32 (2026-07-21 改): 处方表格行 — Top 1 概览行拆出 rx_rows_html
    # 之前: Top 1 概览(病名+病原+概率+方案数)是 table 第一行, rowspan 跨 5 列
    # 问题: 跟真正的药剂方案行混在一起, 视觉上以为是表头, 实际是 metadata
    # 用户原话: "此处将病放在治疗方案表格上面" → 应该是 table 上方的 header, 不是 table 里的第一行
    # 修法: Top 1 概览拆成 rx_top1_header_html, 渲染在 <table> 之前
    #       rx_rows_html 只放真正的药剂方案行
    rx_rows_html = []
    rx_top1_header_html = _render(
        '<div class="rx-top1-header" style="background: #f8fbf9; border: 1px solid var(--line); border-bottom: none; border-radius: 8px 8px 0 0; padding: 10px 14px; margin: 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">\n'
        '  <span style="background: var(--green-bg); color: var(--green); padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 600;">__BADGE__</span>\n'
        '  <span style="color: var(--ink-soft); font-size: 12px;">最可能</span>\n'
        '  <b style="font-size: 15px;">__NAME__</b>\n'
        '  <span style="color: var(--ink-soft); font-size: 13px;">· __PATHOGEN__</span>\n'
        '  <span style="color: var(--green); font-size: 13px; font-weight: 600;">· __PROB__</span>\n'
        '  <span style="color: var(--ink-soft); font-size: 13px;">· __COUNT__ 种方案</span>\n'
        '</div>\n',
        BADGE=html_escape(CANDIDATE_BADGE.get(1, "Top 1")),
        NAME=html_escape(top_name),
        PATHOGEN=html_escape(top_pathogen or "?"),
        PROB=html_escape(probability_disp or "—"),
        COUNT=len(rx_rows),
    )
    for i, row in enumerate(rx_rows, 1):
        if len(row) < 5:
            continue
        plan_type, drug, dose, water, note = row[0], row[1], row[2], row[3], row[4]
        # 用 md_inline_to_html 解析 ** 和 ` (L2.3: note 列也支持 inline markdown)
        note_html = md_inline_to_html(note)
        if "特效" in note or "首选" in note:
            note = '<span class="cell-good">{0}</span>'.format(note_html)
        elif "慎用" in note or "禁用" in note or "药害" in note:
            note = '<span class="cell-mid">{0}</span>'.format(note_html)
        else:
            note = note_html
        rx_rows_html.append(
            "      <tr>\n"
            "        <td>方案 {0}</td>\n"
            "        <td>{1}</td>\n"
            "        <td>{2}</td>\n"
            "        <td>{3}</td>\n"
            "        <td>{4}</td>\n"
            "        <td>{5}</td>\n"
            "      </tr>".format(i, type_to_badge(plan_type),
                                  html_escape(drug),
                                  html_escape(dose),
                                  html_escape(water),
                                  note)
        )
    rx_table = "\n".join(rx_rows_html)

    # P1-19 (2026-07-21 修):"无药可治"文字列表 fallback
    # 之前 parse_diagnosis_section 只解析 5 列表格,如果章节是文字列表(系统性病害/检疫性病害),
    # rx_rows 是空 → HTML 处方段显示"0 种方案"+ 空表
    # 修法: 如果 rx_rows 空但 prescription.content 有文字步骤,渲染成 ol 列表
    # P1-21 (2026-07-21 修):<ol> 给所有 <li> 编号(就算 list-style:none 也算序号),
    #   所以把 warn/note/head 拆出 <ol> 外,只用 <ol> 装 step,编号才从 1 开始
    rx_text_list_html = ""
    if not rx_rows and rx_avail and rx_content:
        text_items = parse_text_list_prescription(rx_content)
        if text_items:
            step_items = []  # 步骤,放在 <ol> 里(自动编号 1-N)
            extra_items = []  # 警示/说明/复喷等,放在 <ol> 外(不参与编号)
            for kind, text in text_items:
                if kind == "step":
                    step_items.append(
                        "    <li style=\"margin-bottom:8px;\">{0}</li>".format(
                            md_inline_to_html(text)))
                elif kind == "warn":
                    extra_items.append(
                        '<div style="background:#fff7e6; border-left:3px solid #f5a623; padding:8px 12px; margin:10px 0;">⚠️ {0}</div>'.format(
                            md_inline_to_html(text)))
                elif kind == "note":
                    extra_items.append(
                        '<div style="background:#f5f9f6; padding:6px 10px; margin:6px 0; font-size:13.5px;">{0}</div>'.format(
                            md_inline_to_html(text)))
                else:  # head
                    extra_items.append(
                        '<div style="background:#f0f4ed; padding:6px 10px; margin:6px 0; font-size:13px; color:#3a3a3a;">{0}</div>'.format(
                            md_inline_to_html(text)))
            ol_html = ""
            if step_items:
                ol_html = (
                    '\n  <ol class="actions" style="list-style: decimal inside; padding-left:0; margin: 12px 0 12px 0;">\n'
                    + "\n".join(step_items) +
                    '\n  </ol>\n'
                )
            # extra_items 放在 ol 之后(不参与编号)
            extras_html = "\n".join(extra_items)
            rx_text_list_html = ol_html + extras_html

    # P1-26 (2026-07-21 加): 表格型处方的"复喷 + ⚠️ 警示"额外信息
    # 之前 parse_diagnosis_section 只解析表格,复喷节奏和警示框被丢,现在补上
    rx_extras_html = ""
    if rx_rows and rx_avail and rx_content:
        extras = parse_prescription_extras(rx_content)
        if extras:
            extras_html_items = []
            for kind, text in extras:
                if kind == "warning":
                    extras_html_items.append(
                        '<div style="background:#fff7e6; border-left:3px solid #f5a623; padding:8px 12px; margin:8px 0;">⚠️ {0}</div>'.format(
                            md_inline_to_html(text)))
                elif kind == "复喷":
                    extras_html_items.append(
                        '<div style="background:#f5f9f6; padding:6px 10px; margin:6px 0; font-size:13.5px;">🔁 {0}</div>'.format(
                            md_inline_to_html(text)))
                elif kind == "打药时间":
                    extras_html_items.append(
                        '<div style="background:#f5f9f6; padding:6px 10px; margin:6px 0; font-size:13.5px;">⏰ {0}</div>'.format(
                            md_inline_to_html(text)))
                else:
                    extras_html_items.append(
                        '<div style="background:#f0f4ed; padding:6px 10px; margin:6px 0; font-size:13px; color:#3a3a3a;">{0}</div>'.format(
                            md_inline_to_html(text)))
            rx_extras_html = "\n".join(extras_html_items)

    # 视觉标签
    tags_html = "\n      ".join(
        '<span class="tag-chip">{0}</span>'.format(md_inline_to_html(c))
        for c in visual_clues
    )

    # 现在能做的(P1-28 加,P1-29 改): fallback 不再"没意义"
    # P1-29 改进: fallback 优先级 — prescription 有方案 → 提具体打药;没方案才说"补拍"
    # 不再给"自相矛盾"的通用建议(有方案却说"不要打药")
    actions_fallback = []
    if not immediate:
        top_cat = top.get("category", "病害")
        # P1-29: 第一优先级 — 处方有方案时, 直接列处方方案作为"现在能做的"
        if rx_avail and rx_rows:
            # 已有药剂方案(表格), 把前 1-2 个方案提出来
            for i, row in enumerate(rx_rows[:2], 1):
                if len(row) >= 4:
                    plan_type, drug, dose, water = row[0], row[1], row[2], row[3]
                    note = row[4] if len(row) >= 5 else ""
                    actions_fallback.append(
                        '<strong>今晚就喷:</strong> ' + html_escape(plan_type) +
                        '药剂 ' + html_escape(drug) +
                        ' 剂量 ' + html_escape(dose) +
                        ' 兑水 ' + html_escape(water) +
                        (' (' + html_escape(note) + ')' if note else '')
                    )
            actions_fallback.append(
                '<strong>打药时间:</strong> 下午 4 点后,避开中午高温和大风'
            )
            actions_fallback.append(
                '<strong>复喷节奏:</strong> 7-10 天一次,连喷 2-3 次,与不同机制药剂交替用防抗药性'
            )
            actions_fallback.append(
                '<strong>配药防护:</strong> 戴口罩/手套,按药剂标签稀释,二次稀释法配药'
            )
        else:
            # P1-29 v2 (2026-07-21 改): 处方没方案时的兜底 — 收敛到"写无"
            # 之前 v1 还会输出"补图重跑" / "摘除病叶" / "严重先控后治" 等通用建议
            # 用户反馈"治疗方案或现在能做的输出这种没意义答案,就写无"
            # 收敛原则:
            # - need_expert=True → 保留 1 条"先联系农技员"(有诊断价值,让用户知道这不是自己能解决的)
            # - 其它全不要,直接"无"(避免"补图重跑"这种空话和"摘除病叶"这种常识)
            # 注意: 虫害/病害/严重/中等/轻症所有分支都不再生成 — 没有 prescription 就没具体可执行的方案
            if need_expert:
                actions_fallback.append(
                    '<strong>先联系农技员</strong>(理由:' + html_escape(expert_reason) + ')。不要凭感觉自行用药,法律上无药可治类病害(检疫/病毒等)擅自处理可能违法。'
                )
    # 渲染(P1-30 v2 2026-07-21 改): fallback_note 完全脱离 actions_html
    # v1 错误: 把 <div> 直接 concat 到 actions_html 字符串前面, HTML5 解析可能把 div 放进 ol
    # v2 修法: fallback_note 独立渲染为 ol 之前的 sibling div, 永远不参与 ol 计数
    # 保险: 1) ol 强制 start=1   2) fallback_note 挪到 ol 之前
    fallback_note_html = ""
    if actions_fallback and not immediate:
        # P1-29 v2 fallback 触发时, 显示一句说明, 让人知道这 5 条不是 AI 直接给的具体行动
        fallback_note_html = '<div style="background:#fff3e0; border-left:3px solid #f5a623; padding:6px 10px; margin: 0 0 10px 0; font-size:13px;">AI 未给出具体行动,以下为基于诊断+处方自动生成的建议:</div>'
    if immediate:
        actions_html = "\n".join("    <li>{0}</li>".format(md_inline_to_html(a)) for a in immediate)
    elif actions_fallback:
        actions_html = "\n".join("    <li>{0}</li>".format(a) for a in actions_fallback)
    else:
        # 没 immediate 也没 fallback — 直接"无", 不要 fallback_note
        actions_html = "    <li>无</li>"

    # 反馈(无 emoji)
    feedback_html = (
        '    <div class="fb-btn"><b>A</b><br>解决了</div>\n'
        '    <div class="fb-btn"><b>B</b><br>改善一些</div>\n'
        '    <div class="fb-btn"><b>C</b><br>没变化</div>\n'
        '    <div class="fb-btn"><b>D</b><br>恶化了</div>\n'
        '    <div class="fb-btn"><b>E</b><br>还没处理</div>'
    )

    # 不确定补充
    uncertain_html = ""
    if top_confidence == "低" or severity == "无法判断" or uncertainty:
        uncertain_html = (
            '\n  <div class="section-title">不确定补充</div>\n'
            '  <p style="color: var(--ink-soft); font-size: 13.5px; margin: 0;">{0}</p>\n'.format(
                md_inline_to_html(truncate(uncertainty or "诊断置信度较低,建议补一张清晰特写", 300))
            )
        )

    # RAG 检索结果(本地图库 top-K 相似,展示给用户看"为什么 LLM 选这个病")
    # 2026-07-21 加:之前 HTML 不渲染 rag_references,只渲染了 LLM 决策,用户看不到依据
    # P1-14 修 (2026-07-21):用 _render() helper 避免 .format() 嵌套冲突
    # P1-17 修 (2026-07-21):缩略图 200KB 限,避免 5 张图把 HTML 撑到 5MB+
    rag_references = data.get("rag_references", []) or []
    rag_section_html = ""
    if rag_references:
        rag_rows = []
        for ref in rag_references[:5]:
            rank = ref.get("rank", "?")
            score = ref.get("score", 0)
            crop = ref.get("crop", "?")
            disease = ref.get("disease", "?")
            desc = ref.get("description", "")
            path = ref.get("path", "")
            # 缩略图(库图 200KB 限)
            thumb_html = ""
            if path and Path(path).exists():
                data_url, _ = embed_image_as_data_url(path, max_bytes=200 * 1024)
                if data_url:
                    thumb_html = _render(
                        '<img src="__URL__" class="rag-thumb" alt="库图 rank __RANK__" />',
                        URL=data_url, RANK=rank)
            # 评分色块
            if score >= 0.5:
                score_color = "var(--green)"
                score_bg = "var(--green-bg)"
            elif score >= 0.3:
                score_color = "#a96b1a"
                score_bg = "#fff3e0"
            else:
                score_color = "var(--ink-soft)"
                score_bg = "var(--line)"
            rag_rows.append(_render(
                "      <tr>\n"
                "        <td><b>#__RANK__</b></td>\n"
                "        <td>__THUMB__</td>\n"
                "        <td><b>[__CROP__ / __DISEASE__]</b><br><span style=\"color: var(--ink-soft); font-size: 12px;\">__DESC__</span></td>\n"
                "        <td><span style=\"display:inline-block; padding: 2px 8px; background: __SCORE_BG__; color: __SCORE_COLOR__; border-radius: 6px; font-weight: 600;\">__SCORE__</span></td>\n"
                "      </tr>",
                RANK=rank,
                THUMB=thumb_html,
                CROP=html_escape(crop),
                DISEASE=html_escape(disease),
                DESC=html_escape(truncate(desc, 120)),
                SCORE_BG=score_bg,
                SCORE_COLOR=score_color,
                SCORE="{:.3f}".format(score),
            ))
        K = len(rag_references[:5])
        rag_section_html = _render(
            '\n  <div class="section-title">RAG 检索结果(本地图库 top-__K__ 相似)</div>\n'
            '  <p class="hint" style="color: var(--ink-soft); font-size: 13px; margin: 0 0 12px 0;">'
            '系统从本地图库 <code>D:\\作物病害图\\</code> 找到最相似的 __K__ 张历史图,'
            '作为 LLM 决策的"参考依据"。分数越高,描述越接近用户照片。</p>\n'
            '  <table class="rx rag-table">\n'
            '    <thead>\n'
            '      <tr>\n'
            '        <th style="width: 6%">排名</th>\n'
            '        <th style="width: 22%">库图缩略</th>\n'
            '        <th style="width: 60%">作物 / 病害 + GLM-4V 描述</th>\n'
            '        <th style="width: 12%">相似度</th>\n'
            '      </tr>\n'
            '    </thead>\n'
            '    <tbody>\n'
            '__ROWS__'
            '\n    </tbody>\n'
            '  </table>\n',
            K=K,
            ROWS="\n".join(rag_rows),
        )

    # 候选概率分布(在处方表格之前展示所有候选的概率,直观对比)
    candidate_prob_html = ""
    if len(diagnosis_list) >= 1:
        cand_rows = []
        for i, d in enumerate(diagnosis_list[:5], 1):
            p = format_probability(d.get("probability"))
            conf = d.get("confidence", "?")
            badge = CANDIDATE_BADGE.get(i, "Top {0}".format(i))
            cand_rows.append(
                "      <tr>\n"
                "        <td>{0}</td>\n"
                "        <td><b>{1}</b></td>\n"
                "        <td><span style=\"font-family: var(--serif); font-size: 17px; font-weight: 600;\">{2}</span></td>\n"
                "        <td>{3}</td>\n"
                "      </tr>".format(
                    badge,
                    html_escape(d.get("name", "?")),
                    html_escape(p or "—"),
                    CONFIDENCE_STARS.get(conf, conf),
                )
            )
        candidate_prob_html = (
            '\n  <div class="section-title">候选概率分布</div>\n'
            '  <table class="rx">\n'
            '    <thead>\n'
            '      <tr>\n'
            '        <th style="width: 15%">候选</th>\n'
            '        <th style="width: 50%">诊断名</th>\n'
            '        <th style="width: 20%">概率</th>\n'
            '        <th style="width: 15%">置信度</th>\n'
            '      </tr>\n'
            '    </thead>\n'
            '    <tbody>\n'
            + "\n".join(cand_rows) +
            '\n    </tbody>\n'
            '  </table>\n'
            '  <div class="alert">\n'
            '    <b>概率计算方法:</b>采用「LLM 视觉自评 + 候选间 softmax 归一化」双步骤。<br>\n'
            '    ① LLM 基于图像特征 + 上下文(作物/天气/部位)给出每个候选的原始分。<br>\n'
            '    ② 所有候选做 softmax 归一化(总和 = 100%),让 Top 1 更突出、Top 2/3 比例合理。<br>\n'
            '    ③ 如 LLM 未给具体数字,按 confidence 映射默认值(高 85% / 中 65% / 低 35%)再归一化。<br>\n'
            '    注:LLM 自评是主观打分(非严格数学计算),供参考,实际处理请结合实物和农资店判断。\n'
            '  </div>\n'
        )

    # 模板里 user-q 用的是问句模板,这里简化成上下文摘要
    user_q = (
        "<b>作物:</b>{0} · <b>图片:</b>{1} 张\n"
        "    <br><b>上下文摘要:</b>见 full-diagnosis.json metadata".format(
            md_inline_to_html(crop), image_count
        )
    )

    # 嵌入用户上传的照片(report-card 里展示)
    image_paths = metadata.get("images", [])
    images_html = ""
    if image_paths:
        img_blocks = []
        for img_path in image_paths:
            data_url, err = embed_image_as_data_url(img_path)
            if data_url:
                img_blocks.append(
                    '<div class="img-cell"><img src="{0}" alt="{1}" /></div>'.format(
                        data_url,
                        html_escape(Path(img_path).name)
                    )
                )
            else:
                img_blocks.append(
                    '<div class="img-cell"><div class="img-missing"><div class="img-error">⚠️ {0}</div></div></div>'.format(
                        html_escape(err or "未知错误")
                    )
                )
        images_html = (
            '\n    <div class="uploaded-images">\n      {0}\n    </div>'.format(
                "\n      ".join(img_blocks)
            )
        )

    # 单图提醒(图片覆盖度不够时,提醒用户补图)
    coverage_warning_html = ""
    if image_count == 1:
        coverage_warning_html = (
            '\n  <div class="alert" style="background:#fce4e4; border-color:#e0a8a8; border-left-color:#b94545; color:#7a2828; margin-bottom:18px;">\n'
            '    <b>📷 单图诊断提醒</b><br>\n'
            '    本结果<b>仅基于 1 张照片</b>,诊断稳定性有局限。<b>建议补拍 1-2 张</b>:\n'
            '    <ul style="margin: 6px 0 0 0; padding-left: 24px;">\n'
            '      <li>受害部位<b>特写</b>(已有请忽略)</li>\n'
            '      <li>受害部位<b>另一面/背面</b>(很多病斑、虫卵在叶背)</li>\n'
            '      <li><b>整体株形</b>(看分布范围 + 蔓延方向)</li>\n'
            '    </ul>\n'
            '    多图综合判断准确度通常<b>显著高于单图</b>。补图后免费重跑,不收费。\n'
            '  </div>\n'
        )
    elif image_count >= 2:
        coverage_warning_html = (
            '\n  <div class="alert" style="background:#e8f1ea; border-color:#b8d4be; border-left-color:#4a7c59; color:#2c4a35; margin-bottom:18px;">\n'
            '    <b>✓ 多图综合判断</b>:本结果基于 {0} 张图综合得出,稳定性高于单图诊断。\n'
            '  </div>\n'.format(image_count)
        )

    # severity sub
    sev_sub_map = {
        "轻": "轻微观察,先处理即可",
        "中": "若不处理可能蔓延更多叶果",
        "重": "需立即处置,建议联系农技员",
        "无法判断": "暂时判断不了,建议补图",
    }
    sev_sub = sev_sub_map.get(severity, "—")

    # confidence sub — 现在 lbl 改成了"Top 1 概率",val 显示具体百分比
    # sub 改为显示置信度星标 + 视觉特征匹配数
    conf_sub = "{0} · 视觉特征匹配 {1} 个".format(
        CONFIDENCE_STARS.get(top_confidence, top_confidence),
        len(visual_clues)
    )

    need_expert_disp = "是" if need_expert else "否"
    need_expert_sub = truncate(expert_reason, 60) if expert_reason else "先按方案处理 3 天观察"

    rx_avail_disp = "是" if rx_avail else "否"

    # 处方子表
    if rx_avail and rx_rows:
        rx_summary = "{0} 种药剂方案".format(len(rx_rows))
    elif rx_avail and rx_text_list_html:
        # P1-19 (2026-07-21 修): "无药可治" 文字列表 fallback 时显示通用处置
        rx_summary = "无药可治 — 文字列表处置"
    else:
        rx_summary = "暂未匹配到详细处方 — 按通用处置建议执行"

    # P1-20 (2026-07-21 修):"无药可治" 章节不要显示"复喷 7-10 天一次"模板
    # P1-24 (2026-07-21 修): prescription.available=False 时也不要显示打药/复喷(没药可用)
    if rx_text_list_html or not rx_avail:
        rx_spray_tip = (
            '    <b>⚠️ 安全提醒:</b>以上方案仅供参考,实际使用请阅读药剂标签、咨询当地农资店、联系当地农技员\n'
        )
    else:
        rx_spray_tip = (
            '    <b>⏰ 打药时间:</b>下午 4 点后,避开中午高温<br>\n'
            '    <b>🔁 复喷:</b>7-10 天一次,连喷 2-3 次,与不同机制药剂交替用防抗药性<br>\n'
            '    <b>⚠️ 安全提醒:</b>以上方案仅供参考,实际使用请阅读药剂标签、咨询当地农资店、联系当地农技员\n'
        )

    # P1-31 (2026-07-21 加):"治疗方案" section 整体收敛
    # 之前无 prescription 时只显示 Top 1 一行空表(0 种方案, 全部 ? ) — 没意义
    # 用户原话:"治疗方案或者现在能做的要是输出这种没意义答案,就写无"
    # 收敛规则:
    # - 有 prescription 方案 (rx_rows 或 rx_text_list_html) → 渲染完整 table + extras + spray_tip
    # - 无 prescription 方案 → 整段替换为"无"提示, 不显示空表
    # P1-33 v2 (2026-07-21 加): 数据一致性检查 — 防止 rx_rows 和 rx_text_list_html 同时非空
    if rx_rows and rx_text_list_html:
        # 严重矛盾: 同一份 prescription 同时有表格行和文字步骤
        # 之前 P1-32 根因之一, 文字列表 case 还会显示空 table
        # 修法: 选一个 (表格型优先, 文字列表 fallback)
        print(
            "[P1-33 warn] rx_rows 和 rx_text_list_html 同时非空 (len={0}/{1}), "
            "prescription 内容可能混了表格+文字两种格式 — 表格型优先, 文字列表丢弃。"
            "诊断: {2}".format(len(rx_rows), len(rx_text_list_html), top_name),
            file=sys.stderr,
        )
    if rx_avail and (rx_rows or rx_text_list_html):
        # P1-32 v2 (2026-07-21 改): rx_rows(表格型) 和 rx_text_list_html(文字列表型) 互斥渲染
        # 之前: 两者都触发, 文字列表 case 还会显示空 table (0 种方案 + 空 tbody)
        # 修法: 表格型 (rx_rows) → 渲染完整 table, 文字列表型 (rx_text_list_html) → 不渲染空 table
        if rx_rows:
            rx_section = _render(
                '\n  <div class="section-title">治疗方案(按候选分类)</div>\n'
                '__RX_TOP1_HEADER__'
                '  <table class="rx" style="border-radius: 0 0 8px 8px; border-top: none;">\n'
                '    <thead>\n'
                '      <tr>\n'
                '        <th style="width: 12%">方案</th>\n'
                '        <th style="width: 14%">类型</th>\n'
                '        <th style="width: 32%">药剂</th>\n'
                '        <th style="width: 12%">剂量(每亩)</th>\n'
                '        <th style="width: 10%">兑水</th>\n'
                '        <th style="width: 20%">备注</th>\n'
                '      </tr>\n'
                '    </thead>\n'
                '    <tbody>\n'
                '__RX_TABLE__\n'
                '    </tbody>\n'
                '  </table>\n'
                '__RX_EXTRAS_HTML__'
                '__RX_TEXT_LIST_HTML__'
                '  <div class="alert">\n'
                '__RX_SPRAY_TIP__'
                '  </div>\n',
                RX_TOP1_HEADER=rx_top1_header_html,
                RX_TABLE=rx_table,
                RX_EXTRAS_HTML=rx_extras_html,
                RX_TEXT_LIST_HTML=rx_text_list_html,
                RX_SPRAY_TIP=rx_spray_tip,
            )
        else:
            # 文字列表型: 不要空 table, 只显示 top1_header + 文字步骤 + 警示 + 安全提醒
            rx_section = _render(
                '\n  <div class="section-title">治疗方案(按候选分类)</div>\n'
                '__RX_TOP1_HEADER__'
                '__RX_TEXT_LIST_HTML__'
                '  <div class="alert">\n'
                '__RX_SPRAY_TIP__'
                '  </div>\n',
                RX_TOP1_HEADER=rx_top1_header_html,
                RX_TEXT_LIST_HTML=rx_text_list_html,
                RX_SPRAY_TIP=rx_spray_tip,
            )
    else:
        # P1-31: 无 prescription 方案时, 整段写"无" — 不显示空表
        # 注意: need_expert 已经在"现在能做的"里显示了"先联系农技员", 这里不重复
        rx_section = _render(
            '\n  <div class="section-title">治疗方案(按候选分类)</div>\n'
            '  <div style="background:#f5f5f3; border-left: 3px solid #c5c5b8; padding: 12px 16px; color: #5a5a5a; font-size: 14px; margin: 0 0 16px 0;">无</div>\n',
        )

    # 拼 HTML
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<div class="wrap">

  <div class="disclaimer">
    <strong>⚠️ 免责声明:</strong>本报告由 AI 辅助诊断生成,仅作技术参考。<b>严禁仅凭本报告用药或处置</b>。实际用药请严格遵守:① <b>当地农资店</b>的库存与建议、② <b>当地农技员</b>的现场指导、③ <b>药剂标签</b>的剂量和安全间隔期。结合具体气候、作物、生育期综合判断,如有疑问请联系当地植保站或农业部门。
  </div>{coverage_warning_html}{user_claim_warning}

  <div class="report-card">
    <span class="tag">作物病害诊断报告 · {timestamp}</span>{crop_id_badge}
    <h1 class="title">{title}</h1>
    <p class="user-q">{user_q}</p>
    {images_html}
  </div>

  <div class="conclusion">
    {conclusion}
  </div>

  <div class="section-title">关键指标</div>
  <div class="metrics">
    <div class="metric {sev_class}">
      <div class="lbl">严重程度</div>
      <div class="val">{severity}</div>
      <div class="sub">{sev_sub}</div>
    </div>
    <div class="metric {conf_class}">
      <div class="lbl">Top 1 概率</div>
      <div class="val">{probability}</div>
      <div class="sub">{conf_sub}</div>
    </div>
    <div class="metric">
      <div class="lbl">候选诊断</div>
      <div class="val">{cand_count}</div>
      <div class="sub">{cand_sub}</div>
    </div>
    <div class="metric {expert_class}">
      <div class="lbl">需联系农技员</div>
      <div class="val">{need_expert}</div>
      <div class="sub">{need_expert_sub}</div>
    </div>
    <div class="metric {rx_class}">
      <div class="lbl">处方可用</div>
      <div class="val">{rx_avail}</div>
      <div class="sub">{rx_sub}</div>
    </div>
  </div>

  <div class="section-title">关键视觉特征</div>
  <div class="tags">
      {visual_tags}
  </div>

  {reasoning_html}
  {rag_section_html}
  {candidate_prob_html}
  {rx_section}

  <div class="section-title">现在能做的(今晚就能动手)</div>
  {fallback_note_html}
  <ol class="actions" start="1">
{actions}
  </ol>

  <div class="section-title">反馈邀请</div>
  <p style="color: var(--ink-soft); font-size: 13.5px; margin: 0 0 8px;">按上面的建议处理后,问题有没有改善?</p>
  <div class="feedback">
{feedback}
  </div>
  <p style="color: var(--ink-soft); font-size: 12.5px; margin-top: 10px;">直接回 A/B/C/D/E 就行,我好根据情况调整建议。</p>
{uncertain}

  <div class="footer-note">
    报告生成时间:{timestamp} · AI 辅助诊断仅供参考
  </div>

</div>
</body>
</html>
""".format(
        title=html_escape(title),
        css=CSS_BLOCK,
        timestamp=html_escape(metadata.get("generated_at", "")[:10] or "—"),
        user_q=user_q,
        images_html=images_html,
        coverage_warning_html=coverage_warning_html,
        user_claim_warning=user_claim_warning,  # v2.1.1 矛盾 case 警告
        crop_id_badge=crop_id_badge,
        conclusion=conclusion_html,
        sev_class="warn" if severity == "中" else ("danger" if severity == "重" else ("ok" if severity == "轻" else "")),
        severity=html_escape(severity_disp),
        sev_sub=html_escape(sev_sub),
        conf_class="ok" if top_confidence == "高" else "",
        probability=html_escape(probability_disp or "—"),
        confidence=html_escape(confidence_disp),
        conf_sub=html_escape(conf_sub),
        cand_count=len(diagnosis_list),
        cand_sub="列出鉴别诊断" if len(diagnosis_list) >= 2 else "未列鉴别诊断",
        expert_class="ok" if not need_expert else "warn",
        need_expert=need_expert_disp,
        need_expert_sub=html_escape(need_expert_sub),
        rx_class="ok" if rx_avail else "warn",
        rx_avail=rx_avail_disp,
        rx_sub=html_escape(rx_summary),
        visual_tags=tags_html,
        reasoning_html=reasoning_html,
        rag_section_html=rag_section_html,
        candidate_prob_html=candidate_prob_html,
        rx_table=rx_table,
        rx_text_list_html=rx_text_list_html,
        rx_extras_html=rx_extras_html,
        rx_spray_tip=rx_spray_tip,
        rx_section=rx_section,
        fallback_note_html=fallback_note_html,
        actions=actions_html,
        feedback=feedback_html,
        uncertain=uncertain_html,
    )
    # P1-18 (2026-07-21 加): sanity check — outer .format() 跑完不应该还有 {N} 数字占位符
    # P1-40 (2026-07-21 重构): 改用 _html_shared 共享函数, 跟 simple/consult 拉齐
    leftover_fmt = check_format_string_leftover(html)
    if leftover_fmt:
        print("[P1-18 warn] HTML 残留 {0} 个 {{N}} 占位符: {1}".format(
            len(leftover_fmt), leftover_fmt[:5]), file=sys.stderr)

    # P1-27 (2026-07-21 加): sanity check — 检查 markdown 残留
    # P1-40 (2026-07-21 重构): 改用 _html_shared 共享函数
    leftover_md = check_markdown_italic_leftover(html)
    if leftover_md:
        print("[P1-27 warn] HTML 残留字面 markdown {0} 处: {1}".format(
            len(leftover_md), leftover_md[:5]), file=sys.stderr)

    return html


def main():
    parser = argparse.ArgumentParser(
        description="把 full-diagnosis.json 渲染成 HTML 报告",
        epilog="示例: python render_html_report.py -i full-diagnosis.json -o report.html"
    )
    parser.add_argument("-i", "--input", default="full-diagnosis.json",
                        help="输入的 full-diagnosis.json 路径(默认当前目录)")
    parser.add_argument("-o", "--output", default=None,
                        help="输出的 HTML 路径(默认 stdout)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit("找不到输入文件: {0}".format(input_path))
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit("full-diagnosis.json 不是合法 JSON: {0}".format(e))

    html = render_full_diagnosis(data)

    if args.output:
        Path(args.output).write_text(html, encoding="utf-8")
        print("[ok] HTML 报告已写入: {0}".format(args.output), file=sys.stderr)
        print("     长度: {0} 字符 / 打开方式: 浏览器双击即可".format(len(html)), file=sys.stderr)
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()