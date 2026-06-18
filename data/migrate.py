"""Migration script: YAML → SQLite"""
import sqlite3, os, json, yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'data', 'job_agent.db')
os.makedirs(os.path.join(BASE, 'data'), exist_ok=True)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ===== Step 1: Create tables =====
c.executescript("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS search_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    data TEXT NOT NULL,
    owner_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS field_schemas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    data TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    detail TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
""")
print('Step 1: Tables created')
print(f'Tables: {[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]}')

# ===== Step 2: Migrate =====

# 2.1 Create admin user
with open(os.path.join(BASE, 'profiles', '.current_user'), 'r') as f:
    current_user_name = f.read().strip()
print(f'\nStep 2.1: Current user = {current_user_name}')

c.execute("INSERT INTO users (username, role) VALUES (?, ?)", (current_user_name, 'admin'))
admin_id = c.lastrowid
print(f'  Created admin user id={admin_id}')

# 2.2 Import user profiles
print('\nStep 2.2: User profiles')
users_dir = os.path.join(BASE, 'instances', 'users')
profiles_count = 0
for fname in sorted(os.listdir(users_dir)):
    if not fname.endswith('.yaml'): continue
    name = fname.replace('.yaml', '')
    with open(os.path.join(users_dir, fname), 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    data_json = json.dumps(data, ensure_ascii=False)
    is_cur = 1 if name == current_user_name else 0
    c.execute("INSERT INTO user_profiles (user_id, name, data, is_current) VALUES (?,?,?,?)",
              (admin_id, name, data_json, is_cur))
    profiles_count += 1
    print(f'  {name} (is_current={is_cur})')
print(f'  Total: {profiles_count}')

# 2.3 search_config
print('\nStep 2.3: search_config')
with open(os.path.join(BASE, 'profiles', 'search_config.yaml'), 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
cfg_json = json.dumps(cfg, ensure_ascii=False)
c.execute("INSERT INTO search_config (data, updated_by) VALUES (?,?)", (cfg_json, admin_id))
print('  1 row imported')

# 2.4 strategies
print('\nStep 2.4: Strategies')
strat_dir = os.path.join(BASE, 'instances', 'strategies')
strat_count = 0
for fname in sorted(os.listdir(strat_dir)):
    if not fname.endswith('.yaml'): continue
    name = fname.replace('.yaml', '')
    with open(os.path.join(strat_dir, fname), 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    c.execute("INSERT INTO strategies (name, data) VALUES (?,?)", (name, json.dumps(data, ensure_ascii=False)))
    strat_count += 1
    print(f'  {name}')
print(f'  Total: {strat_count}')

# 2.5 campaigns
print('\nStep 2.5: Campaigns')
camp_dir = os.path.join(BASE, 'instances', 'campaigns')
camp_count = 0
for fname in sorted(os.listdir(camp_dir)):
    if not fname.endswith('.yaml'): continue
    name = fname.replace('.yaml', '')
    with open(os.path.join(camp_dir, fname), 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    c.execute("INSERT INTO campaigns (name, data, owner_id) VALUES (?,?,NULL)", (name, json.dumps(data, ensure_ascii=False)))
    camp_count += 1
    print(f'  {name}')
print(f'  Total: {camp_count}')

# 2.6 field_schema
print('\nStep 2.6: Field schema')
schema_path = os.path.join(BASE, 'profiles', 'user_field_schema.yaml')
with open(schema_path, 'r', encoding='utf-8') as f:
    schema = yaml.safe_load(f)
c.execute("INSERT INTO field_schemas (name, data, updated_by) VALUES (?,?,?)",
          ('user_field', json.dumps(schema, ensure_ascii=False), admin_id))
print('  user_field imported')

# 2.7 Log
c.execute("INSERT INTO operation_logs (user_id, action, target_type, detail) VALUES (?,?,?,?)",
          (admin_id, 'db_init', 'system', 'Initial migration from all YAML files'))
conn.commit()

# ===== Step 3: Verify =====
print('\n===== Step 3: Verification =====')
for tbl in ['users','user_profiles','search_config','strategies','campaigns','field_schemas','operation_logs']:
    n = c.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    print(f'  {tbl}: {n} rows')

print('\n  is_current check:')
for r in c.execute("SELECT name, is_current FROM user_profiles").fetchall():
    print(f'    {r["name"]}: is_current={r["is_current"]}')

print('\n  Data roundtrip:')
row = c.execute("SELECT name, data FROM user_profiles WHERE is_current=1").fetchone()
restored = json.loads(row['data'])
with open(os.path.join(BASE, 'instances', 'users', f'{row["name"]}.yaml'), 'r', encoding='utf-8') as f:
    orig = yaml.safe_load(f)
ok1 = json.dumps(restored, ensure_ascii=False, sort_keys=True) == json.dumps(orig, ensure_ascii=False, sort_keys=True)
print(f'    {row["name"]}: roundtrip match = {ok1}')

row2 = c.execute("SELECT data FROM search_config LIMIT 1").fetchone()
restored2 = json.loads(row2['data'])
with open(os.path.join(BASE, 'profiles', 'search_config.yaml'), 'r', encoding='utf-8') as f:
    orig2 = yaml.safe_load(f)
ok2 = json.dumps(restored2, ensure_ascii=False, sort_keys=True) == json.dumps(orig2, ensure_ascii=False, sort_keys=True)
print(f'    search_config: roundtrip match = {ok2}')

conn.close()
print(f'\nDatabase: {DB}')
print(f'Size: {os.path.getsize(DB):,} bytes')
print('All done.')
