#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server/app.py — 征途问诊小程序后端

核心流程(两阶段):
  1. /api/identify          识别作物(走 crop-identifier skill)
  2. /api/diagnose         病害诊断(走 crop-disease-diagnosis skill)
                           自动 chain 上一阶段的结果作为 crop 上下文

模式:
  - 默认 demo:不依赖 mavis / matrix,直接返回 5 份预置
  - ?real=1:调真 AI(需要 mavis + matrix 配置)

接口:
  GET  /api/health
  POST /api/identify
    Form: image(可多次), parts, location, season
  POST /api/diagnose
    Form: image, crop(可选,前端从 identify 拿), context
    Query: ?real=1  触发真 AI(默认 demo)
  POST /api/feedback

鉴权:
  - 环境变量 CROP_DOCTOR_TOKEN 必须配
"""
import base64
import hashlib
import json
import disease_kb
import os
import shutil
import subprocess
import threading
import sys
import tempfile
import time
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    print("需要安装: pip install requests", file=sys.stderr)
    raise

try:
    from flask import Flask, request, jsonify, send_file, Response, g
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    from flask_cors import CORS
except ImportError:
    print("需要安装: pip install flask flask-cors", file=sys.stderr)
    raise

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from embedded_mocks import pick_pair

# ===== 微信小程序凭证(AES 解密 encryptedData 用) =====
# cryptography 库是可选的:没装也能跑,只是 encryptedData 解密失败时降级
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    print('[WARN] cryptography 库未装,encryptedData 解密功能不可用', file=sys.stderr)
    print('       安装: pip install cryptography', file=sys.stderr)

# ===== 配置 =====
AUTH_TOKEN = os.environ.get("CROP_DOCTOR_TOKEN", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CROP_DOCTOR_ORIGINS", "").split(",") if o.strip()]

# 微信小程序凭证(用于 jscode2session 换 openid)
# 在微信公众平台 → 开发 → 开发管理 → 开发设置 → 小程序 AppID / AppSecret
WECHAT_APPID = os.environ.get("WECHAT_APPID", "").strip()
# RAG 图库根目录(本地有图库时填,云托管默认空走 demo)
CROP_DOCTOR_DB_ROOT = os.environ.get("CROP_DOCTOR_DB_ROOT", "").strip()
WECHAT_SECRET = os.environ.get("WECHAT_SECRET", "").strip()

# 智谱 GLM-4V API(用于真 AI 诊断,Render 部署必备)
# 注册:https://open.bigmodel.cn/  → API keys
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "").strip()
ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
ZHIPU_MODEL = os.environ.get("ZHIPU_MODEL", "glm-4v-plus").strip()  # 默认 glm-4v-plus


def _zhipu_available():
    """检查智谱 API key 是否配置"""
    return bool(ZHIPU_API_KEY)


def _call_zhipu_glm4v(image_paths, prompt, max_tokens=2048, timeout=60):
    """
    调智谱 GLM-4V API,带图片的多模态对话
    输入:
      - image_paths: 图片绝对路径列表(支持多图)
      - prompt: 文本 prompt(详细指令)
      - max_tokens: 最大输出 token
      - timeout: 超时秒
    返回:
      - 解析后的 JSON dict(模型直接输出 JSON)
    抛出:
      - requests.RequestException: 网络错误
      - ValueError: 解析错误 / 模型返回非 JSON
    """
    if not _zhipu_available():
        raise RuntimeError("ZHIPU_API_KEY 未配置")

    # 把所有图片转 base64
    content = []
    for p in image_paths:
        raw = open(p, "rb").read()
        # 调试: 报告文件大小和首尾字节
        print(f"[zhipu] img {p}: size={len(raw)} head={raw[:8].hex()} tail={raw[-8:].hex()}", file=sys.stderr)
        b64 = base64.b64encode(raw).decode("ascii")
        print(f"[zhipu] img {p}: b64_len={len(b64)} b64_head={b64[:60]}... b64_tail=...{b64[-40:]}", file=sys.stderr)
        # GLM-4V 支持 jpeg/png/webp
        ext = Path(p).suffix.lower().lstrip(".") or "jpeg"
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{mime};base64,{b64}"}
        })
    content.append({"type": "text", "text": prompt})

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ZHIPU_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        # 不强制 response_format(部分智谱视觉模型不支持)
        # 依赖 prompt 引导 + 下面 markdown strip 降级
    }
    r = _requests.post(ZHIPU_API_URL, headers=headers, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"智谱 API HTTP {r.status_code}: {r.text[:300]}")
    resp = r.json()
    if "error" in resp:
        raise RuntimeError(f"智谱 API 错误: {resp['error']}")
    if "choices" not in resp or not resp["choices"]:
        raise RuntimeError(f"智谱 API 无 choices: {resp}")
    text = resp["choices"][0]["message"]["content"]
    # 智谱可能返回 ```json ... ``` 代码块,需要降级 strip
    text = text.strip()
    # 去 markdown code fence
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    # 如果 text 里夹了 leading text (如 "下面是 JSON:\n{...}"),找第一个 { 和最后一个 }
    if not text.startswith("{"):
        first_brace = text.find("{")
        if first_brace >= 0:
            last_brace = text.rfind("}")
            if last_brace > first_brace:
                text = text[first_brace:last_brace + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # 最后降级:打 stderr 详细错误 + 抛
        print(f"[zhipu] JSON parse failed: {e}\ntext (前 500): {text[:500]}", file=sys.stderr)
        raise ValueError(f"智谱返回非 JSON: {e}; raw text: {text[:200]}")


# ===== 智谱 GLM-4V prompt 模板 =====
IDENTIFY_PROMPT_TEMPLATE = """你是作物识别专家,只识别以下常见作物:
番茄、黄瓜、辣椒、茄子、西瓜、草莓、马铃薯、苹果、葡萄、柑橘、水稻、小麦、玉米、大豆、花生、茶叶。

【任务】仔细看图,判断是什么作物。

【输出 JSON 格式(严格,不要任何其他文字)】
{
  "is_crop": true,
  "primary_crop": {
    "name_zh": "番茄",
    "scientific_name": "Solanum lycopersicum",
    "family": "茄科 Solanaceae",
    "category": "果菜类",
    "confidence": 0.85
  },
  "candidates": [
    {"name_zh": "茄子", "confidence": 0.10},
    {"name_zh": "辣椒", "confidence": 0.05}
  ],
  "reasoning": "1-2 句判断依据(看叶片/果实/株型等特征)",
  "downstream_skills": [
    {"name": "crop-disease-diagnosis", "auto_chainable": true}
  ]
}

如果图里没有作物(is_crop=false):
{
  "is_crop": false,
  "primary_crop": {"name_zh": "非作物", "confidence": 0.0},
  "candidates": [],
  "reasoning": "图片不是作物"
}

只输出 JSON,不要 markdown 包裹。"""


DIAGNOSE_PROMPT_TEMPLATE = """你是资深作物病虫害诊断专家。请基于图片内容输出结构化 JSON 诊断。

【诊断流程】
1. 仔细看图片:病斑形态/位置/颜色/分布/有无虫体/整株状态
2. 综合判断:作物 + 病害/虫害/缺素/生理障碍
3. 给出 1 个主诊断 + 1-2 个候选,概率要拉开
4. 输出可执行治疗方案

【用户附加描述】{text_query}

【输出 JSON 格式(严格,不要任何其他文字)】
{
  "is_crop": true,
  "primary_crop": {
    "name_zh": "番茄",
    "scientific_name": "Solanum lycopersicum",
    "family": "茄科 Solanaceae",
    "category": "果菜类",
    "confidence": 0.9
  },
  "candidates": [
    {"name_zh": "茄子", "confidence": 0.05},
    {"name_zh": "辣椒", "confidence": 0.05}
  ],
  "diagnosis": [
    {
      "name": "番茄早疫病",
      "probability": 0.75,
      "severity": "中",
      "reasoning": "叶片有深褐色圆形病斑,带同心轮纹,符合早疫病典型特征",
      "key_visual_clues": ["深褐色圆形病斑", "同心轮纹", "病斑周围黄化"],
      "uncertainty_reason": "图片清晰度有限,需进一步确认病斑发展阶段",
      "need_expert": false
    },
    {
      "name": "番茄晚疫病",
      "probability": 0.20,
      "severity": "中",
      "reasoning": "...",
      "key_visual_clues": ["..."],
      "uncertainty_reason": "...",
      "need_expert": false
    }
  ],
  "treatment": {
    "title": "番茄早疫病治疗方案",
    "actions": [
      {"step": 1, "title": "摘除病叶", "description": "摘除最严重的病叶并带出田块销毁"},
      {"step": 2, "title": "加强通风降湿", "description": "降低田间湿度,提高通风"},
      {"step": 3, "title": "化学防治", "description": "见下方药剂处方"}
    ],
    "prescription": {
      "title": "药剂处方",
      "chemicals": [
        {
          "name": "75% 百菌清可湿性粉剂",
          "dose": "500-800 倍液",
          "method": "叶面喷雾",
          "interval_days": 7,
          "max_times": 3,
          "preharvest_days": 7
        }
      ],
      "safety_warning": "严格按说明书使用,注意防护,采收前 7 天停药",
      "followup": "7 天后复查,若病情继续发展立即换药"
    }
  }
}

注意:
- probability 是 0-1 之间的小数(主诊断 0.6-0.9,候选 0.05-0.3)
- 候选最多 2 个
- need_expert: true 表示建议找农技专家(严重或不确定时)
- severity: 轻/中/重
- treatment.actions 至少 3 步
- 药剂至少 1 种,按规范写

只输出 JSON。"""


def _build_diagnose_prompt(text_query):
    """构造 diagnose prompt,带可选 text 描述"""
    # 把 {text_query} 占位符替换成实际文本(没有就空)
    return DIAGNOSE_PROMPT_TEMPLATE.replace("{text_query}", text_query or "(无附加文字描述)")


CONSULT_PROMPT_TEMPLATE = """你是资深作物病虫害诊断专家。用户没有发图,只有文字描述,你需要基于症状描述做诊断。

