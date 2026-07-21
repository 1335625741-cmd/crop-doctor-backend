# 处方数据库导入指南

> 这份文档讲清楚:**怎么把外部"作物病害 + 治愈方法"数据,导入到 crop-disease-diagnosis skill 的诊断依据里**。
> 适用场景:你手上有 CSV/Excel/JSON/PDF 格式的植保资料,想让 skill 用上。

---

## 1. 现状 — 数据库在哪?怎么被用?

整个诊断的"配方表"就一个文件:

| 文件 | 作用 |
|---|---|
| `references/detailed-prescription.md` | **136 个章节**的处方数据库(98 KB) |
| `bin/lookup_prescription.py` | 模糊匹配器,把模型给的诊断名 → 章节内容 |

调用链:

```
LLM 视觉识别 → 返回"玉米穗腐病"
  → bin/lookup_prescription.py "玉米穗腐病"
  → 模糊匹配 detailed-prescription.md 里的章节标题
  → 把章节内容(药剂表 + 警示)嵌入 HTML 报告
```

**所以:导入数据库 = 按 markdown 章节格式追加内容到 `detailed-prescription.md`**。

---

## 2. 数据源识别

按数据源格式选路径:

| 数据源 | 解析方式 | 典型场景 |
|---|---|---|
| **CSV / Excel** | `pandas.read_csv/excel` | 你的植保笔记、企业 ERP 导出、第三方开放数据集 |
| **JSON** | `json.loads` | API 拉取的数据库、爬虫输出 |
| **SQLite / MySQL** | `sqlite3` / `pymysql` | 现有成熟数据库 |
| **PDF / Word** | 先用 `pdf` / `docx` skill OCR + 解析 | 学术论文、农技手册、政府公告 |
| **图片 / 微信聊天截图** | OCR 或 matrix 视觉 | 老资料、农户群消息 |
| **手写/纸面笔记** | 人工整理 | 老一辈农技员的经验册 |

---

## 3. 章节模板规范(三选一)

每个章节**必须**采用以下三种模板之一。混用会破坏风格一致性。

### 模板 A:有药可治(表格版,首选)

```markdown
### <作物> <病害名>(可选病原/部位备注)

(可选 1-2 句概述,如病原、发病条件)

| 方案 | 药剂 | 剂量(每亩) | 兑水 | 备注 |
|---|---|---|---|---|
| 保护性 | 70% 甲基硫菌灵 | 25 g | 30 kg | 雨季前预防 |
| 治疗性 | 25% 吡唑醚菌酯悬浮剂 | 20-30 ml | 30 kg | 兼防锈病 |
| 治疗性 | 18.7% 丙环·嘧菌酯悬乳剂 | 30 ml | 30 kg | 严重时用 |
| 复配 | 多菌灵 + 戊唑醇 | 30 g + 15 g | 30 kg | 严重时复配 |

(可选)复喷:7-10 天一次,连喷 2-3 次。

⚠️ 警示 1(关键视觉特征,帮模型识别)
⚠️ 警示 2(用药安全:采前停药、混配禁忌等)
⚠️ 警示 3(其他:兼防范围、抗药性等)
```

### 模板 B:无药可治(文字列表版)

```markdown
### <作物> <病害名>

⚠️ **无药可治**(说明为什么:系统性病害/土传/病毒),必须靠综合防控。

1. **<核心措施>**(通常是最关键的一条):具体做法 + 剂量
2. **<次要措施>**:具体做法
3. **<辅助措施>**:具体做法

⚠️ **典型症状**:<2-3 个最能帮模型识别的视觉特征>
⚠️ <其他警示>
```

### 模板 C:无药但有预防性药剂(混合版,少见)

```markdown
### <作物> <病害名>

⚠️ **发生后无药可治,但苗期预防有效**。

**苗期预防**:
| 方案 | 药剂 | 剂量 | 备注 |
|---|---|---|---|
| 种子处理 | 2.5% 咯菌腈悬浮种衣剂 | 按种子量 0.2% 包衣 | 首选 |
| 灌根 | 70% 甲基硫菌灵 | 800 倍液 | 出苗后灌根 |

**发病后**:

1. 拔除病株销毁,减少菌源
2. ...

⚠️ 关键警示
```

---

## 4. 字段映射(CSV → markdown 元素)

如果你想**脚本化**批量导入,以下是 CSV 列的推荐映射:

