# -*- coding: utf-8 -*-
"""
disease_kb.py — 文字问诊"知识库直出"数据库

覆盖 30+ 常见作物问题(病害/虫害/缺素症/药害),每条包含:
  - category: 病害/虫害/缺素/药害
  - pathogen: 病原(真菌/细菌/病毒/害虫/缺素/药剂)
  - severity: 高/中/低
  - key_visual_clues: 关键识别线索
  - actions: 农户可执行步骤
  - prescription: 药剂处方(化学品 + 剂量 + 间隔 + 安全警告)
  - followup: 复喷/复查节奏
  - safety_warning: 安全提醒
  - aliases: 关键词别名(用户文字问诊命中用)

数据来源:公开农业知识(中国农技推广中心、《中国农作物病虫害防治》、
各省植保站手册等通用推荐),不针对特定地区/品种。

知识库命中率:用户文字问诊时(如"玉米黑穗病怎么治"),先扫 aliases,
命中 → 直接出方案 + 标记 _no_need_image=true,前端隐藏"补图"提示。
不命中 → 走原智谱文字模式(可能要求补图)。
"""

DISEASE_KB = {
    # ============ 玉米(6) ============
    "玉米大斑病": {
        "category": "病害", "pathogen": "真菌(大斑凸脐蠕孢属)", "severity": "高",
        "key_visual_clues": ["叶片有大型梭形病斑", "病斑长 5-10cm", "灰褐色或黄褐色"],
        "actions": [
            {"step": 1, "title": "清除病残体", "description": "收获后彻底清除田间病株残体,集中销毁或深埋,减少越冬菌源"},
            {"step": 2, "title": "轮作倒茬", "description": "与豆科、十字花科作物轮作 2-3 年,避免连作"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,发病初期(病斑率 5-10%)及时喷药"},
            {"step": 4, "title": "科学施肥", "description": "增施磷钾肥,避免偏施氮肥,提高植株抗病力"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "50% 多菌灵可湿性粉剂", "dose": "500-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "75% 百菌清可湿性粉剂", "dose": "500-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "25% 吡唑醚菌酯乳油", "dose": "1500-2000 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7-10 天复喷一次,连续 2-3 次,雨后及时补喷",
            "safety_warning": "严格按说明使用,注意防护,采收前 7-21 天停药(看具体药剂)",
        },
        "aliases": ["玉米大斑病", "玉米大斑", "玉米条斑病", "玉米梭斑病"],
    },
    "玉米小斑病": {
        "category": "病害", "pathogen": "真菌(玉蜀黍平脐蠕孢属)", "severity": "中",
        "key_visual_clues": ["叶片小椭圆形病斑", "病斑长 1-2cm", "边缘有黄晕"],
        "actions": [
            {"step": 1, "title": "选抗病品种", "description": "选用抗病杂交种,优先抗小斑病的品种"},
            {"step": 2, "title": "减少菌源", "description": "秸秆还田时粉碎后深翻,加速腐解"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,抽雄前后重点防治"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "70% 甲基托布津可湿性粉剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "75% 百菌清可湿性粉剂", "dose": "600-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2 次,重点喷施中下部叶片",
            "safety_warning": "严格按说明使用,采收前 7-21 天停药",
        },
        "aliases": ["玉米小斑病", "玉米小斑"],
    },
    "玉米黑穗病": {
        "category": "病害", "pathogen": "真菌(丝轴黑粉菌)", "severity": "高",
        "key_visual_clues": ["果穗变黑", "黑粉状物", "病株矮化", "雄穗畸形"],
        "actions": [
            {"step": 1, "title": "拔除病株", "description": "苗期至抽雄前发现病株及时拔除,带出田块深埋或烧毁(病菌在土壤中可存活 3 年)"},
            {"step": 2, "title": "种子处理", "description": "播种前用杀菌剂包衣或拌种,见下方处方"},
            {"step": 3, "title": "轮作倒茬", "description": "与大豆、小麦等非寄主作物轮作 3 年以上"},
            {"step": 4, "title": "选抗病品种", "description": "选用抗丝黑穗病的杂交种"},
        ],
        "prescription": {
            "title": "种子处理处方",
            "chemicals": [
                {"name": "12.5% 烯唑醇可湿性粉剂", "dose": "种子重量的 0.2%", "method": "种子包衣",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "50% 福美双可湿性粉剂", "dose": "种子重量的 0.3%", "method": "种子拌种",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "种子包衣后 1-2 天内播种,效果最佳;田间抽雄前持续拔除病株",
            "safety_warning": "包衣剂有毒,操作时戴手套口罩,包衣种子不可食用或饲用",
        },
        "aliases": ["玉米黑穗病", "玉米丝黑穗病", "玉米黑粉病", "玉米乌米", "玉米灰包"],
    },
    "玉米锈病": {
        "category": "病害", "pathogen": "真菌(柄锈菌属)", "severity": "中",
        "key_visual_clues": ["叶片有黄褐色或红褐色锈粉", "病斑密集分布", "叶片黄化"],
        "actions": [
            {"step": 1, "title": "摘除病叶", "description": "摘除最严重的病叶并带出田块销毁"},
            {"step": 2, "title": "加强通风降湿", "description": "合理密植,降低田间湿度,提高通风"},
            {"step": 3, "title": "化学防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "25% 三唑酮可湿性粉剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 14},
                {"name": "12.5% 烯唑醇可湿性粉剂", "dose": "2000 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "10-15 天复喷一次,连续 2 次,重点喷施中上部叶片",
            "safety_warning": "严格按说明使用,采收前 14-21 天停药",
        },
        "aliases": ["玉米锈病", "玉米普通锈病", "玉米南方锈病"],
    },
    "玉米纹枯病": {
        "category": "病害", "pathogen": "真菌(立枯丝核菌)", "severity": "中",
        "key_visual_clues": ["叶鞘和茎基部有云纹状病斑", "病斑灰白色", "后期有褐色菌核"],
        "actions": [
            {"step": 1, "title": "降低田间湿度", "description": "开沟排水,合理密植,改善通风"},
            {"step": 2, "title": "剥除病叶鞘", "description": "发病初期剥除基部病叶鞘,带出田外"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,重点喷施茎基部"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "5% 井冈霉素水剂", "dose": "500-800 倍液", "method": "茎基部喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "50% 多菌灵可湿性粉剂", "dose": "500 倍液", "method": "茎基部喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7 天复喷一次,连续 2 次,雨后及时补喷",
            "safety_warning": "采收前 14-21 天停药",
        },
        "aliases": ["玉米纹枯病", "玉米烂茎病"],
    },
    "玉米茎基腐病": {
        "category": "病害", "pathogen": "真菌(多种镰刀菌复合)", "severity": "高",
        "key_visual_clues": ["茎基部变褐腐烂", "整株萎蔫", "果穗下垂"],
        "actions": [
            {"step": 1, "title": "及时排水", "description": "低洼田块开沟排水,避免田间积水"},
            {"step": 2, "title": "拔除重病株", "description": "重病株整株拔除销毁,减少菌源"},
            {"step": 3, "title": "药剂灌根", "description": "见下方处方,发病初期灌根处理"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "58% 甲霜灵·锰锌可湿性粉剂", "dose": "500 倍液", "method": "灌根,每株 250-500ml",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "10 天后再灌一次,雨后及时补灌",
            "safety_warning": "严格按说明使用,采收前 21 天停药",
        },
        "aliases": ["玉米茎基腐病", "玉米青枯病"],
    },

    # ============ 水稻(4) ============
    "稻瘟病": {
        "category": "病害", "pathogen": "真菌(稻梨孢菌)", "severity": "高",
        "key_visual_clues": ["叶瘟有梭形病斑", "穗颈瘟有褐色病斑", "白穗或半白穗"],
        "actions": [
            {"step": 1, "title": "选用抗病品种", "description": "因地制宜选用抗稻瘟病品种"},
            {"step": 2, "title": "科学肥水", "description": "控制氮肥用量,增施磷钾肥;浅水勤灌,晒田控蘖"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,叶瘟初见时和抽穗前各防一次"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "75% 三环唑可湿性粉剂", "dose": "1500-2000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "40% 稻瘟灵乳油", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "25% 吡唑醚菌酯乳油", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7-10 天复喷一次,穗颈瘟在破口期和齐穗期各防一次",
            "safety_warning": "严格按说明使用,采收前 14-21 天停药",
        },
        "aliases": ["稻瘟病", "水稻稻瘟", "水稻叶瘟", "水稻穗颈瘟", "稻热病"],
    },
    "水稻纹枯病": {
        "category": "病害", "pathogen": "真菌(立枯丝核菌)", "severity": "高",
        "key_visual_clues": ["叶鞘有云纹状病斑", "病斑边缘褐色", "后期有菌核"],
        "actions": [
            {"step": 1, "title": "晒田控蘖", "description": "分蘖末期适度晒田,控制无效分蘖"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,分蘖盛期和孕穗期重点防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "5% 井冈霉素水剂", "dose": "500-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "30% 苯甲·丙环唑乳油", "dose": "3000 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7-10 天复喷一次,重点喷水稻中下部",
            "safety_warning": "采收前 14-21 天停药",
        },
        "aliases": ["水稻纹枯病", "水稻烂秆病"],
    },
    "水稻白叶枯病": {
        "category": "病害", "pathogen": "细菌(黄单胞杆菌)", "severity": "高",
        "key_visual_clues": ["叶缘有黄白色条斑", "病斑有黄色菌脓", "整叶枯白"],
        "actions": [
            {"step": 1, "title": "选用抗病品种", "description": "选用抗白叶枯病水稻品种"},
            {"step": 2, "title": "种子消毒", "description": "用 85% 强氯精 300 倍液浸种"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,发现病株立即用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "20% 噻菌铜悬浮剂", "dose": "500-700 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "72% 农用链霉素可湿性粉剂", "dose": "4000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7 天一次,连续 2-3 次,台风或暴雨后及时补喷",
            "safety_warning": "细菌性病害,雨后高温高湿易爆发,严防扩散",
        },
        "aliases": ["水稻白叶枯病", "水稻白叶枯"],
    },
    "水稻稻曲病": {
        "category": "病害", "pathogen": "真菌(稻绿核菌)", "severity": "中",
        "key_visual_clues": ["稻穗有墨绿色或黄色菌球", "菌球表面有粉状物", "谷粒膨大变形"],
        "actions": [
            {"step": 1, "title": "选用抗病品种", "description": "优先选抗稻曲病品种"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,孕穗末期(破口前 5-7 天)用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "30% 苯甲·丙环唑乳油", "dose": "3000 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 1, "preharvest_days": 21},
                {"name": "5% 井冈霉素水剂", "dose": "500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 1, "preharvest_days": 14},
            ],
            "followup": "孕穗末期(破口前 5-7 天)用一次即可",
            "safety_warning": "稻曲病带毒,病粒不可食用或饲用,集中销毁",
        },
        "aliases": ["稻曲病", "水稻稻曲", "水稻青粉病"],
    },

    # ============ 番茄(5) ============
    "番茄早疫病": {
        "category": "病害", "pathogen": "真菌(茄链格孢)", "severity": "中",
        "key_visual_clues": ["叶片有褐色圆形病斑", "同心轮纹", "病斑周围黄化"],
        "actions": [
            {"step": 1, "title": "摘除病叶", "description": "摘除老叶病叶,带出田块销毁"},
            {"step": 2, "title": "加强通风", "description": "合理密植,降低棚内湿度,减少结露"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,发病初期及时用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "75% 百菌清可湿性粉剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "50% 异菌脲可湿性粉剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "10% 苯醚甲环唑水分散粒剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7-10 天一次,连续 2-3 次",
            "safety_warning": "采收前 7-14 天停药,严格执行安全间隔期",
        },
        "aliases": ["番茄早疫病", "番茄早疫"],
    },
    "番茄晚疫病": {
        "category": "病害", "pathogen": "真菌(致病疫霉)", "severity": "高",
        "key_visual_clues": ["叶片有水渍状病斑", "边缘模糊", "叶背有白色霉层"],
        "actions": [
            {"step": 1, "title": "严控湿度", "description": "棚内湿度控制在 80% 以下,加强通风排湿"},
            {"step": 2, "title": "拔除重病株", "description": "重病株整株拔除销毁,避免扩散"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,发病初期立即用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "72% 霜脲·锰锌可湿性粉剂", "dose": "600-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "50% 烯酰吗啉可湿性粉剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "68% 精甲霜·锰锌水分散粒剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次,雨后立即补喷",
            "safety_warning": "晚疫病传播极快,需全棚统防统治,采收前 7 天停药",
        },
        "aliases": ["番茄晚疫病", "番茄晚疫", "番茄疫病"],
    },
    "番茄青枯病": {
        "category": "病害", "pathogen": "细菌(青枯假单胞菌)", "severity": "高",
        "key_visual_clues": ["白天萎蔫早晚恢复", "茎基部有褐色条纹", "横切面有白色菌脓"],
        "actions": [
            {"step": 1, "title": "拔除病株", "description": "发现病株立即拔除,撒石灰消毒穴坑"},
            {"step": 2, "title": "轮作", "description": "与禾本科作物轮作 4 年以上"},
            {"step": 3, "title": "药剂灌根", "description": "见下方处方,病株周围植株灌根预防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "72% 农用链霉素可湿性粉剂", "dose": "4000 倍液", "method": "灌根,每株 250ml",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "20% 噻菌铜悬浮剂", "dose": "500 倍液", "method": "灌根",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7-10 天复灌一次,连续 2-3 次",
            "safety_warning": "细菌性维管束病害,无药可救,重在预防",
        },
        "aliases": ["番茄青枯病", "番茄青枯"],
    },
    "番茄病毒病": {
        "category": "病害", "pathogen": "病毒(多种)", "severity": "中",
        "key_visual_clues": ["叶片花叶斑驳", "叶片皱缩畸形", "植株矮化"],
        "actions": [
            {"step": 1, "title": "治虫防病", "description": "病毒由蚜虫、粉虱传播,先治虫"},
            {"step": 2, "title": "拔除病株", "description": "重病株拔除销毁,减少毒源"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,钝化病毒缓解症状"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "20% 盐酸吗啉胍·铜可湿性粉剂", "dose": "500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "10% 吡虫啉可湿性粉剂", "dose": "2000 倍液", "method": "叶面喷雾(治蚜虫粉虱)",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次,同时治虫",
            "safety_warning": "病毒病无药可治,以防为主,采收前 7 天停药",
        },
        "aliases": ["番茄病毒病", "番茄花叶病", "番茄卷叶病"],
    },
    "番茄灰霉病": {
        "category": "病害", "pathogen": "真菌(灰葡萄孢)", "severity": "中",
        "key_visual_clues": ["果实有灰褐色霉层", "花瓣和叶片有水渍状腐烂", "潮湿时灰色霉层明显"],
        "actions": [
            {"step": 1, "title": "降湿通风", "description": "棚内湿度降到 70% 以下,加强通风"},
            {"step": 2, "title": "清除病果病花", "description": "及时摘除病果、病花和病叶"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,优先用烟剂熏蒸"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "50% 腐霉利可湿性粉剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "40% 嘧霉胺悬浮剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "10% 腐霉利烟剂", "dose": "200-300g/亩", "method": "棚内熏蒸",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2 次,阴雨天优先用烟剂",
            "safety_warning": "采收前 7 天停药",
        },
        "aliases": ["番茄灰霉病", "番茄灰霉"],
    },

    # ============ 黄瓜(4) ============
    "黄瓜白粉病": {
        "category": "病害", "pathogen": "真菌(白粉菌属)", "severity": "中",
        "key_visual_clues": ["叶片正面有白色粉状物", "后期变灰白色", "叶片枯黄"],
        "actions": [
            {"step": 1, "title": "加强通风", "description": "合理密植,及时整枝打老叶,改善通风"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,发病初期及时用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "25% 三唑酮可湿性粉剂", "dose": "2000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "10% 苯醚甲环唑水分散粒剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 7},
                {"name": "50% 醚菌酯水分散粒剂", "dose": "3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7-10 天一次,连续 2 次,叶正反两面都要喷到",
            "safety_warning": "采收前 7 天停药",
        },
        "aliases": ["黄瓜白粉病", "黄瓜白粉", "瓜类白粉病"],
    },
    "黄瓜霜霉病": {
        "category": "病害", "pathogen": "真菌(古巴假霜霉)", "severity": "高",
        "key_visual_clues": ["叶片有黄色多角形病斑", "叶背有紫黑色霉层", "潮湿时叶背有水珠"],
        "actions": [
            {"step": 1, "title": "严控湿度", "description": "棚内湿度 70% 以下,加强通风排湿"},
            {"step": 2, "title": "高温闷棚", "description": "晴天上午关闭风口闷棚 2 小时(温度 45°C 左右),闷后通风"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,发病初期立即用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "72% 霜脲·锰锌可湿性粉剂", "dose": "600-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "50% 烯酰吗啉可湿性粉剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "68.75% 氟菌·霜霉威悬浮剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 5},
            ],
            "followup": "7 天一次,连续 2-3 次,重点喷叶背",
            "safety_warning": "霜霉病传播快,采收前 5-7 天停药",
        },
        "aliases": ["黄瓜霜霉病", "黄瓜霜霉", "瓜类霜霉病", "跑马干"],
    },
    "黄瓜细菌性角斑病": {
        "category": "病害", "pathogen": "细菌(丁香假单胞菌)", "severity": "中",
        "key_visual_clues": ["叶片有水渍状多角形病斑", "后期病斑变褐穿孔", "潮湿时有白色菌脓"],
        "actions": [
            {"step": 1, "title": "种子消毒", "description": "50°C 温水浸种 20 分钟,或用 1% 盐酸浸种 15 分钟"},
            {"step": 2, "title": "降湿通风", "description": "棚内湿度 70% 以下,加强通风"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,细菌性病害用铜制剂或链霉素"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "77% 氢氧化铜可湿性粉剂", "dose": "500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "72% 农用链霉素可湿性粉剂", "dose": "4000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次,雨后及时补喷",
            "safety_warning": "细菌性病害,采收前 7 天停药",
        },
        "aliases": ["黄瓜细菌性角斑病", "黄瓜角斑病", "黄瓜细菌角斑"],
    },
    "黄瓜枯萎病": {
        "category": "病害", "pathogen": "真菌(尖孢镰刀菌)", "severity": "高",
        "key_visual_clues": ["白天萎蔫早晚恢复", "茎基部有褐色条纹", "维管束变褐"],
        "actions": [
            {"step": 1, "title": "选用抗病品种", "description": "选用抗枯萎病黄瓜品种"},
            {"step": 2, "title": "轮作", "description": "与非瓜类作物轮作 3-5 年"},
            {"step": 3, "title": "药剂灌根", "description": "见下方处方,病株周围植株灌根预防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "50% 多菌灵可湿性粉剂", "dose": "500 倍液", "method": "灌根,每株 250ml",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "70% 甲基托布津可湿性粉剂", "dose": "1000 倍液", "method": "灌根",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7-10 天复灌一次,连续 2-3 次",
            "safety_warning": "土传病害,重在轮作和抗病品种",
        },
        "aliases": ["黄瓜枯萎病", "黄瓜枯萎", "瓜类枯萎病"],
    },

    # ============ 辣椒(3) ============
    "辣椒炭疽病": {
        "category": "病害", "pathogen": "真菌(刺盘孢属)", "severity": "中",
        "key_visual_clues": ["果实有水渍状褐色病斑", "病斑凹陷有轮纹", "有橙红色粘稠物"],
        "actions": [
            {"step": 1, "title": "清除病果", "description": "摘除病果和病叶,带出田块销毁"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,发病初期及时用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "75% 百菌清可湿性粉剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "70% 甲基托布津可湿性粉剂", "dose": "800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7-10 天一次,连续 2-3 次",
            "safety_warning": "采收前 7-21 天停药",
        },
        "aliases": ["辣椒炭疽病", "辣椒炭疽"],
    },
    "辣椒疫病": {
        "category": "病害", "pathogen": "真菌(辣椒疫霉)", "severity": "高",
        "key_visual_clues": ["茎基部有褐色条斑", "整株萎蔫", "根部变褐腐烂"],
        "actions": [
            {"step": 1, "title": "严控湿度", "description": "高垄栽培,及时排水,降低田间湿度"},
            {"step": 2, "title": "拔除病株", "description": "拔除重病株,撒石灰消毒"},
            {"step": 3, "title": "药剂灌根", "description": "见下方处方,病株周围灌根预防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "72% 霜脲·锰锌可湿性粉剂", "dose": "600 倍液", "method": "灌根,每株 250ml",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "50% 烯酰吗啉可湿性粉剂", "dose": "1500 倍液", "method": "灌根",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7-10 天复灌一次,连续 2-3 次",
            "safety_warning": "疫病传播快,采收前 7 天停药",
        },
        "aliases": ["辣椒疫病"],
    },
    "辣椒疮痂病": {
        "category": "病害", "pathogen": "细菌(黄单胞杆菌)", "severity": "中",
        "key_visual_clues": ["叶片有水渍状小斑点", "病斑隆起疮痂状", "果实有褐色隆起病斑"],
        "actions": [
            {"step": 1, "title": "种子消毒", "description": "1% 硫酸铜液浸种 5 分钟"},
            {"step": 2, "title": "轮作", "description": "与非茄科作物轮作 2-3 年"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,细菌性病害用铜制剂"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "77% 氢氧化铜可湿性粉剂", "dose": "500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "72% 农用链霉素可湿性粉剂", "dose": "4000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次",
            "safety_warning": "细菌性病害,采收前 7 天停药",
        },
        "aliases": ["辣椒疮痂病", "辣椒疮痂"],
    },

    # ============ 其他作物(8) ============
    "茄子褐纹病": {
        "category": "病害", "pathogen": "真菌(茄褐纹拟茎点霉)", "severity": "中",
        "key_visual_clues": ["叶片有褐色圆形病斑", "病斑有同心轮纹", "果实有黑褐色凹陷病斑"],
        "actions": [
            {"step": 1, "title": "选用抗病品种", "description": "优先选抗褐纹病品种"},
            {"step": 2, "title": "种子消毒", "description": "55°C 温水浸种 15 分钟"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "75% 百菌清可湿性粉剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "70% 甲基托布津可湿性粉剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7-10 天一次,连续 2-3 次",
            "safety_warning": "采收前 7-21 天停药",
        },
        "aliases": ["茄子褐纹病", "茄子褐纹"],
    },
    "白菜软腐病": {
        "category": "病害", "pathogen": "细菌(胡萝卜软腐欧文氏菌)", "severity": "高",
        "key_visual_clues": ["叶柄基部有水渍状软腐", "有恶臭", "整株萎蔫倒伏"],
        "actions": [
            {"step": 1, "title": "拔除病株", "description": "发现病株立即拔除销毁,撒石灰消毒穴坑"},
            {"step": 2, "title": "治虫防病", "description": "用杀虫剂防菜青虫、跳甲等咬食害虫(伤口易感染)"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,病株周围灌根"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "72% 农用链霉素可湿性粉剂", "dose": "4000 倍液", "method": "灌根或喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "77% 氢氧化铜可湿性粉剂", "dose": "500 倍液", "method": "喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次",
            "safety_warning": "细菌性软腐,雨后高湿易爆发,采收前 7-14 天停药",
        },
        "aliases": ["白菜软腐病", "白菜软腐", "大白菜软腐病"],
    },
    "马铃薯晚疫病": {
        "category": "病害", "pathogen": "真菌(致病疫霉)", "severity": "高",
        "key_visual_clues": ["叶片有水渍状褐色病斑", "叶背有白色霉层", "块茎有褐色坏死斑"],
        "actions": [
            {"step": 1, "title": "选用抗病品种", "description": "优先选抗晚疫病品种"},
            {"step": 2, "title": "拔除病株", "description": "发现中心病株立即拔除销毁"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,发病初期立即用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "72% 霜脲·锰锌可湿性粉剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "50% 烯酰吗啉可湿性粉剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次,雨后立即补喷",
            "safety_warning": "晚疫病传播极快,采收前 7 天停药",
        },
        "aliases": ["马铃薯晚疫病", "马铃薯晚疫", "土豆晚疫病"],
    },
    "苹果黑星病": {
        "category": "病害", "pathogen": "真菌(苹果黑星菌)", "severity": "高",
        "key_visual_clues": ["叶片有橄榄绿色绒毛状病斑", "果实有黑褐色凹陷病斑", "病斑上有黑色霉层"],
        "actions": [
            {"step": 1, "title": "清除病源", "description": "秋冬彻底清扫果园,销毁落叶和病果"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,花后到套袋前重点防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "10% 苯醚甲环唑水分散粒剂", "dose": "2500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 3, "preharvest_days": 21},
                {"name": "80% 代森锰锌可湿性粉剂", "dose": "800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 21},
            ],
            "followup": "10 天一次,连续 3-4 次,套袋前最后 1 次",
            "safety_warning": "采收前 21 天停药",
        },
        "aliases": ["苹果黑星病", "苹果黑星", "苹果疮痂病"],
    },
    "葡萄白腐病": {
        "category": "病害", "pathogen": "真菌(白腐垫壳孢)", "severity": "高",
        "key_visual_clues": ["果穗有水渍状褐色病斑", "病果表面有灰白色小点", "叶片有褐色不规则病斑"],
        "actions": [
            {"step": 1, "title": "清除病源", "description": "秋冬彻底清园,销毁病果和落叶"},
            {"step": 2, "title": "提高结果部位", "description": "提高结果部位 50cm 以上,减少土传"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "75% 百菌清可湿性粉剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
                {"name": "10% 苯醚甲环唑水分散粒剂", "dose": "2000 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 3, "preharvest_days": 21},
            ],
            "followup": "7-10 天一次,连续 3-4 次,重点喷果穗",
            "safety_warning": "采收前 7-21 天停药",
        },
        "aliases": ["葡萄白腐病", "葡萄白腐"],
    },
    "柑橘溃疡病": {
        "category": "病害", "pathogen": "细菌(柑橘溃疡黄单胞菌)", "severity": "高",
        "key_visual_clues": ["叶片有黄色隆起病斑", "病斑木栓化", "果实有火山口状病斑"],
        "actions": [
            {"step": 1, "title": "检疫", "description": "调运苗木要检疫,防止扩散"},
            {"step": 2, "title": "剪除病枝", "description": "剪除病叶病枝,集中销毁"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,新梢期和幼果期重点防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "77% 氢氧化铜可湿性粉剂", "dose": "500-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 21},
                {"name": "20% 噻菌铜悬浮剂", "dose": "500 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
            ],
            "followup": "7-10 天一次,连续 2-3 次,雨后及时补喷",
            "safety_warning": "细菌性检疫病害,采收前 21 天停药",
        },
        "aliases": ["柑橘溃疡病", "柑橘溃疡"],
    },
    "柑橘黄龙病": {
        "category": "病害", "pathogen": "细菌(韧皮部杆菌)", "severity": "高",
        "key_visual_clues": ["叶片斑驳型黄化", "黄绿相间不对称", "果实小而畸形"],
        "actions": [
            {"step": 1, "title": "砍除病树", "description": "确诊病树立即砍除销毁,这是唯一有效办法"},
            {"step": 2, "title": "防治木虱", "description": "用杀虫剂严防柑橘木虱(传播媒介)"},
            {"step": 3, "title": "用无病苗", "description": "新种苗木必须是无病苗"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "10% 吡虫啉可湿性粉剂", "dose": "2000 倍液", "method": "叶面喷雾(防木虱)",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 14},
                {"name": "20% 噻虫嗪水分散粒剂", "dose": "3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7 天一次,连续防治木虱,新梢期重点",
            "safety_warning": "黄龙病是毁灭性病害,病树无药可治,必须砍除",
        },
        "aliases": ["柑橘黄龙病", "柑橘黄化病"],
    },
    "茶叶炭疽病": {
        "category": "病害", "pathogen": "真菌(茶炭疽菌)", "severity": "中",
        "key_visual_clues": ["成叶和老叶有不规则病斑", "病斑由黄褐色变灰白色", "边缘有黄褐色隆起线"],
        "actions": [
            {"step": 1, "title": "修剪清园", "description": "秋末修剪病枝病叶,集中销毁"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,梅雨季和秋季发病初期防"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "75% 百菌清可湿性粉剂", "dose": "600-800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "70% 甲基托布津可湿性粉剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7-10 天一次,连续 2 次",
            "safety_warning": "采茶前 7-14 天停药,严格执行",
        },
        "aliases": ["茶叶炭疽病", "茶炭疽病", "茶树炭疽病"],
    },
    "草莓灰霉病": {
        "category": "病害", "pathogen": "真菌(灰葡萄孢)", "severity": "中",
        "key_visual_clues": ["果实有灰褐色霉层", "花瓣和叶片有水渍状腐烂", "潮湿时灰色霉层明显"],
        "actions": [
            {"step": 1, "title": "降湿通风", "description": "棚内湿度降到 70% 以下,加强通风"},
            {"step": 2, "title": "清除病果", "description": "及时摘除病果病花"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "50% 腐霉利可湿性粉剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 5},
                {"name": "40% 嘧霉胺悬浮剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 5},
            ],
            "followup": "7 天一次,连续 2-3 次",
            "safety_warning": "草莓连续采摘,采收前 5 天停药",
        },
        "aliases": ["草莓灰霉病", "草莓灰霉"],
    },
    "花生叶斑病": {
        "category": "病害", "pathogen": "真菌(尾孢属和壳二孢属)", "severity": "中",
        "key_visual_clues": ["叶片有褐色或黑色圆形病斑", "病斑有黄色晕圈", "叶片早落"],
        "actions": [
            {"step": 1, "title": "清除病叶", "description": "收获后清除病残体,减少越冬菌源"},
            {"step": 2, "title": "轮作", "description": "与禾本科作物轮作 2-3 年"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "50% 多菌灵可湿性粉剂", "dose": "800 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 21},
                {"name": "75% 百菌清可湿性粉剂", "dose": "600 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 3, "preharvest_days": 7},
            ],
            "followup": "7-10 天一次,连续 2-3 次",
            "safety_warning": "采收前 7-21 天停药",
        },
        "aliases": ["花生叶斑病", "花生褐斑病", "花生黑斑病"],
    },

    # ============ 虫害(5) ============
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
                {"name": "10% 吡虫啉可湿性粉剂", "dose": "2000-3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "25% 噻虫嗪水分散粒剂", "dose": "3000-5000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "50% 抗蚜威可湿性粉剂", "dose": "2000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7 天一次,连续 1-2 次,重点喷叶背",
            "safety_warning": "蚜虫易产生抗药性,轮换用药,采收前 7-14 天停药",
        },
        "aliases": ["蚜虫", "蜜虫", "腻虫", "菜蚜", "麦蚜", "棉蚜"],
    },
    "红蜘蛛": {
        "category": "虫害", "pathogen": "害虫(叶螨科)", "severity": "中",
        "key_visual_clues": ["叶片有细密黄白色斑点", "叶背有红色小点", "叶片失绿发黄", "有蛛丝状物"],
        "actions": [
            {"step": 1, "title": "清除虫源", "description": "清除田边杂草和落叶,减少越冬虫源"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方,点片发生时及时用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "1.8% 阿维菌素乳油", "dose": "3000-5000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "15% 哒螨灵乳油", "dose": "2000-3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "5% 唑螨酯悬浮剂", "dose": "2000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
            ],
            "followup": "7-10 天一次,连续 2 次,叶背重点喷",
            "safety_warning": "红蜘蛛易产生抗药性,轮换用药,采收前 7-14 天停药",
        },
        "aliases": ["红蜘蛛", "叶螨", "朱砂叶螨", "二斑叶螨"],
    },
    "白粉虱": {
        "category": "虫害", "pathogen": "害虫(粉虱科)", "severity": "中",
        "key_visual_clues": ["叶片有白色小蛾子", "叶背有虫和卵", "有蜜露污染", "叶片萎黄"],
        "actions": [
            {"step": 1, "title": "物理防治", "description": "黄板诱杀(每亩 30-40 张)"},
            {"step": 2, "title": "药剂防治", "description": "见下方处方"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "10% 吡虫啉可湿性粉剂", "dose": "2000-3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "25% 噻虫嗪水分散粒剂", "dose": "3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "22% 噻虫·高氯氟悬浮剂", "dose": "3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7 天一次,连续 2-3 次,叶背重点喷",
            "safety_warning": "白粉虱世代重叠,需连续用药,采收前 7 天停药",
        },
        "aliases": ["白粉虱", "粉虱", "小白蛾"],
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
                {"name": "1.8% 阿维菌素乳油", "dose": "2000-3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
                {"name": "5% 氯虫苯甲酰胺悬浮剂", "dose": "1000 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 7},
                {"name": "20% 除虫脲悬浮剂", "dose": "1500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7-10 天一次,连续 1-2 次,3 龄前用药",
            "safety_warning": "采收前 7 天停药,叶菜类尤其注意",
        },
        "aliases": ["菜青虫", "菜粉蝶", "白粉蝶幼虫"],
    },
    "棉铃虫": {
        "category": "虫害", "pathogen": "害虫(鳞翅目夜蛾科)", "severity": "高",
        "key_visual_clues": ["果实有蛀孔", "果实内有幼虫", "叶片有咬食痕迹", "有虫粪"],
        "actions": [
            {"step": 1, "title": "物理防治", "description": "黑光灯或性诱剂诱杀成虫"},
            {"step": 2, "title": "人工捕杀", "description": "清晨人工捕捉幼虫"},
            {"step": 3, "title": "药剂防治", "description": "见下方处方,卵孵化盛期至 2 龄前用药"},
        ],
        "prescription": {
            "title": "药剂处方",
            "chemicals": [
                {"name": "5% 氯虫苯甲酰胺悬浮剂", "dose": "1000-1500 倍液", "method": "叶面喷雾",
                 "interval_days": 10, "max_times": 2, "preharvest_days": 7},
                {"name": "1.8% 阿维菌素乳油", "dose": "2000-3000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 7},
            ],
            "followup": "7-10 天一次,连续 1-2 次,卵孵化期用药",
            "safety_warning": "棉铃虫抗药性强,需轮换用药,采收前 7 天停药",
        },
        "aliases": ["棉铃虫", "钻心虫", "番茄夜蛾"],
    },

    # ============ 缺素症(5) ============
    "缺氮": {
        "category": "缺素", "pathogen": "缺氮", "severity": "中",
        "key_visual_clues": ["老叶先发黄", "叶片均匀黄化", "植株矮小", "新叶淡绿"],
        "actions": [
            {"step": 1, "title": "追施氮肥", "description": "每亩追施尿素 8-10 公斤,或碳酸氢铵 20-30 公斤"},
            {"step": 2, "title": "叶面喷施", "description": "用 1-2% 尿素溶液叶面喷施,见效快"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "尿素(含 N 46%)", "dose": "8-10 公斤/亩", "method": "追施土壤",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "尿素溶液(1-2%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7-10 天后视情况再追一次,叶面喷施见效快",
            "safety_warning": "避免过量,过量易徒长倒伏",
        },
        "aliases": ["缺氮", "氮素缺乏", "黄叶(缺氮)"],
    },
    "缺磷": {
        "category": "缺素", "pathogen": "缺磷", "severity": "中",
        "key_visual_clues": ["叶片暗绿或紫红色", "老叶先出现", "植株矮小", "分蘖少"],
        "actions": [
            {"step": 1, "title": "追施磷肥", "description": "每亩追施过磷酸钙 20-30 公斤,或磷酸二铵 10-15 公斤"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.2-0.3% 磷酸二氢钾叶面喷施"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "过磷酸钙", "dose": "20-30 公斤/亩", "method": "追施土壤",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "磷酸二氢钾(0.3%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7-10 天后再喷一次",
            "safety_warning": "磷肥利用率低,可与有机肥混施",
        },
        "aliases": ["缺磷", "磷素缺乏"],
    },
    "缺钾": {
        "category": "缺素", "pathogen": "缺钾", "severity": "中",
        "key_visual_clues": ["老叶叶尖和叶缘发黄", "后期焦枯", "叶片有褐色斑点", "易倒伏"],
        "actions": [
            {"step": 1, "title": "追施钾肥", "description": "每亩追施氯化钾 10-15 公斤,或硫酸钾 15-20 公斤"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.3-0.5% 磷酸二氢钾叶面喷施"},
        ],
        "prescription": {
            "title": "施肥处方",
            "chemicals": [
                {"name": "氯化钾", "dose": "10-15 公斤/亩", "method": "追施土壤",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
                {"name": "磷酸二氢钾(0.5%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7-10 天后再喷一次,根外追肥见效快",
            "safety_warning": "忌氯作物(烟草、马铃薯)用硫酸钾代替",
        },
        "aliases": ["缺钾", "钾素缺乏"],
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
                {"name": "硫酸亚铁(0.2%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 5, "max_times": 3, "preharvest_days": None},
                {"name": "硫酸亚铁", "dose": "2-3 公斤/亩", "method": "土壤施用",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "5-7 天一次,连续 2-3 次",
            "safety_warning": "碱性土壤易缺铁,可配柠檬酸增加吸收",
        },
        "aliases": ["缺铁", "铁素缺乏", "黄化(缺铁)"],
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
                {"name": "硫酸镁(1%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
                {"name": "硫酸镁", "dose": "10-15 公斤/亩", "method": "土壤施用",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "7-10 天后再喷一次",
            "safety_warning": "酸性土壤易缺镁,石灰过量会加重",
        },
        "aliases": ["缺镁", "镁素缺乏"],
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
                {"name": "硼砂(0.2%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
                {"name": "硼砂", "dose": "0.5-1 公斤/亩", "method": "土壤施用",
                 "interval_days": None, "max_times": 1, "preharvest_days": None},
            ],
            "followup": "花前 7-10 天再喷一次,促进授粉结实",
            "safety_warning": "硼过量易中毒,严格按剂量",
        },
        "aliases": ["缺硼", "硼素缺乏"],
    },

    # ============ 药害(2) ============
    "除草剂药害": {
        "category": "药害", "pathogen": "除草剂(草甘膦、莠去津等)", "severity": "中",
        "key_visual_clues": ["新叶畸形发黄", "叶片有白色或褐色斑点", "生长点坏死", "整株萎蔫"],
        "actions": [
            {"step": 1, "title": "大量浇水", "description": "立即浇大水,稀释土壤中除草剂浓度"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.01% 芸苔素内酯 + 1% 尿素溶液叶面喷施,缓解药害"},
            {"step": 3, "title": "加强管理", "description": "中耕松土,增施有机肥,促进根系恢复"},
        ],
        "prescription": {
            "title": "缓解处方",
            "chemicals": [
                {"name": "0.01% 芸苔素内酯水剂", "dose": "3000-5000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "1-2% 尿素溶液", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7 天一次,连续 2 次,促进恢复",
            "safety_warning": "轻度药害可恢复,严重时无救,需补种",
        },
        "aliases": ["除草剂药害", "药害(除草剂)", "草甘膦药害"],
    },
    "杀虫剂药害": {
        "category": "药害", "pathogen": "杀虫剂(菊酯类、有机磷等)", "severity": "中",
        "key_visual_clues": ["叶片有褐色或白色斑点", "叶片卷曲", "果实有斑点", "生长受抑"],
        "actions": [
            {"step": 1, "title": "大量浇水", "description": "立即浇大水,稀释残留农药"},
            {"step": 2, "title": "叶面喷施", "description": "用 0.01% 芸苔素内酯 + 0.3% 磷酸二氢钾叶面喷施"},
            {"step": 3, "title": "剪除受害组织", "description": "剪除受害严重的新梢和叶片"},
        ],
        "prescription": {
            "title": "缓解处方",
            "chemicals": [
                {"name": "0.01% 芸苔素内酯水剂", "dose": "3000-5000 倍液", "method": "叶面喷雾",
                 "interval_days": 7, "max_times": 2, "preharvest_days": 14},
                {"name": "磷酸二氢钾(0.3%)", "dose": "30-50 公斤/亩", "method": "叶面喷施",
                 "interval_days": 7, "max_times": 2, "preharvest_days": None},
            ],
            "followup": "7 天一次,连续 2 次,促进恢复",
            "safety_warning": "严格按照说明书剂量使用,避免在高温烈日下喷药",
        },
        "aliases": ["杀虫剂药害", "药害(杀虫剂)", "农药药害"],
    },
}


# 构建关键词索引(用于快速查询)
def _build_index():
    """disease_name -> { aliases: [list], data: dict }"""
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

    # 遍历所有别名,找最长匹配
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
