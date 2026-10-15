from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Budget(Model):
    max_generations: int = Field(ge=1, le=10)
    reserved: int = Field(default=0, ge=0)
    consumed: int = Field(default=0, ge=0)


class NextAction(Model):
    code: str
    message: str
    required_artifacts: list[str] = Field(default_factory=list)
    target_role: str | None = None


class State(Model):
    protocol_version: Literal["1.0"] = "1.0"
    case_id: str
    revision: int = 0
    workflow_status: str = "INIT"
    operation_status: str = "active"
    round: int = 1
    pending_task_id: str | None = None
    input_sha256: str
    profile_id: Literal["chatgpt_adapted_v1"] = "chatgpt_adapted_v1"
    config_sha256: str
    required_tools: list[str] = Field(default_factory=list)
    received_tools: list[str] = Field(default_factory=list)
    budget: Budget
    next_action: NextAction
    workflow_completed: bool = False
    restoration_success: bool | None = None
    selected_round: int | None = None
    terminal_reason: str | None = None
    deviated: bool = False
    block_reason: str | None = None
    created_at: str
    updated_at: str


class Artifact(Model):
    path: str
    sha256: str
    kind: str
    width: int | None
    height: int | None


class Request(Model):
    protocol_version: Literal["1.0"] = "1.0"
    task_id: str
    case_id: str
    role: str
    round: int
    attempt_index: int
    expected_state_revision: int
    input_sha256: str
    profile_id: Literal["chatgpt_adapted_v1"] = "chatgpt_adapted_v1"
    template_sha256: str
    prompt_file: str
    payload_schema: str
    allowed_assets: list[Artifact]
    context: dict
    response_file: str
    ready_marker: str


class Response(Model):
    protocol_version: Literal["1.0"] = "1.0"
    task_id: str
    case_id: str
    role: str
    round: int
    expected_state_revision: int
    input_sha256: str
    status: Literal["ok", "error"]
    payload: dict | None
    error: dict | None
    provenance: dict


class EvidenceManifest(Model):
    protocol_version: Literal["1.0"] = "1.0"
    tool_id: str
    input_sha256: str
    status: Literal["ok", "error"]
    model_name: str
    checkpoint_sha256: str | None
    source_width: int
    source_height: int
    tool_width: int
    tool_height: int
    coordinates: Literal["canonical_norm"]
    source_to_tool: list[list[float | int]]
    detections: list[dict]
    assets: list[Artifact]
    data: dict
    error: str | None


class Transition(Model):
    next_status: str
    role: str | None = None
    terminal_reason: str | None = None
    increment_round: bool = False


class ImportResult(Model):
    accepted: bool
    code: str
    message: str


class GateResult(Model):
    valid_geometry: bool = True
    observations: dict = Field(default_factory=dict)


class Selection(Model):
    round: int | None
    success: bool
    reason: str
