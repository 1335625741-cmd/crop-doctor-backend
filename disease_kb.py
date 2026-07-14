# -*- coding: utf-8 -*-
"""
disease_kb.py — 文字问诊"知识库直出"数据库

数据来源:crop-disease-diagnosis skill 的 references/detailed-prescription.md
(公开植保手册与农业技术资料,~210 个常见作物问题)

数据由 build_disease_kb.py 从 markdown 解析生成 → disease_kb_from_skill.json,
本文件读取后构建 DISEASE_KB 字典 + 关键词索引,供后端 _consult_real 查询。
"""

import json as _json
from pathlib import Path as _Path

_DATA_FILE = _Path(__file__).parent / "disease_kb_from_skill.json"
_RAW_DATA = _json.loads(_DATA_FILE.read_text(encoding="utf-8"))


# ============================================================
# 1. 名称 → 别名映射(口语化简称,口语搜索更准)
# ============================================================
_COMMON_ALIASES = {
    "番茄早疫病": ["番茄早疫", "番茄早斑病"],
    "番茄晚疫病": ["番茄晚疫", "番茄瘟病"],
    "番茄病毒病": ["番茄花叶病", "番茄卷叶病"],
    "番茄青枯病": ["番茄青枯"],
    "番茄灰霉病": ["番茄灰霉"],
    "番茄叶霉病": ["番茄叶霉"],
    "番茄枯萎病": ["番茄枯萎"],
    "黄瓜白粉病": ["黄瓜白粉", "瓜类白粉病"],
    "黄瓜霜霉病": ["黄瓜霜霉", "瓜类霜霉病", "跑马干"],
    "黄瓜细菌性角斑病": ["黄瓜角斑病", "黄瓜细菌角斑"],
    "黄瓜枯萎病": ["黄瓜枯萎", "瓜类枯萎病"],
    "黄瓜疫病": ["黄瓜疫"],
    "辣椒炭疽病": ["辣椒炭疽"],
    "辣椒疮痂病": ["辣椒疮痂"],
    "辣椒白粉病": ["辣椒白粉"],
    "辣椒灰霉病": ["辣椒灰霉"],
    "辣椒病毒病": ["辣椒花叶病"],
    "茄子绵疫病": ["茄子绵疫"],
    "茄子青枯病": ["茄子青枯"],
    "茄子黄萎病": ["茄子黄萎"],
    "茄子褐纹病": ["茄子褐纹"],
    "茄子白粉病": ["茄子白粉"],
    "西瓜枯萎病": ["西瓜枯萎"],
    "西瓜炭疽病": ["西瓜炭疽"],
    "西瓜蔓枯病": ["西瓜蔓枯"],
    "西瓜白粉病": ["西瓜白粉"],
    "西瓜疫病": ["西瓜疫"],
    "甜瓜白粉病": ["甜瓜白粉"],
    "甜瓜霜霉病": ["甜瓜霜霉"],
    "南瓜白粉病": ["南瓜白粉"],
    "冬瓜疫病": ["冬瓜疫"],
    "丝瓜霜霉病": ["丝瓜霜霉"],
    "苦瓜白粉病": ["苦瓜白粉"],
    "草莓灰霉病": ["草莓灰霉"],
    "草莓白粉病": ["草莓白粉"],
    "马铃薯早疫病": ["土豆早疫", "马铃薯早疫"],
    "马铃薯晚疫病": ["土豆晚疫", "马铃薯晚疫", "土豆晚疫病"],
    "马铃薯青枯病": ["马铃薯青枯"],
    "稻瘟病": ["水稻稻瘟", "水稻叶瘟", "水稻穗颈瘟", "稻热病"],
    "水稻稻瘟病": ["稻瘟病", "水稻稻瘟", "水稻叶瘟", "水稻穗颈瘟", "穗颈瘟", "叶瘟", "稻热病"],
    "水稻纹枯病": ["水稻烂秆病"],
    "水稻白叶枯病": ["水稻白叶枯"],
    "水稻细菌性条斑病": ["稻细菌性条斑病", "水稻细菌条斑", "水稻细条病", "水稻条斑病"],
    "玉米大斑病 / 小斑病": ["玉米大斑病", "玉米小斑病", "玉米大斑", "玉米小斑", "玉米叶斑病"],
    "玉米茎腐病": ["玉米茎腐", "玉米细菌性茎腐病"],
    "玉米粗缩病": ["玉米粗缩"],
    "玉米锈病": ["玉米锈", "玉米普通锈病", "玉米南方锈病"],
    "玉米丝黑穗病": ["玉米黑穗病", "玉米黑粉病", "玉米乌米", "玉米灰包"],
    "玉米纹枯病": ["玉米纹枯"],
    "玉米穗腐病": ["玉米穗腐"],
    "玉米螟": ["玉米钻心虫", "玉米钻心"],
    "苹果炭疽病 / 轮纹病": ["苹果炭疽病", "苹果轮纹病", "苹果炭疽", "苹果轮纹"],
    "苹果腐烂病": ["苹果烂皮病", "苹果腐烂"],
    "梨黑星病": ["梨黑星"],
    "葡萄白腐病 / 霜霉病": ["葡萄白腐病", "葡萄白腐", "葡萄霜霉病", "葡萄霜霉"],
    "葡萄黑痘病": ["葡萄黑痘", "葡萄疮痂病"],
    "柑橘溃疡病": ["柑橘溃疡"],
    "柑橘疮痂病": ["柑橘疮痂"],
    "桃细菌性穿孔病": ["桃穿孔病", "桃细菌穿孔"],
    "桃褐腐病": ["桃褐腐"],
    "桃缩叶病": ["桃缩叶"],
    "白菜软腐病": ["白菜软腐", "大白菜软腐病"],
    "白菜黑腐病": ["白菜黑腐"],
    "白菜菌核病": ["白菜菌核"],
    "白菜霜霉病": ["白菜霜霉"],
    "花生叶斑病": ["花生褐斑病", "花生黑斑病"],
    "花生青枯病": ["花生青枯"],
    "茶叶炭疽病": ["茶炭疽病", "茶树炭疽病", "茶树炭疽"],
    "马铃薯环腐病": ["马铃薯环腐"],
    "苹果蚜虫": ["苹果蚜"],
    "水稻稻飞虱": ["稻飞虱"],
    "稻纵卷叶螟": ["稻纵卷叶虫", "稻纵卷螟"],
    "甜菜夜蛾": ["甜菜虫"],
    "菜青虫": ["菜粉蝶", "白粉蝶幼虫"],
    "小菜蛾": ["小菜蛾幼虫", "吊丝虫"],
    "棉铃虫": ["钻心虫", "番茄夜蛾"],
    "蚜虫": ["蜜虫", "腻虫", "菜蚜", "麦蚜", "棉蚜"],
    "红蜘蛛": ["叶螨", "朱砂叶螨", "二斑叶螨"],
    "白粉虱": ["粉虱", "小白蛾"],
    "潜叶蝇": ["潜叶虫"],
    "夜蛾": ["夜蛾幼虫"],
    "螟虫": ["螟"],
    "金龟子": ["金龟甲"],
    "蛴螬": ["蛴螬虫"],
    "蝼蛄": ["蝼蛄虫"],
    "地老虎": ["地蚕"],
    "蛀干虫": ["蛀干害虫"],
    "茶小绿叶蝉": ["茶小绿叶蝉", "茶小绿蝉"],
}


