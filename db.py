# -*- coding: utf-8 -*-
"""
db.py — SQLite 数据访问层

3 张表:
  - users: 微信用户信息 + 最后活跃时间
  - diagnoses: 诊断历史(每个用户每次诊断一条)
  - feedbacks: 用户反馈(每条反馈一条,关联到诊断)

存储路径:优先用 DATA_DIR 环境变量,默认 /tmp/crop_doctor.db
  - Render free tier: /tmp 在重启后会清,所以文档要说明"测试数据,生产请用真 DB"
  - 未来可加 Render Persistent Disk 或外部 Postgres

数据加密:openid 是微信给的唯一标识,不算敏感;但 unionid/avatar/nickname 在反馈分析时可能用到
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("CROP_DOCTOR_DB", "/tmp/crop_doctor.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 初始化
# ============================================================
def init_db():
    """启动时调一次,建表 + 索引"""
    with get_conn() as conn:
        c = conn.cursor()

        # 用户表
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

        # 诊断历史表(openid 不强制 FK,未登录用户也能记诊断)
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

        # 反馈表(openid 不直接 FK 到 users,通过 diagnosis_id 间接关联;这样没登录也能反馈)
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
        print(f"[db] 初始化完成, DB 路径: {DB_PATH}", flush=True)


# ============================================================
# 连接管理
# ============================================================
@contextmanager
def get_conn():
    """线程安全的 SQLite 连接(每个请求新连接,简单可靠)"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 提升并发性能
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        # 保险:任何遗漏的 commit 都在 close 前自动 commit(防止数据丢失)
        try:
            conn.commit()
        except Exception:
            pass
        conn.close()


# ============================================================
# Users 表操作
# ============================================================
def upsert_user(openid, unionid=None, nickname=None, avatar_url=None,
                device_model=None, wx_version=None, is_guest=False):
    """登录/活跃时调,upsert(已存在更新字段,不存在插入)

    Returns: (openid, created: bool)
    """
    if not openid:
        return None, False
    now = time.time()
    with get_conn() as conn:
        c = conn.cursor()
        existing = c.execute('SELECT openid, login_count FROM users WHERE openid=?', (openid,)).fetchone()
        if existing:
            c.execute('''
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
            ''', (unionid, nickname, avatar_url, device_model, wx_version,
                  now, 1 if is_guest else 0, openid))
            conn.commit()  # ★ 缺这行!
            return openid, False
        else:
            c.execute('''
                INSERT INTO users(openid, unionid, nickname, avatar_url, device_model, wx_version,
                                   login_at, last_active_at, login_count, is_guest)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ''', (openid, unionid, nickname, avatar_url, device_model, wx_version,
                  now, now, 1 if is_guest else 0))
            conn.commit()  # ★ 缺这行!否则连接关闭后改动丢失
            return openid, True


def touch_user(openid):
    """用户活跃时调(诊断/反馈时),只更新 last_active_at"""
    if not openid:
        return
    with get_conn() as conn:
        conn.execute('UPDATE users SET last_active_at=? WHERE openid=?', (time.time(), openid))
        conn.commit()


def get_user(openid):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE openid=?', (openid,)).fetchone()
        return dict(row) if row else None


def list_users(limit=50, offset=0):
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM users ORDER BY last_active_at DESC LIMIT ? OFFSET ?',
                            (limit, offset)).fetchall()
        return [dict(r) for r in rows]


def count_users():
    with get_conn() as conn:
        return conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]


