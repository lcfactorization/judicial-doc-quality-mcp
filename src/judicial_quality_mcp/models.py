"""Data models for judicial document quality assessment v0.1.0"""

from pydantic import BaseModel, Field


class DeductionItem(BaseModel):
    item: str = Field(default="", description="扣分项名称")
    deduction: int = Field(default=0, description="扣分值")
    quote: str = Field(default="", description="原文引用")
    basis: str = Field(default="", description="规范依据")


class BonusItem(BaseModel):
    item: str = Field(default="", description="加分项名称")
    bonus: int = Field(default=0, description="加分值")
    quote: str = Field(default="", description="原文引用")
    reason: str = Field(default="", description="加分理由")


class DimensionScore(BaseModel):
    dimension: str = Field(default="", description="维度标识")
    dimension_title: str = Field(default="", description="维度中文名")
    weight: float = Field(default=0.0, description="权重")
    score: int = Field(default=0, description="原始得分(0-100)")
    weighted_score: float = Field(default=0.0, description="加权得分")
    quote: str = Field(default="", description="典型原文摘录")
    reasoning: str = Field(default="", description="评分理由")
    deduction_items: list[DeductionItem] = Field(default_factory=list, description="扣分明细")
    bonus_items: list[BonusItem] = Field(default_factory=list, description="加分明细")
    data_completeness: str = Field(default="complete", description="数据完整性: complete/partial/insufficient")


class CrossCheckConflict(BaseModel):
    rule_id: str = Field(default="", description="规则编号")
    rule_name: str = Field(default="", description="规则名称")
    message: str = Field(default="", description="冲突描述")
    conflict_dims: list[str] = Field(default_factory=list, description="冲突维度")


class CrossCheckResult(BaseModel):
    conflict_detected: bool = Field(default=False)
    conflicts: list[CrossCheckConflict] = Field(default_factory=list)
    suggestion: str = Field(default="")


class QualityAssessmentResult(BaseModel):
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    weighted_total: float = Field(default=0.0)
    grade: str = Field(default="")
    grade_description: str = Field(default="")
    cross_check: CrossCheckResult = Field(default_factory=CrossCheckResult)
    report_markdown: str = Field(default="")


class ParsedScoreResult(BaseModel):
    dimension: str = Field(default="")
    parsed: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
    raw_response: str = Field(default="")


class SectionExtractionResult(BaseModel):
    plaintiff_claim: str = Field(default="", description="原告诉称/公诉机关指控")
    defendant_defense: str = Field(default="", description="被告辩称")
    court_finding: str = Field(default="", description="本院查明")
    evidence_analysis: str = Field(default="", description="证据分析/认证")
    reasoning: str = Field(default="", description="本院认为")
    judgment_basis: str = Field(default="", description="法律依据")
    judgment_main: str = Field(default="", description="判决主文")
    case_info: dict = Field(default_factory=dict, description="案件基本信息")
    extraction_confidence: float = Field(default=0.0, description="提取置信度")
