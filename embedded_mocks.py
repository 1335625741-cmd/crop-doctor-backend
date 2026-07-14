# -*- coding: utf-8 -*-
"""
embedded_mocks.py — 服务端内置的 5 份预置诊断

每份包含:
  - full-diagnosis JSON(对齐 bin/full_diagnosis.py 输出)
  - _identified_crop 字段(crop-identifier 识别结果)

本地试运行用,真实 AI 模式不依赖本文件。
"""
import copy
import random


# ===== 5 份"作物识别"结果(对齐 crop-identifier 的 crop-id-result.json) =====

CROP_TOMATO = {
    "is_crop": True,
    "primary_crop": {
        "name_zh": "番茄",
        "name_en": "Tomato",
        "scientific_name": "Solanum lycopersicum",
        "family": "茄科 Solanaceae",
        "category": "蔬菜/茄果类",
        "common_parts": ["果实", "叶片", "整株"],
        "confidence": "高",
        "probability": 0.92,
        "key_visual_clues": [
            "典型羽状复叶(有锯齿)",
            "茎上有细毛",
            "如果是病斑:同心轮纹(早疫病特征)",
        ],
    },
    "candidates": [
        {"name_zh": "番茄", "name_en": "Tomato", "probability": 0.92, "confidence": "高"},
        {"name_zh": "圣女果", "name_en": "Cherry tomato", "probability": 0.06, "confidence": "中"},
    ],
    "downstream_skills": [
        {"name": "crop-disease-diagnosis", "reason": "已识别为番茄(高置信度),建议进入病害诊断", "auto_chainable": True}
    ],
    "uncertainty_reason": None,
    "metadata": {"image_count": 1, "images": [], "generated_at": "2026-07-13T09:25:00+0800"},
}

CROP_RICE = {
    "is_crop": True,
    "primary_crop": {
        "name_zh": "水稻",
        "name_en": "Rice",
        "scientific_name": "Oryza sativa",
        "family": "禾本科 Poaceae",
        "category": "粮食/禾本科",
        "common_parts": ["叶片", "整株", "穗"],
        "confidence": "高",
        "probability": 0.88,
        "key_visual_clues": [
            "细长披针形叶",
            "平行叶脉",
            "水田环境",
        ],
    },
    "candidates": [
        {"name_zh": "水稻", "name_en": "Rice", "probability": 0.88, "confidence": "高"},
        {"name_zh": "小麦", "name_en": "Wheat", "probability": 0.08, "confidence": "中"},
    ],
    "downstream_skills": [
        {"name": "crop-disease-diagnosis", "reason": "已识别为水稻(高置信度),建议进入病害诊断", "auto_chainable": True}
    ],
    "uncertainty_reason": None,
    "metadata": {"image_count": 1, "images": [], "generated_at": "2026-07-13T09:25:00+0800"},
}

CROP_CUCUMBER = {
    "is_crop": True,
    "primary_crop": {
        "name_zh": "黄瓜",
        "name_en": "Cucumber",
        "scientific_name": "Cucumis sativus",
        "family": "葫芦科 Cucurbitaceae",
        "category": "蔬菜/瓜类",
        "common_parts": ["叶片", "果实", "整株"],
        "confidence": "高",
        "probability": 0.90,
        "key_visual_clues": [
            "掌状浅裂叶",
            "蔓生茎,有卷须",
            "如果是病斑:白色粉末状(白粉病特征)",
        ],
    },
    "candidates": [
        {"name_zh": "黄瓜", "name_en": "Cucumber", "probability": 0.90, "confidence": "高"},
        {"name_zh": "丝瓜", "name_en": "Loofah", "probability": 0.07, "confidence": "中"},
    ],
    "downstream_skills": [
        {"name": "crop-disease-diagnosis", "reason": "已识别为黄瓜(高置信度),建议进入病害诊断", "auto_chainable": True}
    ],
    "uncertainty_reason": None,
    "metadata": {"image_count": 1, "images": [], "generated_at": "2026-07-13T09:25:00+0800"},
}

