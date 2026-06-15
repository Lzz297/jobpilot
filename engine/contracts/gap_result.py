from pydantic import BaseModel, Field, ConfigDict


class GapItem(BaseModel):
    model_config = ConfigDict(extra='allow')
    skill: str = Field(default="")
    description: str = Field(default="")
    market_demand: str = Field(default="")
    learning_difficulty: str = Field(default="")
    current_gap: str = Field(default="")
    is_blocker: bool = Field(default=False)
    interview_vs_job: str = Field(default="")
    learning_path: list[str] = Field(default_factory=list)
    priority: str = Field(default="")
    priority_reason: str = Field(default="")
    can_bypass: str = Field(default="")


class StrengthItem(BaseModel):
    model_config = ConfigDict(extra='allow')
    skill: str = Field(default="")
    description: str = Field(default="")
    market_demand: str = Field(default="")
    candidate_level: str = Field(default="")
    advantage: str = Field(default="")
    how_to_leverage: str = Field(default="")


class LowValueSkill(BaseModel):
    model_config = ConfigDict(extra='allow')
    skill: str = Field(default="")
    note: str = Field(default="")


class QuickWinAction(BaseModel):
    model_config = ConfigDict(extra='allow')
    action: str = Field(default="")
    time_needed: str = Field(default="")
    impact: str = Field(default="")
    how_to: str = Field(default="")
    ai_tools: str = Field(default="")


class GapAnalysisResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    market_reality_check: dict = Field(default_factory=dict)
    strengths: list[dict] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    low_value_skills: list[dict] = Field(default_factory=list)
    strategic_advice: list[str] = Field(default_factory=list)
    quick_win_actions: list[dict] = Field(default_factory=list)
