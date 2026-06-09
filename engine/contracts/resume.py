from pydantic import BaseModel, Field


class ResumeBullet(BaseModel):
    text: str = Field(description="bullet 文本")
    source_ids: list[str] = Field(default_factory=list, description="引用的 me.yaml 条目 id 列表")


class Resume(BaseModel):
    summary: str = Field(description="Summary 段落")
    skills: str = Field(description="Skills 段落")
    work_experience: list[ResumeBullet] = Field(default_factory=list)
    projects: list[ResumeBullet] = Field(default_factory=list)
    education: str = Field(description="教育背景")
    certifications: str = Field(description="证书")
