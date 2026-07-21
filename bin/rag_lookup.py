#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rag_lookup.py — 作物病害 RAG(检索增强)模块

工作流程(简化版 MVP,国内 stack):
  1. 预生成阶段(一次性,见 precompute_descriptions.py):
     - 用 GLM-4V 给图库里每张图出 1-2 句特征描述
     - 存到 meta.json 的 description 字段
  2. 查询阶段(每次诊断):
     - GLM-4V 描述 query 图(1 次调用)
     - 用 query 描述 跟 库图描述 做文本相似度匹配(Jaccard 关键词 / BGE embedding)
     - 取 top-K 库图,拼成参考描述注入 diagnosis prompt

为什么不直接用 vision embedding 检索:
- 智谱 GLM-4V 单次推理只支持 1 张图,没法同时看 query + N 张参考图对比
- 调多次 GLM-4V 描述+对比 = token 贵、慢
- 折中:用 text 描述做对比,top-K 后**只把文字描述**注入 prompt,不附图(GLM-4V 也不用看参考图)
- 省 token,加速,效果不差太多(text 描述够用)

国内 stack(避免国外平台):
- LLM/视觉:智谱 GLM-4V(matrix daemon 已经在用)
- text embedding(可选,升级用):BGE(智源)/ M3E(智源+达摩院) — 本地 ONNX
- 向量检索(可选):FAISS(本地)
- 存储:本地 D 盘 npy/json
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

# 不 rewrap stream(避免 PowerShell + Python 3.14 下 close 问题)
# 写中文用 print(s, flush=True) 即可;GBK 编码在 print 时 Python 会 fallback

# ===== 默认配置 =====
DEFAULT_DB_ROOT = r"D:\作物病害图"
DEFAULT_TOP_K = 5

