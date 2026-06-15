from pydantic import BaseModel, Field, ConfigDict


class TechnicalSkill(BaseModel):
    model_config = ConfigDict(extra='allow')
    skill: str = Field(description="技能名称，具体到可学习的程度")
    category: str = Field(description="编程语言/框架/数据库/云平台/DevOps/安全/协议/其他工具")
    description: str = Field(description="技能说明")
    typical_tools: list[str] = Field(default_factory=list)
    count: int = Field(ge=0)
    percentage: str = Field(description="出现百分比，如 60%")
    level: str = Field(description="必须/优先/加分")


class MarketAnalysisResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    sample_size: int = Field(ge=0)
    technical_skills: list[TechnicalSkill] = Field(default_factory=list)
    soft_skills: list[dict] = Field(default_factory=list)
    language_requirements: dict = Field(default_factory=dict)
    salary_overview: dict = Field(default_factory=dict)
    experience_distribution: list[dict] = Field(default_factory=list)
    education_requirements: dict = Field(default_factory=dict)
    common_responsibilities: list[str] = Field(default_factory=list)
    industry_distribution: list[dict] = Field(default_factory=list)
    company_profile: dict = Field(default_factory=dict)
    interview_hints: dict = Field(default_factory=dict)
    key_trends: list[str] = Field(default_factory=list)
