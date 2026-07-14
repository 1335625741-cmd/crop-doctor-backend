# 征途问诊后端

微信小程序「征途问诊」的后端服务。基于 Flask,提供:

- `GET /api/health` - 健康检查
- `POST /api/identify` - 作物识别(走 crop-identifier skill)
- `POST /api/diagnose` - 病害诊断(走 crop-disease-diagnosis skill,自动 chain identify)
- `POST /api/feedback` - 反馈统计
- `POST /api/wechat-login` - 微信快捷登录(jscode2session + encryptedData 解密)

## 🚀 5 分钟部署到 Render(推荐,零成本,稳定)

### 1. 创建 GitHub 仓库

注册 https://github.com(已有跳过),创建新仓库:
- **Repository name**: `crop-doctor-backend`
- **Public** ✓
- **不要**勾 "Add a README file" / "Add .gitignore"(本仓库已有)
- 点 **Create repository**

### 2. 推送代码到 GitHub

复制仓库 URL(形如 `https://github.com/<你的用户名>/crop-doctor-backend.git`),然后:

```bash
cd crop-doctor-backend
git init
git add .
git commit -m "feat: 征途问诊后端 Render 部署"
git branch -M main
git remote add origin https://github.com/<你的用户名>/crop-doctor-backend.git
git push -u origin main
```

> **第一次 push 要 GitHub Personal Access Token** 作密码:
> https://github.com/settings/tokens → Generate new token (classic) → 勾 `repo` → 复制 token 作密码

### 3. Render 部署

注册 https://render.com(用 GitHub 登录免审核),然后:

1. **Dashboard** → **New** → **Blueprint**
2. **Connect a repository**: 选刚创建的 `crop-doctor-backend`
3. Render 自动读 `render.yaml` → 识别 `crop-doctor-backend` 这个 web service
4. 点 **Apply** → Render 开始 build Docker 镜像(2-3 分钟)
5. 部署完成后到 **Environment** 标签加环境变量:
   - `WECHAT_SECRET` = `d49e4c9fda26852e783b43399835bd0b`(勾 **Secret**)
6. Render 自动重启

**Render URL 形如**:`https://crop-doctor-backend.onrender.com`

### 4. 验证

```
https://crop-doctor-backend.onrender.com/api/health
```

应返回:
```json
{"mode": "demo", "ok": true, ...}
```

### 5. 配小程序

打开小程序 `app.js`,改 `baseUrl`:

```js
baseUrl: 'https://crop-doctor-backend.onrender.com'  // 你的 Render URL
```

### 6. 配微信公众平台

https://mp.weixin.qq.com → 开发管理 → 开发设置 → 服务器域名:
- **request 合法域名**:`https://crop-doctor-backend.onrender.com`

(微信要求 HTTPS + 已备案,Render 默认就是 HTTPS)

---

## 🔧 本地 Docker 测试

```bash
cd crop-doctor-backend
docker build -t crop-doctor-backend .
docker run -p 7860:7860 \
  -e CROP_DOCTOR_TOKEN=dev-local-token-123 \
  -e WECHAT_APPID=wx55ada0c10001558a \
  -e WECHAT_SECRET=d49e4c9fda26852e783b43399835bd0b \
  crop-doctor-backend
```

访问 http://localhost:7860/api/health

## 🔧 本地 Python 测试(免 Docker)

```bash
cd crop-doctor-backend
pip install -r requirements.txt
set CROP_DOCTOR_TOKEN=dev-local-token-123
set WECHAT_APPID=wx55ada0c10001558a
set WECHAT_SECRET=d49e4c9fda26852e783b43399835bd0b
python start.py
```

---

## 📡 API 详细

### `GET /api/health`
健康检查。返回:
```json
{
  "ok": true,
  "mode": "demo" | "real",
  "wechat": "real" | "demo",
  "wechat_appid_set": true,
  "wechat_secret_set": true
}
```

### `POST /api/identify`
作物识别。需要 `Authorization: Bearer <CROP_DOCTOR_TOKEN>`。
- Form: `image`(可多次) / `parts` / `location` / `season`
- 返回:`{crop, confidence, alternatives, ...}`

### `POST /api/diagnose`
病害诊断。需要鉴权。
- Form: `image` / `crop`(可选) / `context`
- Query: `?real=1` 走真 AI(默认 demo,返回 5 份预置之一)
- 返回:完整 `full-diagnosis.json` 结构

### `POST /api/feedback`
反馈统计。需要鉴权。
- JSON: `{sessionId, diagnosisName, rating, comment}`
- 返回:`{ok: true, total: N}`

### `POST /api/wechat-login`
微信快捷登录。需要鉴权。
- JSON: `{code, encryptedData?, iv?, userInfoRaw?}`
- 流程:jscode2session → 拿 session_key → 解密 encryptedData → 返回 userInfo
- 兜底:无 AppID/Secret 走 demo openid

---

## 🔒 安全提醒

- ⚠️ **WECHAT_SECRET 绝对不能 commit 到 GitHub**!
- 仓库 `.gitignore` 已加 `start.py` / `start-local.bat` / `start-local.sh`(这些文件可能含真 secret)
- **Render 部署时 WECHAT_SECRET 用环境变量配**,不写 yaml

## 项目结构

```
crop-doctor-backend/
├── Dockerfile          # Docker 镜像(支持 Render / HF Spaces / 本地)
├── requirements.txt    # Python 依赖
├── render.yaml         # Render Blueprint 配置
├── app.py              # Flask 主应用
├── start.py            # 本地开发启动(不部署)
├── embedded_mocks.py   # 5 份预置诊断数据
└── README.md           # 本文档
```
