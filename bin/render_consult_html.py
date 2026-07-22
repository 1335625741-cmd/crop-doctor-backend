#!/usr/bin/env python3
"""
render_consult_html.py — 文字咨询 HTML 报告生成器(2026-07-21 临时建)
替代不存在的 crop-pest-text-advisor skill, 复用 _html_shared.py

结构: 5 必含 + 2 可选 (跟 crop-pest-text-advisor SKILL 一致)
- 段 1: 发病原因
- 段 2: 基础治疗方案(化学类别 + 代表成分, 不写商品名/剂量)
- 段 3: 复喷节奏 + 安全间隔期
- 段 4: 混配禁忌 + 轮换用药
- 段 5: 鉴别诊断
- 段 6 (可选): 症状识别
- 段 7 (可选): 农业防治

输入: JSON 咨询数据(user_question, candidates, comparison, etc)
输出: HTML 报告
"""
import argparse
import json
import re as _re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _html_shared import (
    html_escape,
    md_inline_to_html,
    check_data_consistency,
    check_format_string_leftover,
    check_markdown_italic_leftover,
)

CSS = """
:root { --green: #4a7c59; --green-bg: #e8f1ea; --ink: #2a2a2a; --ink-soft: #6a6a6a; --line: #e0ddd5; --card: #fafaf6; --warn: #b94545; --warn-bg: #fff7e6; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f5f3; color: var(--ink); margin: 0; padding: 24px 12px; line-height: 1.6; font-size: 14px; }
.wrap { max-width: 880px; margin: 0 auto; background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 28px 32px; }
.disclaimer { background: #fce4e4; border: 1px solid #e0a8a8; border-left: 4px solid var(--warn); color: #7a2828; padding: 12px 16px; border-radius: 6px; font-size: 13.5px; margin-bottom: 24px; line-height: 1.7; }
.section-title { font-size: 16px; font-weight: 600; margin: 24px 0 10px; color: var(--ink); padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.alert { background: var(--warn-bg); border-left: 3px solid #f5a623; padding: 10px 14px; margin: 8px 0; border-radius: 4px; font-size: 13.5px; line-height: 1.6; }
.callout { background: var(--card); border-left: 3px solid var(--green); padding: 10px 14px; margin: 8px 0; border-radius: 4px; font-size: 13.5px; line-height: 1.6; }
.question-box { background: #e8f1ea; border: 1px solid #b8d4be; padding: 12px 16px; border-radius: 8px; margin: 0 0 20px; font-size: 14px; }
.q-label { color: var(--green); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { background: var(--card); font-weight: 600; color: var(--ink-soft); font-size: 12px; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11.5px; font-weight: 600; background: var(--green-bg); color: var(--green); }
.pill-warn { background: var(--warn-bg); color: #7a4a0e; }
ol, ul { padding-left: 22px; margin: 8px 0; }
li { margin-bottom: 4px; }
.footer-note { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-soft); text-align: center; }
code { background: #f0f0e8; padding: 1px 5px; border-radius: 3px; font-size: 12.5px; }
"""


