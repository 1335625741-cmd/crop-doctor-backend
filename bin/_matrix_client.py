#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_matrix_client.py — matrix HTTP API 调用公共模块(v2,直连不走 mavis CLI)

变化(v2,2026-07-16):
  - 旧版走 `mavis mcp call matrix matrix_describe_images ...` 经 subprocess
    调 MiniMax Code daemon CLI(在 v3.0.51 已拆掉,cli.js 不存在)
  - 新版直接 urllib POST 到 `https://agent.minimaxi.com/mavis/api/v1/mcp/images_understand`
    base URL / path 来源:`D:\MiniMax Code\resources\app.asar\local-runtime\dist\matrix\matrix-env.js`
    endpoint 名 `images_understand` (不是旧的 `matrix_describe_images`!)
  - 鉴权:Authorization: Bearer <jwt> + User-Agent: MiniMaxAgent
  - token 从 `C:\Users\1\.mavis\mcp\tokens.json` 读,过期自动跑 extract_token.py 重新抽
  - images_understand 不收 `file_path`,必须 `data`(base64) + `mime_type` + `prompt`
  - 保留所有公开 API:`call_matrix` / `call_matrix_with_retry` / `MatrixCallError` /
    `extract_diagnosis_json` / `get_hints` / `dump_debug_log`
    这样 `bin/diagnose.py` / `bin/full_diagnosis.py` 不需要改

提供:
  - MatrixCallError(msg, kind)  : 带 kind 标签的异常
  - TIMEOUT_SECONDS / RETRY_COUNT / DEFAULT_BACKOFF_SECONDS
  - call_matrix(image_info, attempt_label, env_path)
      调一次 matrix API,失败抛 MatrixCallError(kind=...) + 落 debug log
  - call_matrix_with_retry(image_info, env_path, backoff)
      重试 + 指数退避 + auth 失效时自动刷新 token 重试一次
  - extract_diagnosis_json(matrix_response) — 跟旧版一样,从 results[0].description 剥 JSON
  - get_hints() — 错误排查建议
  - dump_debug_log(...) — 失败落 matrix-debug-<ts>-<label>.log

