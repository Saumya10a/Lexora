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


class RepairAttemptLog(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    attempt_number: int
    model_name: str
    error_traceback: str
    corrected_code: str
    compilation_status: str


class RepairLoopSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    final_status: Literal["SUCCESS", "FAILED"]
    total_attempts: int
    attempt_history: list[RepairAttemptLog] = Field(default_factory=list)


class ModelBenchmarkMetrics(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    first_pass_compile: bool
    repair_attempts_needed: int = Field(ge=0)
    final_compilation_status: str
    passed_test_cases: int = Field(ge=0)
    total_test_cases: int = Field(ge=0)
    semantic_migration_accuracy: float = Field(ge=0.0, le=100.0)
    latency_seconds: float = Field(ge=0.0)
    migration_confidence_score: float = Field(ge=0.0, le=100.0)


class BenchmarkReport(BaseModel):
    migration_id: str
    timestamp: datetime
    models_evaluated: list[ModelBenchmarkMetrics]


class MigrationResponse(BaseModel):
    migration_id: str
    source_language: str
    target_language: str
    ast_metrics: dict[str, object]
    applied_rag_rules: list[dict[str, object]]
    results: list[SingleModelTranslationResult]
    repair_summaries: list[RepairLoopSummary] = Field(default_factory=list)

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


class ProjectDeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_framework: Literal["spring-boot", "go-fiber", "node"]


class ProjectDeployResponse(BaseModel):
    migration_id: str
    status: Literal["RUNNING"]
    target_framework: str
    host_port: int
    base_url: str


class ApiProxyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"] = "GET"
    route: str = Field(min_length=1, max_length=512)
    body: dict[str, object] = Field(default_factory=dict)