# ============================================================
# Diagnoses 表操作
# ============================================================
def insert_diagnosis(openid, crop=None, disease_name=None, severity=None,
                     probability=None, image_count=None, is_text_only=False,
                     is_kb_hit=False, is_demo=False, source='real'):
    """插一条诊断历史,返回 id"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO diagnoses(openid, ts, crop, disease_name, severity, probability,
                                   image_count, is_text_only, is_kb_hit, is_demo, source)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (openid, time.time(), crop, disease_name, severity, probability,
              image_count, 1 if is_text_only else 0, 1 if is_kb_hit else 0,
              1 if is_demo else 0, source))
        diag_id = c.lastrowid
        conn.commit()
        # 顺便刷新用户活跃
        if openid:
            touch_user(openid)
        return diag_id


def list_diagnoses(limit=50, offset=0, openid=None):
    with get_conn() as conn:
        if openid:
            rows = conn.execute('SELECT * FROM diagnoses WHERE openid=? ORDER BY ts DESC LIMIT ? OFFSET ?',
                                (openid, limit, offset)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM diagnoses ORDER BY ts DESC LIMIT ? OFFSET ?',
                                (limit, offset)).fetchall()
        return [dict(r) for r in rows]


def count_diagnoses(openid=None):
    with get_conn() as conn:
        if openid:
            return conn.execute('SELECT COUNT(*) FROM diagnoses WHERE openid=?', (openid,)).fetchone()[0]
        return conn.execute('SELECT COUNT(*) FROM diagnoses').fetchone()[0]


# ============================================================
# Feedbacks 表操作
# ============================================================
def insert_feedback(openid=None, diagnosis_id=None, key=None, text=None,
                    crop=None, disease_name=None, severity=None, is_fallback=False):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO feedbacks(openid, diagnosis_id, ts, key, text, crop, disease_name, severity, is_fallback)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (openid, diagnosis_id, time.time(), key, text, crop, disease_name, severity,
              1 if is_fallback else 0))
        fb_id = c.lastrowid
        conn.commit()
        if openid:
            touch_user(openid)
        return fb_id


def list_feedbacks(limit=50, offset=0, openid=None):
    with get_conn() as conn:
        if openid:
            rows = conn.execute('SELECT * FROM feedbacks WHERE openid=? ORDER BY ts DESC LIMIT ? OFFSET ?',
                                (openid, limit, offset)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM feedbacks ORDER BY ts DESC LIMIT ? OFFSET ?',
                                (limit, offset)).fetchall()
        return [dict(r) for r in rows]


def count_feedbacks(openid=None, key=None):
    with get_conn() as conn:
        sql = 'SELECT COUNT(*) FROM feedbacks'
        params = []
        if openid:
            sql += ' WHERE openid=?'; params.append(openid)
        if key:
            sql += (' AND' if openid else ' WHERE') + ' key=?'; params.append(key)
        return conn.execute(sql, params).fetchone()[0]


# ============================================================
# 统计(给 admin dashboard 用)
# ============================================================
def get_stats():
    """总览统计"""
    with get_conn() as conn:
        c = conn.cursor()
        stats = {}

        # 用户
        stats['total_users'] = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        stats['today_active'] = c.execute(
            'SELECT COUNT(*) FROM users WHERE last_active_at > ?',
            (time.time() - 86400,)
        ).fetchone()[0]
        stats['guest_users'] = c.execute('SELECT COUNT(*) FROM users WHERE is_guest=1').fetchone()[0]

        # 诊断
        stats['total_diagnoses'] = c.execute('SELECT COUNT(*) FROM diagnoses').fetchone()[0]
        stats['today_diagnoses'] = c.execute(
            'SELECT COUNT(*) FROM diagnoses WHERE ts > ?',
            (time.time() - 86400,)
        ).fetchone()[0]
        stats['image_diagnoses'] = c.execute('SELECT COUNT(*) FROM diagnoses WHERE is_text_only=0').fetchone()[0]
        stats['text_diagnoses'] = c.execute('SELECT COUNT(*) FROM diagnoses WHERE is_text_only=1').fetchone()[0]
        stats['kb_hits'] = c.execute('SELECT COUNT(*) FROM diagnoses WHERE is_kb_hit=1').fetchone()[0]

        # 反馈
        stats['total_feedbacks'] = c.execute('SELECT COUNT(*) FROM feedbacks').fetchone()[0]
        # 反馈分布(A/B/C/D/E)
        fb_dist = c.execute('''
            SELECT key, COUNT(*) as cnt FROM feedbacks
            WHERE key IS NOT NULL AND key != ''
            GROUP BY key ORDER BY key
        ''').fetchall()
        stats['feedback_distribution'] = {r['key']: r['cnt'] for r in fb_dist}

        # Top 5 常见病
        top_diseases = c.execute('''
            SELECT disease_name, COUNT(*) as cnt FROM diagnoses
            WHERE disease_name IS NOT NULL AND disease_name != ''
            GROUP BY disease_name ORDER BY cnt DESC LIMIT 5
        ''').fetchall()
        stats['top_diseases'] = [{'name': r['disease_name'], 'count': r['cnt']} for r in top_diseases]

        # Top 5 常见作物
        top_crops = c.execute('''
            SELECT crop, COUNT(*) as cnt FROM diagnoses
            WHERE crop IS NOT NULL AND crop != ''
            GROUP BY crop ORDER BY cnt DESC LIMIT 5
        ''').fetchall()
        stats['top_crops'] = [{'name': r['crop'], 'count': r['cnt']} for r in top_crops]

        return stats