兼容:Python 3.5+(避免 f-string,改用 .format())
"""
import base64
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# === Pillow 可用性检测(P0-1 2026-07-20 修) ===
# 原 _PILLOW_AVAILABLE 在 _encode_image_to_data 里被引用但从未定义,
# 用户上传 >5MB 图时直接 NameError。改为顶部 import 时探测。
try:
    from PIL import Image  # noqa: F401
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

# === matrix API 配置(从 mavis asar 配置抽出) ===
# 真实 base:matrix-env.js MANAGED_MATRIX_BASE_URLS.cn.prod
# 默认 cn-prod;可从环境变量 MATRIX_BASE_URL 覆盖
DEFAULT_BASE_URL = "https://agent.minimaxi.com"
TOOL_PATH = "/mavis/api/v1/mcp/images_understand"
USER_AGENT = "MiniMaxAgent"
TIMEOUT_SECONDS = 300          # 冷启动可达 120s,留余量
RETRY_COUNT = 2                # 总共尝试 1 + 1 次 retry
DEFAULT_BACKOFF_SECONDS = [5, 15]

# token 存储位置(由 extract_token.py 写入)
TOKEN_PATH = Path(r"C:\Users\1\.mavis\mcp\tokens.json")
# token 刷新脚本(mavis 桌面端登录态 → JWT 抽取)
EXTRACT_TOKEN_SCRIPT = Path(r"C:\Users\1\.mavis\agents\mavis\workspace\extract_token.py")

DEBUG_LOG_PREFIX = "matrix-debug"
DEBUG_LOG_KEEP = 5
DEBUG_LOG_TRUNCATE_BYTES = 1024 * 1024

# kind → 排查建议
_HINTS = {
    "timeout":             "大概率是冷启动长尾或 matrix 端 hang,稍后再试或减少图片数量",
    "api_error":           "matrix 返回了业务错误,看 message 字段(限流/参数错等)",
    "auth_expired":        "token 过期或失效,已自动跑 extract_token.py 重新抽取并重试,仍失败检查 mavis 桌面端是否登录",
    "image_read_fail":     "本地图片读不到/编码失败,检查路径 + 文件大小(单图上限 20MB)",
    "image_too_large":     "单图 base64 超过 5MB(API 上限),建议压到 2000px 边长或转 JPEG q85",
    "network_error":       "DNS/连接/SSL 失败,检查网络或代理",
    "content_unavailable": "matrix 成功但 results/description 缺失或不可解析",
    "unknown":             "未分类错误,查看 matrix-debug-*.log",
}


class MatrixCallError(RuntimeError):
    """带 kind 标签的 matrix 调用错误"""
    def __init__(self, msg, kind="unknown"):
        super(MatrixCallError, self).__init__(msg)
        self.kind = kind


def _make_child_env(extra_path=None):
    """
    构造子进程 env:把 extra_path 塞进 PATH,强制 PYTHONIOENCODING=utf-8 避免中文乱码
    保留这个函数(虽然 matrix 调用不再用 subprocess),因为 bin/full_diagnosis.py
    还在用它给 identify_crop.py / lookup_prescription.py 等子进程构造 env。
    """
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# === token 管理 ===

def _read_token_file():
    """从 mcp/tokens.json 读 matrix token。返回 dict 或 None"""
    try:
        if not TOKEN_PATH.exists():
            return None
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("matrix")
    except Exception:
        return None


def _is_token_expired(token_info, skew_seconds=60):
    """token 是否过期(预留 60s skew, P2-4 2026-07-20 修: 原 300s 偏短, 常误判)"""
    if not token_info:
        return True
    exp = token_info.get("exp", 0)
    if not exp:
        return True
    return exp < (time.time() + skew_seconds)


def _refresh_token():
    """跑 extract_token.py 重新从 mavis 桌面端 Local Storage 抽 token"""
    if not EXTRACT_TOKEN_SCRIPT.exists():
        raise MatrixCallError(
            "token 刷新脚本不存在: {0}".format(EXTRACT_TOKEN_SCRIPT),
            kind="auth_expired")
    try:
        r = subprocess.run(
            [sys.executable, str(EXTRACT_TOKEN_SCRIPT)],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise MatrixCallError(
                "extract_token.py 失败 (exit={0}): {1}".format(r.returncode, r.stderr[:300]),
                kind="auth_expired")
        return _read_token_file()
    except subprocess.TimeoutExpired:
        raise MatrixCallError(
            "extract_token.py 超时(>30s),检查 mavis 桌面端是否在跑",
            kind="auth_expired")
    except Exception as e:
        raise MatrixCallError(
            "extract_token.py 异常: {0}".format(e), kind="auth_expired")


def get_token(force_refresh=False):
    """拿到当前可用 token(过期则自动刷新一次)"""
    info = None if force_refresh else _read_token_file()
    if info is None or _is_token_expired(info):
        info = _refresh_token()
    if not info or not info.get("token"):
        raise MatrixCallError(
            "拿不到 matrix token(可能 mavis 桌面端未登录),已尝试刷新",
            kind="auth_expired")
    if _is_token_expired(info):
        raise MatrixCallError(
            "刷新后的 token 还是过期(可能 mavis 桌面端未登录),exp={0}".format(info.get("exp")),
            kind="auth_expired")
    return info


# === 图片处理 ===

def _guess_mime(path):
    """根据文件后缀猜 mime,默认 image/jpeg"""
    m, _ = mimetypes.guess_type(str(path))
    return m or "image/jpeg"


def _encode_image_to_data(path):
    """读本地图片 + base64 编码 + 推 mime。返回 (data_b64, mime_type) 或 raise MatrixCallError"""
    p = Path(path)
    if not p.exists():
        raise MatrixCallError(
            "图片不存在: {0}".format(path), kind="image_read_fail")
    try:
        size = p.stat().st_size
    except OSError as e:
        raise MatrixCallError(
            "stat 失败: {0} ({1})".format(path, e), kind="image_read_fail")
    if size == 0:
        raise MatrixCallError(
            "图片为空: {0}".format(path), kind="image_read_fail")
    if size > 20 * 1024 * 1024:
        raise MatrixCallError(
            "图片过大({0:.1f}MB > 20MB): {1}".format(size / 1024 / 1024, path),
            kind="image_read_fail")
    try:
        raw = p.read_bytes()
    except Exception as e:
        raise MatrixCallError(
            "读图失败: {0} ({1})".format(path, e), kind="image_read_fail")
    b64 = base64.b64encode(raw).decode("ascii")
    if len(b64) > 5 * 1024 * 1024:  # 5MB base64 ≈ 3.75MB 原始
        # P2-5 (2026-07-20 修): 尝试用 Pillow 自动压缩(边长缩到 2000px, JPEG q85)
        if _PILLOW_AVAILABLE:
            try:
                from io import BytesIO
                from PIL import Image as _PILImage
                img = _PILImage.open(BytesIO(raw))
                img.thumbnail((2000, 2000))
                buf = BytesIO()
                if img.mode in ("RGBA", "LA", "P"):
                    img.save(buf, format="PNG", optimize=True)
                    mime = "image/png"
                else:
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(buf, format="JPEG", quality=85, optimize=True)
                    mime = "image/jpeg"
                raw = buf.getvalue()
                b64 = base64.b64encode(raw).decode("ascii")
                if len(b64) > 5 * 1024 * 1024:
                    raise MatrixCallError(
                        "压缩后仍 {0:.1f}MB > 5MB, 请手动调整: {1}".format(
                            len(b64) / 1024 / 1024, path),
                        kind="image_too_large")
                return b64, mime
            except ImportError:
                pass  # Pillow 不在, fallback 报错
            except Exception as e:
                print("  [警告] Pillow 压缩失败, fallback: {0}".format(e), file=sys.stderr)
        raise MatrixCallError(
            "base64 编码后 {0:.1f}MB 超过 API 上限(5MB),建议压图后重试: {1}".format(
                len(b64) / 1024 / 1024, path),
            kind="image_too_large")
    return b64, _guess_mime(p)


def _normalize_image_info(image_info, default_prompt=None):
    """把调用方传入的 image_info 列表(每项可能是 {file_path, prompt} 或 {url, mime_type, data})
    统一转成 API 接受的 [{data, mime_type, prompt}, ...] 格式。
    支持的输入格式:
      - {"file_path": "C:/x.jpg", "prompt": "..."}
      - {"url": "https://...", "prompt": "..."}  (直传)
      - {"data": "<base64>", "mime_type": "image/jpeg", "prompt": "..."}
    """
    if not isinstance(image_info, list) or not image_info:
        raise MatrixCallError(
            "image_info 必须是非空 list,实际: {0}".format(type(image_info).__name__),
            kind="api_error")
    out = []
    for i, item in enumerate(image_info):
        if not isinstance(item, dict):
            raise MatrixCallError(
                "image_info[{0}] 必须是 dict,实际: {1}".format(i, type(item).__name__),
                kind="api_error")
        prompt = item.get("prompt") or default_prompt or "描述这张图片"
        if "data" in item and item["data"]:
            # 已 inline base64
            out.append({
                "data": item["data"],
                "mime_type": item.get("mime_type") or "image/jpeg",
                "prompt": prompt,
            })
        elif "url" in item and item["url"]:
            out.append({
                "url": item["url"],
                "prompt": prompt,
            })
        elif "file_path" in item and item["file_path"]:
            data, mime = _encode_image_to_data(item["file_path"])
            out.append({
                "data": data,
                "mime_type": mime,
                "prompt": prompt,
            })
        elif "file" in item and item["file"]:
            # 兼容旧版 build_image_info 用的 "file" 别名
            data, mime = _encode_image_to_data(item["file"])
            out.append({
                "data": data,
                "mime_type": mime,
                "prompt": prompt,
            })
        else:
            raise MatrixCallError(
                "image_info[{0}] 需要 data / url / file_path / file 之一,实际 keys: {1}".format(
                    i, list(item.keys())),
                kind="api_error")
    return out


# === HTTP 调用 ===

def _post_json(url, body, token, timeout):
    """POST JSON,带 auth + UA。返回 dict。raise MatrixCallError。"""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        status = r.status
        try:
            text = r.read().decode("utf-8")
        except UnicodeDecodeError:
            text = r.read().decode("latin-1", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            text = e.read().decode("utf-8")
        except Exception:
            text = str(e)
        # 分类
        if status in (401, 403):
            raise MatrixCallError(
                "HTTP {0} 鉴权失败,token 可能过期: {1}".format(status, text[:300]),
                kind="auth_expired")
        if status == 408:
            raise MatrixCallError(
                "HTTP 408 timeout: {0}".format(text[:300]), kind="timeout")
        if 400 <= status < 500:
            raise MatrixCallError(
                "HTTP {0} 请求错: {1}".format(status, text[:500]), kind="api_error")
        if 500 <= status < 600:
            raise MatrixCallError(
                "HTTP {0} 服务端错: {1}".format(status, text[:500]), kind="api_error")
        raise MatrixCallError(
            "HTTP {0} 未知: {1}".format(status, text[:300]), kind="unknown")
    except urllib.error.URLError as e:
        # DNS/连接/SSL 失败
        raise MatrixCallError(
            "URLError (网络/DNS/SSL): {0}".format(e), kind="network_error")
    except Exception as e:
        # 超时也走这里(socket.timeout)
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            raise MatrixCallError(
                "timeout (>{}s): {}".format(timeout, e), kind="timeout")
        raise MatrixCallError(
            "未知异常: {0} ({1})".format(type(e).__name__, e), kind="unknown")

    if not text:
        raise MatrixCallError("空响应", kind="api_error")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise MatrixCallError(
            "响应不是 JSON: {0} | body: {1}".format(e, text[:300]),
            kind="api_error")


def _resolve_base_url(env_path=None):
    """拿 base URL 。

    P1-6 (2026-07-20 修): env_path dict 参数已废弃, 只保留环境变量。
    - env_path=dict: 调用方如果仍传 dict, 不报错但也不走该分支(只读 env var)
    - env var MATRIX_BASE_URL: 仍可用(例: 调试换线)
    - 默认: DEFAULT_BASE_URL
    """
    if env_path is not None and not isinstance(env_path, dict):
        # 老 API 可能传 str/path(旧类型), 不报错但忽略
        pass
    return os.environ.get("MATRIX_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


# === 公共 API(对外保持兼容) ===

def call_matrix(image_info, attempt_label, env_path=None):
    """调一次 matrix images_understand。失败抛 MatrixCallError(kind=...)。

    image_info 支持:
      - [{"file_path": "C:/x.jpg", "prompt": "..."}, ...]
      - [{"url": "https://...", "prompt": "..."}, ...]
      - [{"data": "<b64>", "mime_type": "image/jpeg", "prompt": "..."}, ...]
      - 也兼容旧版: [{"image_path": "C:/x.jpg"}] (image_path 别名)

    env_path 保留兼容(老 API 传 env dict),新版本忽略内容,只用来 override base URL。
    """
    base_url = _resolve_base_url(env_path)
    url = base_url + TOOL_PATH

    # 兼容 image_path 别名
    norm_input = []
    for it in image_info:
        if isinstance(it, dict) and "image_path" in it and "file_path" not in it:
            it = dict(it)
            it["file_path"] = it.pop("image_path")
        norm_input.append(it)
    payload_image_info = _normalize_image_info(norm_input)

    body = {"image_info": payload_image_info}

    # 取 token
    try:
        tok = get_token(force_refresh=False)
    except MatrixCallError as e:
        dump_debug_log(attempt_label, "", str(e), -1, e.kind, str(e))
        raise

    token = tok["token"]
    print("[{0}] POST {1} (image_count={2})".format(
        attempt_label, url, len(payload_image_info)), file=sys.stderr)

    try:
        resp = _post_json(url, body, token, TIMEOUT_SECONDS)
    except MatrixCallError as e:
        # auth_expired:把请求体也写进 debug(但 base64 太大,只写前 200 字节)
        dbg_body = json.dumps(body, ensure_ascii=False)[:500]
        dump_debug_log(attempt_label, dbg_body, str(e), -1, e.kind, str(e))
        raise

    # 业务校验
    code = resp.get("code", -1)
    if code != 0:
        msg = resp.get("message") or resp.get("base_resp", {}).get("status_msg") or "unknown"
        dump_debug_log(attempt_label,
                       json.dumps(resp, ensure_ascii=False)[:2000],
                       "code != 0", 200, "api_error", msg)
        raise MatrixCallError(
            "matrix 返回 code={0}: {1}".format(code, msg), kind="api_error")

    return resp


def call_matrix_with_retry(image_info, env_path=None,
                            max_attempts=RETRY_COUNT,
                            backoff=DEFAULT_BACKOFF_SECONDS):
    """带 retry + 指数退避 + auth 失败自动刷新 token 重试"""
    last_err = None
    auth_retried = False
    for i in range(1, max_attempts + 1):
        try:
            return call_matrix(image_info, "attempt {0}/{1}".format(i, max_attempts), env_path)
        except MatrixCallError as e:
            last_err = e
            print("[warn] attempt {0} 失败 [{1}]: {2}".format(i, e.kind, e), file=sys.stderr)
            if e.kind == "auth_expired" and not auth_retried:
                # 强制刷新 token 再试一次
                auth_retried = True
                try:
                    info = _refresh_token()
                    print("[info] auth_expired,已刷新 token,继续重试", file=sys.stderr)
                except Exception as re:
                    print("[warn] 刷新 token 失败: {0}".format(re), file=sys.stderr)
                continue
            if i < max_attempts:
                wait = backoff[min(i - 1, len(backoff) - 1)]
                print("[info] {0}s 后重试(指数退避)...".format(wait), file=sys.stderr)
                time.sleep(wait)
    # P1-5 (2026-07-20 修): 改为 raise, 让调用方决定是否退出
    # 之前库函数调 sys.exit 破坏可重用性, 调用方无法做更高级 fallback
    kind = last_err.kind if last_err else "unknown"
    hint = _HINTS.get(kind, _HINTS["unknown"])
    raise MatrixCallError(
        "matrix 调用全部失败 [{0}]: {1}\n排查建议: {2}".format(
            kind, last_err, hint),
        kind=kind,
    )


def get_hints():
    return dict(_HINTS)


# === 诊断 JSON 解析(从 matrix 响应剥 JSON,跟旧版一致) ===

def _extract_outer_json(text):
    """
    从文本里抽最外层 {...} JSON 块。

    P2-7 (2026-07-20 修): 加注释重构, 变量命名更明确
    原代码用 bytes 比较单字节, 但 text 是 str,
    上面 ch = text[i:i+1] 永远是单字符, 但 ch == b'\\"' 永远不为真
    重写为 str 版本
    """
    start = text.find("{")
    if start < 0:
        return None
    brace_depth = 0
    in_string = False
    escape_next = False
    active_quote = None
    for i in range(start, len(text)):
        ch = text[i]
        # 字符串内: 只跟踪引号/转义, 不计括号深度
        if in_string:
            if escape_next:
                escape_next = False
            elif ch == "\\":
                escape_next = True
            elif ch == active_quote:
                in_string = False
                active_quote = None
            continue
        # 字符串外: 跟踪引号 + 括号嵌套
        if ch in ('"', "'"):
            in_string = True
            active_quote = ch
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0:
                return text[start:i + 1]
    return None

def extract_diagnosis_json(matrix_response):
    """从 matrix 返回里剥出诊断 JSON
    失败抛 MatrixCallError(kind="content_unavailable") 并落 debug log

    接受两种返回形式:
      A) 顶层就是诊断 JSON:{diagnosis:[...], severity:..., ...}
      B) JSON 包裹在 results[0].description 字符串里(可能带 ``` 包裹或外层引号)
    """
    results = matrix_response.get("results")
    if results and isinstance(results, list):
        first = results[0]
        if isinstance(first, dict):
            description = first.get("description")
            if isinstance(description, str):
                stripped = description.strip()
                if stripped.startswith("```"):
                    stripped = re.sub(
                        r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.DOTALL).strip()
                if (stripped.startswith('"') and stripped.endswith('"')) or \
                   (stripped.startswith("'") and stripped.endswith("'")):
                    stripped = stripped[1:-1]
                if stripped.startswith("{"):
                    try:
                        return json.loads(stripped)
                    except json.JSONDecodeError:
                        pass
                json_block = _extract_outer_json(stripped)
                if json_block:
                    try:
                        return json.loads(json_block)
                    except json.JSONDecodeError as e:
                        dump_debug_log(
                            "extract_diagnosis_json", stripped, "",
                            0, "content_unavailable",
                            "description 含文本+JSON 块,但 JSON 块本身不合法: {0}".format(e))
                        raise MatrixCallError(
                            "description 抽出的 JSON 块不合法: {0}".format(e),
                            kind="content_unavailable")
                dump_debug_log(
                    "extract_diagnosis_json", stripped, "",
                    0, "content_unavailable",
                    "description 不是合法 JSON(且找不到 { ... } 块): {0}".format(
                        stripped[:100]))
                raise MatrixCallError(
                    "description 字段不是合法 JSON(且找不到 JSON 块): 开头={0}".format(
                        stripped[:100]),
                    kind="content_unavailable")
            if isinstance(description, dict):
                return description
    if "diagnosis" in matrix_response:
        return matrix_response
    dump_debug_log(
        "extract_diagnosis_json",
        json.dumps(matrix_response, ensure_ascii=False, indent=2), "",
        0, "content_unavailable",
        "matrix 返回里找不到 results[0].description 也没有顶层 diagnosis 字段")
    raise MatrixCallError(
        "无法从 matrix 返回里剥出诊断 JSON。返回结构:{0}".format(
            json.dumps(matrix_response, ensure_ascii=False)[:300]),
        kind="content_unavailable")


# === debug log(跟旧版签名一致) ===

def _safe_filename(label):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(label)).strip()
    return cleaned or "unknown"


