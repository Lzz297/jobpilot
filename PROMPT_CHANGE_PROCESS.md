# Prompt 修改流程规范

> 这是一份操作手册，不是自动执行的规则。所有流程需要你手动完成。

---

## 1. 什么时候需要跑评估

当你手动做了以下任一操作后，需要手动运行评估命令：

- 修改了 `profiles/prompts.yaml` 中任何 prompt 模板
- 修改了 `job_match.py` 中评分或权重相关代码
- 修改了 `resume_gen.py` 中简历生成相关 prompt 逻辑
- 修改了 `profiles/me.yaml`（用户画像变更会影响 LLM 判断）
- 切换了 LLM 模型

**评估命令**：

```bash
python evaluation/run_eval.py --dev_set
python evaluation/run_checker_eval.py
```

---

## 2. Dev Set 指标退化了怎么办

对比上次运行结果，如果方向准确率下降：

- 必须修复或给出合理解释
- 解释记录在 Git 提交信息中
- 不能以"模型行为变化"为由忽略 3% 以上的退化

---

## 3. Holdout 怎么用

- 日常调 prompt 只用 `--dev_set`
- 只在认为优化完成、准备收尾时跑 `--holdout`
- 跑之前先在脑子里定好过关线（如"方向正确不少于 4/5"），跑完再对比
- 没过就是没过，不要事后解释
- 报 "4/5" 这种分数形式，不报百分比

---

## 4. Git 提交信息格式

提交时写清楚以下内容：

- 改了什么、为什么改
- Dev 方向准确率（如 14/19）和与上次的变化
- Checker 通过数（当前为"16 用例待战役三启用"）
- 是否跑了 Holdout 及结果
- 当前 LLM 模型名

**示例**：

```
[prompt] 调整匹配评分中的方向判断逻辑

Dev: 14/19 → 15/19 (+1)
Checker: 16 用例待战役三启用
Holdout: 未跑
Model: deepseek-v4-pro
```

---

## 5. 评估集怎么维护

每隔一段时间（2-4 周），手动补充评估集：

- 从最新的 `output/run_xxx/matched_jobs.json` 中挑 3-5 条新 JD
- 按 `instances/eval/ANNOTATION_GUIDE.md` 中的标准标注方向
- 加入 `all_cases.json`
- 从 `all_cases.json` 中移除等量最旧的 JD
- 重新运行 `python evaluation/split_eval.py` 更新 dev_set 和 holdout

这全是手工操作，没有自动化脚本。

---

## 6. 各指标当前状态

| 指标 | 状态 | 说明 |
|------|------|------|
| 方向准确率 | 已启用 | 跨阶段可对比 |
| 分数档位准确率 | 待标注 | 等你填完 score_range 后启用；战役二权重进代码后需重新落基线 |
| Token 消耗 / 成本 | 待战役二 | 当前 llm_call 不返回 usage，显示为 0 |

---

## 7. Holdout 保密

- 日常调 prompt 不碰 holdout
- 不拿 holdout 反复调参
- 只在最终验证时用一次