| CSV 列名建议 | markdown 元素 | 说明 |
|---|---|---|
| `crop` | 章节标题前缀 `### <crop>` | 必填 |
| `disease_name` | 章节标题主名 | 必填 |
| `pathogen_or_note` | 章节标题括号备注 | 可选,如"(细菌)"/"(细条病)" |
| `overview` | 标题下第一段概述 | 可选,1-2 句 |
| `has_chemical` | `true` → 模板 A;`false` → 模板 B | 必填,二选一 |
| `protective_pesticide` | 表格保护性行 | 模板 A 必填 |
| `protective_dose` | 表格"剂量"列 | 同上 |
| `protective_water` | 表格"兑水"列 | 同上 |
| `protective_note` | 表格"备注"列 | 同上 |
| `curative_pesticide` | 表格治疗性行 | 可多行 |
| `curative_dose` | 同上 | — |
| `curative_water` | 同上 | — |
| `curative_note` | 同上 | — |
| `combo_pesticide` | 表格复配行 | 可选 |
| `combo_dose` | 同上 | — |
| `combo_water` | 同上 | — |
| `combo_note` | 同上 | — |
| `respray_interval` | "复喷"行 | 可选,如 "7-10 天一次" |
| `key_clue_1` ~ `key_clue_N` | ⚠️ 警示行 | 至少 1 条 |
| `safety_warning` | ⚠️ 安全警示(单独) | 强烈建议 |
| `typical_symptom` | ⚠️ 典型症状(单独,模板 B 用) | 模板 B 必填 |

---

## 5. 章节命名规范(lookup 匹配核心)

`lookup_prescription.py` 的 4 个匹配规则:

1. 章节完整标题 ⊇ 诊断名(最高优先级)
2. 章节标题去括号 ⊇ 诊断名
3. 诊断名 ⊇ 章节标题去括号
4. 诊断名 ⊇ 章节标题

**核心约束**:章节标题应该**简短、规范、可被多种说法匹配**。

| 规范 | ✅ 推荐 | ❌ 反例 |
|---|---|---|
| 一个病一节 | `### 玉米大斑病` | `### 玉米大斑病/小斑病`(影响匹配,可读性差) |
| 备注用括号 | `### 玉米茎腐病(细菌)` | `### 细菌性玉米茎腐病`(键名过长) |
| 病原/部位用括号 | `### 水稻细菌性条斑病(细条病)` | `### 水稻条斑病细菌性`(顺序影响匹配) |
| 单字病名慎用 | `### 水稻白叶枯病` | `### 白叶枯`(作物必须在前) |
| 不要带"病"以外的词 | `### 苹果炭疽病` | `### 苹果炭疽病防治`(诊断名不含"防治") |
| 避免英文/拉丁 | `### 番茄早疫病` | `### Tomato Early Blight` |

---

## 6. ⚠️ 警示框规范

每章节**至少 1 条**警示,推荐 2-4 条。警示是 skill 输出的"高密度信息点",用户最爱看的部分。

### 警示类型清单

| 类型 | 写法示例 | 用途 |
|---|---|---|
| **关键视觉特征** | ⚠️ 叶片同心轮纹黑褐色斑,茎秆黑斑 | 帮模型识别 + 帮农户自查 |
| **用药安全** | ⚠️ 果实近成熟期禁用;采前 30 天停药 | 防农残超标 |
| **兼防范围** | ⚠️ 兼防锈病/白粉病 | 让用户知道能"一打多" |
| **典型症状**(无药时) | ⚠️ 病株矮化、节间缩短、叶片宽短浓绿 | 区别于其他病 |
| **混配禁忌** | ⚠️ 不可与碱性农药混用 | 防药害 |
| **抗药性提示** | ⚠️ 长期单一使用易产生抗药性,建议轮换 | 减缓抗药性 |
| **无药可治警示** | ⚠️ **无药可治**,必须靠综合防控 | 引导用户预期 |
| **毒素风险** | ⚠️ **病粒含真菌毒素,人畜绝不能吃!** | 安全警戒 |

### 警示写法格式

- 必须以 `⚠️ ` 开头(emoji + 两个空格)
- 一条一行
- 关键信息用 **粗体** 包起来(如药名、关键动作)
- 复杂说明可拆成多条,不要堆在一行

---

## 7. 5 步导入流程

### Step 1 — 准备数据源

把外部数据(CSV/Excel/JSON/PDF)整理到本地。建议放 `workspace/import/你的文件名.csv`。

### Step 2 — 字段映射

对照第 4 节,把 CSV 列名映射到 markdown 元素。如果没有现成的 CSV 列,先整理。

### Step 3 — 转换(脚本化 or 手动)

**脚本化(批量)**:写一个一次性 Python 脚本:

