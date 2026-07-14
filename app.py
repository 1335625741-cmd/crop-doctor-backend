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
import os
import shutil
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
    from flask import Flask, request, jsonify
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
SKILL_BIN_DIR = SKILL_DIR / "bin"
IDENTIFIER_SKILL_DIR = SCRIPT_DIR.parent.parent / "skills" / "crop-identifier"
IDENTIFIER_BIN_DIR = IDENTIFIER_SKILL_DIR / "bin"

app = Flask(__name__)
if ALLOWED_ORIGINS:
    CORS(app, origins=ALLOWED_ORIGINS)
else:
    CORS(app)

UPLOAD_DIR = Path(tempfile.gettempdir()) / "crop_doctor_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_FILE = SCRIPT_DIR / "feedback.jsonl"


# ===== 鉴权 =====
@app.before_request
def check_auth():
    PUBLIC_PATHS = {"/api/health"}
    if request.path in PUBLIC_PATHS:
        return None
    if not AUTH_TOKEN:
        return jsonify({"ok": False, "error": "服务端未配置 CROP_DOCTOR_TOKEN"}), 503
    token = request.headers.get("X-Auth-Token", "").strip()
    if not token or token != AUTH_TOKEN:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return None


# ===== 健康检查 =====
@app.route("/api/health", methods=["GET"])
def health():
    # 真实 AI 优先级:智谱 > mavis
    real_backend = "zhipu-glm4v" if _zhipu_available() else ("mavis" if _matrix_available() else None)
    return jsonify({
        "ok": True,
        "ts": time.time(),
        "version": "1.1.1",
        "mode": "real" if real_backend else "demo",
        "real_backend": real_backend,
        "zhipu_configured": _zhipu_available(),
        "matrix_configured": _matrix_available(),
        "wechat_configured": bool(WECHAT_APPID and WECHAT_SECRET),
    })


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


# ===== /api/identify(作物识别) =====
@app.route("/api/identify", methods=["POST"])
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
        parts = (request.form.get("parts") or "").strip() or None
        location = (request.form.get("location") or "").strip() or None
        season = (request.form.get("season") or "").strip() or None

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
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass


# ===== /api/diagnose(病害诊断,图片 OR 文字) =====
@app.route("/api/diagnose", methods=["POST"])
def diagnose():
    """第二阶段:病害诊断
    - 有 image → 走图片模式(自动 chain identify)
    - 有 text  无 image → 走文字模式(LLM 文字问诊)
    - 两个都没有 → 400
    """
    image_files = request.files.getlist("image")
    text_query = (request.form.get("text") or "").strip()

    if not image_files and not text_query:
        return jsonify({"ok": False, "error": "请上传图片或输入症状描述"}), 400

    use_real = request.args.get("real") == "1"

    if image_files:
        # 图片模式
        if use_real and _zhipu_available():
            return _diagnose_real(image_files)
        elif use_real and _matrix_available():
            return _diagnose_real(image_files)
        return _diagnose_demo(image_files, text_query)
    else:
        # 纯文字模式
        if use_real and _zhipu_available():
            return _consult_real(text_query)
        elif use_real and _matrix_available():
            return _consult_real(text_query)
        return _consult_demo(text_query)


def _diagnose_demo(image_files, text_query=""):
    """demo 模式:返回一对(diagnosis, identified_crop)"""
    # 优先按文字关键词挑,否则按图片 hash
    pair = _pick_pair_by_text(text_query) if text_query else None
    if not pair:
        h = hashlib.md5()
        for f in image_files:
            h.update((f.filename or "").encode("utf-8"))
            f.seek(0, 2)
            h.update(str(f.tell()).encode("utf-8"))
            f.seek(0)
        seed = int(h.hexdigest()[:8], 16)
        pair = pick_pair(image_count=len(image_files), seed=seed)
    diagnosis, identified = pair

    # ★ 关键:把识别结果嵌入诊断返回
    diagnosis["_is_demo"] = True
    diagnosis["_demo_reason"] = "服务端 demo 模式:返回固定诊断 + 固定识别结果,不是基于图片分析"
    diagnosis["_identified_crop"] = identified
    diagnosis["_chain"] = {
        "stage1_identified": True,
        "stage2_diagnosed": True,
        "identified_crop_name": (identified.get("primary_crop") or {}).get("name_zh"),
        "auto_chainable": any(d.get("auto_chainable") for d in identified.get("downstream_skills", [])),
    }
    return jsonify(diagnosis)


# ===== 文字问诊 =====
KEYWORD_MAP = [
    (["番茄", "tomato", "叶黑圈", "同心轮纹", "早疫"], 0),  # 番茄
    (["水稻", "稻子", "稻瘟", "穗颈瘟", "叶瘟"], 1),         # 水稻
    (["黄瓜", "cucumber", "白粉", "面粉", "霜霉"], 2),         # 黄瓜
    (["柑橘", "橘子", "黄龙", "斑驳", "黄化", "缺锌"], 3),     # 柑橘
    (["玉米", "棒子", "大斑", "小斑", "梭形"], 4),            # 玉米
]


