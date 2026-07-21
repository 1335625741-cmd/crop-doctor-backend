#!/usr/bin/env python3
"""
lookup_prescription.py — 根据诊断名从 detailed-prescription.md 找对应的处方章节

用法:
  python lookup_prescription.py "番茄早疫病"
  python lookup_prescription.py "番茄晚疫病"

输入:诊断名(可以包含或不包含作物名前缀,例如 "早疫病" 也能匹配 "番茄早疫病")
输出:匹配的处方章节内容(含表格和备注),找不到则退出码 1 + stderr 说明

为什么存在:
  detailed-prescription.md 有 27+ 个病害方案,LLM 每次手动 grep 太慢且不稳定,
  这个脚本把"按诊断名找处方"固化为确定性调用。

兼容:Python 3.5+(避免 f-string,改用 .format())
"""

import argparse
import re
import sys
from pathlib import Path

# 强制 stdout/stderr 用 UTF-8(Windows 默认 GBK 会在 print 中文时炸 UnicodeEncodeError)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except AttributeError:
    pass  # Python 3.5- 没这个方法,跳过

# 路径常量
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PRESCRIPTION_FILE = SKILL_DIR / "references" / "detailed-prescription.md"


def parse_sections(text):
    """解析 detailed-prescription.md 的 ### 章节
    返回 [{title, start_line, end_line}, ...]
    每个章节的范围:从自己的 start_line 到下一个 ### 章节(或 ## / # / 文件末尾)"""
    lines = text.split("\n")
    sections = []
    current = None
    for i, line in enumerate(lines):
        m = re.match(r"^### (.+)", line)
        if m:
            # 在新章节开始前,先收尾旧章节
            if current:
                current["end_line"] = i
                sections.append(current)
            current = {
                "title": m.group(1).strip(),
                "start_line": i,
                "end_line": None,
            }
        elif current and (line.startswith("## ") or line.startswith("# ")):
            # 遇到 ## / # 标题,当前章节结束
            current["end_line"] = i
            sections.append(current)
            current = None
    # 收尾最后一个章节
    if current:
        current["end_line"] = len(lines)
        sections.append(current)
    return sections


def normalize_title(title):
    """去掉标题里的学名括号、空格等,便于模糊匹配
    "番茄早疫病(Alternaria solani)" → "番茄早疫病"
    """
    return re.sub(r"\([^)]+\)", "", title).strip()


# P1-25 (2026-07-21 加):别名映射表 — 库图目录名跟详细处方章节名不同,
# 但实际上是同一个病。例:"苹果果树腐烂病"对应"苹果腐烂病(烂皮病)"(别称)。
# lookup 时先把查询转成 canonical 名再 fuzzy 匹配。
DIAGNOSIS_ALIAS = {
    "樱桃根瘤病": "樱桃根癌病",
    "苹果果树腐烂病": "苹果腐烂病",
    "辣椒花叶病": "辣椒病毒病",
    "辣椒病毒花叶病": "辣椒病毒病",
    # 玉米小斑病 / 大斑病 — 章节合写,需规则 5 关键词匹配
}


def find_best_match(diagnosis_name, sections):
    """模糊匹配诊断名到章节标题
    规则(优先级从高到低):
      1. 完整标题包含诊断名
      2. 去除学名后的标题包含诊断名
      3. 诊断名包含去除学名后的标题
      4. 标题以诊断名开头(去除作物名前缀后)
      5. (P1-25 加)核心关键词匹配 — 拆词后看标题是否包含尾部关键词(处理"小斑病" 这种核心词)
    """
    matches = []
    diag = diagnosis_name.strip()
    # P1-25: 先查别名映射
    if diag in DIAGNOSIS_ALIAS:
        diag = DIAGNOSIS_ALIAS[diag]

    for sec in sections:
        title = sec["title"]
        clean = normalize_title(title)

        # 规则 1-2:标题(含或不含学名)包含诊断名
        if diag in title or diag in clean:
            matches.append((sec, 1))
            continue
        # 规则 3:诊断名包含干净标题
        if clean in diag:
            matches.append((sec, 2))
            continue
        # 规则 4:诊断名以干净标题结尾(允许作物名不同)
        if diag.endswith(clean) and len(clean) >= 2:
            matches.append((sec, 3))
            continue
        # 规则 5:核心关键词 match — 拆掉作物名前缀,看尾部核心病名(2+ chars)是否在标题里
        # 例: "玉米小斑病" → "小斑病",标题"玉米大斑病 / 小斑病" 含"小斑病" ✓
        # 例: "苹果果树腐烂病" → "腐烂病",标题"苹果腐烂病(烂皮病)" 含"腐烂病" ✓
        for kw_len in (3, 2):  # 优先匹配 3 字词(更精确),失败试 2 字
            if len(diag) > kw_len:
                keyword = diag[-kw_len:]
                if keyword in clean and keyword not in ("病", "虫", "症", "害", "疫", "斑"):
                    matches.append((sec, 4 + (3 - kw_len) * 0.1))  # 3字优先于 2字
                    break

    if not matches:
        return None

    # 按规则优先级 + 标题长度排序,选最优
    matches.sort(key=lambda x: (x[1], len(x[0]["title"])))
    return matches[0][0]


def lookup(diagnosis_name):
    """主函数:查诊断名对应的处方章节内容"""
    if not PRESCRIPTION_FILE.exists():
        sys.exit("找不到 {0}".format(PRESCRIPTION_FILE))

    text = PRESCRIPTION_FILE.read_text(encoding="utf-8")
    sections = parse_sections(text)
    match = find_best_match(diagnosis_name, sections)

    if not match:
        return None, None

    lines = text.split("\n")
    content = "\n".join(lines[match["start_line"]:match["end_line"]]).rstrip()
    return match["title"], content


def main():
    parser = argparse.ArgumentParser(
        description="按诊断名查对应用药章节",
        epilog='示例: lookup_prescription.py "番茄早疫病"'
    )
    parser.add_argument("diagnosis", help="诊断名(如 番茄早疫病 / 黄瓜白粉病)", nargs="*")
    args = parser.parse_args()

    if not args.diagnosis:
        parser.print_help()
        sys.exit(1)

    diagnosis = " ".join(args.diagnosis).strip()
    title, content = lookup(diagnosis)

    if not content:
        sys.exit('没找到诊断 "{0}" 对应的处方章节'.format(diagnosis))

    # 在 stdout 打章节标题 + 内容,producer 直接用
    print("# 来源章节: {0}".format(title))
    print("---")
    print(content)
    print("---")
    print("# 重要提醒:以上方案来自公开植保资料,实际使用请务必:")
    print("#  1. 阅读并遵守药剂标签(剂量、间隔期、混配禁忌)")
    print("#  2. 咨询当地农资店,确认库存与本地抗药性情况")
    print("#  3. 联系当地农技员,确认是否适合当地作物与气候")


if __name__ == "__main__":
    main()