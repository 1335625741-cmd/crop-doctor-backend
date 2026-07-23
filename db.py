# -*- coding: utf-8 -*-
"""
db.py — 数据访问层 v2.2.0

支持两种后端(自动检测):
  - **MySQL** (生产,云托管): 环境变量 MYSQL_HOST/PORT/USER/PASSWORD/DATABASE 全配 → 用 PyMySQL
  - **SQLite** (本地开发): 上述环境变量没全配 → 走原来的 SQLite(文件在 /tmp 或 CROP_DOCTOR_DB)

3 张表(users / diagnoses / feedbacks)的 schema 自动适配两种后端。

**关键设计**:上层函数接口保持原样,内部用一个轻量 _DB 适配器把 SQLite 的
`?` 占位符 + Row 字典 + lastrowid 全部映射到 MySQL 的对应 API。
这样:
  1. app.py 完全不用改
  2. SQL 几乎不用改(只有 CREATE TABLE 的 PRIMARY KEY AUTOINCREMENT 改成 AUTO_INCREMENT)
  3. 本地开发继续用 SQLite,生产换 MySQL
"""

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path


# ============================================================
# 检测后端类型
# ============================================================
def _env(name, default=""):
    v = os.environ.get(name, "").strip()
    return v if v else default


def _detect_backend():
    """根据环境变量决定用 MySQL 还是 SQLite

    Returns: ("mysql", dict) 或 ("sqlite", str)
    """
    host = _env("MYSQL_HOST")
    user = _env("MYSQL_USER")
    password = _env("MYSQL_PASSWORD")
    database = _env("MYSQL_DATABASE")
    if host and user and database:
        # 密码可以为空(测试用),但实际生产必须有
        return "mysql", {
            "host": host,
            "port": int(_env("MYSQL_PORT", "3306")),
            "user": user,
            "password": password,
            "database": database,
            "charset": "utf8mb4",
            "connect_timeout": 5,
            "read_timeout": 30,
            "write_timeout": 30,
        }
    return "sqlite", _env("CROP_DOCTOR_DB", "/tmp/crop_doctor.db")


BACKEND, BACKEND_CONFIG = _detect_backend()
DB_PATH_REASON = ""  # 启动后填充


def _init_db_path_reason():
    global DB_PATH_REASON
    if BACKEND == "mysql":
        cfg = BACKEND_CONFIG
        DB_PATH_REASON = (
            f"MySQL ({cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']})"
        )
    else:
        DB_PATH_REASON = f"SQLite ({BACKEND_CONFIG}, 本地开发用,容器重启会清!)"


_init_db_path_reason()
# 兼容旧代码里 DB_PATH / DB_PATH_REASON 名字
DB_PATH = BACKEND_CONFIG if BACKEND == "sqlite" else f"{BACKEND_CONFIG['host']}:{BACKEND_CONFIG['port']}/{BACKEND_CONFIG['database']}"
print(f"[db] 后端: {BACKEND.upper()} (原因: {DB_PATH_REASON})", file=sys.stderr)


# ============================================================
# 延迟 import 后端库(避免本地没装 pymysql 就直接挂)
# ============================================================
if BACKEND == "mysql":
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError:
        print("[db] 需要安装 pymysql: pip install pymysql", file=sys.stderr)
        raise
else:
    import sqlite3


# ============================================================
# 占位符转换
# ============================================================
def _adapt_sql(sql):
    """把 SQLite 的 `?` 占位符转成 MySQL 的 `%s`

    - SQLite 用 ?  (或者 :name / ?1 / ?N,但我们代码只用 ?)
    - MySQL 用 %s
    - 字符串里的 ? 不应被替换(我们的 SQL 都没这种情况,但稳妥起见检查一下)
    """
    if BACKEND == "mysql" and "?" in sql:
        # 我们 SQL 里没有带问号的字符串字面量(查询里没有 "?" 这种)
        # 简单字符串替换就够
        return sql.replace("?", "%s")
    return sql


# ============================================================
# 初始化:建表
# ============================================================
def init_db():
    """启动时调一次,建表 + 索引"""
    if BACKEND == "mysql":
        _init_db_mysql()
    else:
        _init_db_sqlite()