def _generate_aliases(name):
    """根据病名自动生成常见别名(用于关键词匹配)"""
    aliases = {name}

    # 1. 去掉括号内容(学名等)
    aliases.add(name.split('(')[0].split('（')[0].strip())

    # 2. 细菌/真菌 前缀简化
    for prefix in ['细菌性', '细菌', '真菌性', '真菌']:
        if name.startswith(prefix):
            aliases.add(name[len(prefix):])
            break

    # 3. 数字/汉字替换
    name_simple = name
    for old, new in [('大斑', '大'), ('小斑', '小'), ('白粉', ''), ('锈病', '锈')]:
        name_simple = name_simple.replace(old, new)
    if name_simple != name:
        aliases.add(name_simple)

    # 4. common_aliases 手工别名
    if name in _COMMON_ALIASES:
        aliases.update(_COMMON_ALIASES[name])

    # 5. 口语化简称
    if "丝黑穗" in name:
        aliases.add(name.replace("丝黑穗", "黑穗"))
    if "细菌性条斑" in name:
        aliases.add(name.replace("细菌性条斑", "细菌条斑"))
        aliases.add(name.replace("细菌性条斑病", "细条病"))
    # "X 病 / Y 病" 拆开
    if " / " in name:
        for sub in name.split(" / "):
            aliases.add(sub.strip())
    if "、 " in name or "、" in name:
        for sub in name.replace("、 ", "、").split("、"):
            aliases.add(sub.strip())

    return list(aliases)


