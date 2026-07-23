# 云托管数据持久化 — MySQL 方案(v2.2.0+)

## 背景

2026-07-23 排查发现,微信云托管的"对象存储挂载"**实际上没下发到容器**:

- `proc_mounts` 里没有任何 FUSE 挂载
- `storage_env` 是空(没有 STORAGE/BUCKET/COS 相关 env var)
- 容器里的 `/tmp` 和 `/mnt` 都是同一个 overlayfs(19.52 GB),**不是独立磁盘**
- `/data` 根本不存在

**结论:云托管这个实例上,数据持久化做不了**。容器一重启,无论是 `/tmp` 还是 `/mnt` 还是 `/data`,**全丢**。

## 解决方案:接云数据库 MySQL

微信云数据库 MySQL 在**同一个 cloud1 环境**里,跟云托管一个控制台,内网互通。

- 几个月免费试用
- 生产稳定,自动备份 + 高可用
- 容器重启不丢数据

---

## 部署步骤

### 1. 创建 MySQL 实例(5 分钟)

1. 打开 https://console.cloud.tencent.com/tcb
2. 顶部环境:确认是 `cloud1-d5gr59b5iib32f5fb2f1`
3. 左侧菜单 → **MySQL** (或 MySQL 在 "数据库" 组里)
4. 点 **"创建"**:
   - **版本**:**MySQL 8.0**(推荐)
   - **规格**:**最小档**(测试用,后期升级)
   - **存储**:**1-2 GB**
   - **数据库名**:`crop_doctor`
   - **用户名**:`crop_doctor`(或自动生成)
   - **密码**:**自己设一个**,记下来
5. 等 1-2 分钟,状态变"运行中"

### 2. 配置环境变量

进云托管服务 `crop-doctor-backend` → **环境变量** → 加上 5 个:

| 变量名 | 值(示例) | 说明 |
|---|---|---|
| `MYSQL_HOST` | `cdb-xxxx.tencentcloud.com` | **内网地址**(不是外网!) |
| `MYSQL_PORT` | `3306` | 默认 3306 |
| `MYSQL_USER` | `crop_doctor` | 步骤 1 的用户名 |
| `MYSQL_PASSWORD` | `你设的密码` | 步骤 1 的密码 |
| `MYSQL_DATABASE` | `crop_doctor` | 步骤 1 的库名 |

> **5 个必须全配**,否则 db.py 自动 fallback 到 SQLite(走 `/tmp` 临时路径,容器重启数据会清)

### 3. 重新部署

- 上传新的 zip(或 GitHub push)
- 服务详情 → **重新部署** → 等 1-3 分钟

### 4. 验证

```bash
curl -s https://crop-doctor-backend-285364-5-1449852859.sh.run.tcloudbase.com/api/health
```

返回里应该有:

```json
{
  "ok": true,
  "version": "2.2.0",
  "db_backend": "mysql",
  "zhipu_configured": true,
  ...
}
```

`db_backend: "mysql"` 就算成功。

---

## 本地开发模式

不配 5 个 `MYSQL_*` 环境变量(或全空)时,db.py 自动 fallback 到 **SQLite**:

- 默认路径:`/tmp/crop_doctor.db`(容器重启会清)
- 显式指定:配 `CROP_DOCTOR_DB` 环境变量,例如 `CROP_DOCTOR_DB=/path/to/local.db`

---

## 技术细节

### db.py 兼容层设计

- 上层函数接口**完全保持原样**(app.py 0 修改)
- 内部用 `_adapt_sql()` 把 SQLite 的 `?` 占位符替换成 MySQL 的 `%s`
- `sqlite3.Row` / PyMySQL `dict` → 统一用 `_row_to_dict()` 转成普通 dict
- `INTEGER PRIMARY KEY AUTOINCREMENT` → MySQL 改用 `BIGINT AUTO_INCREMENT PRIMARY KEY`
- `TEXT` → MySQL 用 `VARCHAR(N)`(根据语义选长度)
- `REAL` → MySQL 用 `DOUBLE`

### 自动检测逻辑

```python
def _detect_backend():
    host = os.environ.get("MYSQL_HOST", "").strip()
    user = os.environ.get("MYSQL_USER", "").strip()
    database = os.environ.get("MYSQL_DATABASE", "").strip()
    if host and user and database:
        return "mysql", {...}  # PyMySQL 配置
    return "sqlite", "/tmp/crop_doctor.db"  # 本地 fallback
```

### 连接管理

- 每请求新连接(简单可靠,Flask 同步模型下没问题)
- `autocommit=False` + 退出时 `commit()`(保证写入)
- 异常时 `rollback()`(避免脏数据)
- `connect_timeout=5`,`read_timeout=30`,`write_timeout=30`(防止长阻塞)

### 启动日志

容器启动时,stderr 会有这一行:

```
[db] 后端: MYSQL (原因: MySQL (crop_doctor@cdb-xxxx.tencentcloud.com:3306/crop_doctor))
[db] 初始化完成 (MySQL), crop_doctor@cdb-xxxx.tencentcloud.com:3306/crop_doctor
```

或者 fallback 到 SQLite:

```
[db] 后端: SQLITE (原因: SQLite (/tmp/crop_doctor.db, 本地开发用,容器重启会清!))
[db] 初始化完成 (SQLite), path: /tmp/crop_doctor.db
```

---

## 升级 / 降级

- **2.1.0 → 2.2.0**:**不丢数据**!SQLite 时代的 `/tmp/crop_doctor.db` 仍然能用(只是重启丢)
- **降级到 2.1.0**:**数据可能不一致** — SQLite 时代的 `INSERT INTO feedbacks(...key...)` 跟 MySQL 时代的 `INSERT INTO feedbacks(...`key`...)` 略有不同,降级后读 MySQL 数据可能报错。建议清空老数据再降级

---

## 故障排查

### `db_backend: "sqlite"` 但配了 MYSQL_HOST

- 检查 5 个环境变量**都设了**(不是只有 MYSQL_HOST)
- 检查没有空格 / 拼写错误
- 看 stderr 日志:`[db] 后端: SQLITE` 表示检测逻辑走了 fallback

### `OperationalError (2003, ...)` (连不上)

- 检查 `MYSQL_HOST` 是**内网地址**(`cdb-xxxx.tencentcloud.com`),不是外网
- 检查 MySQL 实例的 **VPC** 跟云托管是同一个(默认是,改过的话可能不通)
- 检查 MySQL 状态是"运行中"

### `OperationalError (1045, ...)` (拒绝访问)

- 用户名 / 密码错了,回 MySQL 控制台重置密码

### `OperationalError (1049, ...)` (数据库不存在)

- `MYSQL_DATABASE` 写错了,或者没在 MySQL 控制台建这个库

### `pymysql.err.ProgrammingError` 语法错误

- 看 stderr 报哪个 SQL 出错,可能是 schema 跟代码对不上
- 解决:在 MySQL 控制台 `DROP DATABASE crop_doctor;` → 重新建库 → 重新部署,代码会跑 `init_db` 自动建表

---

## 何时切回对象存储

**短期不推荐**。对象存储走 FUSE 挂载到容器,性能差,而且这次实测根本没生效。

**长期**:如果你想用 SQLite(简单)而不是 MySQL(强大),等云托管出真正的"实例存储"功能(目前没有)再切。

## 何时切云数据库 MySQL

**就是现在,已经切了** ☑️