用户描述:{text_query}

【任务】综合判断可能是什么病害/虫害/缺素症/生理障碍。

【输出 JSON 格式(严格)】
{{
  "is_crop": true,
  "primary_crop": {{"name_zh": "(从描述推断,如不明确填'未知')", "confidence": 0.5}},
  "candidates": [],
  "diagnosis": [
    {{
      "name": "可能病害名",
      "probability": 0.7,
      "severity": "中",
      "reasoning": "基于症状描述的判断依据",
      "key_visual_clues": ["用户提到的症状"],
      "uncertainty_reason": "没有图片,建议用户补图确认",
      "need_expert": true
    }}
  ],
  "treatment": {{
    "title": "建议方案",
    "actions": [
      {{"step": 1, "title": "补图", "description": "上传 1-3 张清晰照片获取精准诊断"}},
      {{"step": 2, "title": "观察", "description": "记录症状发展(扩散?好转?)"}}
    ],
    "prescription": {{
      "title": "初步建议(需补图确认)",
      "chemicals": [],
      "safety_warning": "未确诊前不建议盲目用药",
      "followup": "上传图片后免费重跑诊断"
    }}
  }}
}}

只输出 JSON。注意 need_expert 通常为 true(没有图,建议补图 + 找专家)。"""


def _build_response_from_kb(kb_match, text_query):
    """从知识库命中数据构建标准响应结构(扁平,文字问诊格式)

    知识库结构(简洁):
      {category, pathogen, severity, key_visual_clues, actions, prescription{...}}

    标准文字问诊响应(扁平,前端 parser 会 normalize):
      { primary_crop, diagnosis:[], treatment:{...}, _kb_hit, _no_need_image, ... }
    """
    data = kb_match["data"]
    canonical = kb_match["canonical_name"]

    # 从病名提取作物名(简单启发式:取前 2 字符,在常见作物名集合里)
    common_crops = ["玉米", "水稻", "小麦", "番茄", "黄瓜", "辣椒", "茄子", "白菜", "萝卜",
                    "马铃薯", "苹果", "葡萄", "柑橘", "茶叶", "草莓", "花生", "大豆", "桃", "梨"]
    crop = canonical[:2]
    for c in common_crops:
        if canonical.startswith(c):
            crop = c
            break

    diagnosis = [{
        "name": canonical,
        "probability": 0.85,  # 知识库命中,置信度较高
        "severity": data.get("severity", "中"),
        "reasoning": f"知识库匹配:用户文字问诊命中「{canonical}」,直接给出标准治疗方案(数据来源:中国农技推广中心公开技术资料)",
        "key_visual_clues": data.get("key_visual_clues", []),
        "uncertainty_reason": f"基于用户文字描述的初步判断,建议结合田间实际情况;如有图片可二次确认病斑细节",
        "need_expert": data.get("severity") == "高",
    }]

    treatment = {
        "title": f"{canonical}治疗方案",
        "actions": data.get("actions", []),
        "prescription": data.get("prescription", {}),
    }

    return {
        "primary_crop": {"name_zh": crop, "confidence": 0.9},
        "diagnosis": diagnosis,
        "treatment": treatment,
        "is_crop": True,
        "_is_demo": False,
        "_is_text_only": True,
        "_kb_hit": True,            # 知识库命中标志
        "_no_need_image": True,     # 前端隐藏"补图"提示
        "_identified_crop": {
            "primary_crop": {"name_zh": crop, "confidence": 0.9},
            "candidates": [],
        },
        "_chain": {
            "stage1_identified_by": "text_kb",
            "stage2_diagnosed_by": "disease_kb",
            "identified_crop_name": crop,
            "auto_chainable": True,
        },
    }


def _build_consult_prompt(text_query):
    """构造 consult prompt"""
    return CONSULT_PROMPT_TEMPLATE.format(text_query=text_query)

def decrypt_wechat_data(session_key_b64, encrypted_data_b64, iv_b64):
    """
    ★ 微信 AES-128-CBC 解密(encryptedData)
    输入:session_key / encryptedData / iv 都是 base64 编码
    输出:明文 dict(微信用户信息,含 unionid/openid/nickName/avatarUrl/...)

    算法:参考微信官方文档
      https://developers.weixin.qq.com/miniprogram/dev/api-backend/open-api/signature.html
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography 库未装,无法解密")

    import base64
    import struct
    key = base64.b64decode(session_key_b64)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(encrypted_data_b64)

    # AES-128-CBC + PKCS#7
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    # 去 PKCS#7 填充
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()

    # 微信加密数据前 16 字节是随机数,跳过
    plain = plain[16:]
    # 剩下 4 字节是 data 长度(big-endian),再后面是 JSON
    data_len = struct.unpack(">I", plain[:4])[0]
    json_bytes = plain[4:4 + data_len]
    return json.loads(json_bytes.decode("utf-8"))



SKILL_DIR = SCRIPT_DIR.parent.parent / "skills" / "crop-disease-diagnosis"
# ★ 优先用后端自带的 bin/(已 copy),然后 fallback 到 skill 原位置
_LOCAL_BIN_DIR = SCRIPT_DIR / "bin"
if _LOCAL_BIN_DIR.exists():
    SKILL_BIN_DIR = _LOCAL_BIN_DIR
else:
    SKILL_BIN_DIR = SKILL_DIR / "bin"
# references 同样优先用本地
_LOCAL_REFS_DIR = SCRIPT_DIR / "references"
if _LOCAL_REFS_DIR.exists():
    SKILL_REFS_DIR = _LOCAL_REFS_DIR
else:
    SKILL_REFS_DIR = SKILL_DIR / "references"
# crop-identifier 暂用 SKILL_DIR
IDENTIFIER_SKILL_DIR = SCRIPT_DIR.parent.parent / "skills" / "crop-identifier"
IDENTIFIER_BIN_DIR = IDENTIFIER_SKILL_DIR / "bin"

app = Flask(__name__)
if ALLOWED_ORIGINS:
    CORS(app, origins=ALLOWED_ORIGINS)

# 限流触发时返 JSON(默认是 HTML,前端 fetch 会卡住)
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "ok": False,
        "error": "rate_limit_exceeded",
        "message": "请求太频繁,请稍后再试",
        "limit": str(e.description) if hasattr(e, "description") else "见 X-RateLimit-* 头",
    }), 429

# ===== API 限流(防脚本刷量、刷智谱额度)=====
# Render free tier 单 worker,内存存储够用;若以后多 worker,需换 Redis
# 限制维度:IP(forwarded 优先,因为 Render 转发会带 X-Forwarded-For)
def _rate_limit_key():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
            or "unknown")

limiter = Limiter(
    key_func=_rate_limit_key,
    app=app,
    default_limits=[],  # 默认不限流,只在敏感端点单独加
    storage_uri="memory://",
    headers_enabled=True,  # 加 X-RateLimit-* 响应头
)

# 各端点限流规则(防止脚本把智谱额度刷爆)
LIMITS = {
    "diagnose":      "30 per hour",     # AI 诊断(走智谱,贵)
    "diagnose_burst": "5 per minute",   # 突发保护
    "identify":      "30 per hour",     # 作物识别
    "feedback":      "20 per hour",     # 反馈
    "wechat_login":  "10 per hour",     # 微信登录(jscode2session 限频)
}

UPLOAD_DIR = Path(tempfile.gettempdir()) / "crop_doctor_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_FILE = SCRIPT_DIR / "feedback.jsonl"


# ===== 法律文件路由(用户协议 / 隐私政策)=====
LEGAL_DIR = Path(__file__).parent / "legal"

@app.route("/legal/<name>")
def serve_legal(name):
    """提供用户协议 / 隐私政策的 HTML(给小程序 web-view 用)"""
    # 只允许 4 个固定文件名,防止路径穿越
    if name not in ("agreement.html", "privacy.html", "agreement", "privacy"):
        return jsonify({"ok": False, "error": "not found"}), 404
    file_path = LEGAL_DIR / name
    if not file_path.exists():
        return jsonify({"ok": False, "error": "file not found"}), 404
    return send_file(str(file_path), mimetype="text/html; charset=utf-8")


# ===== 静态文件服务(让前端能拿到上传的原图,做"已上传图片预览") =====
@app.route("/uploads/<path:filepath>")
def serve_upload(filepath):
    """serve UPLOAD_DIR 下的图片,供前端 wx:image 组件直接 src"""
    # 安全:防止路径穿越(只能访问 UPLOAD_DIR 下文件)
    target = (UPLOAD_DIR / filepath).resolve()
    print(f"[uploads] req path={request.path} target={target} exists={target.exists()}", file=sys.stderr)
    if not str(target).startswith(str(UPLOAD_DIR.resolve())):
        return jsonify({"ok": False, "error": "path traversal blocked"}), 403
    if not target.exists() or not target.is_file():
        # debug: 列 UPLOAD_DIR 实际有什么
        siblings = []
        try:
            for p in UPLOAD_DIR.iterdir():
                siblings.append(p.name)
        except Exception as e:
            siblings = [f"<list err: {e}>"]
        return jsonify({
            "ok": False,
            "error": "file not found",
            "target": str(target),
            "upload_dir": str(UPLOAD_DIR),
            "siblings_in_upload_dir": siblings[:20],
        }), 404
    return send_file(str(target))


