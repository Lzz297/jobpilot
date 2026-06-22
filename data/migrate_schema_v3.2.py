"""v3.2: Add hints and placeholders to user_field schema fields."""
import sqlite3, json, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_agent.db')
conn = sqlite3.connect(DB)
c = conn.cursor()

r = c.execute("SELECT data FROM field_schemas WHERE name = 'user_field'").fetchone()
schema = json.loads(r[0])
groups = schema['groups']
group_map = {g['key']: g for g in groups}

# Helper: get or create hint on a field/column
def add_hint(obj, hint_text):
    obj['hint'] = hint_text

def add_placeholder(obj, ph_text):
    obj['placeholder'] = ph_text

# ============================================================
# 1. profile_summary
# ============================================================
ps = group_map['profile_summary']
for f in ps['fields']:
    if f['key'] == 'strategic_positioning':
        f['rows'] = 15
        add_hint(f, '定义你的职业定位，如 Web3 支付基础设施工程师。LLM 用于匹配 JD 方向。')
    elif f['key'] == 'summary':
        f['rows'] = 18
        add_hint(f, '总结你的核心竞争力和优势。LLM 用于判断岗位匹配度。')

# ============================================================
# 2. job_intent
# ============================================================
ji = group_map['job_intent']
for f in ji['fields']:
    if f['key'] == 'target_titles':
        add_hint(f, '多个用换行或逗号分隔')
        add_placeholder(f, '后端开发工程师, 数据分析师')
    elif f['key'] == 'target_industries':
        add_hint(f, '多个用换行或逗号分隔')
        add_placeholder(f, '金融, 互联网')
    elif f['key'] == 'location_preference':
        add_hint(f, '多个用换行或逗号分隔')
        add_placeholder(f, 'Hong Kong')

# ============================================================
# 3. work_experience columns
# ============================================================
we = group_map['work_experience']
for col in we['columns']:
    if col['key'] == 'period':
        add_placeholder(col, '如：2024.08 - 2026.05')
    elif col['key'] == 'overview':
        add_hint(col, '简要描述公司业务和你的职责范围，2-3 句即可。')
    elif col['key'] == 'company_description':
        add_hint(col, '公司业务简介，帮助 LLM 评估行业匹配度。一句话即可。')
    elif col['key'] == 'highlights':
        add_hint(col, '每行一个亮点，按 Enter 换行。突出量化成果和关键贡献。')
    elif col['key'] == 'key_achievements':
        for sub in col.get('columns', []):
            if sub['key'] == 'resume_bullet':
                add_hint(sub, '用 STAR 法则写简历要点。如"Designed X that improved Y by Z%"。LLM 直接用于生成简历。')
            elif sub['key'] == 'story':
                add_hint(sub, '面试用详细故事：背景、挑战、行动、结果。用于应对面试追问。')
            elif sub['key'] == 'interview_keywords':
                add_hint(sub, '按 Enter 添加关键词，用于面试准备。')

# ============================================================
# 4. projects columns
# ============================================================
proj = group_map['projects']
for col in proj['columns']:
    if col['key'] == 'period':
        add_placeholder(col, '如：2024.08 - 2026.05')
    elif col['key'] == 'description':
        add_hint(col, '项目背景、目标和技术亮点。2-3 句即可。')
    elif col['key'] == 'resume_bullets':
        for sub in col.get('columns', []):
            if sub['key'] == 'text':
                add_hint(sub, '用 STAR 法则写简历要点。')

# ============================================================
# 5. languages
# ============================================================
lang = group_map['languages']
for col in lang['columns']:
    if col['key'] == 'certificate':
        add_hint(col, '如：IELTS 7.0、CET-6、JLPT N1')

c.execute("UPDATE field_schemas SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE name = 'user_field'",
          (json.dumps(schema, ensure_ascii=False),))
conn.commit()
conn.close()
print("v3.2: Added hints and placeholders to schema fields.")
print("  profile_summary: strategic_positioning, summary")
print("  job_intent: target_titles, target_industries, location_preference")
print("  work_experience: period, overview, company_description, highlights")
print("  work_experience.key_achievements: resume_bullet, story, interview_keywords")
print("  projects: period, description, resume_bullets.text")
print("  languages: certificate")