CROP_CITRUS = {
    "is_crop": True,
    "primary_crop": {
        "name_zh": "柑橘",
        "name_en": "Citrus",
        "scientific_name": "Citrus reticulata",
        "family": "芸香科 Rutaceae",
        "category": "果树/柑橘类",
        "common_parts": ["叶片", "果实", "整株"],
        "confidence": "中",
        "probability": 0.65,
        "key_visual_clues": [
            "革质单叶,叶脉明显",
            "叶片有油点(透光可见)",
            "如果是病斑:斑驳型黄化(黄龙病特征)",
        ],
    },
    "candidates": [
        {"name_zh": "柑橘", "name_en": "Citrus", "probability": 0.65, "confidence": "中"},
        {"name_zh": "柚子", "name_en": "Pomelo", "probability": 0.20, "confidence": "中"},
        {"name_zh": "橙子", "name_en": "Orange", "probability": 0.10, "confidence": "中"},
    ],
    "downstream_skills": [
        {"name": "crop-disease-diagnosis", "reason": "已识别为柑橘(中置信度),建议进入病害诊断,但需用户确认", "auto_chainable": False}
    ],
    "uncertainty_reason": "柑橘属多种果树叶片相似,需要更多特征(果实/树形)才能确定具体种",
    "metadata": {"image_count": 1, "images": [], "generated_at": "2026-07-13T09:25:00+0800"},
}

CROP_CORN = {
    "is_crop": True,
    "primary_crop": {
        "name_zh": "玉米",
        "name_en": "Corn / Maize",
        "scientific_name": "Zea mays",
        "family": "禾本科 Poaceae",
        "category": "粮食/禾本科",
        "common_parts": ["叶片", "整株", "果穗"],
        "confidence": "高",
        "probability": 0.91,
        "key_visual_clues": [
            "宽大披针形叶(比水稻宽 3-5 倍)",
            "叶缘有波状起伏",
            "如果是病斑:大型梭形(大斑病特征)",
        ],
    },
    "candidates": [
        {"name_zh": "玉米", "name_en": "Corn", "probability": 0.91, "confidence": "高"},
        {"name_zh": "高粱", "name_en": "Sorghum", "probability": 0.06, "confidence": "中"},
    ],
    "downstream_skills": [
        {"name": "crop-disease-diagnosis", "reason": "已识别为玉米(高置信度),建议进入病害诊断", "auto_chainable": True}
    ],
    "uncertainty_reason": None,
    "metadata": {"image_count": 1, "images": [], "generated_at": "2026-07-13T09:25:00+0800"},
}

# 作物名 → 识别结果的索引
CROP_INDEX = {
    "番茄": CROP_TOMATO,
    "水稻": CROP_RICE,
    "黄瓜": CROP_CUCUMBER,
    "柑橘": CROP_CITRUS,
    "玉米": CROP_CORN,
}


# ===== 5 份"诊断"结果(对齐 full_diagnosis.py 输出) =====

MOCK_TOMATO = {
    "diagnosis": {
        "diagnosis": [
            {"name": "番茄早疫病", "category": "病害", "pathogen": "真菌(链格孢属)", "confidence": "高", "probability": 0.75,
             "key_visual_clues": ["叶片上典型同心轮纹斑(像年轮/靶心)", "病斑褐色至黑褐色,边缘清晰", "从下层老叶开始向上蔓延"]},
            {"name": "番茄晚疫病", "category": "病害", "pathogen": "卵菌(疫霉属)", "confidence": "中", "probability": 0.20,
             "key_visual_clues": ["大块水浸状斑,叶背有白色霉层(本次未明显观察到)"]},
            {"name": "番茄叶霉病", "category": "病害", "pathogen": "真菌", "confidence": "低", "probability": 0.05,
             "key_visual_clues": ["叶正面有椭圆形或不规则淡黄色斑"]},
        ],
        "severity": "中",
        "cause_summary": "连着下了几天雨 + 大棚湿度大 → 闷热潮湿天气易得早疫病,病原通过气流和雨水传播。",
        "immediate_actions": [
            "摘掉发黄和有黑圈的叶子,装袋扔出大棚,不要丢在地里(会继续传染)",
            "大棚先放风 2-3 小时,把湿气散出去;接下来白天多通风",
            "这两天先别浇水,等叶子干了再浇",
            "叶面叶背都打透,推荐雨后 24 小时内喷施",
        ],
        "need_expert": False,
        "uncertainty_reason": None,
        "differential": [
            {"not": "番茄晚疫病", "reason": "晚疫病为水浸状大斑 + 叶背白色霉层,且暴风雨后 2-3 天可毁园,本次未观察到霉层"},
        ],
    },
    "top_diagnosis_name": "番茄早疫病",
    "prescription": {
        "title": "番茄早疫病",
        "content": (
            "## 番茄早疫病\n\n"
            "| 方案类型 | 药剂 | 剂量(每亩) | 兑水 | 备注 |\n"
            "|---|---|---|---|---|\n"
            "| 保护性 | 80% 代森锰锌可湿性粉剂(大生) | 20-25 g | 30 kg(600-800 倍) | 雨季前预防首选,广谱保护 |\n"
            "| 治疗性 | 25% 嘧菌酯悬浮剂(阿米西达) | 8-10 ml | 16 kg(1500-2000 倍) | 内吸,治疗效果好 |\n"
            "| 治疗性 | 10% 苯醚甲环唑水分散粒剂(世高) | 10 g | 15 kg(1500 倍) | 三唑类,与嘧菌酯交替用,延缓抗药性 |\n"
            "| 复配 | 75% 百菌清 + 70% 甲基硫菌灵 | 25 g + 15 g | 15 kg | 老配方,便宜有效 |\n\n"
            "## 提醒\n\n"
            "⏰ 打药时间:下午 4 点后,避开中午高温\n\n"
            "🔁 复喷:7-10 天一次,连喷 2-3 次,与不同机制的药剂交替使用\n\n"
            "⚠️ 安全提醒:以上方案仅供参考,实际使用请阅读药剂标签、咨询当地农资店、联系当地农技员"
        ),
        "available": True,
    },
    "metadata": {"image_count": 2, "images": [], "crop": "番茄", "generated_at": "2026-07-13T09:25:00+0800"},
}

