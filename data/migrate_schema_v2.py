"""Migrate user_field schema v1 → v2
- basic_info.hk_permanent_resident: toggle → select
- job_intent: textarea → tags for target_titles/target_industries/location_preference
- job_intent.notice_period: input → select
- job_intent.salary_expectation.currency: input → select
- education.period: add placeholder
- New group: languages (table with language/proficiency/certificate)
- Reorder: basic_info, profile_summary, job_intent, languages, skills,
  work_experience, core_modules, projects, education, certifications
"""
import sqlite3, json, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_agent.db')
conn = sqlite3.connect(DB)
c = conn.cursor()
r = c.execute("SELECT data FROM field_schemas WHERE name = 'user_field'").fetchone()
schema = json.loads(r[0])
groups = schema['groups']

# 1. basic_info: hk_permanent_resident -> select
for f in groups[0]['fields']:
    if f['key'] == 'hk_permanent_resident':
        f['label'] = '工作权利 / 居留身份'
        f['widget'] = 'select'
        f['options'] = ['香港永久居民', '持有工作签证', '需要工作签证', '其他']
        f.pop('type', None)

# 2. job_intent: widget changes
for g in groups:
    if g['key'] == 'job_intent':
        for f in g['fields']:
            if f['key'] in ('target_titles', 'target_industries'):
                f['widget'] = 'tags'
                f.pop('rows', None)
                f.pop('placeholder', None)
            elif f['key'] == 'location_preference':
                f['widget'] = 'tags'
                f.pop('rows', None)
            elif f['key'] == 'notice_period':
                f['widget'] = 'select'
                f['options'] = ['即时到岗', '1个月内', '3个月内', '面议']
            elif f['key'] == 'salary_expectation':
                for sf in f.get('fields', []):
                    if sf['key'] == 'currency':
                        sf['widget'] = 'select'
                        sf['options'] = ['HKD', 'CNY', 'USD']
                    elif sf['key'] == 'note':
                        sf['placeholder'] = '如：可面议、不含 bonus、期望年薪非月薪'
        break

# 3. education: period placeholder
for g in groups:
    if g['key'] == 'education':
        for col in g.get('columns', []):
            if col['key'] == 'period':
                col['placeholder'] = '如：2020-2024'
        break

# 4. new languages group
languages_group = {
    "key": "languages", "label": "语言能力", "type": "array", "widget": "table",
    "description": "语言能力列表。LLM 将根据此信息评估岗位语言要求匹配度。",
    "columns": [
        {"key": "language", "label": "语言", "type": "string", "widget": "input"},
        {"key": "proficiency", "label": "熟练度", "type": "string", "widget": "select",
         "options": ["母语", "流利", "良好", "基础"]},
        {"key": "certificate", "label": "证书 / 考试", "type": "string", "widget": "input"}
    ]
}

# 5. reorder
NEW_ORDER = ['basic_info', 'profile_summary', 'job_intent', 'languages',
             'skills', 'work_experience', 'core_modules', 'projects',
             'education', 'certifications']
group_map = {g['key']: g for g in groups}
group_map['languages'] = languages_group
new_groups = [group_map[k] for k in NEW_ORDER]

schema['groups'] = new_groups
c.execute("UPDATE field_schemas SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE name = 'user_field'",
          (json.dumps(schema, ensure_ascii=False),))
conn.commit()
conn.close()

print('Schema v2 migration complete.')
for i, g in enumerate(new_groups):
    n = len(g.get('fields', [])) or len(g.get('columns', [])) or 0
    print(f'  {i}. {g["label"]} ({g["key"]}) - {n} items')