# ===== 鉴权 =====
# 三种信任方式(按优先级):
#   1. 微信云托管注入 X-WX-OPENID + X-WX-APPID(可信,代表微信小程序请求)
#   2. 客户端传 X-Auth-Token(必须匹配 CROP_DOCTOR_TOKEN)
#   3. 白名单路径(/api/health, /admin, /uploads/* 等)
@app.before_request
def check_auth():
    PUBLIC_PATHS = {"/", "/api/health", "/admin", "/admin/login", "/api/wechat-login"}
    # /api/admin/* 用自己的 admin token 鉴权(不放进 PUBLIC,但也不要全局 token 拦)
    if request.path.startswith("/api/admin/"):
        return None
    # 静态文件(uploads/)是用户自己上传的图片,wx:image src 不带 token,需要公开
    if request.path in PUBLIC_PATHS or request.path.startswith("/uploads/") or request.path.startswith("/legal/"):
        return None

    # ★ 方式 1:微信云托管自动注入 X-WX-OPENID(代表微信小程序发的请求,可信)
    wx_openid = request.headers.get("X-WX-OPENID", "").strip()
    wx_appid = request.headers.get("X-WX-APPID", "").strip()
    if wx_openid and wx_appid:
        # 存到 flask.g,后续 endpoint 可用 g.wx_openid
        from flask import g
        g.wx_openid = wx_openid
        g.wx_appid = wx_appid
        g.trust_source = "wxcloud"
        return None  # 放行

    # ★ 方式 2:客户端传 X-Auth-Token(自己测试/管理用)
    if not AUTH_TOKEN:
        return jsonify({"ok": False, "error": "服务端未配置 CROP_DOCTOR_TOKEN"}), 503
    token = request.headers.get("X-Auth-Token", "").strip()
    if token and token == AUTH_TOKEN:
        from flask import g
        g.wx_openid = None
        g.wx_appid = None
        g.trust_source = "token"
        return None

    return jsonify({"ok": False, "error": "Unauthorized"}), 401


# ===== 健康检查 =====
@app.route("/", methods=["GET"])
def root():
    """根路径:给个简短的 service banner,方便 curl 验证服务起来了"""
    return jsonify({
        "service": "crop-doctor-backend",
        "version": "2.1.0",
        "ok": True,
        "endpoints": {
            "health": "/api/health",
            "diagnose": "/api/diagnose",
            "consult": "/api/consult",
            "feedback": "/api/feedback",
            "admin": "/admin",
        },
    })


@app.route("/api/health", methods=["GET"])
def health():
    # 真实 AI 优先级:智谱 > mavis
    real_backend = "zhipu-glm4v" if _zhipu_available() else ("mavis" if _matrix_available() else None)
    return jsonify({
        "ok": True,
        "ts": time.time(),
        "version": "2.1.0",
        "mode": "real" if real_backend else "demo",
        "real_backend": real_backend,
        "zhipu_configured": _zhipu_available(),
        "matrix_configured": _matrix_available(),
        "wechat_configured": bool(WECHAT_APPID and WECHAT_SECRET),
    })


# ===== Debug:看实际请求(本地 debug 用) =====
# ★ 生产环境打包时会被排除(见 _build_zip.py)
@app.route("/api/_debug_echo", methods=["POST", "GET", "OPTIONS"])
def debug_echo():
    """看云托管网关到底转发了什么头/body(本地 debug 用)"""
    raw = request.data or b''
    info = {
        "method": request.method,
        "content_type": request.content_type,
        "is_json": request.is_json,
        "content_length": request.content_length,
        "raw_data_len": len(raw),
        "raw_data_bytes_hex": raw[:50].hex(),
        "raw_data_ascii_safe": ''.join(chr(b) if 32 <= b < 127 else '?' for b in raw[:200]),
    }
    return jsonify(info)


def _matrix_available():
    """检查真实 AI 链路(mavis + matrix + skill)是否可用"""
    if not SKILL_BIN_DIR.exists() or not (SKILL_BIN_DIR / "full_diagnosis.py").exists():
        return False
    if not IDENTIFIER_BIN_DIR.exists() or not (IDENTIFIER_BIN_DIR / "identify_crop.py").exists():
        return False
    return True


# ===== 工具:落临时目录 =====
def _save_images_to_tmp(image_files, prefix="img"):
    """保存上传图片到临时目录,返回路径列表

    关键:不直接用 werkzeug FileStorage.save()——
    部分版本/部分环境下 save() 会偷偷在文件头尾插入/修改字节(实测多出 CRLF 等),
    导致智谱 GLM-4V 报 1210 图片格式错误。
    改用 f.stream.read() 显式拿原始字节,再以二进制模式写入磁盘,保证字节级一致。
    """
    ts = int(time.time() * 1000)
    session_dir = UPLOAD_DIR / f"{prefix}-{ts}"
    session_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for idx, f in enumerate(image_files):
        ext = Path(f.filename or "img.jpg").suffix or ".jpg"
        save_path = session_dir / f"{idx}{ext}"
        # 显式读 stream 的原始字节,绕开 FileStorage.save() 的潜在副作用
        try:
            f.stream.seek(0)
        except Exception:
            pass
        # 优先用 f.read()(FileStorage.read,会跳过 leading CRLF)
        # 兜底用 stream.read()
        try:
            raw = f.read()
        except Exception:
            raw = f.stream.read()
        if isinstance(raw, str):
            raw = raw.encode("latin-1", errors="replace")
        # 剥掉 werkzeug 解析 multipart 时可能带进来的 leading CRLF/blank lines
        # 找 JPEG/PNG/WEBP 的 magic byte 起点
        for sig, name in [(b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"RIFF", "webp")]:
            idx_sig = raw.find(sig)
            if idx_sig > 0:
                print(f"[save] {save_path}: 剥掉 {idx_sig} 字节前缀(leading CRLF 等), magic={name}", file=sys.stderr)
                raw = raw[idx_sig:]
                break
        # 剥掉 trailing 残留(末尾的 \r\n 或 ? 等)
        for trailer in (b"\r\n--", b"\r\n", b"?"):
            if raw.endswith(trailer):
                raw = raw[: -len(trailer)]
                break
        with open(save_path, "wb") as out:
            out.write(raw)
        saved_paths.append(str(save_path))
        print(f"[save] {save_path}: size={len(raw)} head={raw[:8].hex()} tail={raw[-8:].hex()}", file=sys.stderr)
    return saved_paths, session_dir


def _get_field(name, default=""):
    """统一从 request.form 拿字段(v1.5.1 修过自递归 bug,2.0 重构时误删,这里补回)

    ★ 不要写成 (_get_field(name) or '').strip() or default —— 那会无限自递归
       必须直接用 request.form.get()
    """
    v = request.form.get(name)
    return v if v is not None else default


def _schedule_cleanup(session_dir, delay_seconds=3600):
    """延迟删除 session_dir(默认 1 小时后),给前端 wx:image 组件足够时间拉图

    实现:用 threading.Timer 在后台延迟删。
    为什么不用 finally 立即删:前端拿 URL 后需要时间下载图(image 组件 src 加载),
    立即删会 404。
    """
    def _do_cleanup():
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
            print(f"[cleanup] removed {session_dir}", file=sys.stderr)
        except Exception as e:
            print(f"[cleanup] err: {e}", file=sys.stderr)

    try:
        timer = threading.Timer(delay_seconds, _do_cleanup)
        timer.daemon = True
        timer.start()
        print(f"[cleanup] scheduled {session_dir} in {delay_seconds}s", file=sys.stderr)
    except Exception as e:
        print(f"[cleanup] schedule err: {e}", file=sys.stderr)


# ===== /api/identify(作物识别) =====
@app.route("/api/identify", methods=["POST"])
@limiter.limit(LIMITS["identify"])
def identify():
    """第一阶段:识别作物是什么"""
    image_files = request.files.getlist("image")
    if not image_files:
        return jsonify({"ok": False, "error": "请至少上传 1 张图片"}), 400

    use_real = request.args.get("real") == "1"
    if use_real and _zhipu_available():
        return _identify_real(image_files)
    elif use_real and _matrix_available():
        return _identify_real(image_files)
    else:
        return _identify_demo(image_files)


def _identify_demo(image_files):
    """demo 模式:用图片 hash 选一份 mock"""
    h = hashlib.md5()
    for f in image_files:
        h.update((f.filename or "").encode("utf-8"))
        f.seek(0, 2)
        h.update(str(f.tell()).encode("utf-8"))
        f.seek(0)
    seed = int(h.hexdigest()[:8], 16)
    _, identified = pick_pair(image_count=len(image_files), seed=seed)
    identified["_is_demo"] = True
    identified["_demo_reason"] = "服务端 demo 模式:返回固定识别结果,不基于图片分析"
    return jsonify(identified)


def _identify_real(image_files):
    """真实模式:调智谱 GLM-4V 识别作物"""
    saved_paths, session_dir = _save_images_to_tmp(image_files, prefix="identify")
    try:
        # 构造 identify prompt
        parts = (_get_field("parts") or "").strip() or None
        location = (_get_field("location") or "").strip() or None
        season = (_get_field("season") or "").strip() or None

        extra = []
        if parts:
            extra.append(f"重点看部位:{parts}")
        if location:
            extra.append(f"种植地点:{location}")
        if season:
            extra.append(f"当前季节:{season}")
        extra_text = ("\n附加信息:" + "; ".join(extra)) if extra else ""

        prompt = IDENTIFY_PROMPT_TEMPLATE + extra_text

        # 调智谱(max_tokens 1-2048,智谱 glm-4v-plus 限制)
        print(f"[zhipu] identify: {len(saved_paths)} 张图", file=sys.stderr)
        result = _call_zhipu_glm4v(saved_paths, prompt, max_tokens=1500, timeout=45)
        # 兜底字段
        result.setdefault("is_crop", True)
        result.setdefault("primary_crop", {"name_zh": "未识别", "confidence": 0.0})
        result.setdefault("candidates", [])
        result.setdefault("reasoning", "")
        result.setdefault("downstream_skills", [
            {"name": "crop-disease-diagnosis", "auto_chainable": True}
        ])
        result["_is_demo"] = False
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": "识别服务异常: " + str(e)}), 500
    finally:
        # 延迟删除(1 小时后),给前端 wx:image 组件足够时间拉图
        _schedule_cleanup(session_dir, delay_seconds=3600)



# ====================================================================
# ★★★ 2.1.0 重构:走 crop-disease-diagnosis skill v2.2 完整流程 ★★★
#   + db.py 智能选路径 (env / /data 实例存储 / /tmp fallback)
# ====================================================================