MOCK_RICE = {
    "diagnosis": {
        "diagnosis": [
            {"name": "水稻稻瘟病(叶瘟)", "category": "病害", "pathogen": "真菌(稻梨孢属)", "confidence": "高", "probability": 0.6682,
             "key_visual_clues": ["叶片梭形或纺锤形病斑,中央灰白色,边缘褐色", "急性型病斑呈水浸状暗绿色,慢性型有'三部一线'特征", "病斑上可观察到灰绿色霉层"]},
            {"name": "水稻胡麻斑病", "category": "病害", "pathogen": "真菌", "confidence": "低", "probability": 0.3318,
             "key_visual_clues": ["病斑为褐色小圆点,似胡麻籽,无明显晕圈"]},
        ],
        "severity": "重",
        "cause_summary": "阴雨连绵 + 偏施氮肥 + 稻田通风差 → 叶瘟大发生条件。品种抗性差也会加重病情。",
        "immediate_actions": [
            "立即排水晒田,降低田间湿度",
            "控制氮肥,增施磷钾肥,增强稻株抗病力",
            "先摘除中心病株(急性病斑所在单株)销毁,阻断扩散源头",
            "抢晴喷药,推荐 24 小时内完成第一轮施药",
        ],
        "need_expert": True,
        "uncertainty_reason": "单凭照片无法 100% 区分叶瘟慢性斑与胡麻斑,需结合田间分布和天气综合判断",
        "differential": [
            {"not": "水稻胡麻斑病", "reason": "胡麻斑病病斑为褐色小圆点无晕圈,且霉层为深褐色,与稻瘟病灰绿色霉层不同"},
        ],
    },
    "top_diagnosis_name": "水稻稻瘟病(叶瘟)",
    "prescription": {
        "title": "水稻稻瘟病",
        "content": (
            "## 水稻稻瘟病\n\n"
            "| 方案类型 | 药剂 | 剂量(每亩) | 兑水 | 备注 |\n"
            "|---|---|---|---|---|\n"
            "| 保护性 | 75% 三环唑可湿性粉剂 | 30 g | 30 kg | 经典保护剂,雨季前预防 |\n"
            "| 治疗性 | 40% 稻瘟灵乳油(富士一号) | 100 ml | 30 kg | 内吸强,治疗首选 |\n"
            "| 治疗性 | 25% 咪鲜胺乳油 | 50-60 ml | 30 kg | 与稻瘟灵交替使用 |\n"
            "| 复配 | 40% 稻瘟灵 + 75% 三环唑 | 70 ml + 20 g | 30 kg | 治疗+保护兼用,病情重时用 |\n\n"
            "## 提醒\n\n"
            "⏰ 打药时间:下午 4 点后,避开扬花期;抢晴施药\n\n"
            "🔁 复喷:7-10 天一次,连喷 2-3 次,不同药剂交替\n\n"
            "⚠️ 警示:叶瘟如不及时控制会发展成'穗颈瘟'导致大幅减产,务必重视\n\n"
            "⚠️ 安全提醒:以上方案仅供参考,实际使用请阅读药剂标签、咨询当地农资店、联系当地农技员"
        ),
        "available": True,
    },
    "metadata": {"image_count": 1, "images": [], "crop": "水稻", "generated_at": "2026-07-13T09:25:00+0800"},
}