def _pick_pair_by_text(text):
    """按文字关键词挑 mock,没匹配返回 None"""
    if not text:
        return None
    lower = text.lower()
    for keywords, idx in KEYWORD_MAP:
        for kw in keywords:
            if kw.lower() in lower:
                from embedded_mocks import MOCK_PAIR
                import copy
                return copy.deepcopy(MOCK_PAIR[idx][0]), copy.deepcopy(MOCK_PAIR[idx][1])
    return None


def _consult_demo(text_query):
    """文字问诊 demo 模式:按关键词挑 mock"""
    pair = _pick_pair_by_text(text_query)
    if not pair:
        # 没匹配:随机挑 + 提示"请补充作物名"
        import random
        idx = random.randint(0, 4)
        from embedded_mocks import MOCK_PAIR
        import copy
        pair = (copy.deepcopy(MOCK_PAIR[idx][0]), copy.deepcopy(MOCK_PAIR[idx][1]))

    diagnosis, identified = pair

    diagnosis["_is_demo"] = True
    diagnosis["_is_text_only"] = True
    diagnosis["_demo_reason"] = (
        "服务端 demo 模式:基于您输入的文字关键词匹配到 1 份预置诊断。"
        "要接真实 AI,请在服务端启用 ?real=1 模式(需配置 mavis + matrix)。"
    )
    diagnosis["_identified_crop"] = identified
    diagnosis["_chain"] = {
        "stage1_identified_by": "text_keyword",
        "stage2_diagnosed_by": "demo_template",
        "identified_crop_name": (identified.get("primary_crop") or {}).get("name_zh"),
        "auto_chainable": True,
    }
    return jsonify(diagnosis)


def _consult_real(text_query):
    """文字问诊真实模式:调智谱 GLM-4V 文字版"""
    try:
        prompt = _build_consult_prompt(text_query)
        # 文字问诊无图,传空 list(智谱 glm-4v-plus max_tokens 1-2048)
        print(f"[zhipu] consult: text='{text_query[:50]}'", file=sys.stderr)
        result = _call_zhipu_glm4v([], prompt, max_tokens=1500, timeout=45)
        # 兜底
        result.setdefault("is_crop", True)
        result.setdefault("primary_crop", {"name_zh": "未知", "confidence": 0.3})
        result.setdefault("candidates", [])
        result.setdefault("diagnosis", [{
            "name": "文字描述待确认",
            "probability": 0.5,
            "severity": "未知",
            "reasoning": "基于文字描述的初步判断",
            "key_visual_clues": [],
            "uncertainty_reason": "没有图片,建议上传 1-3 张照片获取精准诊断",
            "need_expert": True,
        }])
        result.setdefault("treatment", {
            "title": "文字问诊建议",
            "actions": [
                {"step": 1, "title": "补图", "description": "上传 1-3 张清晰照片(病斑特写/整株/不同角度)"},
                {"step": 2, "title": "补文字", "description": "描述症状持续时间/扩散速度/受影响面积"},
            ],
            "prescription": {
                "title": "未确诊前不建议盲目用药",
                "chemicals": [],
                "safety_warning": "未确诊前不建议盲目用药",
                "followup": "上传图片后免费重跑诊断",
            },
        })
        result["_is_demo"] = False
        result["_is_text_only"] = True
        result["_identified_crop"] = {
            "primary_crop": result.get("primary_crop"),
            "candidates": result.get("candidates", []),
        }
        result["_chain"] = {
            "stage1_identified_by": "text_llm",
            "stage2_diagnosed_by": "zhipu_glm4v",
            "identified_crop_name": result.get("primary_crop", {}).get("name_zh"),
            "auto_chainable": True,
        }
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": "文字问诊异常: " + str(e)}), 500