def _run_rag_diagnose(image_files, text_query, user_crop, user_context):
    """真实模式:调 diagnose_with_rag.py 走 RAG 增强路径"""
    saved_paths, session_dir = _save_images_to_tmp(image_files, prefix="rag_diagnose")
    print(f"[rag] saved {len(saved_paths)} images to {session_dir}", file=sys.stderr)
    try:
        if not SKILL_BIN_DIR.exists() or not (SKILL_BIN_DIR / "diagnose_with_rag.py").exists():
            return {"ok": False, "error": "diagnose_with_rag.py 不存在,无法走 RAG 路径"}
        duration = user_context.get("duration") or ""
        weather = user_context.get("weather") or ""
        chemical = user_context.get("chemical") or ""
        cmd = [
            sys.executable,
            str(SKILL_BIN_DIR / "diagnose_with_rag.py"),
            "-i", saved_paths[0],
        ]
        for p in saved_paths[1:]:
            cmd.extend(["-i", p])
        if user_crop:
            cmd.extend(["-c", user_crop])
        if duration:
            cmd.extend(["-d", duration])
        if weather:
            cmd.extend(["-w", weather])
        if chemical:
            cmd.extend(["-m", chemical])
        output_json = session_dir / "full-diagnosis-with-rag.json"
        cmd.extend(["--output", str(output_json)])
        db_root = os.environ.get("CROP_DOCTOR_DB_ROOT", "")
        if db_root:
            cmd.extend(["--db-root", db_root])
        print(f"[rag] cmd: {' '.join(cmd[:5])}... + {len(cmd)-5} more", file=sys.stderr)
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "RAG 诊断超时(>300s)"}
        try:
            stdout = result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            stdout = result.stdout.decode("latin-1", errors="replace")
        try:
            stderr = result.stderr.decode("utf-8")
        except UnicodeDecodeError:
            stderr = result.stderr.decode("latin-1", errors="replace")
        if result.returncode != 0:
            return {"ok": False, "error": "RAG 诊断失败: " + (stderr[-300:] or "未知"), "stdout_tail": stdout[-500:]}
        if not output_json.exists():
            return {"ok": False, "error": "RAG 未产出 full-diagnosis-with-rag.json"}
        with open(output_json, "r", encoding="utf-8") as f:
            full = json.load(f)
        # 渲染 HTML
        html = None
        try:
            html_proc = subprocess.run(
                [sys.executable, str(SKILL_BIN_DIR / "render_html_report.py"), "-i", str(output_json)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            try:
                html = html_proc.stdout.decode("utf-8")
            except UnicodeDecodeError:
                html = html_proc.stdout.decode("latin-1", errors="replace")
            if html_proc.returncode != 0:
                print(f"[rag] HTML render fail", file=sys.stderr)
                html = None
        except Exception as e:
            print(f"[rag] HTML render exception: {e}", file=sys.stderr)
            html = None
        return {"ok": True, "full": full, "html": html, "saved_paths": saved_paths}
    except Exception as e:
        import traceback
        return {"ok": False, "error": "RAG 诊断异常: " + str(e), "traceback": traceback.format_exc()[-1500:]}
    finally:
        _schedule_cleanup(session_dir, delay_seconds=3600)


def _run_consult_text(text_query, user_crop=None, location=None, context=None):
    """文字咨询路径(无图):走 crop-pest-text-advisor 内化逻辑"""
    try:
        if not SKILL_BIN_DIR.exists() or not (SKILL_BIN_DIR / "render_consult_html.py").exists():
            return {"ok": False, "error": "render_consult_html.py 不存在,无法走文字咨询路径"}
        consult_input = {
            "user_question": text_query,
            "summary": (text_query[:30] + "...") if len(text_query) > 30 else text_query,
            "crop": user_crop or "",
            "location": location or "",
            "context": context or "",
            "cause": "基于您描述的症状,以下是常见原因参考(具体诊断需结合图片)",
            "treatments": [],
            "spray_schedule": "7-10 天一次,连喷 2-3 次,采收前 7-14 天停药(具体看药剂标签)",
            "mixing_rotation": "三唑类 → 甲氧基丙烯酸酯类 → 苯并咪唑类 三循环,避免同种药剂连续使用",
            "differential": [
                {"name": "请上传照片", "key_diff": "光看文字无法确诊,建议上传 4 张照片(特写/另一面/整体/受害部位)走 RAG 路径"},
            ],
            "symptoms": "文字咨询路径不展示具体症状(需要图片诊断)",
            "ag_control": "1. 加强田间巡查 2. 及时清除病叶 3. 改善通风 4. 轮作换茬",
            "need_expert": True,
        }
        consult_json_path = Path(tempfile.gettempdir()) / f"consult_input_{int(time.time() * 1000)}.json"
        with open(consult_json_path, "w", encoding="utf-8") as f:
            json.dump(consult_input, f, ensure_ascii=False, indent=2)
        output_html = Path(tempfile.gettempdir()) / f"consult_output_{int(time.time() * 1000)}.html"
        cmd = [
            sys.executable,
            str(SKILL_BIN_DIR / "render_consult_html.py"),
            "-i", str(consult_json_path),
            "-o", str(output_html),
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "render_consult_html 超时"}
        try:
            stdout = result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            stdout = result.stdout.decode("latin-1", errors="replace")
        try:
            stderr = result.stderr.decode("utf-8")
        except UnicodeDecodeError:
            stderr = result.stderr.decode("latin-1", errors="replace")
        if result.returncode != 0:
            return {"ok": False, "error": "render_consult_html 失败: " + stderr[-300:]}
        if not output_html.exists():
            return {"ok": False, "error": "render_consult_html 未产出文件"}
        with open(output_html, "r", encoding="utf-8") as f:
            html = f.read()
        try:
            consult_json_path.unlink()
        except OSError:
            pass
        return {"ok": True, "html": html, "parsed": consult_input}
    except Exception as e:
        import traceback
        return {"ok": False, "error": "文字咨询异常: " + str(e), "traceback": traceback.format_exc()[-1500:]}


def _build_demo_diagnose(image_files, text_query, user_crop, user_context):
    """demo 模式:返回简单占位结构"""
    if image_files:
        saved_paths, session_dir = _save_images_to_tmp(image_files, prefix="demo_diagnose")
        try:
            full = {
                "diagnosis": {
                    "diagnosis": [{"name": "示例诊断(演示)", "probability": 0.5, "confidence": "中"}],
                    "severity": "中",
                    "cause_summary": "demo 模式:这是固定占位,不是真实 AI 诊断。生产环境请切换到真实模式。",
                    "immediate_actions": ["1. 上传真实图片", "2. 切换到真实模式"],
                    "need_expert": False,
                },
                "top_diagnosis_name": "示例诊断(演示)",
                "prescription": {"available": False, "title": "", "content": ""},
                "metadata": {"image_count": len(image_files), "crop": user_crop, "backend": "demo"},
                "_is_demo": True,
            }
            return {"ok": True, "full": full, "html": None, "saved_paths": saved_paths}
        finally:
            _schedule_cleanup(session_dir, delay_seconds=3600)
    else:
        full = {
            "diagnosis": {
                "diagnosis": [{"name": "示例诊断(演示)", "probability": 0.5, "confidence": "中"}],
                "severity": "中",
                "cause_summary": "demo 模式:纯文字,关键词匹配,不是真实 AI 诊断",
                "immediate_actions": ["1. 上传图片走 RAG 路径", "2. 切换到真实模式"],
                "need_expert": False,
            },
            "top_diagnosis_name": "示例诊断(演示)",
            "prescription": {"available": False, "title": "", "content": ""},
            "metadata": {"image_count": 0, "crop": user_crop, "backend": "demo"},
            "_is_demo": True,
        }
        return {"ok": True, "full": full, "html": None, "saved_paths": []}


# ===== /api/diagnose 2.0:重写主路由 =====
@app.route("/api/diagnose", methods=["POST"])
@limiter.limit(LIMITS["diagnose"])
@limiter.limit(LIMITS["diagnose_burst"])
def diagnose_v2():
    """v2.0 诊断主路由 — 走 crop-disease-diagnosis skill v2.2 完整流程"""
    is_json = request.is_json or (request.content_type or '').startswith('application/json')
    image_files = []
    if is_json:
        try:
            data_json = request.get_json(silent=True) or {}
        except Exception:
            data_json = {}
        text_query = (data_json.get("text") or "").strip()
        user_crop = (data_json.get("crop") or "").strip()
        context = data_json.get("context") or {}
        if not hasattr(g, "_json_data"):
            g._json_data = data_json
        images_b64 = data_json.get("images_base64") or []
        if isinstance(data_json.get("image_base64"), str):
            images_b64 = [data_json.get("image_base64")]
        from werkzeug.datastructures import FileStorage
        from io import BytesIO
        for idx, b64str in enumerate(images_b64):
            try:
                if "," in b64str:
                    b64str = b64str.split(",", 1)[1]
                raw = __import__('base64').b64decode(b64str)
                fs = FileStorage(stream=BytesIO(raw), filename=f"json_{idx}.jpg", content_type="image/jpeg")
                image_files.append(fs)
            except Exception as e:
                print(f"[diag-v2] base64 decode err idx={idx}: {e}", file=sys.stderr)
    else:
        image_files = request.files.getlist("image")
        text_query = (_get_field("text") or "").strip()
        user_crop = (_get_field("crop") or "").strip()
        context_str = (_get_field("context") or "").strip()
        context = {}
        if context_str:
            try:
                import json as _json_mod
                context = _json_mod.loads(context_str)
            except Exception:
                context = {"raw": context_str}

    if not image_files and not text_query:
        return jsonify({"ok": False, "error": "请上传图片或输入症状描述"}), 400

    use_real = request.args.get("real") == "1"
    if is_json and hasattr(g, "_json_data"):
        openid = (getattr(g, "wx_openid", None) or g._json_data.get("openid") or "").strip() or None
    else:
        openid = (getattr(g, "wx_openid", None) or _get_field("openid") or "").strip() or None
    print(f"[diag-v2] real={use_real} text={bool(text_query)} img={len(image_files)} crop='{user_crop}' openid={openid}", file=sys.stderr)

    image_type = "crop_disease"  # 默认,真实模式可由 GLM-4V 判

    if use_real and image_files:
        result = _run_rag_diagnose(image_files, text_query, user_crop, context)
    elif use_real and not image_files:
        result = _run_consult_text(text_query, user_crop, context.get("location"), context)
    elif image_files:
        result = _build_demo_diagnose(image_files, text_query, user_crop, context)
    else:
        result = _build_demo_diagnose([], text_query, user_crop, context)

    if not result.get("ok"):
        return jsonify(result), 500

    full = result.get("full") or {}
    return jsonify({
        "ok": True,
        "version": "2.1.0",
        "image_type": image_type,
        "need_confirm": False,
        "need_confirm_data": None,
        "crop_id_method": "manual",
        "crop_id_result": full.get("_identified_crop"),
        "parsed": full.get("diagnosis", {}),
        "full": full,
        "html": result.get("html"),
        "saved_paths": result.get("saved_paths", []),
        "fallback_reason": None,
        "_is_demo": full.get("_is_demo", False),
    })


# ===== /api/consult v2:文字咨询路径 =====
@app.route("/api/consult", methods=["POST"])
@limiter.limit(LIMITS["diagnose"])
@limiter.limit(LIMITS["diagnose_burst"])
def consult_v2():
    """v2.0 文字咨询 — 走 crop-pest-text-advisor 内化逻辑"""
    is_json = request.is_json or (request.content_type or '').startswith('application/json')
    if is_json:
        try:
            data_json = request.get_json(silent=True) or {}
        except Exception:
            data_json = {}
        text_query = (data_json.get("text") or "").strip()
        user_crop = (data_json.get("crop") or "").strip()
        location = (data_json.get("location") or "").strip()
        context_str = (data_json.get("context") or "").strip()
        if not hasattr(g, "_json_data"):
            g._json_data = data_json
    else:
        text_query = (_get_field("text") or "").strip()
        user_crop = (_get_field("crop") or "").strip()
        location = (_get_field("location") or "").strip()
        context_str = (_get_field("context") or "").strip()

    if not text_query:
        return jsonify({"ok": False, "error": "请输入症状描述或问题"}), 400

    use_real = request.args.get("real") == "1"
    print(f"[consult-v2] real={use_real} text='{text_query[:50]}' crop='{user_crop}' loc='{location}'", file=sys.stderr)
    result = _run_consult_text(text_query, user_crop, location, context_str)
    if not result.get("ok"):
        return jsonify(result), 500
    return jsonify({
        "ok": True,
        "version": "2.1.0",
        "parsed": result.get("parsed", {}),
        "html": result.get("html"),
    })


# ===== 反馈 =====
@app.route("/api/feedback", methods=["POST"])
@limiter.limit(LIMITS["feedback"])
def feedback():
    """提交反馈(存 SQLite, 取代原 feedback.jsonl)

    payload 字段:
      - openid: 用户 openid(可选,登录后透传)
      - diagnosis_id: 关联 diagnoses.id(可选,前端从 /api/diagnose 拿到)
      - key: 反馈选项(A/B/C/D/E)
      - text: 自由文本
      - crop: 作物名
      - disease_name: 病名
      - severity: 严重程度
      - is_fallback: 是否离线模式
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        # ★ openid 优先级:微信云托管注入 > 前端透传
        openid = (getattr(g, "wx_openid", None)
                  or data.get("openid")
                  or data.get("openId")
                  or "").strip() or None
        diagnosis_id = data.get("diagnosis_id") or data.get("diagnosisId")
        key = data.get("key")
        text = data.get("text") or data.get("remark")
        crop = data.get("crop") or data.get("cropName")
        disease_name = data.get("disease_name") or data.get("topDiagnosis") or data.get("topName")
        severity = data.get("severity")
        is_fallback = bool(data.get("is_fallback") or data.get("isFallback"))

        # 写 SQLite
        fb_id = _db.insert_feedback(
            openid=openid,
            diagnosis_id=diagnosis_id,
            key=key,
            text=text,
            crop=crop,
            disease_name=disease_name,
            severity=severity,
            is_fallback=is_fallback,
        )
        return jsonify({"ok": True, "id": fb_id})
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500


# ===== 微信快捷登录 =====
# 完整真微信登录流程(用上微信的 4 个真接口):
#   1. wx.login()      → 拿临时 code
#   2. wx.getUserProfile() → 弹窗让用户授权,拿到明文 userInfo + encryptedData/iv
#   3. POST /api/wechat-login {code, encryptedData?, iv?, userInfoRaw?}
#   4. 后端用 code 调 jscode2session 换 session_key + openid
#   5. 后端用 session_key + AES-128-CBC 解密 encryptedData,拿到真微信用户信息(unionid/openid/...)
#   6. 返回完整 userInfo 给前端
#
# 真微信模式:需要环境变量 WECHAT_APPID + WECHAT_SECRET
# 兜底模式:没配 WECHAT_APPID 时,返回 fake openid(只供本地体验,不能用于生产)
# 解密降级:cryptography 库没装或解密失败,降级用前端明文 userInfoRaw
@app.route("/api/wechat-login", methods=["POST"])
@limiter.limit(LIMITS["wechat_login"])
def wechat_login():
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    encrypted_data = (data.get("encryptedData") or "").strip()
    iv = (data.get("iv") or "").strip()
    user_info_raw = data.get("userInfoRaw") or {}

    # ★ 关键:没配 WECHAT_APPID / WECHAT_SECRET 时,直接走 demo
    if not WECHAT_APPID or not WECHAT_SECRET:
        fake_openid = "demo_" + code[:12] + "_" + str(int(time.time()))
        # ★ 也入库一条 demo 用户记录(便于 admin 看 demo 用户)
        try:
            _db.upsert_user(
                openid=fake_openid,
                nickname=user_info_raw.get("nickName") or "体验用户",
                avatar_url=user_info_raw.get("avatarUrl"),
                device_model=data.get("deviceModel"),
                wx_version=data.get("wxVersion"),
                is_guest=True,
            )
        except Exception as e:
            print(f"[登录] demo 入库失败: {e}", file=sys.stderr)
        return jsonify({
            "ok": True,
            "openid": fake_openid,
            "sessionToken": "demo_token_" + str(int(time.time())),
            "userInfo": {
                "nickname": user_info_raw.get("nickName") or "体验用户",
                "avatar": user_info_raw.get("avatarUrl") or "🌾",
                "isLocal": True,
            },
            "_fallback_reason": "后端未配置 WECHAT_APPID,使用 demo openid(未走真微信接口)",
        })

    # ★ 真微信模式
    import urllib.request
    try:
        url = (
            f"https://api.weixin.qq.com/sns/jscode2session"
            f"?appid={WECHAT_APPID}&secret={WECHAT_SECRET}&js_code={code}&grant_type=authorization_code"
        )
        with urllib.request.urlopen(url, timeout=8) as r:
            wx_resp = json.loads(r.read().decode("utf-8"))
        if "errcode" in wx_resp and wx_resp["errcode"] != 0:
            return jsonify({
                "ok": False,
                "error": f"wechat errcode={wx_resp.get('errcode')}, errmsg={wx_resp.get('errmsg')}",
            }), 502

        openid = wx_resp.get("openid", "")
        session_key = wx_resp.get("session_key", "")
        unionid = wx_resp.get("unionid", "")

        # ★ 真微信用户信息(用 session_key 解密 encryptedData)
        decrypted_user_info = None
        if encrypted_data and iv and session_key and _CRYPTO_AVAILABLE:
            try:
                decrypted_user_info = decrypt_wechat_data(session_key, encrypted_data, iv)
                print(f"[登录] ✓ 成功解密微信用户信息(unionid={decrypted_user_info.get('unionid', '?')[:8]}...)", file=sys.stderr)
            except Exception as e:
                print(f"[登录] ✗ 解密 encryptedData 失败: {e}", file=sys.stderr)
                # 解密失败:降级用前端明文
                decrypted_user_info = None

        # 组装 userInfo(优先用解密结果,否则用前端明文)
        if decrypted_user_info:
            final_user_info = {
                "nickname": decrypted_user_info.get("nickName", ""),
                "avatar": decrypted_user_info.get("avatarUrl", ""),
                "openid": openid,
                "unionid": unionid or decrypted_user_info.get("unionId", ""),
                "gender": decrypted_user_info.get("gender", 0),
                "country": decrypted_user_info.get("country", ""),
                "province": decrypted_user_info.get("province", ""),
                "city": decrypted_user_info.get("city", ""),
                "isLocal": False,
            }
        else:
            # 兜底:用前端明文
            final_user_info = {
                "nickname": user_info_raw.get("nickName") or "微信用户",
                "avatar": user_info_raw.get("avatarUrl") or "👤",
                "openid": openid,
                "unionid": unionid,
                "isLocal": False,
            }
            if not encrypted_data:
                final_user_info["_decrypt_status"] = "skipped:no encryptedData"
            else:
                final_user_info["_decrypt_status"] = "failed:fallback to raw userInfo"

        # ★ 存到 SQLite(用户表)
        # 取前端透传的 device_model / wx_version(从 request.json 或 header 拿)
        device_model = data.get("deviceModel") or data.get("device_model") or request.headers.get("X-Device-Model", "")
        wx_version = data.get("wxVersion") or data.get("wx_version") or request.headers.get("X-WX-Version", "")
        try:
            _db.upsert_user(
                openid=openid,
                unionid=unionid or None,
                nickname=final_user_info.get("nickname"),
                avatar_url=final_user_info.get("avatar") if final_user_info.get("avatar", "").startswith("http") else None,
                device_model=device_model or None,
                wx_version=wx_version or None,
                is_guest=False,
            )
        except Exception as e:
            print(f"[登录] ⚠️ 入库失败(不影响登录): {e}", file=sys.stderr)

        return jsonify({
            "ok": True,
            "openid": openid,
            "unionid": unionid,
            "sessionToken": session_key,  # 真微信:session_key 就是 session token
            "userInfo": final_user_info,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"wechat jscode2session 失败: {e}"}), 500





# ===== 启动 =====
# 初始化 SQLite(每次启动建表)
import db as _db
_db.init_db()


# ============================================================
# Admin API(管理后台用)
# ============================================================
ADMIN_TOKEN = os.environ.get("CROP_DOCTOR_ADMIN_TOKEN", AUTH_TOKEN)  # 默认复用 AUTH_TOKEN


def _check_admin():
    """admin 鉴权(从 query 或 header 拿)"""
    token = (request.args.get("admin_token") or
             request.headers.get("X-Admin-Token", "")).strip()
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return jsonify({"ok": False, "error": "admin unauthorized"}), 401
    return None


@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    """总览统计(支持 time_range 过滤)"""
    err = _check_admin()
    if err: return err
    time_range = request.args.get("time_range")  # '24h' / '7d' / '30d' / None
    return jsonify({
        "ok": True,
        "stats": _db.get_stats(time_range=time_range),
        "time_range": time_range or "all",
    })


@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    """用户列表(支持 time_range)"""
    err = _check_admin()
    if err: return err
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    time_range = request.args.get("time_range")
    users = _db.list_users(limit=limit, offset=offset, time_range=time_range)
    total = _db.count_users(time_range=time_range)
    return jsonify({"ok": True, "users": users, "total": total})


@app.route("/api/admin/diagnoses", methods=["GET"])
def admin_diagnoses():
    """诊断历史(支持 time_range)"""
    err = _check_admin()
    if err: return err
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    openid = request.args.get("openid")
    time_range = request.args.get("time_range")
    diags = _db.list_diagnoses(limit=limit, offset=offset, openid=openid, time_range=time_range)
    total = _db.count_diagnoses(openid=openid, time_range=time_range)
    return jsonify({"ok": True, "diagnoses": diags, "total": total})


@app.route("/api/admin/feedbacks", methods=["GET"])
def admin_feedbacks():
    """反馈列表(支持 time_range + key 过滤)"""
    err = _check_admin()
    if err: return err
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    openid = request.args.get("openid")
    key = request.args.get("key")  # A/B/C/D/E
    time_range = request.args.get("time_range")
    fbs = _db.list_feedbacks(limit=limit, offset=offset, openid=openid, key=key, time_range=time_range)
    total = _db.count_feedbacks(openid=openid, key=key, time_range=time_range)
    return jsonify({"ok": True, "feedbacks": fbs, "total": total})


@app.route("/api/admin/negative-feedbacks", methods=["GET"])
def admin_negative_feedbacks():
    """最近负面反馈(D恶化+E还没)— 高亮用"""
    err = _check_admin()
    if err: return err
    limit = int(request.args.get("limit", 20))
    time_range = request.args.get("time_range", "24h")
    fbs = _db.get_recent_negative_feedbacks(limit=limit, time_range=time_range)
    return jsonify({"ok": True, "feedbacks": fbs, "time_range": time_range})


# ============================================================
# Admin HTML 页面
# ============================================================
_ADMIN_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>征途问诊 · 管理后台</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
       background: #f5f7fa; color: #1f2937; }
.container { max-width: 1280px; margin: 0 auto; padding: 24px; }
h1 { font-size: 24px; margin-bottom: 8px; }
h2 { font-size: 18px; margin: 24px 0 12px; color: #374151; }
.subtitle { color: #6b7280; font-size: 14px; margin-bottom: 16px; }
.login-box { max-width: 400px; margin: 80px auto; padding: 32px; background: #fff;
             border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.login-box h1 { text-align: center; margin-bottom: 24px; }
.login-box input { width: 100%; padding: 12px; font-size: 15px; border: 1px solid #d1d5db;
                  border-radius: 8px; margin-bottom: 12px; }
.login-box button { width: 100%; padding: 12px; background: #10b981; color: #fff;
                    border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
.login-box button:hover { background: #059669; }
.error { color: #ef4444; font-size: 13px; margin-top: 8px; text-align: center; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.stat-card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
.stat-label { color: #6b7280; font-size: 13px; }
.stat-value { font-size: 32px; font-weight: 600; margin-top: 4px; color: #10b981; }
.stat-sub { font-size: 12px; color: #9ca3af; margin-top: 4px; }
.row { display: flex; gap: 16px; flex-wrap: wrap; }
.section { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
          flex: 1; min-width: 320px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }
th { background: #f9fafb; font-weight: 600; color: #374151; }
tr:hover { background: #f9fafb; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.badge-success { background: #d1fae5; color: #065f46; }
.badge-warn { background: #fef3c7; color: #92400e; }
.badge-info { background: #dbeafe; color: #1e40af; }
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tab { padding: 8px 16px; border-radius: 8px; background: #e5e7eb; cursor: pointer;
       font-size: 14px; user-select: none; }
.tab.active { background: #10b981; color: #fff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.empty { color: #9ca3af; text-align: center; padding: 24px; font-size: 14px; }
.fb-A { background: #d1fae5; }
.fb-B { background: #ecfccb; }
.fb-C { background: #fef9c3; }
.fb-D { background: #fed7aa; }
.fb-E { background: #fecaca; }
.severity-高 { color: #ef4444; font-weight: 600; }
.severity-中 { color: #f59e0b; }
.severity-低 { color: #10b981; }
.refresh-btn { float: right; padding: 6px 12px; background: #10b981; color: #fff;
               border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
.refresh-btn:hover { background: #059669; }
.ts { color: #9ca3af; font-size: 12px; }
.truncate { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toolbar { background: #fff; padding: 16px 20px; border-radius: 10px; margin-bottom: 16px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.toolbar label { font-size: 13px; color: #4a5568; }
.toolbar select { padding: 6px 10px; border-radius: 6px; border: 1px solid #d1d5db;
                 background: #fff; font-size: 13px; cursor: pointer; }
.toolbar .live-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981;
                     display: inline-block; animation: pulse 2s infinite; margin-right: 6px; }
.toolbar .live-dot.paused { background: #9ca3af; animation: none; }
.toolbar .live-toggle { padding: 4px 10px; border: 1px solid #d1d5db; background: #fff;
                       border-radius: 6px; cursor: pointer; font-size: 12px; }
.toolbar .live-toggle.active { background: #10b981; color: #fff; border-color: #10b981; }
.negative-banner { background: linear-gradient(135deg, #fee2e2, #fecaca); border: 2px solid #ef4444;
                    border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
.negative-banner-title { color: #991b1b; font-weight: 700; font-size: 16px; margin-bottom: 8px; }
.negative-banner-item { background: #fff; border-radius: 6px; padding: 8px 12px; margin-top: 6px;
                        font-size: 13px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.negative-banner-item .badge-D { background: #ef4444; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.negative-banner-item .badge-E { background: #b91c1c; color: #fff; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.fb-cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 16px; }
.fb-card { background: #fff; border: 2px solid #e5e7eb; border-radius: 10px; padding: 16px 12px;
           text-align: center; cursor: pointer; transition: all 0.15s; user-select: none; }
.fb-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.fb-card.selected { border-color: #10b981; background: linear-gradient(135deg, #ecfdf5, #d1fae5); box-shadow: 0 2px 8px rgba(16,185,129,0.2); }
.fb-card .fb-card-key { font-size: 24px; font-weight: 700; padding: 4px 0; border-radius: 6px; margin-bottom: 6px; }
.fb-card .fb-card-label { font-size: 12px; color: #6b7280; margin-bottom: 4px; }
.fb-card .fb-card-count { font-size: 20px; font-weight: 700; color: #1f2937; }
.fb-card[data-key="A"] .fb-card-key { background: #d1fae5; color: #065f46; }
.fb-card[data-key="B"] .fb-card-key { background: #ecfccb; color: #3f6212; }
.fb-card[data-key="C"] .fb-card-key { background: #fef9c3; color: #854d0e; }
.fb-card[data-key="D"] .fb-card-key { background: #fed7aa; color: #9a3412; }
.fb-card[data-key="E"] .fb-card-key { background: #fecaca; color: #991b1b; }
.fb-list-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.fb-list-header .refresh-btn { background: #3b82f6; }
.fb-list-header .refresh-btn:hover { background: #2563eb; }
.fb-list-status { font-size: 13px; color: #4a5568; }
.fb-list-status b { color: #1f2937; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>
</head>
<body>
<div class="container" id="root">
  <div id="loginView" class="login-box">
    <h1>🌾 征途问诊管理后台</h1>
    <p class="subtitle" style="text-align:center;margin-bottom:24px;">请输入 Admin Token 登录</p>
    <input id="adminToken" type="password" placeholder="Admin Token (环境变量 CROP_DOCTOR_ADMIN_TOKEN)" />
    <button onclick="doLogin()">登 录</button>
    <div id="loginError" class="error"></div>
  </div>
  <div id="mainView" style="display:none;">
    <h1>🌾 征途问诊管理后台</h1>
    <p class="subtitle">用户 · 诊断 · 反馈 统计与分析</p>
    <button class="refresh-btn" onclick="loadAll()">🔄 刷新全部</button>

    <!-- ★ 负面反馈高亮区(D 恶化 + E 还没处理) -->
    <div id="negativeBanner" class="negative-banner" style="display:none;">
      <div class="negative-banner-title">⚠️ 近期负面反馈</div>
      <div id="negativeBannerList"></div>
    </div>

    <!-- ★ 工具栏:时间范围 + 30 秒轮询开关(反馈选项已挪到反馈 tab 顶部卡片) -->
    <div class="toolbar">
      <label>时间范围:</label>
      <select id="timeRange" onchange="onTimeRangeChange()">
        <option value="">全部</option>
        <option value="24h" selected>最近 24 小时</option>
        <option value="7d">最近 7 天</option>
        <option value="30d">最近 30 天</option>
      </select>
      <div style="flex:1;"></div>
      <span class="live-dot" id="liveDot"></span>
      <span style="font-size:12px;color:#6b7280;" id="liveStatus">30秒自动刷新</span>
      <button class="live-toggle active" id="liveToggle" onclick="toggleLive()">⏸ 暂停</button>
    </div>

    <div class="tabs">
      <div class="tab active" data-tab="overview" onclick="switchTab('overview')">📊 总览</div>
      <div class="tab" data-tab="users" onclick="switchTab('users')">👤 用户</div>
      <div class="tab" data-tab="diagnoses" onclick="switchTab('diagnoses')">🩺 诊断</div>
      <div class="tab" data-tab="feedbacks" onclick="switchTab('feedbacks')">💬 反馈</div>
    </div>
    <div id="tab-overview" class="tab-content active"></div>
    <div id="tab-users" class="tab-content"></div>
    <div id="tab-diagnoses" class="tab-content"></div>
    <div id="tab-feedbacks" class="tab-content"></div>
  </div>
</div>
<script>
// ★ 支持 ?admin_token=xxx URL 参数(方便分享,首次访问时直接登录)
const _urlToken = new URLSearchParams(location.search).get('admin_token') || '';
if (_urlToken) localStorage.setItem('admin_token', _urlToken);
let ADMIN_TOKEN = localStorage.getItem('admin_token') || '';
// ★ 反馈 tab 状态:当前选中的 A-E(默认 null = 全部)
let _fbSelectedKey = null;
let _fbListCache = null;       // 缓存上次列表结果
let _fbListLoading = false;    // 防抖
function $(id) { return document.getElementById(id); }
// ★ 登录页 input 自动填(localStorage 有就预填)
document.addEventListener('DOMContentLoaded', () => {
  const inp = $('adminToken');
  if (inp && ADMIN_TOKEN) inp.value = ADMIN_TOKEN;
});
function doLogin() {
  ADMIN_TOKEN = $('adminToken').value.trim();
  if (!ADMIN_TOKEN) { $('loginError').textContent = '请输入 token'; return; }
  localStorage.setItem('admin_token', ADMIN_TOKEN);
  loadAll().then(() => {
    if ($('mainView').style.display !== 'none') {
      $('loginView').style.display = 'none';
      startLive();  // ★ 登录成功 → 启动 30 秒轮询
    }
  }).catch(e => {
    $('loginError').textContent = 'Token 错误或后端不可用: ' + e.message;
    localStorage.removeItem('admin_token');
  });
}
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.toggle('active', t.id === 'tab-' + tab));
}
async function api(path) {
  const sep = path.includes('?') ? '&' : '?';
  const fullUrl = path + sep + 'admin_token=' + encodeURIComponent(ADMIN_TOKEN);
  const r = await fetch(fullUrl);
  if (r.status === 401) throw new Error('admin token 无效 (401)');
  if (!r.ok) {
    // ★ 非 2xx(404/500/...),显式提示,方便排查
    const t = await r.text();
    throw new Error('HTTP ' + r.status + ' on ' + path + ' — ' + t.substring(0, 200));
  }
  const ct = r.headers.get('Content-Type') || '';
  if (!ct.includes('application/json')) {
    const t = await r.text();
    throw new Error('非 JSON 响应 from ' + path + ' (Content-Type: ' + ct + ') — ' + t.substring(0, 200));
  }
  return r.json();
}
function fmtTs(ts) {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
}
function renderOverview(s, tr) {
  const feedbackHtml = Object.entries(s.feedback_distribution || {}).map(
    ([k, v]) => `<tr><td><span class="badge fb-${k}">${k}</span></td><td>${v}</td></tr>`
  ).join('') || '<tr><td colspan="2" class="empty">暂无反馈</td></tr>';
  const topDis = (s.top_diseases || []).map(d =>
    `<tr><td>${d.name}</td><td>${d.count}</td></tr>`
  ).join('') || '<tr><td colspan="2" class="empty">暂无数据</td></tr>';
  const topCr = (s.top_crops || []).map(d =>
    `<tr><td>${d.name}</td><td>${d.count}</td></tr>`
  ).join('') || '<tr><td colspan="2" class="empty">暂无数据</td></tr>';
  const trLabel = tr === '24h' ? '最近 24 小时' : tr === '7d' ? '最近 7 天' : tr === '30d' ? '最近 30 天' : '全部时间';
  const neg = s.negative_feedbacks || 0;
  const negCard = neg > 0
    ? `<div class="stat-card" style="background:linear-gradient(135deg,#fef2f2,#fee2e2);border:2px solid #ef4444;">
         <div class="stat-label" style="color:#991b1b;">⚠️ 负面反馈</div>
         <div class="stat-value" style="color:#b91c1c;">${neg}</div>
         <div class="stat-sub" style="color:#7f1d1d;">D 恶化 + E 未处理 · ${trLabel}</div>
       </div>`
    : `<div class="stat-card">
         <div class="stat-label">⚠️ 负面反馈</div>
         <div class="stat-value" style="color:#10b981;">0</div>
         <div class="stat-sub">D 恶化 + E 未处理 · ${trLabel}</div>
       </div>`;
  return `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">总用户</div><div class="stat-value">${s.total_users}</div><div class="stat-sub">${trLabel}</div></div>
      <div class="stat-card"><div class="stat-label">总诊断</div><div class="stat-value">${s.total_diagnoses}</div><div class="stat-sub">今日 ${s.today_diagnoses} · 图 ${s.image_diagnoses} · 文 ${s.text_diagnoses}</div></div>
      <div class="stat-card"><div class="stat-label">KB 命中</div><div class="stat-value">${s.kb_hits}</div><div class="stat-sub">知识库直出,免智谱调用</div></div>
      <div class="stat-card"><div class="stat-label">总反馈</div><div class="stat-value">${s.total_feedbacks}</div><div class="stat-sub">${trLabel}</div></div>
      ${negCard}
    </div>
    <div class="row">
      <div class="section">
        <h2>📈 Top 5 常见病</h2>
        <table><thead><tr><th>病名</th><th>次数</th></tr></thead><tbody>${topDis}</tbody></table>
      </div>
      <div class="section">
        <h2>🌾 Top 5 常见作物</h2>
        <table><thead><tr><th>作物</th><th>次数</th></tr></thead><tbody>${topCr}</tbody></table>
      </div>
      <div class="section">
        <h2>💬 反馈分布</h2>
        <table><thead><tr><th>选项</th><th>数量</th></tr></thead><tbody>${feedbackHtml}</tbody></table>
      </div>
    </div>
  `;
}
function renderUsers(data) {
  if (!data.users || !data.users.length) return '<div class="empty">暂无用户</div>';
  return `<div class="section"><h2>👤 用户列表 (共 ${data.total})</h2>
    <table><thead><tr><th>openid</th><th>昵称</th><th>设备</th><th>登录数</th><th>最后活跃</th><th>注册时间</th></tr></thead><tbody>
    ${data.users.map(u => `<tr>
      <td class="truncate" title="${u.openid}">${u.openid}</td>
      <td>${u.nickname || '-'}</td>
      <td>${u.device_model || '-'}</td>
      <td>${u.login_count}</td>
      <td class="ts">${fmtTs(u.last_active_at)}</td>
      <td class="ts">${fmtTs(u.login_at)}</td>
    </tr>`).join('')}
    </tbody></table></div>`;
}
function renderDiagnoses(data) {
  if (!data.diagnoses || !data.diagnoses.length) return '<div class="empty">暂无诊断</div>';
  return `<div class="section"><h2>🩺 诊断历史 (共 ${data.total})</h2>
    <table><thead><tr><th>时间</th><th>openid</th><th>作物</th><th>病名</th><th>严重度</th><th>概率</th><th>类型</th><th>来源</th></tr></thead><tbody>
    ${data.diagnoses.map(d => `<tr>
      <td class="ts">${fmtTs(d.ts)}</td>
      <td class="truncate" title="${d.openid || ''}">${d.openid || '-'}</td>
      <td>${d.crop || '-'}</td>
      <td>${d.disease_name || '-'}</td>
      <td><span class="severity-${d.severity || ''}">${d.severity || '-'}</span></td>
      <td>${d.probability != null ? (d.probability * 100).toFixed(0) + '%' : '-'}</td>
      <td>${d.is_text_only ? '文字' : (d.image_count + '图')}</td>
      <td>${d.is_kb_hit ? '<span class="badge badge-success">KB</span>' : (d.is_demo ? '<span class="badge badge-warn">demo</span>' : '<span class="badge badge-info">AI</span>')}</td>
    </tr>`).join('')}
    </tbody></table></div>`;
}
function renderFeedbacks(dist, data) {
  // dist = { A: 2, B: 0, ... } (来自 stats,按 time_range 过滤后的分布)
  // data = { feedbacks: [...], total: N } (当前选中选项的列表,可能为 null 表示还没刷新)
  const labels = { A: '解决了', B: '改善一些', C: '没变化', D: '恶化了', E: '还没处理' };
  const cards = ['A', 'B', 'C', 'D', 'E'].map(k => {
    const cnt = (dist && dist[k]) || 0;
    const sel = _fbSelectedKey === k;
    return `<div class="fb-card ${sel ? 'selected' : ''}" data-key="${k}" onclick="selectFbKey('${k}')" title="点击${sel ? '取消' : '筛选'}${labels[k]}的反馈">
      <div class="fb-card-key">${k}</div>
      <div class="fb-card-label">${labels[k]}</div>
      <div class="fb-card-count">${cnt}</div>
    </div>`;
  }).join('');
  // ★ 列表头部:手动刷新按钮 + 当前状态
  const listHeader = `
    <div class="fb-list-header">
      <button class="refresh-btn" onclick="refreshFbList()" id="fbRefreshBtn">🔄 手动刷新</button>
      <span class="fb-list-status">
        当前选项: <b>${_fbSelectedKey ? _fbSelectedKey + ' ' + labels[_fbSelectedKey] : '全部'}</b>
        ${data && data.total != null ? `· 共 <b>${data.total}</b> 条` : '· <span style="color:#9ca3af;">未刷新</span>'}
        ${_fbListLoading ? '· <span style="color:#3b82f6;">⏳ 加载中...</span>' : ''}
      </span>
      <span class="ts" style="margin-left:auto;" id="fbLastRefresh"></span>
    </div>
  `;
  // ★ 列表内容
  let listHtml;
  if (!data) {
    listHtml = '<div class="empty">点击「🔄 手动刷新」加载反馈列表</div>';
  } else if (!data.feedbacks || !data.feedbacks.length) {
    listHtml = `<div class="empty">${_fbSelectedKey ? '该选项暂无反馈' : '暂无反馈'}</div>`;
  } else {
    listHtml = `<div class="section"><table><thead><tr>
      <th>时间</th><th>openid</th><th>选项</th><th>病名</th><th>严重度</th><th>文本</th>
    </tr></thead><tbody>
    ${data.feedbacks.map(f => `<tr>
      <td class="ts">${fmtTs(f.ts)}</td>
      <td class="truncate" title="${f.openid || ''}">${f.openid || '-'}</td>
      <td><span class="badge fb-${f.key}">${f.key || '-'}</span></td>
      <td>${f.disease_name || '-'}</td>
      <td><span class="severity-${f.severity || ''}">${f.severity || '-'}</span></td>
      <td>${f.text || '-'}</td>
    </tr>`).join('')}
    </tbody></table></div>`;
  }
  return `
    <h2 style="margin:8px 0 12px;">💬 反馈管理</h2>
    <div class="fb-cards">${cards}</div>
    ${listHeader}
    <div id="fbListContainer">${listHtml}</div>
  `;
}
async function loadAll() {
  if (!ADMIN_TOKEN) { $('mainView').style.display = 'none'; $('loginView').style.display = 'block'; return; }
  // ★ 拿当前过滤参数(注意:反馈选项过滤已挪到卡片点击,这里不再传 key)
  const tr = $('timeRange').value;
  // ★ trQ 必须是 ? 开头(被拼到 path 后面,如果 & 开头会变成 /stats&... 这种坏 URL)
  const trQ = tr ? '?time_range=' + encodeURIComponent(tr) : '';
  const [stats, users, diags, fbs, negatives] = await Promise.all([
    api('/api/admin/stats' + trQ),
    api('/api/admin/users' + trQ),
    api('/api/admin/diagnoses' + trQ),
    api('/api/admin/feedbacks' + trQ),  // 不带 key,让 _fbSelectedKey 在 refreshFbList 里控制
    api('/api/admin/negative-feedbacks?time_range=' + (tr || '24h')),
  ]);
  $('loginView').style.display = 'none';
  $('mainView').style.display = 'block';
  $('tab-overview').innerHTML = renderOverview(stats.stats, stats.time_range);
  $('tab-users').innerHTML = renderUsers(users);
  $('tab-diagnoses').innerHTML = renderDiagnoses(diags);
  // ★ 反馈 tab:不重渲整个列表,只更新顶部卡片(用缓存的列表数据)
  _lastDist = stats.stats.feedback_distribution || {};
  $('tab-feedbacks').innerHTML = renderFeedbacks(_lastDist, _fbListCache);
  // ★ 如果反馈 tab 还没加载过,自动加载一次(首次进入)
  if (!_fbListCache && !_fbListLoading) {
    refreshFbList();
  }

  // ★ 渲染负面反馈高亮区
  if (negatives.feedbacks && negatives.feedbacks.length > 0) {
    $('negativeBanner').style.display = 'block';
    $('negativeBannerList').innerHTML = negatives.feedbacks.map(f => `
      <div class="negative-banner-item">
        <span class="badge-${f.key}">${f.key === 'D' ? '恶化' : '未处理'}</span>
        <span><b>${f.disease_name || '未知病'}</b> · ${f.crop || '-'} · ${f.severity || '-'}</span>
        <span class="ts">${fmtTs(f.ts)}</span>
        <span style="color:#6b7280;">${f.openid ? f.openid.substring(0, 12) + '...' : '-'}</span>
        <span style="color:#374151;flex:1;">${f.text ? '💬 ' + f.text : ''}</span>
      </div>
    `).join('');
  } else {
    $('negativeBanner').style.display = 'none';
  }
}

// ★ 自动轮询(30 秒)
let liveTimer = null;
let livePaused = false;
function startLive() {
  if (liveTimer) return;
  livePaused = false;
  $('liveToggle').textContent = '⏸ 暂停';
  $('liveToggle').classList.add('active');
  $('liveDot').classList.remove('paused');
  $('liveStatus').textContent = '30秒自动刷新';
  liveTimer = setInterval(loadAll, 30000);
}
function stopLive() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  livePaused = true;
  $('liveToggle').textContent = '▶ 恢复';
  $('liveToggle').classList.remove('active');
  $('liveDot').classList.add('paused');
  $('liveStatus').textContent = '已暂停';
}
function toggleLive() { livePaused ? startLive() : stopLive(); }

// ★ 反馈 tab:点击 A/B/C/D/E 卡片切换筛选
function selectFbKey(k) {
  if (_fbSelectedKey === k) {
    _fbSelectedKey = null;  // 再次点击取消选中
  } else {
    _fbSelectedKey = k;
  }
  refreshFbList();  // 重新拉取列表
}

// ★ 反馈 tab:手动刷新按钮 / 切换选项时调用
async function refreshFbList() {
  if (!ADMIN_TOKEN) return;
  if (_fbListLoading) return;  // 防抖:已有请求在跑
  _fbListLoading = true;
  // 立刻显示「加载中」
  const tabEl = $('tab-feedbacks');
  if (tabEl) tabEl.innerHTML = renderFeedbacks(_lastDist, _fbListCache);
  try {
    const tr = $('timeRange').value;
    const fk = _fbSelectedKey;
    // ★ 必须 ? 开头(同 loadAll 的修复)
    const trQ = tr ? '?time_range=' + encodeURIComponent(tr) : '';
    const fkQ = fk ? (trQ ? '&key=' : '?key=') + encodeURIComponent(fk) : '';
    const fbs = await api('/api/admin/feedbacks' + trQ + fkQ);
    _fbListCache = fbs;
    if (tabEl) tabEl.innerHTML = renderFeedbacks(_lastDist, fbs);
    const ts = $('fbLastRefresh');
    if (ts) ts.textContent = '上次刷新: ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
  } catch (e) {
    alert('刷新失败: ' + e.message);
  } finally {
    _fbListLoading = false;
  }
}

// ★ 缓存最新的 distribution(供 refreshFbList 重渲时用)
let _lastDist = null;

// ★ 时间范围切换:先 loadAll 刷新卡片,再 refreshFbList 同步列表
async function onTimeRangeChange() {
  _fbListCache = null;  // 旧列表作废,让 refreshFbList 重新拉
  await loadAll();
  await refreshFbList();
}

// 启动轮询(用户登录成功后由 doLogin 触发)
if (ADMIN_TOKEN) { loadAll().then(startLive); }
</script>
</body>
</html>'''


@app.route("/admin", methods=["GET"])
def admin_page():
    """管理后台 HTML(简单密码保护)"""
    # 用 query 参数 ?admin_token=xxx 或 cookie 鉴权
    token = (request.args.get("admin_token") or
             request.cookies.get("admin_token") or
             "").strip()
    body = _ADMIN_HTML
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        # 返登录页(包含 token 输入框)
        body = _ADMIN_HTML.replace('id="mainView" style="display:none;"', 'id="mainView" style="display:none;"')
    # ★ 强制不缓存,JS 升级时浏览器不会跑旧版
    resp = Response(body, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/admin/login", methods=["POST"])
def admin_login():
    """admin 登录(返回 cookie)"""
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("admin_token") or "").strip()
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return jsonify({"ok": False, "error": "token 错误"}), 401
    resp = jsonify({"ok": True})
    resp.set_cookie("admin_token", token, max_age=86400, httponly=True, samesite="Lax")
    return resp

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print(f"征途问诊后端启动: http://0.0.0.0:{port}", file=sys.stderr)
    print(f"  GET  /api/health         - 健康检查(公开)", file=sys.stderr)
    print(f"  POST /api/identify       - 作物识别(默认 demo,?real=1 走真 AI)", file=sys.stderr)
    print(f"  POST /api/diagnose       - 病害诊断(自动 chain identify,?real=1 走真 AI)", file=sys.stderr)
    print(f"  POST /api/feedback       - 提交反馈(需 X-Auth-Token,SQLite 持久化)", file=sys.stderr)
    print(f"  POST /api/wechat-login   - 微信快捷登录(存 SQLite users 表)", file=sys.stderr)
    print(f"  GET  /api/admin/stats    - 管理后台统计(需 admin token)", file=sys.stderr)
    print(f"  GET  /api/admin/users    - 用户列表(需 admin token)", file=sys.stderr)
    print(f"  GET  /api/admin/diagnoses- 诊断历史(需 admin token)", file=sys.stderr)
    print(f"  GET  /api/admin/feedbacks- 反馈列表(需 admin token)", file=sys.stderr)
    print(f"  GET  /admin              - 管理后台 HTML(简单密码保护)", file=sys.stderr)
    if AUTH_TOKEN:
        print(f"  Token 鉴权:已启用(token 长度: {len(AUTH_TOKEN)})", file=sys.stderr)
    else:
        print(f"  Token 鉴权:[WARNING] 未配置 CROP_DOCTOR_TOKEN", file=sys.stderr)
    if WECHAT_APPID and WECHAT_SECRET:
        print(f"  微信登录:已配置(真 jscode2session 模式)", file=sys.stderr)
    else:
        print(f"  微信登录:[INFO] 未配置 WECHAT_APPID,使用 demo openid 兜底", file=sys.stderr)
    print(f"  真实 AI 链路:{'✓ 可用' if _matrix_available() else '✗ 不可用(本地 demo 模式)'}", file=sys.stderr)
    app.run(host="0.0.0.0", port=port, debug=False)