# ===== 关键词表(病名别名 + 关键症状) =====
# 用于增强文本匹配,而不是纯字符串 Jaccard
# 来自 detailed-prescription.md 各章节的关键词
KEYWORD_SYNONYMS = {
    # 真菌病害
    "叶霉病": ["叶霉", "霉层", "橄榄绿", "绒毛", "褪绿斑", "叶背", "番茄叶霉", "Passalora", "Cladosporium"],
    "早疫病": ["早疫", "同心轮纹", "轮纹斑", "褐色斑", "Alternaria", "solani", "早疫轮纹"],
    "晚疫病": ["晚疫", "水渍", "水渍状", "白霉", "叶背白霉", "Phytophthora", "infestans", "晚疫霉"],
    "灰霉病": ["灰霉", "灰白色霉", "絮状霉", "Botrytis", "cinerea", "花器腐烂", "果实灰霉"],
    "白粉病": ["白粉", "白粉状", "面粉状", "Oidium", "neolycopersici", "叶面白粉"],
    "斑枯病": ["斑枯", "鱼鳞状", "鱼鳞斑", "小白点", "Septoria", "白星病", "Septoria lycopersici"],
    "白绢病": ["白绢", "白色绢丝", "菌核", "油菜籽", "Sclerotium", "rolfsii", "茎基部白绢"],
    # 细菌病害
    "青枯病": ["青枯", "萎蔫", "维管束变褐", "白色菌脓", "白天萎蔫晚上恢复", "Ralstonia", "solanacearum"],
    "细菌性斑点病": ["细菌性斑点", "细菌斑点", "小褐斑", "水渍小斑", "Xanthomonas", "vesicatoria", "细菌性角斑"],
    # 病毒
    "斑萎病": ["斑萎", "同心轮纹", "铜色花叶", "TSWV", "tospovirus", "番茄斑萎病毒", "褐色条纹"],
    # 线虫
    "根结线虫病": ["根结线虫", "根瘤", "根结", "小米粒", "Meloidogyne", "incognita"],
    # 其他常见
    "枯萎病": ["枯萎", "维管束变褐", "Fusarium", "oxysporum", "无白色菌脓", "整株枯死"],
    # ===== 虫害关键词(2026-07-17 加;目录独立保留为 D:\\作物病害图\\虫害\\<害虫>\\) =====
    "蚜虫": ["蚜虫", "蜜虫", "腻虫", "桃蚜", "棉蚜", "菜蚜", "黄蚜", "绿蚜", "黑蚜", "烟蚜", "萝卜蚜", "麦二叉蚜", "麦长管蚜", "桃粉蚜", "Aphis", "gossypii"],
    "红蜘蛛": ["红蜘蛛", "叶螨", "朱砂叶螨", "二斑叶螨", "黄蜘蛛", "火龙", "茶黄螨", "侧多食跗线螨", "红叶螨", "叶背红点", "结网", "Tetranychus", "urticae", "cinnabarinus"],
    "白粉虱": ["白粉虱", "小白蛾", "温室白粉虱", "小白虫", "粉虱", "Trialeurodes", "vaporariorum"],
    "烟粉虱": ["烟粉虱", "B型烟粉虱", "银叶粉虱", "Q型烟粉虱", "MEAM1", "MED", "Bemisia", "tabaci", "烟粉虱若虫"],
    "蓟马": ["蓟马", "葱蓟马", "西花蓟马", "棕榈蓟马", "烟蓟马", "金翅蓟马", "稻蓟马", "花蓟马", "锉吸式口器", "Thrips", "palmi", "tabaci"],
    "菜青虫": ["菜青虫", "菜粉蝶幼虫", "青虫", "菜粉蝶", "白粉蝶幼虫", "Pieris", "rapae", "小青虫"],
    "斜纹夜蛾": ["斜纹夜蛾", "夜盗虫", "黑头虫", "烟草斜纹夜蛾", "斜纹夜蛾幼虫", "Spodoptera", "litura", "大龄幼虫", "体侧黄线"],
    "甜菜夜蛾": ["甜菜夜蛾", "白菜褐夜蛾", "甜菜夜蛾幼虫", "Spodoptera", "exigua", "甘蓝夜蛾", "小造桥虫", "体侧黄线", "绿色幼虫", "褐色幼虫", "气门黑点"],
    "棉铃虫": ["棉铃虫", "棉铃实夜蛾", "钻心虫", "棉铃虫幼虫", "Helicoverpa", "armigera", "玉米穗虫", "番茄钻心虫", "体表肉刺", "钻蛀花蕾", "体侧纵带", "绿色幼虫", "粉色幼虫", "褐色幼虫"],
    "地老虎": ["地老虎", "小地老虎", "黄地老虎", "大地老虎", "夜盗虫", "切根虫", "地老虎幼虫", "Agrotis", "ipsilon", "segetum", "灰褐色幼虫", "颗粒突起", "咬断茎基", "昼伏夜出", "卷曲成C形"],
    "蛞蝓": ["蛞蝓", "鼻涕虫", "黏虫蛞蝓", "野蛞蝓", "黄蛞蝓", "灰蛞蝓", "Agriolimax", "agrestis", "Limax", "软体动物", "触角", "腹足", "黏液痕迹", "银色爬痕"],
    "蜗牛": ["蜗牛", "灰蜗牛", "条华蜗牛", "散大蜗牛", "白玉蜗牛", "褐云玛瑙螺", "非洲大蜗牛", "Achatina", "fulica", "Cathaica", "软体动物", "螺旋壳", "触角", "腹足", "黏液", "舔食叶肉", "咬断幼苗"],
    "绿盲蝽": ["绿盲蝽", "盲蝽", "苜蓿盲蝽", "三点盲蝽", "中黑盲蝽", "Apolygus", "lucorum", "Lygus", "Halticus", "楯形前翅", "膜质部褐色", "绿色若虫", "棉花盲蝽", "茶盲蝽", "苜蓿盲蝽", "破头疯", "破叶疯", "多头症", "顶芽枯死"],
    "茶尺蠖": ["茶尺蠖", "茶尺蛾", "造桥虫", "茶尺蠖幼虫", "Ectropis", "obliqua", "茶园尺蠖", "拱桥姿态", "拟态枝条", "斜立如枝", "腹足2对", "尺蠖状", "茶褐色幼虫", "啃食茶叶", "边缘缺刻"],
    "金针虫": ["金针虫", "叩头虫幼虫", "金针虫幼虫", "沟金针虫", "细胸金针虫", "褐纹金针虫", "Elateridae", "Agriotes", "细长圆筒", "金黄色幼虫", "茶褐色幼虫", "体壁坚硬", "无腹足", "3对胸足短小", "咬食根系", "咬食块茎", "地下害虫"],
    "东亚飞蝗": ["东亚飞蝗", "飞蝗", "亚洲飞蝗", "西藏飞蝗", "Locusta", "migratoria", "manilensis", "蝗虫", "蚂蚱", "群集型", "迁飞型", "散居型", "黄褐色", "绿褐色", "后足跳跃", "遮天蔽日", "暴发性", "黄淮海流域", "历史性蝗灾", "禾本科", "牧草", "啃食叶肉"],
    "凤蝶": ["凤蝶", "柑橘凤蝶", "玉带凤蝶", "达摩凤蝶", "花椒凤蝶", "金凤蝶", "凤蝶幼虫", "Papilio", "xuthus", "polytes", "demoleus", "machaon", "燕尾", "尾突", "橙色眼斑", "Y形臭腺", "臭角", "深绿幼虫", "深褐幼虫", "鸟粪幼虫"],
    "蛴螬": ["蛴螬", "金龟子幼虫", "金龟甲幼虫", "鳃金龟", "丽金龟", "花金龟", "蛴螬幼虫", "Scarabaeidae", "白色幼虫", "C形蜷曲", "头壳红褐", "腹末黑色", "横皱褶", "咬食根系", "咬食块根", "地下害虫"],
    "蝼蛄": ["蝼蛄", "东方蝼蛄", "华北蝼蛄", "台湾蝼蛄", "土狗子", "啦啦蛄", "Gryllotalpa", "orientalis", "unispina", "开掘足", "铲状前足", "前足特化", "挖隧道", "夜间出土", "咕咕声", "咬断幼根"],
    "稻纵卷叶螟": ["稻纵卷叶螟", "卷叶虫", "稻纵卷叶螟幼虫", "Cnaphalocrocis", "medinalis", "水稻卷叶螟", "黄绿色幼虫", "细长幼虫", "吐丝纵卷", "卷叶为害", "啃食叶肉", "白叶苞"],
    "二化螟": ["二化螟", "二化螟幼虫", "钻心虫", "水稻钻心虫", "Chilo", "suppressalis", "螟虫", "体背5条纵线", "淡褐色幼虫", "钻蛀稻茎", "枯心", "白穗", "枯孕穗"],
    "稻飞虱": ["稻飞虱", "褐飞虱", "白背飞虱", "灰飞虱", "Nilaparvata", "lugens", "Sogatella", "furcifera", "Laodelphax", "striatellus", "长翅型", "短翅型", "后足跳跃", "刺吸式", "虱烧", "穿顶", "团粒不实", "传毒虫媒", "条纹叶枯病", "黑条矮缩病"],
    "黄曲条跳甲": ["黄曲条跳甲", "跳甲", "黄条跳甲", "黄曲条菜跳甲", "Phyllotreta", "striolata", "黄条叶甲", "曲条跳甲", "黄曲条跳甲成虫", "后足跳跃", "密集小孔", "叶面虫孔", "十字花科害虫", "白菜跳甲", "萝卜跳甲"],
    "蚧壳虫": ["蚧壳虫", "蚧", "介壳虫", "蜡蚧", "盾蚧", "绵蚧", "粉蚧", "Coccoidea", "吹绵蚧", "Icerya", "purchasi", "桑白蚧", "矢尖蚧", "梨圆蚧", "红蜡蚧", "草履蚧", "白蜡蚧", "白蚧壳", "蜡丝", "固定枝条", "刺吸式", "煤污病", "树势衰弱", "枝条枯死"],
    "木虱": ["木虱", "梨木虱", "柑橘木虱", "桑木虱", "枸杞木虱", "中国梨木虱", "Psylla", "pyricola", "柑橘木虱成虫", "黄绿色若虫"],
}

