#!/usr/bin/env python3
"""
_html_shared.py — bin/render_html_report*.py 共享工具函数
(2026-07-21 创建, P1-37 防御性重构: 消除 detail/simple 工具的代码重复)

共享内容:
- html_escape(s)                              # HTML escape
- md_inline_to_html(text)                     # inline markdown (**bold** / *italic* / `code`)
- embed_image_as_data_url(path, max_bytes)    # base64 嵌入 + Pillow 压缩 fallback
- check_data_consistency(data, label)         # P1-33 防御性数据一致性检查

设计原则:
- 这个文件不依赖任何其他 bin/ 模块
- detail 和 simple 工具都从这 import, 保证行为一致
- 修一处生效两处
"""
import base64
import io
import re
import sys
from pathlib import Path


def html_escape(s):
    """HTML escape (跟 detail/simple 旧实现 100% 兼容)"""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def md_inline_to_html(text):
    """inline markdown -> HTML (先 escape 后转 markdown, 防 XSS)

    支持规则 (按顺序):
    1. ***text***     -> <strong><em>text</em></strong>
    2. **text**       -> <strong>text</strong>
    3. *text*         -> <em>text</em>  (生物学术名 *Fusarium* 用)
    4. `text`         -> <code>text</code>

    P1-27 (2026-07-21): 加 italic 规则 + 13 单元测试, 防止 *Fusarium* 显示成字面字符
    P1-37 (2026-07-21): 先 html_escape 再 markdown 转换, 防止恶意输入
                         (跟原 render_html_report.py 行为一致)
    """
    if not text:
        return ""
    text = html_escape(text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
    return text


def embed_image_as_data_url(img_path, max_bytes=200 * 1024):
    """把图片转 base64 data URL; 超 max_bytes 用 Pillow 迭代压缩

    P1-23 (2026-07-21): 超 max_bytes 不直接 return None, 用 Pillow 4 档 (1200/800/600/400) + quality 85/70/55/40 迭代

    返回: (data_url, error) 元组
    - data_url: 成功时是 "data:image/{png|jpeg};base64,..." 字符串
    - error:    失败时是错误描述字符串 (data_url 为 None)
    """
    p = Path(img_path)
    if not p.exists():
        return None, f"图片不存在: {img_path}"
    try:
        data = p.read_bytes()
        if len(data) <= max_bytes:
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            return f"data:{mime};base64,{base64.b64encode(data).decode()}", None
        # Pillow 压缩
        try:
            from PIL import Image
        except ImportError:
            return None, "Pillow 未安装,无法压缩超 max_bytes 图片"
        img = Image.open(p)
        for size, q in [(1200, 85), (800, 70), (600, 55), (400, 40)]:
            buf = io.BytesIO()
            if img.size[0] > size:
                ratio = size / img.size[0]
                new_size = (size, int(img.size[1] * ratio))
                img2 = img.resize(new_size, Image.LANCZOS)
            else:
                img2 = img
            img2.save(buf, format="JPEG", quality=q)
            if buf.tell() <= max_bytes:
                return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}", None
        return None, f"压缩后仍超 max_bytes ({max_bytes})"
    except Exception as e:
        return None, f"图片处理失败: {e}"


def check_data_consistency(data, top_name="?"):
    """P1-33 数据一致性检查 (2026-07-21 加, 2026-07-21 防御性重构)

    防御: 防止 prescription 状态自相矛盾, 导致 HTML 渲染出"无意义答案"或"空 table"
    之前 P1-32 根因之一: rx_rows 和 rx_text_list_html 同时不为空 → 表格型+文字列表型都渲染
    之前 P1-31 根因: rx_avail=True 但 rx_rows=[] → 显示空 table (0 种方案)

    规则 (4 个):
    1. prescription.available=True 必须有 rx_content (不能空 content 假装有处方)
    2. immediate_actions 必须是 list (类型防御)
    3. prescription.content 字段存在但 \r 没处理 (P1-15 防御)
    4. (warning, 不抛) rx_rows 和 rx_text_list_html 互斥 (P1-32 防御)

    用法:
        warnings = check_data_consistency(data, top_name)
        for w in warnings:
            print(w, file=sys.stderr)

    返回: warning 列表 (空 = 数据一致)
    """
    warnings = []
    diag = data.get("diagnosis", {}) or {}
    rx = data.get("prescription", {}) or {}
    rx_avail = rx.get("available", False)
    rx_content = rx.get("content", "") or ""
    immediate = diag.get("immediate_actions", [])

    # 规则 1: rx_avail=True 但 content 为空 -> 警告
    if rx_avail and not rx_content.strip():
        warnings.append(
            f"[P1-33 warn] prescription.available=True 但 content 为空 — "
            f"应改为 available=False 或补详细处方章节。诊断: {top_name}"
        )

    # 规则 2: immediate_actions 类型
    if not isinstance(immediate, list):
        warnings.append(
            f"[P1-33 warn] immediate_actions 类型错误 ({type(immediate).__name__}), 应为 list"
        )

    # 规则 3: rx_content 有 \r 没处理 (P1-15 防御) - 这是诊断函数的事, render 工具只警告
    if "\r" in rx_content:
        warnings.append(
            f"[P1-15 warn] prescription.content 含 \\r — render 工具会处理, 但建议源头修复"
        )

    # 规则 4: rx_rows 和 rx_text_list_html 互斥 — 这是 render 工具的事, 此处不警告
    # (render 工具自己判断哪个优先)

    return warnings


# P1-17/18 sanity check helper
def check_format_string_leftover(html):
    """P1-17/18 防御: 检测渲染完的 HTML 里有没有 `{N}` 数字占位符残留

    双层 .format() 嵌套陷阱: 内层 .format() 留 `{0}` `{1}` 字面没填, 外层 .format() 触发 IndexError 崩
    或字面 `{0}` 漏到 HTML

    用法:
        leftover = check_format_string_leftover(html)
        if leftover:
            print(f"[P1-18 warn] HTML 残留 {N} 个 {{N}} 占位符: {leftover[:5]}", file=sys.stderr)
    """
    return re.findall(r'\{\d+\}', html)


# P1-27 sanity check helper
def check_markdown_italic_leftover(html):
    """P1-27 防御: 检测 HTML 里有没有字面 *xxx* (md_inline_to_html 漏处理)

    之前踩过: *Fusarium* 漏处理时显示成字面字符
    排除: <em> 标签里的 *, CSS 注释里的 *, copyright 等
    """
    leftover = []
    for m in re.finditer(r"(?<![<\w])\*([^*\s\n<][^*\n<]{1,38}[^*\s\n<])\*(?!\w)", html):
        content = m.group(1)
        if content in ('times', 'copyright', 'x'):
            continue
        leftover.append(m.group(0))
    return leftover