def _truncate(text, max_bytes, label):
    if not text:
        return text
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return "{0}\n... [truncated at {1} bytes; total {2} bytes] ...".format(
        truncated, max_bytes, len(encoded))


def _cleanup_old_debug_logs(keep=DEBUG_LOG_KEEP, cwd=None):
    base = Path(cwd) if cwd else Path.cwd()
    try:
        logs = sorted(
            [p for p in base.glob("{0}-*.log".format(DEBUG_LOG_PREFIX))],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in logs[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def dump_debug_log(label, stdout, stderr, returncode, error_kind, error_detail,
                   max_bytes=DEBUG_LOG_TRUNCATE_BYTES, cwd=None):
    """失败时把请求/响应详情落盘。文件名:matrix-debug-<timestamp>-<safe_label>.log"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe_label = _safe_filename(label)
    debug_path = (Path(cwd) if cwd else Path.cwd()) / "{0}-{1}-{2}.log".format(
        DEBUG_LOG_PREFIX, ts, safe_label)
    content = (
        "=== matrix_debug_dump ===\n"
        "label: {0}\n"
        "timestamp: {1}\n"
        "error_kind: {2}\n"
        "error_detail: {3}\n"
        "returncode: {4}\n"
        "\n--- stdout ---\n{5}\n"
        "\n--- stderr ---\n{6}\n"
    ).format(
        label, ts, error_kind, error_detail, returncode,
        _truncate(stdout or "", max_bytes, "stdout"),
        _truncate(stderr or "", max_bytes, "stderr"),
    )
    try:
        debug_path.write_text(content, encoding="utf-8")
        _cleanup_old_debug_logs(cwd=cwd)
        return debug_path
    except Exception as write_err:
        print("[warn] debug log 写盘失败: {0}".format(write_err), file=sys.stderr)
        return None