# ===== 类别常量(目录结构区分) =====
# 目录布局: <db_root>/<crop>/<disease>/(病害,两层)
#       或: <db_root>/虫害/<pest>/(虫害,两层 — 独立保留,不许删不许合并)
CATEGORY_DISEASE = "病害"
CATEGORY_PEST = "虫害"
PEST_CATEGORY_DIR = "虫害"  # 顶级目录名 = 虫害类别
DEFAULT_PEST_CROP = "通用"   # 虫害图通常不绑具体作物(用户后续可填具体作物如"番茄")


def tokenize_chinese(text):
    """中文文本分词(简单实现,2-gram 切分)

    例子: "叶正面有橄榄绿霉层" -> ["叶正", "正面", "面有", "有橄", "橄榄", "榄绿", "绿霉", "霉层"]
    """
    text = re.sub(r"[^\w]", "", text)
    if len(text) < 2:
        return [text]
    # 1-gram + 2-gram
    tokens = set()
    tokens.update(text)  # 1-gram
    for i in range(len(text) - 1):
        tokens.add(text[i:i+2])  # 2-gram
    return list(tokens)


# P1-1 (2026-07-20 加): 部位词典 — 部位(叶正/叶背/果实/雄穗/嫩端等)
# 对诊断关键, 2-gram 区分不开(叶正面 vs 叶背 差一个字但 Jaccard 仍 ~0.9)
PART_TOKENS = [
    "叶正面", "叶背", "叶面", "果实", "茎基", "根部",
    "嫩端", "嫩叶", "叶鞘", "雄穗", "果穗", "苞叶",
    "薯块", "芡粒", "花霉", "果肉", "苡端",
    # 虫害专属
    "虫体", "子虫", "若虫", "成虫", "蛰虫", "幼虫",
]

