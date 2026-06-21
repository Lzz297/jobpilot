"""Migrate user_field schema + user profile data v2 → v3
Changes:
  Schema:
  - Remove core_modules from groups (becomes inline under work_experience)
  - skills: update description about languages migration
  - work_experience: + company_description, company_size columns
  - education: + school_en column
  Data:
  - hk_permanent_resident: boolean → string mapping
  - Clean top-level core_modules residue
  - Migrate skills.languages → top-level languages table
"""
import sqlite3, json, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_agent.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ============================================================
# PART 1: Schema changes
# ============================================================
r = c.execute("SELECT data FROM field_schemas WHERE name = 'user_field'").fetchone()
schema = json.loads(r['data'])
groups = schema['groups']
group_map = {g['key']: g for g in groups}

# 2a. Remove core_modules from groups
groups = [g for g in groups if g['key'] != 'core_modules']

# 2b. Update skills description
for g in groups:
    if g['key'] == 'skills':
        g['description'] = '语言能力（普通话/粤语/英语等）已迁移至独立的「语言能力」分组，请在上方填写。'
        break

# 2c. Add company_description + company_size to work_experience columns
for g in groups:
    if g['key'] == 'work_experience':
        cols = g['columns']
        cols.append({"key": "company_description", "label": "公司简介", "type": "string", "widget": "textarea"})
        cols.append({"key": "company_size", "label": "公司规模", "type": "string", "widget": "select",
                      "options": ["初创 (<20人)", "中小 (20-200人)", "中大型 (200-1000人)", "大型 (1000人以上)"]})
        break

# 2d. Add school_en to education columns (after period)
for g in groups:
    if g['key'] == 'education':
        cols = g['columns']
        cols.insert(4, {"key": "school_en", "label": "学校 (英文)", "type": "string", "widget": "input"})
        break

NEW_ORDER = ['basic_info', 'profile_summary', 'job_intent', 'languages',
             'skills', 'work_experience', 'projects', 'education', 'certifications']
new_group_map = {g['key']: g for g in groups}
new_groups = [new_group_map[k] for k in NEW_ORDER]
schema['groups'] = new_groups

c.execute("UPDATE field_schemas SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE name = 'user_field'",
          (json.dumps(schema, ensure_ascii=False),))
print("Schema v3: core_modules removed, work_experience +2 cols, education +1 col")
for i, g in enumerate(new_groups):
    n = len(g.get('fields', [])) or len(g.get('columns', [])) or 0
    print(f"  {i}. {g['key']} ({g['label']}) - {n} items")

# ============================================================
# PART 2: Data migration
# ============================================================

# Get all user profiles
profiles = c.execute("SELECT id, name, data FROM user_profiles").fetchall()
migrated = 0

for row in profiles:
    profile = json.loads(row['data'])
    changed = False

    # 3a. Fix hk_permanent_resident boolean -> string
    hk = profile.get('hk_permanent_resident')
    if isinstance(hk, bool):
        profile['hk_permanent_resident'] = '香港永久居民' if hk else '需要工作签证'
        changed = True
        print(f"  [{row['name']}] hk_permanent_resident: {hk} → '{profile['hk_permanent_resident']}'")

    # 3b. Clean top-level core_modules residue
    if 'core_modules' in profile:
        del profile['core_modules']
        changed = True
        print(f"  [{row['name']}] Removed top-level core_modules residue")

    # 3c. Migrate skills.languages → top-level languages table
    skills = profile.get('skills', {})
    old_langs = skills.pop('languages', None)
    if old_langs and isinstance(old_langs, list) and len(old_langs) > 0:
        PROFICIENCY_MAP = {'母语': '母语', '流利': '流利', '良好': '良好',
                           '基础': '基础', '入门': '基础', '精通': '流利'}
        new_langs = []
        for item in old_langs:
            name = item.get('name', '')
            note = item.get('note', '') or item.get('detail', '')
            level = item.get('level', '')
            # guess proficiency from level or note
            prof = '良好'
            for k, v in PROFICIENCY_MAP.items():
                if k in str(level) or k in str(note):
                    prof = v
                    break
            new_langs.append({
                "language": name,
                "proficiency": prof,
                "certificate": note if note and 'CET' in str(note) else ''
            })
        profile['languages'] = new_langs
        changed = True
        print(f"  [{row['name']}] Migrated {len(old_langs)} languages: skills.languages → top-level languages")

    # Also remove languages from skills schema sub-types if they exist
    if 'languages' in skills:
        del skills['languages']
        changed = True

    if changed:
        c.execute("UPDATE user_profiles SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                  (json.dumps(profile, ensure_ascii=False), row['id']))
        migrated += 1

conn.commit()
conn.close()
print(f"\nData migration complete. {migrated} profile(s) updated.")
