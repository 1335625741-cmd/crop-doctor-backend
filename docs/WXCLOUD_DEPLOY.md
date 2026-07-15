# 微信云托管 部署指南

> 征途问诊后端迁移到微信云托管(替代 Render)的完整步骤

## 微信云托管是什么

- 官方 PaaS,微信小程序后端首选
- 自动 HTTPS,免备案(部分免)
- 小程序调用时**自动注入 `X-WX-OPENID`**,免后端鉴权
- 免配域名白名单(微信小程序直接调)
- 计费:新用户有试用金,生产按量

## 第一步:注册 / 登录

1. 打开 [微信云托管控制台](https://cloud.weixin.qq.com/cloudrun)
2. 用**小程序管理员**微信扫码登录
3. 同意服务协议

## 第二步:创建服务

1. 点 **"服务管理"** → **"创建服务"**
2. 选 **"代码上传 / 仓库导入"**
3. 选 **"Dockerfile 部署"**
4. 服务名:`crop-doctor-backend`(可改)
5. 仓库:选 **"GitHub"**(需要授权)→ 选 `crop-doctor-backend` repo
6. 端口:**80**
7. 实例规格:**基础版**(0.5C 1G,试用期内免费)
8. 副本数:**1**(试用期内只能 1 个)
9. 点 **"创建"**

## 第三步:配置环境变量

服务创建后,到 **"服务详情"** → **"环境变量"**:

### 必填(从 env 切换到 secret,标记为敏感)

| Key | Value | 备注 |
|---|---|---|
| `ZHIPU_API_KEY` | `eb59e98...` | 智谱 GLM-4V 的 API key |
| `WECHAT_SECRET` | `d49e4c...` | 小程序 AppSecret(配在 Secret 区) |
| `CROP_DOCTOR_TOKEN` | `2249a1...` | 后端 token(给非微信小程序调用方用) |

### 普通变量

| Key | Value | 备注 |
|---|---|---|
| `ZHIPU_MODEL` | `glm-4v-plus` | 模型名 |
| `PUBLIC_BASE_URL` | **部署后填**(见下) | 给图片拼完整 URL |
| `PORT` | `80` | 端口(Dockerfile 默认是 80) |

> ⚠️ `PUBLIC_BASE_URL` **先留空**,等部署完成后,微信云托管会给一个类似 `https://crop-doctor-backend-xxx.run.app` 的域名,把那个填进来,**再触发一次重新部署**。

## 第四步:配置小程序授权(关键!)

让 微信云托管 自动给后端注入 `X-WX-OPENID`,需要在小程序后台授权:

1. 微信云托管控制台 → 服务详情 → **"服务设置"** → **"微信小程序授权"**
2. 点 **"添加授权"** → 选你那个小程序(注意 appid 要对应)
3. 授权成功后,云托管调这个后端时,请求头会自动带 `X-WX-OPENID` 和 `X-WX-APPID`

> **不授权会怎样?**
> 后端会落到 `X-Auth-Token` 校验,小程序调的时候因为没传 token 会被 401。所以这一步**必须**做。

## 第五步:首次部署

1. 服务列表 → 选 `crop-doctor-backend` → **"版本列表"** → **"新版本"**
2. 来源:**GitHub 仓库** → 分支 `main`
3. Dockerfile 路径:`./Dockerfile`(默认)
4. 触发方式:**手动** 或 **git push 自动**
5. 点 **"开始部署"**
6. 等待 3-5 分钟(构建 + 启动)
7. 看日志,出现 `Your service is live 🎉` 或 `* Running on http://0.0.0.0:80` 就 OK

## 第六步:拿域名 + 配 PUBLIC_BASE_URL

1. 服务详情 → **"基础信息"** → **"服务域名"**
2. 复制默认域名,长这样:
   ```
   https://crop-doctor-backend-1234567890.run.app
   ```
3. 验证一下(浏览器直接访问):
   ```
   https://crop-doctor-backend-xxx.run.app/api/health
   ```
   返回 `{"ok": true, "version": "1.4.1", ...}` 就 OK
4. 回到 **"环境变量"**,把 `PUBLIC_BASE_URL` 填成上面的域名(带 https://)
5. 重新部署一次(让新 env 生效)

## 第七步:前端指向新域名

改 `crop-doctor-miniapp/app.js`:
```js
globalData: {
  baseUrl: 'https://crop-doctor-backend-xxx.run.app',  // ← 改成云托管域名
  ...
}
```

## 第八步:验证完整链路

打开微信开发者工具 → 编译运行,试一下:

1. 微信登录 → 拿到 openid(云托管自动注入)
2. 发"番茄叶子有黑圈"或上传图片 → 看到诊断结果
3. 点 A/B/C/D/E 反馈 → 反馈落库
4. 管理员后台:`https://crop-doctor-backend-xxx.run.app/admin?admin_token=2249a1...`
   - 能看到用户/诊断/反馈
   - 顶部红色负面 banner(如果 D/E 反馈)
5. 协议页:`https://crop-doctor-backend-xxx.run.app/legal/agreement.html`

## 第九步:数据迁移(可选)

如果之前在 Render 有数据:
- 微信云托管 是容器,SQLite 数据**容器重启会丢**
- 两种方案:
  - A. **简单**:接受丢数据(测试阶段 OK)
  - B. **正式**:接 微信云托管 MySQL 或自建 Postgres

## 第十步:关闭 Render(确认稳定后)

如果云托管跑 1-2 周没问题,可以去 Render 把服务删了(避免双跑扣费)。

## 常见问题

### Q1:部署后 `/api/health` 返回 502/503?
- 检查 Docker 构建日志,可能是依赖装不上(网络问题)
- 检查 80 端口是否被占用(应该不会,云托管自动放行)

### Q2:小程序调用报 401 Unauthorized?
- 没配"微信小程序授权"(第四步)
- 或者 baseUrl 写错

### Q3:图片上传失败?
- 检查 `PUBLIC_BASE_URL` 是否配了
- 检查 `/uploads/` 路径在云托管里能不能访问(浏览器试)

### Q4:数据怎么备份?
- 微信云托管容器**不持久**
- 装一个 cron job 每天 `sqlite3 /tmp/crop_doctor.db .dump > backup.sql`
- 或者直接用 MySQL(更稳)

### Q5:智谱 API 调不通?
- 检查 `ZHIPU_API_KEY` 是否配对
- 看云托管日志(在服务详情 → "日志")

## 费用预估

| 项目 | 试用期内 | 正式(基础版) |
|---|---|---|
| 计算资源 | 免费 | 0.05 元/小时 × 24 × 30 = **36 元/月** |
| 出网流量 | 免费 5GB | 超出 0.8 元/GB |
| MySQL(可选) | 免费试用 | 30 元/月起 |
| **总计** | **0 元** | **~50 元/月** |

比 Render 贵点,但:
- 免备案 ✓
- 国内速度 ✓
- 微信生态原生支持 ✓
- 数据可控 ✓

## 紧急回滚

如果出问题想回 Render:
1. 改 `app.js` 的 `baseUrl` 改回 `https://crop-doctor-backend-5ejy.onrender.com`
2. Render 服务还在(数据没清)
3. 提一个 hotfix 即可

`app.js` 改 baseUrl 不用重新走审核,只是数据走另一条路。