def jaccard_similarity(text_a, text_b):
    """Jaccard 相似度(2-gram + 部位词加权)"""
    set_a = set(tokenize_chinese(text_a or ""))
    set_b = set(tokenize_chinese(text_b or ""))
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    base = len(intersection) / len(union)
    # P1-1: 部位词加权(字符级匹配, 2-gram 区分不开补上)
    common_parts = sum(1 for p in PART_TOKENS if p in (text_a or "") and p in (text_b or ""))
    return base + common_parts * 0.05


KEYWORD_BOOST_CAP = 0.4  # P1-2 v2 (2026-07-20 修): 调高上限 0.15→0.4(上一版本 0.0187 太弱)  # P2-3 (2026-07-20 修): 实际历史是 0.15→0.4,不是 0.3→0.4

def keyword_boost(query_text, disease):
    """疾病名关键词加权(归一化 + cap, v2 2026-07-20)

    设计调整: 旧版本每命中 +0.1(上限 1.7, 全靠近 Jaccard)
    中间版本归一化上 0.15(上限 0.15, 会失效)
    v2: 归一化 × 0.5 + 1 hit 套上底 0.05(上限 0.4)
    """
    synonyms = KEYWORD_SYNONYMS.get(disease, [disease])
    if not synonyms:
        return 0.0
    n_synonyms = max(len(synonyms), 1)
    n_hits = sum(1 for kw in synonyms if kw and kw in query_text)
    if n_hits == 0:
        return 0.0
    # 归一化: 1 个 hit 贡献约 0.05, 17 hits 贡献 ≈ 0.4(cap)
    return min(0.05 + (n_hits / n_synonyms) * 0.5, KEYWORD_BOOST_CAP)


# ===== 描述生成(query 阶段) =====

def build_describe_prompt(crop_hint=None):
    """构造 GLM-4V 描述 prompt

    要求 1-2 句中文,覆盖:作物部位 + 病斑形态 + 颜色 + 关键特征(霉/粉/斑/水渍等)
    """
    if crop_hint:
        crop_line = "已知作物:{0}。\n".format(crop_hint)
    else:
        crop_line = ""
    return (
        "你是一名资深植保员。请用 1-2 句中文(50 字内)描述这张图的关键症状,用于后续检索。\n"
        "必须包含:1)部位(叶正面/叶背/果实/茎秆/根部),2)病斑形态(圆形/不规则/水渍/轮纹/霉层/粉状...),3)颜色。\n"
        "不要寒暄,不要诊断结论,只描述所见。\n"
        "{0}"
        "示例输出:叶正面散生褐色小圆斑,边缘深褐,中心灰白,无明显霉层。\n"
        "你的描述:"
    ).format(crop_line)


# ===== 库加载 + 索引 =====

# P2-8 (2026-07-20 修): 简单内存缓存 + invalidate()
_LOAD_DB_CACHE = {}

def invalidate_load_db_cache():
    """清空 load_db 缓存(新增图后调用, 不用重启)"""
    _LOAD_DB_CACHE.clear()

