from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal


class Scores(BaseModel):
    model_config = ConfigDict(extra='allow')
    skill: Literal[95, 80, 60, 40, 20]
    experience: Literal[95, 80, 60, 40, 20]
    level: Literal[95, 80, 60, 40, 20]
    industry: Literal[95, 80, 60, 40, 20]
    bonus: Literal[95, 80, 60, 40, 20]


class MatchResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    reason: str = Field(
        description="匹配推理过程"
    )
    direction: Optional[str] = Field(
        default=None,
        description="岗位赛道标签，从系统策略配置中定义的方向名称中选择。评分步骤不输出此字段，方向由独立的预判步骤确定。"
    )
    scores: Scores = Field(description="五维原始分，每个维度 0-100 整数")
