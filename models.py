"""Typed action, observation, and state models for Incident Commander."""

from __future__ import annotations

from typing import Literal

from openenv.core.env_server.types import Action, Observation, State
from pydantic import Field

ActionType = Literal[
    "list_alerts",
    "inspect_service",
    "query_metrics",
    "query_logs",
    "read_runbook",
    "restart_service",
    "scale_service",
    "rollback_service",
    "toggle_feature_flag",
    "post_status_update",
    "resolve_incident",
]

Difficulty = Literal["easy", "medium", "hard"]
IncidentStatus = Literal["active", "mitigated", "resolved", "timeout"]
ServiceHealth = Literal["healthy", "degraded", "failing"]
AlertSeverity = Literal["critical", "high", "medium", "low"]
AlertStatus = Literal["firing", "cleared"]


class IncidentAlert(Observation):
    """Structured alert surfaced to the incident commander."""

    alert_id: str = Field(..., description="Unique alert identifier")
    service: str = Field(..., description="Service responsible for the alert")
    severity: AlertSeverity = Field(..., description="Alert severity")
    title: str = Field(..., description="Short alert title")
    description: str = Field(..., description="Human-readable alert details")
    status: AlertStatus = Field(default="firing", description="Alert lifecycle status")


class ServiceStatus(Observation):
    """Observable health snapshot for a service involved in the incident."""

    name: str = Field(..., description="Service identifier")
    status: ServiceHealth = Field(..., description="Current health state")
    release: str = Field(..., description="Currently deployed release")
    replicas: int = Field(..., ge=1, description="Replica count")
    cpu_pct: float = Field(..., ge=0.0, le=100.0, description="CPU percentage")
    error_rate: float = Field(..., ge=0.0, le=1.0, description="Error rate")
    latency_ms: int = Field(..., ge=0, description="Observed p95 latency")
    summary: str = Field(..., description="Compact service summary for the model")
    feature_flags: dict[str, bool] = Field(
        default_factory=dict,
        description="Visible feature flags for this service",
    )


class IncidentCommanderAction(Action):
    """Action schema for operating the incident response environment."""

    action_type: ActionType = Field(..., description="The action to execute")
    service: str | None = Field(
        default=None,
        description="Target service for service-scoped actions",
    )
    flag_name: str | None = Field(
        default=None,
        description="Feature flag to mutate for toggle_feature_flag",
    )
    enabled: bool | None = Field(
        default=None,
        description="Desired feature flag state for toggle_feature_flag",
    )
    target_instances: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Target replica count for scale_service",
    )
    release: str | None = Field(
        default=None,
        description="Release identifier for rollback_service",
    )
    message: str = Field(
        default="",
        description="Free-form note used for status updates or resolution summaries",
    )


class IncidentCommanderObservation(Observation):
    """Observation returned after reset and each step."""

    task_id: str = Field(default="", description="Current task identifier")
    task_title: str = Field(default="", description="Task title")
    difficulty: Difficulty = Field(default="easy", description="Task difficulty")
    objective: str = Field(default="", description="What the agent must achieve")
    incident_status: IncidentStatus = Field(
        default="active",
        description="Current incident lifecycle status",
    )
    situation_summary: str = Field(
        default="",
        description="Compact natural-language briefing for the current incident",
    )
    active_alerts: list[IncidentAlert] = Field(
        default_factory=list,
        description="Alerts still firing after the action",
    )
    service_statuses: list[ServiceStatus] = Field(
        default_factory=list,
        description="Service health snapshots",
    )
    recent_findings: list[str] = Field(
        default_factory=list,
        description="Evidence gathered so far from logs, metrics, and runbooks",
    )
    completed_milestones: list[str] = Field(
        default_factory=list,
        description="Completed grader milestones",
    )
    remaining_milestones: list[str] = Field(
        default_factory=list,
        description="Milestones still needed for a perfect score",
    )
    available_actions: list[str] = Field(
        default_factory=list,
        description="Allowed actions for the model",
    )
    recommended_focus: list[str] = Field(
        default_factory=list,
        description="Suggested next areas of attention derived from the current state",
    )
    last_action_result: str = Field(
        default="",
        description="Human-readable result of the action that was just executed",
    )
    last_action_error: str | None = Field(
        default=None,
        description="Validation or execution error for the latest action",
    )
    partial_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Deterministic grader score after the latest action",
    )
    final_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Final score when the episode ends",
    )
    remaining_steps: int = Field(
        default=0,
        ge=0,
        description="Remaining step budget for the episode",
    )


class IncidentCommanderState(State):
    """Server-side episode state exposed through the OpenEnv state endpoint."""

    task_id: str = Field(default="", description="Current task identifier")
    task_title: str = Field(default="", description="Current task title")
    difficulty: Difficulty = Field(default="easy", description="Current difficulty")
    incident_status: IncidentStatus = Field(
        default="active",
        description="Current incident lifecycle status",
    )
    max_steps: int = Field(default=0, ge=0, description="Maximum allowed steps")
    timeline_min: int = Field(default=0, ge=0, description="Elapsed incident minutes")
    partial_score: float = Field(default=0.0, ge=0.0, le=1.0)
    final_score: float = Field(default=0.0, ge=0.0, le=1.0)
    completed_milestones: list[str] = Field(default_factory=list)
    remaining_milestones: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
    last_action: str = Field(default="", description="Most recent action signature")
    last_action_error: str | None = Field(default=None)
    status_updates_sent: int = Field(default=0, ge=0)