# ============================================================
# 2. 通用 actions(很多病没在 skill 文档列具体步骤,补充)
# ============================================================
_DEFAULT_ACTIONS = [
    {"step": 1, "title": "清除病残体", "description": "摘除病叶、病果,带出田块销毁,减少病原越冬"},
    {"step": 2, "title": "加强田间管理", "description": "合理密植,加强通风,降低田间湿度"},
    {"step": 3, "title": "药剂防治", "description": "见下方处方,发病初期及时喷药"},
]


def _infer_category(name):
    if "缺" in name and any(k in name for k in ['氮', '磷', '钾', '铁', '镁', '硼', '锌', '硫', '钙']):
        return "缺素"
    if "药害" in name:
        return "药害"
    if any(k in name for k in ['虫', '蚜', '螨', '蛾', '螟', '虱', '青虫', '棉铃', '斜纹', '甜菜', '食心', '潜叶', '蛀', '金龟', '蛴螬', '蝼蛄', '地老虎', '小菜']):
        return "虫害"
    if "草" in name and "除" in name:
        return "药害"
    return "病害"


def _infer_severity(name, safety):
    high_kw = ['检疫性', '毁灭性', '无药可治', '必须砍除', '毁园', '不可治', '枯萎', '青枯', '黄龙', '晚疫', '白叶枯', '细菌性条斑']
    if any(k in name or k in safety for k in high_kw):
        return "高"
    low_kw = ['缺素', '叶斑', '白粉', '锈', '斑点', '煤污', '病毒', '黄化', '药害']
    if any(k in name for k in low_kw):
        return "中"
    return "中"


