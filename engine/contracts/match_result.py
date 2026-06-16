from pydantic import BaseModel, Field, ConfigDict


class Scores(BaseModel):
    model_config = ConfigDict(extra='allow')
    skill: int = Field(ge=0, le=100, description="技能匹配度 0-100")
    experience: int = Field(ge=0, le=100, description="经验年限匹配度 0-100")
    level: int = Field(ge=0, le=100, description="职级匹配度 0-100")
    industry: int = Field(ge=0, le=100, description="行业对口度 0-100")
    bonus: int = Field(ge=0, le=100, description="加分项匹配度 0-100")


class MatchResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    reason: str = Field(
        description="匹配推理过程"
    )
    direction: str = Field(
        description="岗位赛道标签：web3 / payment / solutions / technical / default"
    )
    scores: Scores = Field(description="五维原始分，每个维度 0-100 整数")