MOCK_CUCUMBER = {
    "diagnosis": {
        "diagnosis": [
            {"name": "黄瓜白粉病", "category": "病害", "pathogen": "真菌(白粉菌属)", "confidence": "高", "probability": 1.0,
             "key_visual_clues": ["叶片正面白色粉末状圆斑(像撒了面粉)", "病斑扩大后连片,叶面像盖了一层白霜", "严重时叶片发黄、干枯"]},
        ],
        "severity": "中",
        "cause_summary": "大棚通风差 + 闷热 → 白粉病真菌大量繁殖。该病在干旱与高湿交替时最易爆发。",
        "immediate_actions": [
            "白天加大大棚通风,避免闷热环境",
            "剪掉发病严重的叶片,装袋带出大棚销毁,不要丢在沟里或地头",
            "去农资店买三唑类或甲氧基丙烯酸酯类杀菌剂,按说明书兑水喷雾",
            "喷药时叶面叶背都要打透,尤其叶背是白粉病菌的'老巢'",
        ],
        "need_expert": False,
        "uncertainty_reason": None,
    },
    "top_diagnosis_name": "黄瓜白粉病",
    "prescription": {
        "title": "黄瓜白粉病",
        "content": (
            "## 黄瓜白粉病\n\n"
            "| 方案类型 | 药剂 | 剂量(每亩) | 兑水 | 备注 |\n"
            "|---|---|---|---|---|\n"
            "| 保护性 | 70% 甲基硫菌灵可湿性粉剂 | 20 g | 15 kg | 老药,便宜 |\n"
            "| 治疗性 | 25% 乙嘧酚悬浮剂 | 20-25 ml | 15 kg | 特效,但每年最多用 2 次,避免抗药性 |\n"
            "| 治疗性 | 10% 苯醚甲环唑(世高) | 10 g | 15 kg | 与乙嘧酚交替 |\n"
            "| 治疗性 | 30% 醚菌酯悬浮剂 | 15 ml | 15 kg | 安全性好,适合采收期 |\n"
            "| 物理 | 硫磺粉 | 1-1.5 kg | 喷粉 | 大棚内慎用,易出药害 |\n\n"
            "## 提醒\n\n"
            "⏰ 打药时间:下午 4 点后,避开中午高温\n\n"
            "🔁 复喷:7-10 天一次,连喷 2-3 次,不同机制药剂交替\n\n"
            "⚠️ 安全提醒:以上方案仅供参考,实际使用请阅读药剂标签、咨询当地农资店、联系当地农技员"
        ),
        "available": True,
    },
    "metadata": {"image_count": 1, "images": [], "crop": "黄瓜", "generated_at": "2026-07-13T09:25:00+0800"},
}

MOCK_CITRUS = {
    "diagnosis": {
        "diagnosis": [
            {"name": "柑橘黄龙病", "category": "病害", "pathogen": "韧皮部杆菌(细菌,检疫性病害)", "confidence": "中", "probability": 0.4138,
             "key_visual_clues": ["叶片斑驳型黄化(黄绿相间、不对称)", "新梢叶片硬化、叶脉肿大", "部分果实小而畸形(青果/红鼻果)"]},
            {"name": "柑橘缺锌症", "category": "缺素", "pathogen": "--", "confidence": "中", "probability": 0.3223,
             "key_visual_clues": ["叶脉间失绿发黄,叶脉保持绿色(网状黄化)", "斑驳通常对称"]},
            {"name": "柑橘衰退病", "category": "病害", "pathogen": "病毒", "confidence": "低", "probability": 0.2639,
             "key_visual_clues": ["新梢节间缩短、丛枝"]},
        ],
        "severity": "重",
        "cause_summary": "黄龙病是检疫性细菌病害,通过木虱和带病苗木传播。无药可治,只能预防 + 砍除病树。",
        "immediate_actions": [
            "立即隔离疑似病株,不要剪枝、不要移栽到其他地块",
            "联系当地植保站或农业部门,送检确认(PCR 检测可确诊)",
            "检查周围柑橘园木虱情况,统一防治柑橘木虱(传毒媒介)",
            "不要到非正规苗圃购买苗木,要求出示'无黄龙病'证明",
        ],
        "need_expert": True,
        "uncertainty_reason": "黄龙病斑驳与缺锌/缺锰斑驳易混淆,需 PCR 检测才能 100% 确诊",
        "differential": [
            {"not": "柑橘缺锌症", "reason": "缺锌是网状对称黄化(叶脉间失绿),黄龙病是斑驳不对称黄化"},
        ],
    },
    "top_diagnosis_name": "柑橘黄龙病",
    "prescription": {
        "title": "柑橘黄龙病(降级路径)",
        "content": (
            "## 柑橘黄龙病(降级路径)\n\n"
            "| 处置方向 | 具体做法 |\n"
            "|---|---|\n"
            "| 农业措施 | 隔离病株 + 砍除销毁 + 全园统一防治木虱(传毒媒介) |\n"
            "| 药剂参考 | 20% 噻虫嗪水分散粒剂 10-15 g/亩 喷雾(防木虱);无治疗药剂 |\n"
            "| 鉴别建议 | 送当地植保站 PCR 检测,100% 确诊后再处置 |\n"
            "| 关键警示 | 检疫性病害,无药可治,务必上报;不要私自丢弃病树枝条 |\n\n"
            "## 提醒\n\n"
            "⚠️ 当前 detailed-prescription.md 对黄龙病仅提供预防/木虱防治方案,无治疗药剂\n\n"
            "⚠️ 关键警示:黄龙病是国内外检疫性病害,发现疑似病株务必联系当地农业部门,不得私自处置"
        ),
        "available": True,
    },
    "metadata": {"image_count": 1, "images": [], "crop": "柑橘", "generated_at": "2026-07-13T09:25:00+0800"},
}

