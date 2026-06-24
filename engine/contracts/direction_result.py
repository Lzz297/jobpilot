from pydantic import BaseModel, Field, ConfigDict


class DirectionLabel(BaseModel):
    """LLM 方向预判步骤的单条输出模型。"""
    model_config = ConfigDict(extra='allow')
    index: int = Field(description="岗位编号")
    direction: str = Field(description="从可选方向列表中选择的方向名")


class CommonRequirements(BaseModel):
    model_config = ConfigDict(extra='allow')
    direct_match: list[dict] = Field(default_factory=list)
    quick_learnable: list[dict] = Field(default_factory=list)
    hard_gap: list[dict] = Field(default_factory=list)


class DirectionAggregationResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    direction: str = Field(default="")
    common_requirements: CommonRequirements = Field(default_factory=CommonRequirements)
    typical_responsibilities: list[str] = Field(default_factory=list)
    common_bonus: list[str] = Field(default_factory=list)
    resume_strategy: str = Field(default="")