# ============================================================
# 3. 补充 SKILL 没覆盖的(虫害 + 缺素 + 药害)
# ============================================================
_EXTRA_DATA = {
    "蚜虫": {
        "category": "虫害", "pathogen": "害虫(蚜虫科)", "severity": "中",
        "key_visual_clues": ["叶片有密集小虫", "叶背有虫", "叶片皱缩", "有蜜露"],
        "actions": [
            {"step": 1, "title": "物理防治", "description": "黄板诱杀(每亩 30-40 张)"},
            {"step": 2, "title": "保护天敌", "description": "保护瓢虫、草蛉等天敌"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,虫口密度大时用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "10% 吡虫啉可湿性粉剂", "dose": "2000-3000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "25% 噻虫嗪水分散粒剂", "dose": "3000-5000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "50% 抗蚜威可湿性粉剂", "dose": "2000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7 天一次,连续 1-2 次,重点喷叶背",
            "safety_warning": "蚜虫易产生抗药性,轮换用药,采收前 7-14 天停药",
        },
    },
    "红蜘蛛": {
        "category": "虫害", "pathogen": "害虫(叶螨科)", "severity": "中",
        "key_visual_clues": ["叶片有细密黄白色斑点", "叶背有红色小点", "叶片失绿发黄"],
        "actions": [
            {"step": 1, "title": "清除虫源", "description": "清除田边杂草和落叶,减少越冬虫源"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,点片发生时及时用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "1.8% 阿维菌素乳油", "dose": "3000-5000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "15% 哒螨灵乳油", "dose": "2000-3000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7-10 天一次,连续 2 次,叶背重点喷",
            "safety_warning": "红蜘蛛易产生抗药性,轮换用药,采收前 7-14 天停药",
        },
    },
    "白粉虱": {
        "category": "虫害", "pathogen": "害虫(粉虱科)", "severity": "中",
        "key_visual_clues": ["叶片有白色小蛾子", "叶背有虫和卵", "有蜜露污染"],
        "actions": [
            {"step": 1, "title": "物理防治", "description": "黄板诱杀(每亩 30-40 张)"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "10% 吡虫啉可湿性粉剂", "dose": "2000-3000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "25% 噻虫嗪水分散粒剂", "dose": "3000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次,叶背重点喷",
            "safety_warning": "白粉虱世代重叠,需连续用药,采收前 7 天停药",
        },
    },
    "菜青虫": {
        "category": "虫害", "pathogen": "害虫(鳞翅目粉蝶科)", "severity": "中",
        "key_visual_clues": ["叶片有咬食孔洞", "叶面有绿色幼虫", "有绿色虫粪"],
        "actions": [
            {"step": 1, "title": "人工捕杀", "description": "幼龄期人工捕捉幼虫和卵块"},
            {"step": 2, "title": "保护天敌", "description": "保护赤眼蜂、瓢虫等天敌"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,3 龄前用药效果最好"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "1.8% 阿维菌素乳油", "dose": "2000-3000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "5% 氯虫苯甲酰胺悬浮剂", "dose": "1000 倍液", "method": "叶面喷雾", "interval_days": 10, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7-10 天一次,连续 1-2 次,3 龄前用药",
            "safety_warning": "采收前 7 天停药,叶菜类尤其注意",
        },
    },
    "棉铃虫": {
        "category": "虫害", "pathogen": "害虫(鳞翅目夜蛾科)", "severity": "高",
        "key_visual_clues": ["果实有蛀孔", "果实内有幼虫", "叶片有咬食痕迹"],
        "actions": [
            {"step": 1, "title": "物理防治", "description": "黑光灯或性诱剂诱杀成虫"},
            {"step": 2, "title": "人工捕杀", "description": "清晨人工捕捉幼虫"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,卵孵化盛期至 2 龄前用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "5% 氯虫苯甲酰胺悬浮剂", "dose": "1000-1500 倍液", "method": "叶面喷雾", "interval_days": 10, "max_times": 2, "preharvest_days": 7},
                {"name": "1.8% 阿维菌素乳油", "dose": "2000-3000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7-10 天一次,连续 1-2 次,卵孵化期用药",
            "safety_warning": "棉铃虫抗药性强,需轮换用药,采收前 7 天停药",
        },
    },
    "缺氮": {
        "category": "缺素", "pathogen": "缺氮", "severity": "中",
        "key_visual_clues": ["老叶先发黄", "叶片均匀黄化", "植株矮小"],
        "actions": [
            {"step": 1, "title": "追施氮肥", "description": "每亩追施尿素 8-10 公斤,或碳酸氢铵 20-30 公斤"},
            {"step": 2, "title": "叶面喷施", "description": "用 1-2% 尿素溶液叶面喷施,见效快"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "尿素(含 N 46%)", "dose": "8-10 公斤/亩", "method": "追施土壤", "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "1-2% 尿素溶液", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7-10 天后视情况再追一次,叶面喷施见效快",
            "safety_warning": "避免过量,过量易徒长倒伏",
        },
    },
    "缺磷": {
        "category": "缺素", "pathogen": "缺磷", "severity": "中",
        "key_visual_clues": ["叶片暗绿或紫红色", "老叶先出现", "植株矮小"],
        "actions": [
            {"step": 1, "title": "追施磷肥", "description": "每亩追施过磷酸钙 20-30 公斤"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.2-0.3% 磷酸二氢钾叶面喷施"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "过磷酸钙", "dose": "20-30 公斤/亩", "method": "追施土壤", "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "磷酸二氢钾(0.3%)", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7-10 天后再喷一次",
            "safety_warning": "磷肥利用率低,可与有机肥混施",
        },
    },
    "缺钾": {
        "category": "缺素", "pathogen": "缺钾", "severity": "中",
        "key_visual_clues": ["老叶叶尖和叶缘发黄", "后期焦枯", "叶片有褐色斑点"],
        "actions": [
            {"step": 1, "title": "追施钾肥", "description": "每亩追施氯化钾 10-15 公斤,或硫酸钾 15-20 公斤"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.3-0.5% 磷酸二氢钾叶面喷施"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "氯化钾", "dose": "10-15 公斤/亩", "method": "追施土壤", "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "磷酸二氢钾(0.5%)", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7-10 天后再喷一次,根外追肥见效快",
            "safety_warning": "忌氯作物(烟草、马铃薯)用硫酸钾代替",
        },
    },
    "缺铁": {
        "category": "缺素", "pathogen": "缺铁", "severity": "中",
        "key_visual_clues": ["新叶发黄", "叶脉绿色叶肉黄色", "严重时新叶变白"],
        "actions": [
            {"step": 1, "title": "叶面喷施", "description": "用 0.1-0.2% 硫酸亚铁溶液叶面喷施"},
            {"step": 2, "title": "土壤补铁", "description": "每亩施硫酸亚铁 2-3 公斤,与有机肥混施"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "硫酸亚铁(0.2%)", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 5, "max_times": 3, "preharvest_days": None},
                {"name": "硫酸亚铁", "dose": "2-3 公斤/亩", "method": "土壤施用", "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "5-7 天一次,连续 2-3 次",
            "safety_warning": "碱性土壤易缺铁,可配柠檬酸增加吸收",
        },
    },
    "缺镁": {
        "category": "缺素", "pathogen": "缺镁", "severity": "中",
        "key_visual_clues": ["老叶叶脉间发黄", "叶脉保持绿色", "后期叶肉变褐"],
        "actions": [
            {"step": 1, "title": "叶面喷施", "description": "用 0.5-1% 硫酸镁溶液叶面喷施"},
            {"step": 2, "title": "土壤补镁", "description": "每亩施硫酸镁 10-15 公斤"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "硫酸镁(1%)", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
                {"name": "硫酸镁", "dose": "10-15 公斤/亩", "method": "土壤施用", "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "7-10 天后再喷一次",
            "safety_warning": "酸性土壤易缺镁,石灰过量会加重",
        },
    },
    "缺硼": {
        "category": "缺素", "pathogen": "缺硼", "severity": "中",
        "key_visual_clues": ["新叶畸形皱缩", "顶芽枯死", "花而不实", "果实畸形"],
        "actions": [
            {"step": 1, "title": "叶面喷施", "description": "用 0.1-0.2% 硼砂溶液叶面喷施"},
            {"step": 2, "title": "土壤补硼", "description": "每亩施硼砂 0.5-1 公斤"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "硼砂(0.2%)", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
                {"name": "硼砂", "dose": "0.5-1 公斤/亩", "method": "土壤施用", "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "花前 7-10 天再喷一次,促进授粉结实",
            "safety_warning": "硼过量易中毒,严格按剂量",
        },
    },
    "除草剂药害": {
        "category": "药害", "pathogen": "除草剂(草甘膦、莠去津等)", "severity": "中",
        "key_visual_clues": ["新叶畸形发黄", "叶片有白色或褐色斑点", "生长点坏死"],
        "actions": [
            {"step": 1, "title": "大量浇水", "description": "立即浇大水,稀释土壤中除草剂浓度"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.01% 芸苔素内酯 + 1% 尿素溶液叶面喷施,缓解药害"},
            {"step": 3, "title": "加强管理", "description": "中耕松土,增施有机肥,促进根系恢复"},
        ],
        "prescription": {
            "title": "缓解处方",
            "chemicals": [
                {"name": "0.01% 芸苔素内酯水剂", "dose": "3000-5000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "1-2% 尿素溶液", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7 天一次,连续 2 次,促进恢复",
            "safety_warning": "轻度药害可恢复,严重时无救,需补种",
        },
    },
    "杀虫剂药害": {
        "category": "药害", "pathogen": "杀虫剂(菊酯类、有机磷等)", "severity": "中",
        "key_visual_clues": ["叶片有褐色或白色斑点", "叶片卷曲", "果实有斑点"],
        "actions": [
            {"step": 1, "title": "大量浇水", "description": "立即浇大水,稀释残留农药"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.01% 芸苔素内酯 + 0.3% 磷酸二氢钾叶面喷施"},
            {"step": 3, "title": "剪除受害组织", "description": "剪除受害严重的新梢和叶片"},
        ],
        "prescription": {
            "title": "缓解处方",
            "chemicals": [
                {"name": "0.01% 芸苔素内酯水剂", "dose": "3000-5000 倍液", "method": "叶面喷雾", "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "磷酸二氢钾(0.3%)", "dose": "30-50 公斤/亩", "method": "叶面喷施", "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7 天一次,连续 2 次,促进恢复",
            "safety_warning": "严格按照说明书剂量使用,避免在高温烈日下喷药",
        },
    },
}


# ============================================================
# 4. 构建 DISEASE_KB
# ============================================================
DISEASE_KB = {}

# 先从 skill 数据(208 个)
for item in _RAW_DATA:
    name = item["name"]
    chemicals = item.get("chemicals", [])
    actions = item.get("actions", []) or _DEFAULT_ACTIONS
    followup = item.get("followup", "") or "7-10 天一次,连喷 2-3 次"
    safety = item.get("safety_warning", "") or "严格按说明使用,采收前 7-21 天停药"

    # 表格里的 cells 转成 chemicals
    rx_chems = []
    for c in chemicals:
        rx_chems.append({
            "name": c.get("name", ""),
            "dose": c.get("dose", ""),
            "method": c.get("method", ""),
            "note": c.get("note", ""),
        })

    DISEASE_KB[name] = {
        "category": _infer_category(name),
        "pathogen": "见详细方案",
        "severity": _infer_severity(name, safety),
        "key_visual_clues": [],
        "actions": actions,
        "prescription": {
            "title": "药剂处方",
            "chemicals": rx_chems,
            "followup": followup,
            "safety_warning": safety,
        },
        "aliases": _generate_aliases(name),
    }

# 补充 SKILL 没覆盖的(虫害 + 缺素 + 药害)
for name, info in _EXTRA_DATA.items():
    if name not in DISEASE_KB:
        DISEASE_KB[name] = {**info, "aliases": _generate_aliases(name)}


# ============================================================
# 5. 关键词索引(用于 search_kb)
# ============================================================
def _build_index():
    index = {}
    for canonical_name, info in DISEASE_KB.items():
        aliases = info.get("aliases", [])
        for alias in [canonical_name] + aliases:
            if alias and alias not in index:
                index[alias] = {"canonical": canonical_name, "data": info}
    return index


KB_INDEX = _build_index()


def search_kb(text_query):
    """根据用户文字问诊查询知识库,返回最长匹配的疾病信息

    Args:
        text_query: 用户文字(如"玉米黑穗病怎么治")
    Returns:
        dict { matched: bool, canonical_name, data } 或 None
    """
    if not text_query or not text_query.strip():
        return None

    text = text_query.strip()
    best_match = None
    best_len = 0

    for alias, info in KB_INDEX.items():
        if alias in text and len(alias) > best_len:
            best_match = info
            best_len = len(alias)

    if best_match:
        return {
            "matched": True,
            "canonical_name": best_match["canonical"],
            "data": best_match["data"],
        }
    return None
