from pydantic import BaseModel, Field, ConfigDict


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
