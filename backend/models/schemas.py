from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GROQ_MODEL_NAME = "openai/gpt-oss-20b"


class HealthResponse(BaseModel):
    status: str
    database_connected: bool
    environment: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str
    message: str
    details: dict[str, object] | list[object] | str | None = None


class ASTAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1)
    language: Literal["cpp", "java", "python"]


class ASTMetrics(BaseModel):
    total_lines_of_code: int
    function_count: int
    class_count: int
    loop_count: int
    conditional_count: int
    cyclomatic_complexity: int
    complexity_rating: Literal["LOW", "MEDIUM", "HIGH"]


class ASTAnalysisResponse(BaseModel):
    language: Literal["cpp", "java", "python"]
    metrics: ASTMetrics
    ast_tree_string: str


class MigrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1)
    source_language: str = Field(min_length=1)
    target_language: str = Field(min_length=1)
    selected_models: list[str] = Field(
        default_factory=lambda: ["fine_tuned_hf", GROQ_MODEL_NAME],
        min_length=1,
    )


class SingleModelTranslationResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    translated_code: str
    execution_time_seconds: float
    file_path: str


class MigrationResponse(BaseModel):
    migration_id: str
    source_language: str
    target_language: str
    ast_metrics: dict[str, object]
    applied_rag_rules: list[dict[str, object]]
    results: list[SingleModelTranslationResult]

class CompilationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    migration_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
    model_name: str = Field(pattern=r"^(fine_tuned_hf|openai/gpt-oss-20b)$")


class CompilationResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    migration_id: str
    model_name: str
    status: Literal["SUCCESS", "FAILED"]
    stdout: str
    stderr: str
    execution_time_seconds: float
    error_type: str