```python
import pandas as pd

df = pd.read_csv('你的文件.csv')
chapters = []
for _, row in df.iterrows():
    chapter = build_chapter(row)  # 按字段映射拼接 markdown
    chapters.append(chapter)

with open('detailed-prescription.md', 'a', encoding='utf-8') as f:
    f.write('\n\n---\n\n')
    f.write('\n\n'.join(chapters))
```

**手动(少量章节)**:直接复制模板,填字段。

### Step 4 — 人工审核

转换出来的章节**一定要人工审一遍**,重点检查:

- [ ] 剂量数字是否合理(没出现 100 kg 这种离谱值)
- [ ] ⚠️ 警示是否覆盖安全风险(尤其用药安全)
- [ ] 章节标题是否符合第 5 节规范
- [ ] 没有合并病名(没用 "/" 或 "、")
- [ ] 没有学术名词堆砌(分生孢子、菌丝体等要换成白话)

### Step 5 — 集成验证

跑两个验证:

```bash
# 1. lookup 匹配测试(每个新章节单独测一次)
python bin/lookup_prescription.py "你的新病害名"

# 2. skill 自检
python bin/skill_check.py

# 3. 端到端验证(用一张图触发诊断)
python bin/full_diagnosis.py -i test.jpg -c 你的作物 -p 你的部位 --backoff 5,15,45
```

如果 lookup 返回"没找到",回到 Step 4 修章节标题。

---

## 8. 完整示例:CSV → markdown

### 输入 CSV

```csv
作物,病名,病原,有药,保护性,治疗性,警示
苹果,炭疽病,真菌,有,"70% 甲基硫菌灵 25 g/亩 兑水 30 kg 雨季前预防","25% 吡唑醚菌酯悬浮剂 20-30 ml/亩 兑水 30 kg",果实近成熟期禁用;采前 30 天停药
柑橘,黄龙病,细菌,无,无,无,无药可治!必须砍除病树+木虱防治
```

### 转换后(自动追加到 detailed-prescription.md)

```markdown
### 苹果炭疽病

| 方案 | 药剂 | 剂量(每亩) | 兑水 | 备注 |
|---|---|---|---|---|
| 保护性 | 70% 甲基硫菌灵 | 25 g | 30 kg | 雨季前预防 |
| 治疗性 | 25% 吡唑醚菌酯悬浮剂 | 20-30 ml | 30 kg | — |

复喷:7-10 天一次,连喷 2-3 次。

⚠️ 果实近成熟期禁用;采前 30 天停药。
⚠️ 兼防轮纹病。

---

### 柑橘黄龙病

⚠️ **无药可治**(细菌性系统病害),必须靠综合防控。

1. **砍除病树**:整株挖除,带出果园销毁
2. **严防木虱传毒**:10% 吡虫啉 20 g/亩 喷雾
3. **选用无病苗木**:正规苗圃,带检疫证
4. **加强果园管理**:增强树势

⚠️ **典型症状**:叶片斑驳型黄化(俗称"黄龙"),果实小而畸形(红鼻子果)。
```

### 验证

```bash
$ python bin/lookup_prescription.py "苹果炭疽病"
# 来源章节: 苹果炭疽病
# ... 完整章节内容 ...

$ python bin/lookup_prescription.py "柑橘黄龙病"
# 来源章节: 柑橘黄龙病
# ... 完整章节内容 ...
```

---

## 9. FAQ

### Q1:导入 = 替换现有章节吗?

**不是**。导入是**追加**到 `detailed-prescription.md` 末尾。现有章节不删。

如果你想**修改**某个现有章节(比如觉得"玉米大斑病"配方不对),直接 edit 那一节就行,不用走导入流程。

### Q2:导入后章节数变了,会不会影响 skill_check.py?

`skill_check.py` 不强制章节数,只检查关键文件存在性。所以章节数 134 → 150 没问题。

### Q3:章节多了,lookup 会不会变慢?

不会。`detailed-prescription.md` 100 KB,Python 正则匹配 < 1ms。

### Q4:能用向量数据库(SQLite/pgvector/FAISS)替代 markdown 吗?

技术上可以,但要重写 `bin/lookup_prescription.py` 和 HTML 渲染。**不建议**,除非章节数破千。

当前 markdown + 正则匹配:
- ✅ 简单透明,人工可读可改
- ✅ 版本控制友好(Git diff 清楚)
- ✅ lookup 性能足够
- ✅ 单文件部署

只有以下场景才考虑迁:
- 章节数 > 1000(单文件超过 1 MB,Git diff 痛苦)
- 需要语义搜索("玉米叶斑"要命中"玉米大斑病")
- 多语言章节混排