def load_db(db_root, crop_filter=None, disease_filter=None, category_filter=None):
    """加载图库元数据(从每个病目录的 meta.json)

    支持双结构(2026-07-17 起,虫害独立保留):
      - 病害(老): <db_root>/<crop>/<disease>/meta.json  → category="病害"
      - 虫害(新): <db_root>/<虫害>/<pest>/meta.json      → category="虫害"
                  顶级目录名 PEST_CATEGORY_DIR = "虫害"
                  crop 字段:从 meta.json.crop 读,缺省 "通用"

    输入:
    - db_root: 图库根目录
    - crop_filter: 可选,只取某作物的病(如 "番茄")或某害虫的"作物归属"(如 "番茄")
    - disease_filter: 可选,只取某病/某害虫(如 "叶霉病" 或 "蚜虫")
    - category_filter: 可选,限定 category("病害"/"虫害"),None=全要

    输出: list of {"path", "category", "crop", "disease", "description", "source"}
    """
    # P2-8: 缓存检查
    cache_key = (str(db_root), crop_filter, disease_filter, category_filter)
    if cache_key in _LOAD_DB_CACHE:
        return _LOAD_DB_CACHE[cache_key]
    db_root = Path(db_root)
    if not db_root.exists():
        return []

    out = []
    # 扫所有顶级目录(病害作物目录 + 虫害顶级目录)
    top_dirs = (
        [db_root / crop_filter] if crop_filter
        else sorted([d for d in db_root.iterdir() if d.is_dir() and not d.name.startswith("_")])
    )

    for top_dir in top_dirs:
        if not top_dir.is_dir():
            continue
        top_name = top_dir.name

        # 判定 category:顶级目录名 == PEST_CATEGORY_DIR → 虫害,其他 → 病害
        is_pest_category = (top_name == PEST_CATEGORY_DIR)
        category = CATEGORY_PEST if is_pest_category else CATEGORY_DISEASE

        # category 过滤
        if category_filter and category != category_filter:
            continue

        for sub_dir in sorted(top_dir.iterdir()):
            if not sub_dir.is_dir():
                continue
            sub_name = sub_dir.name  # 病害 = disease名,虫害 = 害虫名

            # disease / pest 名过滤
            if disease_filter and sub_name != disease_filter:
                continue

            meta_path = sub_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            for entry in meta:
                desc = entry.get("description")
                if not desc:
                    # 没预生成描述的图,跳过(必须有描述才能检索)
                    continue

                # P1-4 (2026-07-20 修): 统一从 entry.crop 读, fallback 到目录名
                # 之前病害忽略 entry.crop(老逻辑仅用目录名), 造成
                # 语义不一致(虫害从 entry 读, 病害从目录). 现统一。
                if is_pest_category:
                    entry_crop = entry.get("crop") or DEFAULT_PEST_CROP
                else:
                    entry_crop = entry.get("crop") or top_name  # 老数据 meta 没 crop 字段时回退目录名

                # crop 过滤
                if crop_filter and entry_crop != crop_filter:
                    continue

                out.append({
                    "path": str(sub_dir / entry["filename"]),
                    "category": category,
                    "crop": entry_crop,
                    "disease": sub_name,
                    "description": desc,
                    "source": entry.get("source", ""),
                })
    # P2-8: 写缓存
    _LOAD_DB_CACHE[cache_key] = out
    return out


# ===== 主检索函数 =====

def crop_priority_boost(entry_crop, user_crop_hint):
    """B1 排序优先级:具体作物图 > 通用图 > 其它作物图

    - entry_crop == user_crop_hint(精确匹配)→ +0.20
    - entry_crop == "通用"(中性兜底)     →  0.00
    - 其它情况                            → -0.10
    - user_crop_hint 为空(用户没报作物)   →  0.00
    """
    if not user_crop_hint:
        return 0.0
    if entry_crop == user_crop_hint:
        return 0.20
    if entry_crop == DEFAULT_PEST_CROP:  # "通用" 中性
        return 0.0
    return -0.10