def _init_db_sqlite():
    """SQLite 时代的建表逻辑,几乎原样搬过来"""
    p = Path(BACKEND_CONFIG)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        c = conn.cursor()
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            openid        TEXT PRIMARY KEY,
            unionid       TEXT,
            nickname      TEXT,
            avatar_url    TEXT,
            device_model  TEXT,
            wx_version    TEXT,
            login_at      REAL,
            last_active_at REAL,
            login_count   INTEGER DEFAULT 1,
            is_guest      INTEGER DEFAULT 0
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active_at)')

        c.execute('''
        CREATE TABLE IF NOT EXISTS diagnoses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            openid          TEXT,
            ts              REAL,
            crop            TEXT,
            disease_name    TEXT,
            severity        TEXT,
            probability     REAL,
            image_count     INTEGER,
            is_text_only    INTEGER,
            is_kb_hit       INTEGER,
            is_demo         INTEGER,
            source          TEXT
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_diag_openid ON diagnoses(openid)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_diag_ts ON diagnoses(ts)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_diag_disease ON diagnoses(disease_name)')

        c.execute('''
        CREATE TABLE IF NOT EXISTS feedbacks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            openid        TEXT,
            diagnosis_id  INTEGER,
            ts            REAL,
            key           TEXT,
            text          TEXT,
            crop          TEXT,
            disease_name  TEXT,
            severity      TEXT,
            is_fallback   INTEGER,
            FOREIGN KEY(diagnosis_id) REFERENCES diagnoses(id)
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_fb_openid ON feedbacks(openid)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_fb_ts ON feedbacks(ts)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_fb_key ON feedbacks(key)')
        conn.commit()
    print(f"[db] 初始化完成 (SQLite), path: {p}", flush=True)


def _init_db_mysql():
    """MySQL 建表逻辑 — schema 跟 SQLite 保持字段一致,只换类型

    注意:
    - INTEGER PRIMARY KEY AUTOINCREMENT → BIGINT AUTO_INCREMENT PRIMARY KEY
    - REAL → DOUBLE
    - TEXT → VARCHAR(255)/TEXT(根据语义选)
    - IF NOT EXISTS for INDEX 8.0+ 支持
    """
    cfg = BACKEND_CONFIG
    conn = pymysql.connect(**cfg, autocommit=False, cursorclass=DictCursor)
    try:
        c = conn.cursor()
        # users
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            openid        VARCHAR(64) PRIMARY KEY,
            unionid       VARCHAR(64),
            nickname      VARCHAR(128),
            avatar_url    VARCHAR(512),
            device_model  VARCHAR(128),
            wx_version    VARCHAR(32),
            login_at      DOUBLE,
            last_active_at DOUBLE,
            login_count   INT DEFAULT 1,
            is_guest      TINYINT DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        c.execute('CREATE INDEX idx_users_last_active ON users(last_active_at)')

        # diagnoses
        c.execute('''
        CREATE TABLE IF NOT EXISTS diagnoses (
            id              BIGINT AUTO_INCREMENT PRIMARY KEY,
            openid          VARCHAR(64),
            ts              DOUBLE,
            crop            VARCHAR(64),
            disease_name    VARCHAR(128),
            severity        VARCHAR(32),
            probability     DOUBLE,
            image_count     INT,
            is_text_only    TINYINT,
            is_kb_hit       TINYINT,
            is_demo         TINYINT,
            source          VARCHAR(32)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        c.execute('CREATE INDEX idx_diag_openid ON diagnoses(openid)')
        c.execute('CREATE INDEX idx_diag_ts ON diagnoses(ts)')
        c.execute('CREATE INDEX idx_diag_disease ON diagnoses(disease_name)')

        # feedbacks
        c.execute('''
        CREATE TABLE IF NOT EXISTS feedbacks (
            id            BIGINT AUTO_INCREMENT PRIMARY KEY,
            openid        VARCHAR(64),
            diagnosis_id  BIGINT,
            ts            DOUBLE,
            `key`         VARCHAR(8),
            text          TEXT,
            crop          VARCHAR(64),
            disease_name  VARCHAR(128),
            severity      VARCHAR(32),
            is_fallback   TINYINT,
            INDEX idx_fb_diagnosis (diagnosis_id),
            INDEX idx_fb_openid (openid),
            INDEX idx_fb_ts (ts),
            INDEX idx_fb_key (`key`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        conn.commit()
    finally:
        conn.close()
    print(f"[db] 初始化完成 (MySQL), {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}", flush=True)


# ============================================================
# 连接管理
# ============================================================
@contextmanager
def get_conn():
    """获取一个 DB 连接(用完自动 commit/close)

    - SQLite:每请求新连接,timeout=30,WAL 模式
    - MySQL:每请求新连接,autocommit=False,DictCursor
    """
    if BACKEND == "mysql":
        conn = pymysql.connect(**BACKEND_CONFIG, autocommit=False, cursorclass=DictCursor)
        try:
            yield conn
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.commit()
            except Exception:
                pass
            conn.close()
    else:
        conn = sqlite3.connect(BACKEND_CONFIG, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.cursor().execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            conn.cursor().execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        try:
            yield conn
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.commit()
            except Exception:
                pass
            conn.close()


# 兼容老名字(app.py 里 import _db.get_conn 也行)
_get_conn = get_conn


# ============================================================
# Users 表
# ============================================================
def upsert_user(openid, unionid=None, nickname=None, avatar_url=None,
                device_model=None, wx_version=None, is_guest=False):
    if not openid:
        return None, False
    now = time.time()
    with get_conn() as conn:
        c = conn.cursor()
        sql_sel = _adapt_sql('SELECT openid, login_count FROM users WHERE openid=?')
        c.execute(sql_sel, (openid,))
        existing = c.fetchone()
        if existing:
            sql_upd = _adapt_sql('''
                UPDATE users SET
                    unionid=COALESCE(?, unionid),
                    nickname=COALESCE(?, nickname),
                    avatar_url=COALESCE(?, avatar_url),
                    device_model=COALESCE(?, device_model),
                    wx_version=COALESCE(?, wx_version),
                    last_active_at=?,
                    login_count = login_count + 1,
                    is_guest=?
                WHERE openid=?
            ''')
            c.execute(sql_upd, (unionid, nickname, avatar_url, device_model, wx_version,
                                now, 1 if is_guest else 0, openid))
            conn.commit()
            return openid, False
        else:
            sql_ins = _adapt_sql('''
                INSERT INTO users(openid, unionid, nickname, avatar_url, device_model, wx_version,
                                   login_at, last_active_at, login_count, is_guest)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ''')
            c.execute(sql_ins, (openid, unionid, nickname, avatar_url, device_model, wx_version,
                                now, now, 1 if is_guest else 0))
            conn.commit()
            return openid, True


def touch_user(openid):
    if not openid:
        return
    with get_conn() as conn:
        sql = _adapt_sql('UPDATE users SET last_active_at=? WHERE openid=?')
        conn.cursor().execute(sql, (time.time(), openid))
        conn.commit()


def get_user(openid):
    with get_conn() as conn:
        sql = _adapt_sql('SELECT * FROM users WHERE openid=?')
        c = conn.cursor()
        c.execute(sql, (openid,))
        row = c.fetchone()
        return _row_to_dict(row)


def list_users(limit=50, offset=0, time_range=None):
    with get_conn() as conn:
        wheres = []
        params = []
        if time_range:
            cutoff = _time_range_to_cutoff(time_range)
            if cutoff:
                wheres.append('last_active_at >= ?'); params.append(cutoff)
        where_sql = (' WHERE ' + ' AND '.join(wheres)) if wheres else ''
        sql = _adapt_sql(f'SELECT * FROM users{where_sql} ORDER BY last_active_at DESC LIMIT ? OFFSET ?')
        params.extend([limit, offset])
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        return [_row_to_dict(r) for r in rows]


def count_users(time_range=None):
    with get_conn() as conn:
        if time_range:
            cutoff = _time_range_to_cutoff(time_range)
            if cutoff:
                sql = _adapt_sql('SELECT COUNT(*) FROM users WHERE last_active_at >= ?')
                c = conn.cursor()
                c.execute(sql, (cutoff,))
                return c.fetchone()[0]
        sql = _adapt_sql('SELECT COUNT(*) FROM users')
        c = conn.cursor()
        c.execute(sql)
        return c.fetchone()[0]


# ============================================================
# Diagnoses 表
# ============================================================
def insert_diagnosis(openid, crop=None, disease_name=None, severity=None,
                     probability=None, image_count=None, is_text_only=False,
                     is_kb_hit=False, is_demo=False, source='real'):
    with get_conn() as conn:
        c = conn.cursor()
        sql = _adapt_sql('''
            INSERT INTO diagnoses(openid, ts, crop, disease_name, severity, probability,
                                   image_count, is_text_only, is_kb_hit, is_demo, source)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''')
        c.execute(sql, (openid, time.time(), crop, disease_name, severity, probability,
                        image_count, 1 if is_text_only else 0, 1 if is_kb_hit else 0,
                        1 if is_demo else 0, source))
        diag_id = c.lastrowid
        conn.commit()
        if openid:
            touch_user(openid)
        return diag_id


def list_diagnoses(limit=50, offset=0, openid=None, time_range=None):
    with get_conn() as conn:
        wheres = []
        params = []
        if openid:
            wheres.append('openid=?'); params.append(openid)
        if time_range:
            cutoff = _time_range_to_cutoff(time_range)
            if cutoff:
                wheres.append('ts >= ?'); params.append(cutoff)
        where_sql = (' WHERE ' + ' AND '.join(wheres)) if wheres else ''
        sql = _adapt_sql(f'SELECT * FROM diagnoses{where_sql} ORDER BY ts DESC LIMIT ? OFFSET ?')
        params.extend([limit, offset])
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        return [_row_to_dict(r) for r in rows]


def count_diagnoses(openid=None, time_range=None):
    with get_conn() as conn:
        wheres = []
        params = []
        if openid:
            wheres.append('openid=?'); params.append(openid)
        if time_range:
            cutoff = _time_range_to_cutoff(time_range)
            if cutoff:
                wheres.append('ts >= ?'); params.append(cutoff)
        where_sql = (' WHERE ' + ' AND '.join(wheres)) if wheres else ''
        sql = _adapt_sql(f'SELECT COUNT(*) FROM diagnoses{where_sql}')
        c = conn.cursor()
        c.execute(sql, params)
        return c.fetchone()[0]


# ============================================================
# Feedbacks 表
# ============================================================
def insert_feedback(openid=None, diagnosis_id=None, key=None, text=None,
                    crop=None, disease_name=None, severity=None, is_fallback=False):
    with get_conn() as conn:
        c = conn.cursor()
        sql = _adapt_sql('''
            INSERT INTO feedbacks(openid, diagnosis_id, ts, `key`, text, crop, disease_name, severity, is_fallback)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''')
        # 注意:`key` 是 MySQL 关键字,SQLite 不在意;_adapt_sql 不会动这个
        # 同时 `?` 占位符在 SQL 模板里也不变,只 ? 变 %s
        c.execute(sql, (openid, diagnosis_id, time.time(), key, text, crop, disease_name, severity,
                        1 if is_fallback else 0))
        fb_id = c.lastrowid
        conn.commit()
        if openid:
            touch_user(openid)
        return fb_id


def list_feedbacks(limit=50, offset=0, openid=None, key=None, time_range=None):
    with get_conn() as conn:
        wheres = []
        params = []
        if openid:
            wheres.append('openid=?'); params.append(openid)
        if key:
            wheres.append('`key`=?'); params.append(key)
        if time_range:
            cutoff = _time_range_to_cutoff(time_range)
            if cutoff:
                wheres.append('ts >= ?'); params.append(cutoff)
        where_sql = (' WHERE ' + ' AND '.join(wheres)) if wheres else ''
        sql = _adapt_sql(f'SELECT * FROM feedbacks{where_sql} ORDER BY ts DESC LIMIT ? OFFSET ?')
        params.extend([limit, offset])
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        return [_row_to_dict(r) for r in rows]


def count_feedbacks(openid=None, key=None, time_range=None):
    with get_conn() as conn:
        wheres = []
        params = []
        if openid:
            wheres.append('openid=?'); params.append(openid)
        if key:
            wheres.append('`key`=?'); params.append(key)
        if time_range:
            cutoff = _time_range_to_cutoff(time_range)
            if cutoff:
                wheres.append('ts >= ?'); params.append(cutoff)
        where_sql = (' WHERE ' + ' AND '.join(wheres)) if wheres else ''
        sql = _adapt_sql(f'SELECT COUNT(*) FROM feedbacks{where_sql}')
        c = conn.cursor()
        c.execute(sql, params)
        return c.fetchone()[0]


def _time_range_to_cutoff(time_range):
    if not time_range:
        return None
    now = time.time()
    if time_range == '24h':
        return now - 86400
    if time_range == '7d':
        return now - 86400 * 7
    if time_range == '30d':
        return now - 86400 * 30
    return None


# ============================================================
# 统计(给 admin dashboard 用)
# ============================================================
def get_stats(time_range=None):
    cutoff = _time_range_to_cutoff(time_range) if time_range else None
    with get_conn() as conn:
        c = conn.cursor()
        stats = {}

        c.execute(_adapt_sql('SELECT COUNT(*) FROM users'))
        stats['total_users'] = c.fetchone()[0]
        c.execute(
            _adapt_sql('SELECT COUNT(*) FROM users WHERE last_active_at > ?'),
            (time.time() - 86400,)
        )
        stats['today_active'] = c.fetchone()[0]
        c.execute(_adapt_sql('SELECT COUNT(*) FROM users WHERE is_guest=1'))
        stats['guest_users'] = c.fetchone()[0]

        c.execute(_adapt_sql('SELECT COUNT(*) FROM diagnoses'))
        stats['total_diagnoses'] = c.fetchone()[0]
        c.execute(
            _adapt_sql('SELECT COUNT(*) FROM diagnoses WHERE ts > ?'),
            (time.time() - 86400,)
        )
        stats['today_diagnoses'] = c.fetchone()[0]
        c.execute(_adapt_sql('SELECT COUNT(*) FROM diagnoses WHERE is_text_only=0'))
        stats['image_diagnoses'] = c.fetchone()[0]
        c.execute(_adapt_sql('SELECT COUNT(*) FROM diagnoses WHERE is_text_only=1'))
        stats['text_diagnoses'] = c.fetchone()[0]
        c.execute(_adapt_sql('SELECT COUNT(*) FROM diagnoses WHERE is_kb_hit=1'))
        stats['kb_hits'] = c.fetchone()[0]

        # 反馈(支持 time_range)
        if cutoff:
            c.execute(_adapt_sql('SELECT COUNT(*) FROM feedbacks WHERE ts >= ?'), (cutoff,))
            stats['total_feedbacks'] = c.fetchone()[0]
            c.execute(_adapt_sql('''
                SELECT `key`, COUNT(*) as cnt FROM feedbacks
                WHERE `key` IS NOT NULL AND `key` != '' AND ts >= ?
                GROUP BY `key` ORDER BY `key`
            '''), (cutoff,))
            fb_dist_rows = c.fetchall()
        else:
            c.execute(_adapt_sql('SELECT COUNT(*) FROM feedbacks'))
            stats['total_feedbacks'] = c.fetchone()[0]
            c.execute(_adapt_sql('''
                SELECT `key`, COUNT(*) as cnt FROM feedbacks
                WHERE `key` IS NOT NULL AND `key` != ''
                GROUP BY `key` ORDER BY `key`
            '''))
            fb_dist_rows = c.fetchall()
        fb_dist = {}
        for r in fb_dist_rows:
            d = _row_to_dict(r)
            fb_dist[d['key']] = d['cnt']
        stats['feedback_distribution'] = fb_dist

        stats['negative_feedbacks'] = stats['feedback_distribution'].get('D', 0) + stats['feedback_distribution'].get('E', 0)

        # Top 5 常见病
        if cutoff:
            top_diseases = c.execute(_adapt_sql('''
                SELECT disease_name, COUNT(*) as cnt FROM diagnoses
                WHERE disease_name IS NOT NULL AND disease_name != '' AND ts >= ?
                GROUP BY disease_name ORDER BY cnt DESC LIMIT 5
            '''), (cutoff,)).fetchall()
        else:
            top_diseases = c.execute(_adapt_sql('''
                SELECT disease_name, COUNT(*) as cnt FROM diagnoses
                WHERE disease_name IS NOT NULL AND disease_name != ''
                GROUP BY disease_name ORDER BY cnt DESC LIMIT 5
            ''')).fetchall()
        stats['top_diseases'] = [{'name': _row_to_dict(r)['disease_name'],
                                  'count': _row_to_dict(r)['cnt']} for r in top_diseases]

        # Top 5 常见作物
        if cutoff:
            top_crops = c.execute(_adapt_sql('''
                SELECT crop, COUNT(*) as cnt FROM diagnoses
                WHERE crop IS NOT NULL AND crop != '' AND ts >= ?
                GROUP BY crop ORDER BY cnt DESC LIMIT 5
            '''), (cutoff,)).fetchall()
        else:
            top_crops = c.execute(_adapt_sql('''
                SELECT crop, COUNT(*) as cnt FROM diagnoses
                WHERE crop IS NOT NULL AND crop != ''
                GROUP BY crop ORDER BY cnt DESC LIMIT 5
            ''')).fetchall()
        stats['top_crops'] = [{'name': _row_to_dict(r)['crop'],
                               'count': _row_to_dict(r)['cnt']} for r in top_crops]

        return stats


def get_recent_negative_feedbacks(limit=20, time_range='24h'):
    cutoff = _time_range_to_cutoff(time_range) or _time_range_to_cutoff('24h')
    with get_conn() as conn:
        rows = conn.cursor().execute(_adapt_sql('''
            SELECT * FROM feedbacks
            WHERE `key` IN ('D', 'E') AND ts >= ?
            ORDER BY ts DESC LIMIT ?
        '''), (cutoff, limit)).fetchall()
        return [_row_to_dict(r) for r in rows]


# ============================================================
# 工具:行转 dict
# ============================================================
def _row_to_dict(row):
    """SQLite Row / MySQL dict 都转成普通 dict"""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    # 兜底:tuple
    return dict(row)