def _diagnose_real(image_files):
    """真实模式:调智谱 GLM-4V,单次输出 identify + diagnose + treatment"""
    saved_paths, session_dir = _save_images_to_tmp(image_files, prefix="diagnose")
    print(f"[diag] _diagnose_real start, {len(saved_paths)} images", file=sys.stderr)
    try:
        text_query = (request.form.get("text") or "").strip()
        crop = (request.form.get("crop") or "").strip()
        parts = (request.form.get("parts") or "").strip()
        print(f"[diag] form text='{text_query[:30]}' crop='{crop}'", file=sys.stderr)

        # 构造 diagnose prompt
        prompt = _build_diagnose_prompt(text_query)
        print(f"[diag] prompt len={len(prompt)}", file=sys.stderr)

        # 调智谱 GLM-4V(单次调用,一次性输出识别+诊断+方案)
        # 智谱 glm-4v-plus 限制 max_tokens 1-2048
        print(f"[zhipu] diagnose: {len(saved_paths)} 张图, text='{text_query[:50]}'", file=sys.stderr)
        diagnosis = _call_zhipu_glm4v(saved_paths, prompt, max_tokens=2000, timeout=60)
        print(f"[diag] zhipu OK, keys={list(diagnosis.keys())}", file=sys.stderr)

        # 兜底字段
        diagnosis.setdefault("is_crop", True)
        diagnosis.setdefault("primary_crop", {"name_zh": crop or "未识别", "confidence": 0.5})
        diagnosis.setdefault("candidates", [])
        diagnosis.setdefault("diagnosis", [])
        diagnosis.setdefault("treatment", {"title": "", "actions": [], "prescription": {}})

        # 提取 top_diagnosis_name
        diag_list = diagnosis.get("diagnosis", [])
        if not diag_list:
            diag_list = [{"name": "未诊断", "probability": 0, "severity": "未知"}]
            diagnosis["diagnosis"] = diag_list
        top_diag = diag_list[0]
        top_name = top_diag.get("name", "")

        # 构造 prescription(从 treatment 提取)
        treatment = diagnosis.get("treatment", {})
        pres = treatment.get("prescription", {})
        pres_title = pres.get("title", "")
        # 拼成 markdown 表格
        pres_lines = []
        if pres_title:
            pres_lines.append(f"### {pres_title}")
        for chem in pres.get("chemicals", []):
            pres_lines.append(
                f"- **{chem.get('name', '?')}**: {chem.get('dose', '?')} · {chem.get('method', '?')}"
                + (f" · 间隔 {chem.get('interval_days', '?')} 天" if chem.get('interval_days') else "")
                + (f" · 最多 {chem.get('max_times', '?')} 次" if chem.get('max_times') else "")
            )
        if pres.get("safety_warning"):
            pres_lines.append(f"\n⚠️ **{pres['safety_warning']}**")
        if pres.get("followup"):
            pres_lines.append(f"\n📅 **复喷节奏**:{pres['followup']}")
        pres_content = "\n".join(pres_lines) if pres_lines else ""

        full = {
            "diagnosis": diagnosis,
            "top_diagnosis_name": top_name,
            "prescription": {
                "title": pres_title,
                "content": pres_content,
                "available": bool(pres_title),
            },
            "metadata": {
                "image_count": len(saved_paths),
                "images": [p.replace("\\", "/") for p in saved_paths],
                "crop": crop or diagnosis.get("primary_crop", {}).get("name_zh"),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "backend": "zhipu-glm4v",
            },
            "_is_demo": False,
            "_identified_crop": {
                "primary_crop": diagnosis.get("primary_crop"),
                "candidates": diagnosis.get("candidates", []),
            },
            "_chain": {
                "stage1_identified": True,
                "stage2_diagnosed": True,
                "identified_crop_name": diagnosis.get("primary_crop", {}).get("name_zh"),
                "auto_chainable": True,
            },
        }
        return jsonify(full)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        return jsonify({
            "ok": False,
            "error": "诊断服务异常: " + str(e),
            "traceback": tb[-2000:],  # 最近 2000 字符
            "type": type(e).__name__,
        }), 500
    finally:
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass


# ===== 反馈 =====
@app.route("/api/feedback", methods=["POST"])
def feedback():
    try:
        data = request.get_json(force=True, silent=True) or {}
        # ★ 接收前端送来的完整上下文(便于离线分析)
        record = {
            "ts": data.get("ts") or int(time.time() * 1000),
            "key": data.get("key"),
            "topDiagnosis": data.get("topDiagnosis") or data.get("topName"),
            "cropName": data.get("cropName"),
            "severity": data.get("severity"),
            "probability": data.get("probability"),
            "isFallback": bool(data.get("isFallback")),
            "feedbackId": data.get("feedbackId"),
            "messageId": data.get("messageId"),
            "sessionId": data.get("sessionId"),  # ★ 关联 session
            "remark": data.get("remark"),
            "round": data.get("round") or 1,
            "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        }
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print(f"征途问诊后端启动: http://0.0.0.0:{port}", file=sys.stderr)
    print(f"  GET  /api/health         - 健康检查(公开)", file=sys.stderr)
    print(f"  POST /api/identify       - 作物识别(默认 demo,?real=1 走真 AI)", file=sys.stderr)
    print(f"  POST /api/diagnose       - 病害诊断(自动 chain identify,?real=1 走真 AI)", file=sys.stderr)
    print(f"  POST /api/feedback       - 提交反馈(需 X-Auth-Token)", file=sys.stderr)
    print(f"  POST /api/wechat-login   - 微信快捷登录(可选 WECHAT_APPID+SECRET)", file=sys.stderr)
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