def lookup(query_description, db_root, top_k=DEFAULT_TOP_K, crop_filter=None,
           disease_filter=None, method="jaccard+keyword",
           user_crop_hint=None, category_filter=None):
    """用 query 描述在图库中检索 top-K 相似

    输入:
    - query_description: GLM-4V 生成的 query 图描述(1-2 句中文)
    - db_root: 图库根目录
    - top_k: 返回多少条
    - crop_filter: 限定作物(精确过滤,只查这个作物)
    - disease_filter: 限定病(精确过滤,只查这个病/害虫)
    - method: 评分方法
        - "jaccard": 纯 2-gram Jaccard
        - "jaccard+keyword": Jaccard + 关键词加权(推荐)
        - "keyword": 纯关键词匹配
    - user_crop_hint: 用户报出的作物(如 "番茄"),用于 B1 排序加权,**不**作精确过滤
    - category_filter: 限定 category("病害"/"虫害"),None=全要

    输出: list of {"path", "category", "crop", "disease", "description", "score", "rank"}
    """
    db = load_db(
        db_root,
        crop_filter=crop_filter,
        disease_filter=disease_filter,
        category_filter=category_filter,
    )
    if not db:
        return []

    # 评分
    scored = []
    for entry in db:
        if method == "jaccard":
            score = jaccard_similarity(query_description, entry["description"])
        elif method == "keyword":
            # 纯关键词:每命中一个 disease / pest 的关键词 +1/n_synonyms
            synonyms = KEYWORD_SYNONYMS.get(entry["disease"], [entry["disease"]])
            hits = sum(1 for kw in synonyms if kw and kw in query_description)
            score = hits / max(len(synonyms), 1)
        else:  # "jaccard+keyword"
            score = jaccard_similarity(query_description, entry["description"])
            score += keyword_boost(query_description, entry["disease"])
        # B1:作物归属排序加权
        score += crop_priority_boost(entry.get("crop", ""), user_crop_hint)
        entry_copy = dict(entry)
        entry_copy["score"] = round(score, 4)
        scored.append(entry_copy)

    # 排序
    scored.sort(key=lambda e: e["score"], reverse=True)
    for rank, e in enumerate(scored[:top_k], 1):
        e["rank"] = rank
    return scored[:top_k]