def render_consult_html(data):
    user_q = data.get("user_question", "")
    summary = data.get("summary", "")  # 1 句话总结
    cause = data.get("cause", "")  # 发病原因
    treatments = data.get("treatments", [])  # [{category, agents, notes}] - 类别 + 代表成分
    spray_schedule = data.get("spray_schedule", "")  # 复喷节奏 + 安全间隔期
    mixing_rotation = data.get("mixing_rotation", "")  # 混配禁忌 + 轮换用药
    differential = data.get("differential", [])  # 鉴别诊断 [{name, key_diff}]
    symptoms = data.get("symptoms", "")  # 症状识别 (可选)
    ag_control = data.get("ag_control", "")  # 农业防治 (可选)
    need_expert = data.get("need_expert", False)  # 是否需要联系农技员
    expert_reason = data.get("expert_reason", "")

    # P1-40 (2026-07-21 加, 拉齐 P1-37/38 防御): 入口数据一致性检查
    # 防御: 防止 prescription/consult 数据状态矛盾导致"无意义答案"
    warnings = check_data_consistency(data, summary[:30] or "咨询")
    for w in warnings:
        print(w, file=sys.stderr)

    parts = ['<!DOCTYPE html>', '<html lang="zh-CN">', '<head>',
             '<meta charset="UTF-8">',
             # P1-40 (2026-07-21 修): title 里 strip markdown 标记 (title 不渲染 HTML)
             # 之前 html_escape 不转 *, ** , 字面 "*玉米丝黑穗病*" 显示在浏览器标签页
             # 2026-07-22: 拆出变量(Python 3.11 f-string 不允许表达式内含 backslash)
             '<title>咨询报告 — ' + html_escape(_re.sub(r"\\*+([^*]+?)\\*+", r"\1", summary[:30])) + '</title>',
             f'<style>{CSS}</style>',
             '</head>', '<body>', '<div class="wrap">']

    # 免责声明
    parts.append(
        '<div class="disclaimer"><strong>免责声明:</strong>本报告由 AI 辅助生成,仅作技术参考。'
        '<strong>严禁仅凭本报告用药或处置</strong>。实际用药请严格遵守:① 当地农资店的库存与建议、'
        '② 当地农技员的现场指导、③ 药剂标签的剂量和安全间隔期。结合具体气候、作物、生育期综合判断,'
        '如有疑问请联系当地植保站或农业部门。</div>'
    )

    # 用户问题
    parts.append(f'<div class="question-box"><div class="q-label">用户提问</div>{md_inline_to_html(user_q)}</div>')

    # 总结
    if summary:
        parts.append(f'<div class="callout"><strong>一句话总结:</strong>{md_inline_to_html(summary)}</div>')

    # 段 1: 发病原因
    if cause:
        parts.append('<div class="section-title">1. 发病原因</div>')
        parts.append(f'<p>{md_inline_to_html(cause)}</p>')

    # 段 2: 基础治疗方案 (化学类别 + 代表成分, 不写商品名)
    if treatments:
        parts.append('<div class="section-title">2. 基础治疗方案</div>')
        parts.append('<p style="color: var(--ink-soft); font-size: 13px;">下表只列化学类别和代表成分,具体商品名请咨询当地农资店。</p>')
        rows = []
        for t in treatments:
            category = t.get("category", "?")
            agents = t.get("agents", [])
            notes = t.get("notes", "")
            agents_str = "、".join(agents) if isinstance(agents, list) else str(agents)
            rows.append(
                f"<tr><td><span class='pill'>{html_escape(category)}</span></td>"
                f"<td>{html_escape(agents_str)}</td>"
                f"<td>{md_inline_to_html(notes)}</td></tr>"
            )
        parts.append(
            '<table><thead><tr><th style="width:18%">化学类别</th><th style="width:42%">代表成分</th><th>说明</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )

    # 段 3: 复喷节奏 + 安全间隔期
    if spray_schedule:
        parts.append('<div class="section-title">3. 复喷节奏 + 安全间隔期</div>')
        parts.append(f'<p>{md_inline_to_html(spray_schedule)}</p>')

    # 段 4: 混配禁忌 + 轮换用药
    if mixing_rotation:
        parts.append('<div class="section-title">4. 混配禁忌 + 轮换用药</div>')
        parts.append(f'<p>{md_inline_to_html(mixing_rotation)}</p>')

    # 段 5: 鉴别诊断
    if differential:
        parts.append('<div class="section-title">5. 鉴别诊断</div>')
        parts.append('<p style="color: var(--ink-soft); font-size: 13px;">不同病害外观相似,以下帮您快速对号入座:</p>')
        rows = []
        for d in differential:
            name = d.get("name", "?")
            key_diff = d.get("key_diff", "")
            rows.append(
                f"<tr><td><b>{html_escape(name)}</b></td><td>{md_inline_to_html(key_diff)}</td></tr>"
            )
        parts.append(
            f'<table><thead><tr><th style="width:30%">候选</th><th>关键区别</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
        )

    # 段 6 (可选): 症状识别
    if symptoms:
        parts.append('<div class="section-title">6. 症状识别(帮助您确认)</div>')
        parts.append(f'<p>{md_inline_to_html(symptoms)}</p>')

    # 段 7 (可选): 农业防治
    if ag_control:
        parts.append('<div class="section-title">7. 农业防治</div>')
        parts.append(f'<p>{md_inline_to_html(ag_control)}</p>')

    # need_expert 提示
    if need_expert:
        # P1-40 (2026-07-21 修): 用 md_inline_to_html 不是 html_escape
        # 修法: expert_reason 里常有 **强烈建议** *检疫性病害* 等 markdown 标记
        #       html_escape 只转 < > & ", 不会转 **, 字面显示带星号
        parts.append(
            f'<div class="alert"><strong>建议联系农技员</strong>({md_inline_to_html(expert_reason)})。</div>'
        )

    parts.append('<div class="footer-note">作物病害咨询报告 · 文字版 · 仅供技术参考</div>')
    parts.append('</div></body></html>')
    html = "\n".join(parts)

    # P1-40 (2026-07-21 加, 拉齐 P1-37 防御): format string + markdown 残留 sanity check
    leftover_fmt = check_format_string_leftover(html)
    if leftover_fmt:
        print("[P1-18 warn] HTML 残留 {0} 个 {{N}} 占位符: {1}".format(
            len(leftover_fmt), leftover_fmt[:5]), file=sys.stderr)
    leftover_md = check_markdown_italic_leftover(html)
    if leftover_md:
        print("[P1-27 warn] HTML 残留字面 markdown {0} 处: {1}".format(
            len(leftover_md), leftover_md[:5]), file=sys.stderr)

    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="输入咨询 JSON 路径")
    parser.add_argument("-o", "--output", default=None, help="输出 HTML 路径(默认 stdout)")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    html = render_consult_html(data)
    if args.output:
        Path(args.output).write_text(html, encoding="utf-8")
        print(f"[ok] 咨询 HTML 已写入: {args.output}", file=sys.stderr)
        print(f"     长度: {len(html)} 字符", file=sys.stderr)
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
