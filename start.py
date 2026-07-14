#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start.py — 征途问诊后端一键启动脚本(纯 Python,不会被 SmartScreen 拦)

用法:
  1. 命令行:python start.py
  2. 双击(需先关联 .py → python.exe)
  3. 微信开发者工具:右键 → 在终端中打开 → python start.py

它会:
  1. 配 CROP_DOCTOR_TOKEN 环境变量
  2. 检查 Python 依赖(自动 pip install)
  3. 启动 Flask app
  4. Ctrl+C 退出
"""
import os
import sys
import subprocess
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# 1. 配 token(必须和前端 app.js 的 authToken 一致)
TOKEN = os.environ.get("CROP_DOCTOR_TOKEN") or "dev-local-token-123"
# 端口优先级:PORT 环境变量(本地/Docker/HF 都用) → 默认 8765
#   - 本地直接跑:PORT 空,默认 8765
#   - Docker / HF:Dockerfile 里 ENV PORT=7860
PORT = os.environ.get("PORT") or "8765"

# ★ 微信小程序凭证(填了就启用真 jscode2session 模式,空就用 demo openid)
#    在微信公众平台 → 开发 → 开发管理 → 开发设置 → 小程序 AppID / AppSecret
#    ⚠️ 真实值不要 commit 到公开仓库!留空,走环境变量(本机 / Render 控制台配)
WECHAT_APPID = os.environ.get("WECHAT_APPID", "").strip()  # 默认空:本地 demo 模式
WECHAT_SECRET = os.environ.get("WECHAT_SECRET", "").strip()  # 默认空:本地 demo 模式

os.environ["CROP_DOCTOR_TOKEN"] = TOKEN
os.environ["PORT"] = PORT
os.environ["WECHAT_APPID"] = WECHAT_APPID
os.environ["WECHAT_SECRET"] = WECHAT_SECRET

BANNER = r"""
============================================================
  征途问诊后端启动中...
============================================================
  监听地址:  http://127.0.0.1:%(port)s
  鉴权 token: %(token)s
  微信登录:   %(wx)s
  停止:      Ctrl + C
============================================================
""" % {
    "port": PORT,
    "token": TOKEN,
    "wx": "真 jscode2session" if (WECHAT_APPID and WECHAT_SECRET) else "demo 模式(AppID/Secret 未配)",
}


def check_python():
    """检查 python 版本"""
    if sys.version_info < (3, 8):
        print("[ERROR] 需要 Python 3.8+,你的是 Python %d.%d" % sys.version_info[:2])
        sys.exit(1)


def check_deps():
    """检查并装依赖"""
    try:
        import flask  # noqa
        import flask_cors  # noqa
        return
    except ImportError:
        pass

    print("[INFO] 正在安装依赖 flask flask-cors ...")
    req_file = SCRIPT_DIR / "requirements.txt"
    if not req_file.exists():
        print("[ERROR] 找不到 requirements.txt")
        sys.exit(1)
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
        cwd=str(SCRIPT_DIR),
    )
    if r.returncode != 0:
        print("[ERROR] 依赖安装失败,试试手动: pip install -r requirements.txt")
        sys.exit(1)


def main():
    check_python()
    print(BANNER)
    check_deps()

    # 2. 启动
    app_file = SCRIPT_DIR / "app.py"
    if not app_file.exists():
        print("[ERROR] 找不到 app.py")
        sys.exit(1)

    # 把 server 目录加到 sys.path(让 app.py 能 import 同目录的模块)
    sys.path.insert(0, str(SCRIPT_DIR))

    # 先 import app 检查 demo 模式
    print("[INFO] 检查后端模式 ...")
    from app import _matrix_available  # noqa
    if _matrix_available():
        print("[INFO] ✓ 真实 AI 链路可用(/api/diagnose?real=1 走真 AI)")
        print("[INFO] 默认仍走 demo 模式(返回 5 份预置之一)")
    else:
        print("[INFO] ✗ 真实 AI 链路不可用(本地 demo 模式)")
        print("[INFO]   缺 mavis daemon 或 matrix 配置,但不影响 demo 跑通")
    print()

    print("[INFO] 启动 Flask app ...")
    print()
    try:
        # 直接 import 跑(避免子进程慢)
        from app import app
        app.run(host="0.0.0.0", port=int(PORT), debug=False)
    except KeyboardInterrupt:
        print()
        print("[INFO] 已停止")
    except Exception as e:
        print(f"[ERROR] 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