def format_rag_references(refs, max_chars=800):
    """把 top-K 参考拼成注入 prompt 的文本

    P1-3 (2026-07-20 修): 逐行均分 max_chars, 不再整行丢弃
    之前为了不超 max_chars, 超出后后续 top-K 候选整行丢弃(不公平)
    """
    if not refs:
        return ""
    # P1-3: 均分 max_chars 给每行, 保证所有 top-K 都出现
    n = len(refs)
    fixed_overhead = 12  # "参考图 N:[X/Y] " 前缀
    per_line_budget = max(40, (max_chars - n * fixed_overhead) // n)
    lines = []
    for r in refs:
        category = r.get("category", CATEGORY_DISEASE)
        disease = r.get("disease", "?")
        if category == CATEGORY_PEST:
            tag = "{0}/{1}".format(CATEGORY_PEST, disease)
        else:
            crop = r.get("crop", "?")
            tag = "{0}/{1}".format(crop, disease)
        desc = (r.get("description") or "")[:per_line_budget]
        line = "参考图 {0}:[{1}] {2}".format(
            r.get("rank", "?"),
            tag,
            desc,
        )
        lines.append(line)
    return "\n".join(lines)


def format_rag_candidates_table(refs):
    """把 top-K 参考拼成 markdown 表格,用于 {{rag_candidates}} 占位符(2026-07-20 加)

    输出格式:markdown 表格,每行一张候选图
      | rank | category | crop/disease | rag_score | description |
      | ---- | -------- | ------------ | --------- | ----------- |
      | 1    | 病害     | 番茄/早疫病   | 0.8523    | 叶片有... |
      | 2    | 病害     | 番茄/晚疫病   | 0.7150    | ... |
      | 3    | 虫害     | 虫害/蚜虫    | 0.6523    | ... |

    适合:让 LLM 在诊断时看到结构化候选(有 score 排序);
    比 format_rag_references 更结构化,适合 rag_lookup 性能评估/调优。
    """
    if not refs:
        return ""
    lines = [
        "| rank | category | crop/disease | rag_score | description |",
        "| ---- | -------- | ------------ | --------- | ----------- |",
    ]
    for r in refs:
        category = r.get("category", CATEGORY_DISEASE)
        disease = r.get("disease", "?")
        if category == CATEGORY_PEST:
            tag = "{0}/{1}".format(CATEGORY_PEST, disease)
        else:
            crop = r.get("crop", "?")
            tag = "{0}/{1}".format(crop, disease)
        rank = r.get("rank", "?")
        score = r.get("score", 0.0)
        desc = (r.get("description") or "").replace("|", "/").replace("\n", " ")[:100]
        lines.append("| {0} | {1} | {2} | {3:.4f} | {4} |".format(
            rank, category, tag, score, desc
        ))
    return "\n".join(lines)


# ===== 描述生成(库图预生成时用) =====

def build_precompute_prompt(crop_name, disease_name, category=CATEGORY_DISEASE):
    """库图描述 prompt — 已知病/害虫名,出更精准的描述

    2026-07-17 适配虫害独立:
    - category="病害" → "已知作物+已知病害",prompt 要求描述霉/粉/脓等病征
    - category="虫害" → "已知作物+已知害虫",prompt 要求描述虫体形态/聚集部位/为害状
    """
    if category == CATEGORY_PEST:
        # 虫害:虫体形态 + 聚集部位 + 为害状
        target_label = "害虫"
        return (
            "你是一名资深植保员。已知作物:{0},已知害虫:{1}。\n"
            "请用 1-2 句中文(50 字内)客观描述这张图的视觉特征,用于后续检索同类害虫图。\n"
            "必须包含:1)虫体形态(颜色/大小/体节/有无翅/若虫或成虫),\n"
            "2)聚集部位(叶正面/叶背/嫩梢/果实/茎秆),\n"
            "3)数量与分布(单只/成群/成片/线状排列),\n"
            "4)为害状(叶片皱缩/褪绿/煤污/虫瘿/缺刻/蛀孔等,无则写「为害状不显」)。\n"
            "不要寒暄,不要重复「已知」,直接写描述。\n"
            "示例:叶背密集黄绿色小虫,体长 1-2 mm,部分有翅成虫;嫩梢叶面皱缩、可见蜜露。\n"
            "你的描述:"
        ).format(crop_name, disease_name)
    else:
        # 病害:病斑形态 + 颜色 + 霉/粉/脓
        target_label = "病害"
        return (
            "你是一名资深植保员。已知作物:{0},已知病害:{1}。\n"
            "请用 1-2 句中文(50 字内)客观描述这张图的视觉症状,用于后续检索同类病图。\n"
            "必须包含:1)部位(叶正面/叶背/果实/茎秆/根部),2)病斑形态(形状/边缘/分布),3)颜色,4)有无霉层/粉/脓。\n"
            "不要寒暄,不要重复「已知」,直接写描述。\n"
            "示例:叶正面散生褐色小圆斑,边缘深褐,中心灰白,叶背无明显霉层。\n"
            "你的描述:"
        ).format(crop_name, disease_name)


# ===== CLI =====

def main():
    ap = argparse.ArgumentParser(
        description="RAG 检索:用 query 描述在图库中找 top-K 相似",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-q", "--query-desc", required=True, help="query 描述文本(GLM-4V 生成)")
    ap.add_argument("--db-root", default=DEFAULT_DB_ROOT, help="图库根目录")
    ap.add_argument("-k", "--top-k", type=int, default=DEFAULT_TOP_K, help="返回 top-K")
    ap.add_argument("-c", "--crop", help="限定作物(如 番茄)")
    ap.add_argument("-d", "--disease", help="限定病/害虫(如 叶霉病 或 蚜虫)")
    ap.add_argument("--user-crop", help="用户报出的作物(用于 B1 排序加权,不作过滤)")
    ap.add_argument("--category", choices=[CATEGORY_DISEASE, CATEGORY_PEST],
                    help="限定 category(病害/虫害),默认全要")
    ap.add_argument("--method", default="jaccard+keyword",
                    choices=["jaccard", "keyword", "jaccard+keyword"])
    ap.add_argument("--format", choices=["json", "text", "rag"], default="text",
                    help="输出格式:json(完整)/text(列表)/rag(注入 prompt 的文本)")
    args = ap.parse_args()

    refs = lookup(
        args.query_desc, args.db_root,
        top_k=args.top_k, crop_filter=args.crop, disease_filter=args.disease,
        method=args.method, user_crop_hint=args.user_crop,
        category_filter=args.category,
    )

    if args.format == "json":
        print(json.dumps(refs, ensure_ascii=False, indent=2))
    elif args.format == "rag":
        print(format_rag_references(refs))
    else:
        for r in refs:
            category = r.get("category", CATEGORY_DISEASE)
            if category == CATEGORY_PEST:
                tag = "{0}/{1}".format(CATEGORY_PEST, r["disease"])
            else:
                tag = "{0}/{1}".format(r["crop"], r["disease"])
            print("[rank {0}] score={1:.4f}  [{2}]  category={3}".format(
                r["rank"], r["score"], tag, category))
            print("    {0}".format(r["path"]))
            print("    描述: {0}".format(r["description"]))
            print()


if __name__ == "__main__":
    main()