MOCK_CORN = {
    "diagnosis": {
        "diagnosis": [
            {"name": "玉米大斑病", "category": "病害", "pathogen": "真菌(大斑凸脐蠕孢属)", "confidence": "高", "probability": 0.6525,
             "key_visual_clues": ["叶片上大型梭形病斑(长 5-10 cm,宽 1-2 cm)", "病斑中央灰褐色,边缘深褐色", "潮湿时病斑上可观察到黑色霉层"]},
            {"name": "玉米小斑病", "category": "病害", "pathogen": "真菌", "confidence": "低", "probability": 0.3475,
             "key_visual_clues": ["病斑小而多(长 1-2 cm),椭圆形,边缘紫红色"]},
        ],
        "severity": "中",
        "cause_summary": "连作 + 雨多 + 玉米品种抗性差 → 大斑病大发生。病原在病残体上越冬,来年春夏借风雨传播。",
        "immediate_actions": [
            "摘除底部老叶(发病最重的叶),装袋带出田外销毁",
            "疏通排水沟,排出积水,降低田间湿度",
            "增施磷钾肥,提高抗病力;控制氮肥",
            "下一年轮作大豆/小麦,减少病原积累",
        ],
        "need_expert": False,
        "uncertainty_reason": None,
    },
    "top_diagnosis_name": "玉米大斑病",
    "prescription": {
        "title": "玉米大斑病",
        "content": (
            "## 玉米大斑病\n\n"
            "| 方案类型 | 药剂 | 剂量(每亩) | 兑水 | 备注 |\n"
            "|---|---|---|---|---|\n"
            "| 保护性 | 50% 多菌灵可湿性粉剂 | 80-100 g | 30 kg | 老药,便宜广谱 |\n"
            "| 治疗性 | 25% 丙环唑乳油(敌力脱) | 30-40 ml | 30 kg | 三唑类,内吸强 |\n"
            "| 治疗性 | 18% 戊唑醇悬浮剂 | 30-40 ml | 30 kg | 与丙环唑交替 |\n"
            "| 复配 | 25% 嘧菌酯 + 25% 丙环唑 | 10 ml + 30 ml | 30 kg | 治疗+保护兼用,病重时用 |\n\n"
            "## 提醒\n\n"
            "⏰ 打药时间:下午 4 点后,避开扬花期\n\n"
            "🔁 复喷:7-10 天一次,连喷 2-3 次\n\n"
            "⚠️ 提醒:玉米大斑病流行年份可减产 20-50%,务必早防早治\n\n"
            "⚠️ 安全提醒:以上方案仅供参考,实际使用请阅读药剂标签、咨询当地农资店、联系当地农技员"
        ),
        "available": True,
    },
    "metadata": {"image_count": 1, "images": [], "crop": "玉米", "generated_at": "2026-07-13T09:25:00+0800"},
}

# 诊断结果列表 + 配对的识别结果
MOCK_PAIR = [
    (MOCK_TOMATO, CROP_TOMATO),
    (MOCK_RICE, CROP_RICE),
    (MOCK_CUCUMBER, CROP_CUCUMBER),
    (MOCK_CITRUS, CROP_CITRUS),
    (MOCK_CORN, CROP_CORN),
]


def pick_pair(image_count=0, seed=0):
    """挑一对(diagnosis, identified_crop)返回(深拷贝)"""
    if image_count >= 2:
        idx = 0  # 多图 → 番茄(有 3 候选)
    else:
        idx = (seed or image_count) % len(MOCK_PAIR)
    diagnosis, identified = MOCK_PAIR[idx]
    return copy.deepcopy(diagnosis), copy.deepcopy(identified)