### Q5:PDF / 图片资料怎么导入?

推荐流程:

1. **PDF**:用 `pdf` skill 提取文字(保留结构)→ 人工整理成 CSV → 按本指南导入
2. **图片**:用 `matrix_describe_images` 让模型描述图片内容(它能读表格) → 人工校核 → 整理成 CSV
3. **微信聊天截图**:OCR 文字 + 人工整理

### Q6:导入章节后,模型输出的诊断名变了怎么办?

诊断名由模型决定。如果模型用"苹果果实炭疽病"这种说法,lookup 应该能匹配"苹果炭疽病"(因为诊断名 ⊇ 章节标题去括号)。

如果匹配不上,在新章节标题里加一个括号别名,如 `### 苹果炭疽病(果实炭疽)`。

### Q7:能批量导入上百个章节吗?

可以,按第 7 节写脚本批量转换。但**强烈建议**先小批量试水(10-20 个),确认格式对、人审核过,再大规模跑。

### Q8:章节命名冲突怎么办?

如果你导入的章节标题跟现有重复,lookup 会按**第一次出现**的章节返回。规避方法:
- 新章节标题加上数据集来源后缀,如 `### 苹果炭疽病(北方版)`
- 或者先确认现有章节没有,再追加

---

## 10. 数据来源建议(权威清单)

导入数据时,**优先使用以下权威源**,数据质量有保证:

| 数据源 | 类型 | 适用 |
|---|---|---|
| **中国农技推广网**(natesc.moa.gov.cn) | 政府公告 | 重大病虫害预警 |
| **全国农技中心**(natesc.moa.gov.cn) | 技术手册 | 标准化处方 |
| **地方植保站发布**(各省) | 区域性强 | 当地特有病 |
| **农药登记公告**(中国农药信息网, http://www.chinapesticide.org.cn) | 药剂信息 | 用药合规性 |
| **IPM Images / Bugwood** | 病害图片库 | 视觉特征参考 |
| **CABI Compendium** | 国际权威 | 病害学名、病原 |

**慎用**:
- ❌ 论坛/贴吧的偏方(没经过验证)
- ❌ 厂家宣传材料(有商业目的)
- ❌ 旧的资料(农药登记证过期、停用)

---

## 11. 进阶:自动化脚本(可选)

如果你频繁导入(每月更新),建议写一个 `bin/import_prescription.py`,核心功能:

```python
# 伪代码
def import_from_csv(csv_path, mode='append'):
    df = pd.read_csv(csv_path)
    
    # 1. 校验字段
    required = ['crop', 'disease_name', 'has_chemical']
    assert all(col in df.columns for col in required)
    
    # 2. 转 markdown
    chapters = [build_chapter(row) for _, row in df.iterrows()]
    
    # 3. 预览(不写文件)
    if mode == 'preview':
        print('\n\n---\n\n'.join(chapters))
        return
    
    # 4. 追加
    with open('detailed-prescription.md', 'a', encoding='utf-8') as f:
        f.write('\n\n---\n\n')
        f.write('\n\n'.join(chapters))
    
    # 5. 验证 lookup
    for _, row in df.iterrows():
        full_name = f"{row['crop']}{row['disease_name']}"
        assert lookup_prescription(full_name), f'{full_name} 匹配失败!'
    
    print(f'✅ 成功导入 {len(df)} 个章节')

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('-i', '--input', required=True)
    p.add_argument('--preview', action='store_true')
    args = p.parse_args()
    mode = 'preview' if args.preview else 'append'
    import_from_csv(args.input, mode)
```

调用:

```bash
# 先预览(不写文件)
python bin/import_prescription.py -i 我的数据.csv --preview

# 确认无误,正式导入
python bin/import_prescription.py -i 我的数据.csv
```

---

## 12. 检查清单(导入完成前过一遍)

- [ ] 章节总数 +N(N 是新增数)
- [ ] 每个新章节标题符合第 5 节规范
- [ ] 每个新章节至少 1 条 ⚠️ 警示
- [ ] 无药可治的章节用模板 B(文字列表)
- [ ] 有药可治的章节用模板 A(表格)
- [ ] 没有合并病名(无 "/" 或 "、")
- [ ] `python bin/skill_check.py` 通过
- [ ] 每个新章节单独 lookup 都能命中
- [ ] 端到端诊断跑通(用一张图触发 Top 1 命中新增章节)

---

**文档版本**:1.0 · 2026-07-07 · 适用于 crop-disease-diagnosis skill v1.x