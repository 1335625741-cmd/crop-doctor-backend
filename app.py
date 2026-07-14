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
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

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
    return jsonify({
        "ok": True,
        "ts": time.time(),
        "version": "1.0.0",
        "mode": "demo" if not _matrix_available() else "real_available",
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
    """保存上传图片到临时目录,返回路径列表"""
    ts = int(time.time() * 1000)
    session_dir = UPLOAD_DIR / f"{prefix}-{ts}"
    session_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for idx, f in enumerate(image_files):
        ext = Path(f.filename or "img.jpg").suffix or ".jpg"
        save_path = session_dir / f"{idx}{ext}"
        f.save(save_path)
        saved_paths.append(str(save_path))
    return saved_paths, session_dir


# ===== /api/identify(作物识别) =====
@app.route("/api/identify", methods=["POST"])
def identify():
    """第一阶段:识别作物是什么"""
    image_files = request.files.getlist("image")
    if not image_files:
        return jsonify({"ok": False, "error": "请至少上传 1 张图片"}), 400

    use_real = request.args.get("real") == "1"
    if use_real and _matrix_available():
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
    """真实模式:调 crop-identifier skill"""
    saved_paths, session_dir = _save_images_to_tmp(image_files, prefix="identify")
    try:
        sys.path.insert(0, str(IDENTIFIER_BIN_DIR))
        # 复用 _matrix_client 公共模块
        from _matrix_client import call_matrix_with_retry, extract_diagnosis_json
        from identify_crop import (
            fill_placeholders, load_prompt_template, build_image_info,
            normalize_crop_probabilities,
        )

        template = load_prompt_template()
        import argparse
        args = argparse.Namespace(
            image=saved_paths,
            parts=(request.form.get("parts") or "").strip() or None,
            location=(request.form.get("location") or "").strip() or None,
            season=(request.form.get("season") or "").strip() or None,
        )
        prompt = fill_placeholders(template, args)
        image_info = build_image_info(saved_paths, prompt)

        env_path = str(IDENTIFIER_BIN_DIR)
        matrix_resp = call_matrix_with_retry(image_info, env_path, backoff=[5, 15, 45])
        result = extract_diagnosis_json(matrix_resp)
        normalize_crop_probabilities(result)
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
        if use_real and _matrix_available():
            return _diagnose_real(image_files, text_query)
        return _diagnose_demo(image_files, text_query)
    else:
        # 纯文字模式
        if use_real and _matrix_available():
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
    """文字问诊真实模式:调 LLM 当诊断专家(占位 TODO)"""
    # TODO: 等接好 mavis 后,实现 LLM 文字对话:
    #   1. system prompt 教它"你是作物病害诊断专家"
    #   2. 用户输入当 user message
    #   3. 调 matrix 的 text generation 工具(或任何 LLM)
    #   4. 返回结构化 JSON(同 full-diagnosis 结构)
    #
    # 现在没接 LLM,降级到 demo:
    print(f"[TODO] _consult_real called, text='{text_query[:50]}...', 降级到 demo", file=sys.stderr)
    return _consult_demo(text_query)


def _diagnose_real(image_files):
    """真实模式:先 identify 再 diagnose(两阶段 chain)"""
    saved_paths, session_dir = _save_images_to_tmp(image_files, prefix="diagnose")
    try:
        crop = (request.form.get("crop") or "").strip()
        context = (request.form.get("context") or "").strip()
        parts = (request.form.get("parts") or "").strip()

        # Stage 1: identify(如果前端没传 crop)
        identified_crop = None
        if not crop:
            try:
                sys.path.insert(0, str(IDENTIFIER_BIN_DIR))
                from _matrix_client import call_matrix_with_retry, extract_diagnosis_json
                from identify_crop import (
                    fill_placeholders, load_prompt_template, build_image_info,
                    normalize_crop_probabilities,
                )
                template = load_prompt_template()
                import argparse as ap
                args = ap.Namespace(
                    image=saved_paths, parts=parts or None,
                    location=None, season=None,
                )
                prompt = fill_placeholders(template, args)
                image_info = build_image_info(saved_paths, prompt)
                env_path = str(IDENTIFIER_BIN_DIR)
                matrix_resp = call_matrix_with_retry(image_info, env_path, backoff=[5, 15, 45])
                identified_crop = extract_diagnosis_json(matrix_resp)
                normalize_crop_probabilities(identified_crop)
                if identified_crop.get("is_crop") and identified_crop.get("primary_crop"):
                    crop = identified_crop["primary_crop"].get("name_zh") or ""
            except Exception as e:
                print(f"[warn] identify stage failed: {e}", file=sys.stderr)

        # Stage 2: diagnose
        sys.path.insert(0, str(SKILL_BIN_DIR))
        from full_diagnosis import (
            normalize_diagnosis_probabilities,
            lookup_prescription,
            build_image_info,
            fill_placeholders,
            load_prompt_template,
        )
        from _matrix_client import call_matrix_with_retry, extract_diagnosis_json

        template = load_prompt_template()
        import argparse
        args = argparse.Namespace(
            image=saved_paths, crop=crop or None,
            duration=None, weather=None, chemical=None, parts=parts or None,
        )
        prompt = fill_placeholders(template, args)
        image_info = build_image_info(saved_paths, prompt)

        env_path = str(SKILL_BIN_DIR)
        matrix_resp = call_matrix_with_retry(image_info, env_path, backoff=[5, 15, 45])
        diagnosis = extract_diagnosis_json(matrix_resp)
        normalize_diagnosis_probabilities(diagnosis.get("diagnosis", []))

        top_diag = (diagnosis.get("diagnosis") or [{}])[0]
        top_name = top_diag.get("name", "")
        pres_title, pres_content = lookup_prescription(top_name, env_path)

        full = {
            "diagnosis": diagnosis,
            "top_diagnosis_name": top_name,
            "prescription": {
                "title": pres_title,
                "content": pres_content,
                "available": pres_title is not None,
            },
            "metadata": {
                "image_count": len(saved_paths),
                "images": [p.replace("\\", "/") for p in saved_paths],
                "crop": crop or None,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            "_is_demo": False,
            "_identified_crop": identified_crop,
            "_chain": {
                "stage1_identified": identified_crop is not None,
                "stage2_diagnosed": True,
                "identified_crop_name": (identified_crop or {}).get("primary_crop", {}).get("name_zh") if identified_crop else None,
                "auto_chainable": any(d.get("auto_chainable") for d in (identified_crop or {}).get("downstream_skills", [])),
            },
        }
        return jsonify(full)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error": "诊断服务异常: " + str(e),
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
