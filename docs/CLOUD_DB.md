# 云托管数据库配置 (v2.1.0+)

## 背景

之前 SQLite db 存在 `/tmp/crop_doctor.db`, **容器重启会清空** — 所有用户的
登录态、诊断记录、反馈全丢。

v2.1.0 起, `db.py` 自动检测三种存储位置 (按优先级):

1. **`CROP_DOCTOR_DB` 环境变量** (显式指定, 最优先)
2. **`/data/crop_doctor.db`** (云托管实例存储, 容器重启不丢) ← 推荐
3. **`/tmp/crop_doctor.db`** (fallback, 本地开发或没挂载实例存储)

启动时 `[db] DB 路径: ...` 这行会打 stderr, 确认实际用哪个。

## 部署步骤 (云托管控制台)

### 1. 创建实例存储

```
腾讯云控制台 → 云开发 CloudBase → 云托管
   → 服务管理 → crop-doctor-backend
   → 左侧 "存储管理" → "实例存储"
   → 点 "创建挂载"
   → 挂载路径: /data
   → 容量: 1 GB (够用了, SQLite db 一般 < 10 MB)
   → 确认
```

服务会自动重启, `/data` 就出现在容器里。

### 2. (可选) 显式指定环境变量

如果你想把 db 放别处, 或者想用 `/data` 的子目录:

```
云托管控制台 → 服务详情 → 环境变量
   → 添加:
      键: CROP_DOCTOR_DB
      值: /data/crop_doctor.db
```

**不写这个变量也行**, `db.py` 会自动检测 `/data` 存在就用。

### 3. 部署新版

上传 `crop-doctor-wxcloud-2.1.0.zip` (包含改过的 `db.py`),
等部署完成。

### 4. 验证

部署完后, 在云托管控制台 → 服务详情 → "日志" 或 "实例终端":

```
看 stderr 里这一行:
   [db] DB 路径: /data/crop_doctor.db (原因: /data(实例存储))
```

看到 "实例存储" 就 OK 了。

如果看到 "本地或未挂载实例存储, 重启会清!" — 说明 `/data` 没挂上,
回去看步骤 1。

## 本地开发

本地跑 `python start.py` 时, 不会创建 `/data` 目录, 自动用 `/tmp/crop_doctor.db`。
重启本机不会清, 但每次新 clone 重装环境会清。

如果想在本地用别的路径:

```bash
# Windows PowerShell
$env:CROP_DOCTOR_DB = "D:\test\my_crop.db"
python start.py
```

## 重要: 升级 1.x → 2.1.0

老版本的 db 文件在 `/tmp/crop_doctor.db`, 升级后会重新建一个空 db。
**老数据不会自动迁移**, 但当前 1.x 的 db 里只有几个测试用户和 feedback,
丢了也无所谓 (生产用户还没接入)。

如果以后真要迁, 思路:
1. 在 1.x 上 `sqlite3 /tmp/crop_doctor.db .dump > backup.sql`
2. 升级到 2.1.0 + 挂载实例存储
3. `cat backup.sql | sqlite3 /data/crop_doctor.db`

## 容量建议

- 1 GB 最多放 ~100 万条诊断 (每条 < 1 KB)
- 1 GB 最多放 ~10 万张反馈
- 现阶段 100 MB 都用不完, 1 GB 足够未来 2-3 年

## 风险: 实例存储 vs 真云数据库

| | 实例存储 + SQLite | 云数据库 MySQL |
|---|---|---|
| **多副本** | ❌ 单实例, 扩缩容时新实例拿不到数据 | ✅ 高可用 |
| **数据安全** | 实例销毁会丢 | 自动备份 + 主从 |
| **多实例** | 只能挂 1 个实例 | N 个实例共享 |
| **查询性能** | OK, 1 GB 以内飞快 | 适合大数据量 |

**当前选实例存储** 的原因: 用户量小, 单实例够用, 改造成本最低。
**何时迁 MySQL**: ① 真用户超过 100 个 ② 需要扩缩容 ③ 想要自动备份。

迁 MySQL 那天再说, 现在的代码 (3 张表 + 简单 SQL) 改起来 2-3 小时。
