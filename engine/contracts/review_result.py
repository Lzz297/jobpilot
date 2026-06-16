from pydantic import BaseModel, Field, ConfigDict


class ResumeReviewResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    overall_score: str = Field(default="")
    six_second_test: str = Field(default="")
    missing_keywords: list[str] = Field(default_factory=list)
    bullets_to_rewrite: list[dict] = Field(default_factory=list)
    quantification_opportunities: list[str] = Field(default_factory=list)
    weakness_exposures: list[str] = Field(default_factory=list)
    space_optimization: str = Field(default="")
    top_3_improvements: list[str] = Field(default_factory=list)
