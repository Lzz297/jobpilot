"""
v4: Strategy 账号级隔离 — 添加 owner_id / display_name / description / is_default

将全局共享的 strategies 表改为账号级：
  - 添加 owner_id (FK users) — 归属账号
  - 添加 display_name — 人类可读名称
  - 添加 description — 策略说明
  - 添加 is_default — 是否系统默认（新用户自动复制）

现有 5 条策略归给管理员，标记 is_default=1。
"""
import sqlite3, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_agent.db')
conn = sqlite3.connect(DB)
c = conn.cursor()

# 获取现有列
cols = {r[1] for r in c.execute("PRAGMA table_info(strategies)").fetchall()}

# 幂等添加列
migrations = [
    ("owner_id",    "INTEGER REFERENCES users(id)"),
    ("display_name","TEXT NOT NULL DEFAULT ''"),
    ("description", "TEXT NOT NULL DEFAULT ''"),
    ("is_default",  "INTEGER NOT NULL DEFAULT 0"),
]

for col_name, col_def in migrations:
    if col_name not in cols:
        c.execute(f"ALTER TABLE strategies ADD COLUMN {col_name} {col_def}")
        print(f"  [OK] 添加列: {col_name}")
    else:
        print(f"  - 列已存在，跳过: {col_name}")

# 现有策略归给管理员 + 标记为默认
admin = c.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
if admin:
    admin_id = admin[0]
    c.execute("UPDATE strategies SET owner_id = ? WHERE owner_id IS NULL", (admin_id,))
    c.execute("UPDATE strategies SET is_default = 1 WHERE is_default = 0")
    print(f"\n  [OK] 现有策略已归给管理员 (user_id={admin_id})，标记 is_default=1")
else:
    print("\n  [WARN] 未找到管理员用户，跳过 owner_id 赋值")

# 重建 strategies 表：将 UNIQUE(name) 改为 UNIQUE(name, owner_id)
# SQLite 无法直接修改约束，需要重建表
create_sql = c.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='strategies'"
).fetchone()[0]
needs_rebuild = 'UNIQUE(name)' in create_sql or 'name TEXT UNIQUE' in create_sql

if needs_rebuild:
    # 先清理可能残留的临时表（上次运行中断）
    c.execute("DROP TABLE IF EXISTS strategies_new")
    c.execute("""
        CREATE TABLE strategies_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            data TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            display_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, owner_id)
        )
    """)
    # 迁移数据（跳过 name+owner_id 重复的行）
    c.execute("""
        INSERT INTO strategies_new (id, name, data, owner_id, display_name, description, is_default, created_at, updated_at)
        SELECT id, name, data, owner_id, display_name, description, is_default, created_at, updated_at
        FROM strategies
        WHERE id NOT IN (
            SELECT s1.id FROM strategies s1 JOIN strategies s2
            ON s1.name = s2.name AND s1.owner_id = s2.owner_id AND s1.id > s2.id
        )
    """)
    c.execute("DROP TABLE strategies")
    c.execute("ALTER TABLE strategies_new RENAME TO strategies")
    print("  [OK] UNIQUE 约束已改为 (name, owner_id)")
else:
    print("  - UNIQUE(name, owner_id) 已存在，跳过")

conn.commit()
conn.close()

print(f"\n[OK] v4 迁移完成")
print(f"  DB: {DB}")
print(f"  大小: {os.path.getsize(DB):,} bytes")
