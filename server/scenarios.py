"""Scenario definitions and deterministic graders for Incident Commander."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

AVAILABLE_ACTIONS = [
    "list_alerts()",
    "inspect_service(service)",
    "query_metrics(service)",
    "query_logs(service)",
    "read_runbook(service)",
    "restart_service(service)",
    "scale_service(service, target_instances)",
    "rollback_service(service, release)",
    "toggle_feature_flag(service, flag_name, enabled)",
    "post_status_update(message)",
    "resolve_incident(message)",
]


@dataclass
class ServiceRuntime:
    """Mutable service state used by the internal simulator."""

    name: str
    status: str
    release: str
    stable_release: str
    replicas: int
    cpu_pct: float
    error_rate: float
    latency_ms: int
    summary: str
    feature_flags: dict[str, bool] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)
    runbook_steps: list[str] = field(default_factory=list)
    inspected: bool = False
    metrics_checked: bool = False
    logs_checked: bool = False
    runbook_checked: bool = False
    restart_applied: bool = False
    rollback_applied: bool = False
    scale_applied: bool = False


@dataclass
class AlertRuntime:
    """Mutable alert state."""

    alert_id: str
    service: str
    severity: str
    title: str
    description: str
    status: str = "firing"


@dataclass(frozen=True)
class TaskGrader:
    """Deterministic milestone-based grader returning scores in [0.0, 1.0]."""

    milestone_weights: dict[str, float]
    milestone_titles: dict[str, str]
    max_penalty: float = 0.25

    def score(self, runtime: "EpisodeRuntime") -> float:
        achieved = sum(
            weight
            for milestone, weight in self.milestone_weights.items()
            if milestone in runtime.completed_milestones
        )
        score = achieved - min(runtime.penalty_total, self.max_penalty)
        return round(max(0.0, min(1.0, score)), 4)

    def completed_titles(self, runtime: "EpisodeRuntime") -> list[str]:
        return [
            title
            for milestone, title in self.milestone_titles.items()
            if milestone in runtime.completed_milestones
        ]

    def remaining_titles(self, runtime: "EpisodeRuntime") -> list[str]:
        return [
            title
            for milestone, title in self.milestone_titles.items()
            if milestone not in runtime.completed_milestones
        ]


@dataclass(frozen=True)
class TaskSpec:
    """Immutable task blueprint."""

    task_id: str
    title: str
    difficulty: str
    objective: str
    narrative: str
    max_steps: int
    services: dict[str, ServiceRuntime]
    alerts: list[AlertRuntime]
    recommended_focus: list[str]
    grader: TaskGrader


@dataclass
class EpisodeRuntime:
    """Mutable state for a single incident episode."""

    spec: TaskSpec
    services: dict[str, ServiceRuntime]
    alerts: dict[str, AlertRuntime]
    findings: list[str] = field(default_factory=list)
    status_updates: list[str] = field(default_factory=list)
    completed_milestones: set[str] = field(default_factory=set)
    penalties: list[str] = field(default_factory=list)
    penalty_total: float = 0.0
    incident_status: str = "active"
    last_action_result: str = ""
    last_action_error: str | None = None
    final_score: float = 0.0
    timeline_min: int = 0
    action_history: list[str] = field(default_factory=list)


def _payments_worker_backlog() -> TaskSpec:
    grader = TaskGrader(
        milestone_weights={
            "alerts_reviewed": 0.05,
            "worker_inspected": 0.10,
            "worker_metrics_checked": 0.10,
            "worker_logs_checked": 0.15,
            "worker_runbook_checked": 0.10,
            "worker_restarted": 0.30,
            "status_update_sent": 0.10,
            "incident_resolved": 0.10,
        },
        milestone_titles={
            "alerts_reviewed": "Review the alert feed",
            "worker_inspected": "Inspect the failing payments-worker service",
            "worker_metrics_checked": "Check payments-worker metrics",
            "worker_logs_checked": "Check payments-worker logs",
            "worker_runbook_checked": "Read the payments-worker runbook",
            "worker_restarted": "Restart the deadlocked worker service",
            "status_update_sent": "Communicate an external status update",
            "incident_resolved": "Resolve the incident after recovery",
        },
    )
    return TaskSpec(
        task_id="payments_worker_backlog",
        title="Payments Worker Backlog",
        difficulty="easy",
        objective=(
            "Restore payment processing after the payments-worker backlog alert. "
            "Use evidence, apply the correct mitigation, communicate briefly, and "
            "resolve only once the alert clears."
        ),
        narrative=(
            "A background payment worker is deadlocked. The API is still serving "
            "traffic, but queued jobs are piling up and charge settlements are late."
        ),
        max_steps=8,
        services={
            "payments-worker": ServiceRuntime(
                name="payments-worker",
                status="failing",
                release="2026.04.05.2",
                stable_release="2026.04.05.2",
                replicas=2,
                cpu_pct=96.0,
                error_rate=0.18,
                latency_ms=5200,
                summary="Queue depth is surging and the worker pool is wedged.",
                log_lines=[
                    "deadlock detected in worker_pool while acking settlement job",
                    "retry loop exhausted after 12 attempts for settlement queue",
                ],
                runbook_steps=[
                    "If queue backlog + deadlock is observed, restart payments-worker.",
                    "Do not rollback unrelated services for this class of incident.",
                ],
            ),
            "payments-api": ServiceRuntime(
                name="payments-api",
                status="healthy",
                release="2026.04.04.1",
                stable_release="2026.04.04.1",
                replicas=4,
                cpu_pct=41.0,
                error_rate=0.01,
                latency_ms=210,
                summary="Customer-facing payments API is currently healthy.",
            ),
            "ledger-db": ServiceRuntime(
                name="ledger-db",
                status="healthy",
                release="2026.03.30.6",
                stable_release="2026.03.30.6",
                replicas=3,
                cpu_pct=37.0,
                error_rate=0.0,
                latency_ms=18,
                summary="Ledger database is operating normally.",
            ),
        },
        alerts=[
            AlertRuntime(
                alert_id="ALERT-PAY-101",
                service="payments-worker",
                severity="high",
                title="Payment settlement queue backlog",
                description="payments-worker queue depth exceeded 4,500 for 9 minutes.",
            )
        ],
        recommended_focus=["payments-worker", "queue backlog", "deadlock evidence"],
        grader=grader,
    )


def _checkout_flag_regression() -> TaskSpec:
    grader = TaskGrader(
        milestone_weights={
            "alerts_reviewed": 0.05,
            "checkout_inspected": 0.10,
            "checkout_metrics_checked": 0.10,
            "checkout_logs_checked": 0.15,
            "checkout_runbook_checked": 0.15,
            "flag_disabled": 0.25,
            "status_update_sent": 0.10,
            "incident_resolved": 0.10,
        },
        milestone_titles={
            "alerts_reviewed": "Review the alert feed",
            "checkout_inspected": "Inspect checkout-api",
            "checkout_metrics_checked": "Check checkout-api metrics",
            "checkout_logs_checked": "Check checkout-api logs",
            "checkout_runbook_checked": "Read the checkout-api runbook",
            "flag_disabled": "Disable the bad experiment flag",
            "status_update_sent": "Communicate an external status update",
            "incident_resolved": "Resolve the incident after checkout recovers",
        },
    )
    return TaskSpec(
        task_id="checkout_flag_regression",
        title="Checkout Feature Flag Regression",
        difficulty="medium",
        objective=(
            "Recover checkout success rate after a bad experimentation flag rollout. "
            "Identify the affected service, disable the offending flag, communicate "
            "status, and resolve when error rates normalize."
        ),
        narrative=(
            "A recommendation experiment was enabled for checkout traffic. Error "
            "rates are spiking, carts are failing to convert, and customer latency "
            "is above the SLO."
        ),
        max_steps=8,
        services={
            "checkout-api": ServiceRuntime(
                name="checkout-api",
                status="degraded",
                release="2026.04.04.7",
                stable_release="2026.04.04.7",
                replicas=4,
                cpu_pct=81.0,
                error_rate=0.23,
                latency_ms=3400,
                summary="Checkout requests fail intermittently after an experiment rollout.",
                feature_flags={
                    "reco_shadow_launch": True,
                    "express_checkout_beta": False,
                },
                log_lines=[
                    "NullPointerError in recommendation_shadow_adapter: missing price_cents",
                    "checkout failure rate spikes only when reco_shadow_launch=true",
                ],
                runbook_steps=[
                    "If checkout failures correlate with reco_shadow_launch, disable the flag.",
                    "Restart is only needed if config propagation stalls after the flag is disabled.",
                ],
            ),
            "cart-api": ServiceRuntime(
                name="cart-api",
                status="healthy",
                release="2026.04.03.3",
                stable_release="2026.04.03.3",
                replicas=3,
                cpu_pct=46.0,
                error_rate=0.01,
                latency_ms=180,
                summary="Cart service is healthy and not the primary fault domain.",
            ),
            "feature-config": ServiceRuntime(
                name="feature-config",
                status="healthy",
                release="2026.04.01.9",
                stable_release="2026.04.01.9",
                replicas=2,
                cpu_pct=28.0,
                error_rate=0.0,
                latency_ms=42,
                summary="Feature flag control plane is responding normally.",
            ),
        },
        alerts=[
            AlertRuntime(
                alert_id="ALERT-CHK-220",
                service="checkout-api",
                severity="high",
                title="Checkout error-rate regression",
                description="checkout-api error rate exceeded 20% after experiment rollout.",
            )
        ],
        recommended_focus=[
            "checkout-api",
            "recommendation experiment flags",
            "error-rate evidence",
        ],
        grader=grader,
    )


def _auth_token_rollover_cascade() -> TaskSpec:
    grader = TaskGrader(
        milestone_weights={
            "alerts_reviewed": 0.05,
            "auth_inspected": 0.10,
            "auth_logs_checked": 0.10,
            "auth_runbook_checked": 0.10,
            "cache_inspected": 0.10,
            "cache_metrics_checked": 0.10,
            "auth_rolled_back": 0.20,
            "cache_scaled": 0.15,
            "status_update_sent": 0.05,
            "incident_resolved": 0.05,
        },
        milestone_titles={
            "alerts_reviewed": "Review the alert feed",
            "auth_inspected": "Inspect auth-service",
            "auth_logs_checked": "Check auth-service logs",
            "auth_runbook_checked": "Read the auth-service runbook",
            "cache_inspected": "Inspect session-cache",
            "cache_metrics_checked": "Check session-cache metrics",
            "auth_rolled_back": "Rollback the faulty auth release",
            "cache_scaled": "Scale session-cache to absorb retry load",
            "status_update_sent": "Communicate an external status update",
            "incident_resolved": "Resolve the incident after downstream recovery",
        },
    )
    return TaskSpec(
        task_id="auth_token_rollover_cascade",
        title="Auth Token Rollover Cascade",
        difficulty="hard",
        objective=(
            "Coordinate a multi-service auth incident. Identify the bad auth rollout "
            "and the retry-induced session-cache saturation, roll back auth-service, "
            "add cache capacity, communicate status, and resolve only after downstream "
            "services stabilize."
        ),
        narrative=(
            "A new auth release broke token signing. Clients are retrying, the "
            "session cache is saturating, and api-gateway is timing out on auth."
        ),
        max_steps=10,
        services={
            "auth-service": ServiceRuntime(
                name="auth-service",
                status="failing",
                release="2026.04.06.1",
                stable_release="2026.04.03.4",
                replicas=3,
                cpu_pct=89.0,
                error_rate=0.41,
                latency_ms=4100,
                summary="Auth is failing hard after the latest release and breaking token issuance.",
                log_lines=[
                    "Token signing key mismatch introduced in release 2026.04.06.1",
                    "JWT issuer regression causes 401 storms and downstream retries",
                ],
                runbook_steps=[
                    "If token signer regression is detected, rollback auth-service to 2026.04.03.4.",
                    "After rollback, confirm downstream retry pressure is receding.",
                ],
            ),
            "session-cache": ServiceRuntime(
                name="session-cache",
                status="degraded",
                release="2026.03.22.1",
                stable_release="2026.03.22.1",
                replicas=2,
                cpu_pct=78.0,
                error_rate=0.05,
                latency_ms=900,
                summary="Session cache is saturated by auth retry traffic and eviction churn.",
                log_lines=[
                    "evictions surged due to auth retry storm",
                    "cache saturation above 85% while auth retries fan out",
                ],
                runbook_steps=[
                    "If auth retry storm saturates cache, scale session-cache to at least 4 replicas.",
                    "Do not resolve the incident until downstream latency recovers.",
                ],
            ),
            "api-gateway": ServiceRuntime(
                name="api-gateway",
                status="degraded",
                release="2026.04.02.9",
                stable_release="2026.04.02.9",
                replicas=6,
                cpu_pct=74.0,
                error_rate=0.19,
                latency_ms=2500,
                summary="Gateway latency is elevated because auth-service is timing out upstream.",
                log_lines=[
                    "upstream auth-service timeout from /session/refresh",
                ],
                runbook_steps=[
                    "api-gateway is downstream. Fix auth and cache pressure before restarting gateway.",
                ],
            ),
        },
        alerts=[
            AlertRuntime(
                alert_id="ALERT-AUTH-500",
                service="auth-service",
                severity="critical",
                title="Auth 5xx spike",
                description="auth-service 5xx error rate exceeded 40% after release 2026.04.06.1.",
            ),
            AlertRuntime(
                alert_id="ALERT-GW-121",
                service="api-gateway",
                severity="high",
                title="Gateway auth upstream timeouts",
                description="api-gateway timeout rate exceeds 18% on auth-dependent routes.",
            ),
            AlertRuntime(
                alert_id="ALERT-CACHE-77",
                service="session-cache",
                severity="medium",
                title="Session cache saturation",
                description="session-cache saturation above 85% with elevated eviction churn.",
            ),
        ],
        recommended_focus=[
            "auth-service release health",
            "session-cache capacity",
            "downstream gateway impact",
        ],
        grader=grader,
    )


TASK_ORDER = (
    "payments_worker_backlog",
    "checkout_flag_regression",
    "auth_token_rollover_cascade",
)

TASK_SPECS = {
    spec.task_id: spec
    for spec in (
        _payments_worker_backlog(),
        _checkout_flag_regression(),
        _auth_token_rollover_cascade(),
    )
}


def list_task_specs() -> dict[str, TaskSpec]:
    """Return the immutable task catalog."""

    return TASK_SPECS


def initialize_runtime(task_id: str) -> EpisodeRuntime:
    """Create a fresh episode runtime from a task id."""

    if task_id not in TASK_SPECS:
        raise ValueError(
            f"Unknown task_id '{task_id}'. Available tasks: {', '.join(TASK_ORDER)}"
        )

    spec = TASK_SPECS[task_id]
    runtime = EpisodeRuntime(
        spec=spec,
        services=deepcopy(spec.services),
        alerts={alert.alert_id: deepcopy(alert) for alert in spec.alerts},
    )
    runtime.last_action_result = (
        "Incident room ready. Start with list_alerts(), then inspect the affected services."
    )
    runtime.final_score = 0.0
    return runtime


def render_action_signature(action: object) -> str:
    """Create a compact string signature for loop detection and state exposure."""

    action_type = getattr(action, "action_type", "unknown")
    service = getattr(action, "service", None)
    flag_name = getattr(action, "flag_name", None)
    enabled = getattr(action, "enabled", None)
    target_instances = getattr(action, "target_instances", None)
    release = getattr(action, "release", None)
    message = getattr(action, "message", "") or ""

    parts = [action_type]
    if service:
        parts.append(f"service={service}")
    if flag_name:
        parts.append(f"flag={flag_name}")
    if enabled is not None:
        parts.append(f"enabled={enabled}")
    if target_instances is not None:
        parts.append(f"target_instances={target_instances}")
    if release:
        parts.append(f"release={release}")
    if message:
        compact = " ".join(message.split())
        parts.append(f"message={compact[:48]}")
    return "|".join(parts)


def active_alerts(runtime: EpisodeRuntime) -> list[AlertRuntime]:
    """Return the still-firing alerts."""

    return [alert for alert in runtime.alerts.values() if alert.status == "firing"]


def current_score(runtime: EpisodeRuntime) -> float:
    """Return the current deterministic grader score."""

    return runtime.spec.grader.score(runtime)


def completed_titles(runtime: EpisodeRuntime) -> list[str]:
    """Return completed milestone titles."""

    return runtime.spec.grader.completed_titles(runtime)


def remaining_titles(runtime: EpisodeRuntime) -> list[str]:
    """Return remaining milestone titles."""

    return runtime.spec.grader.remaining_titles(runtime)


def recommended_focus(runtime: EpisodeRuntime) -> list[str]:
    """Return lightweight guidance derived from the current incident state."""

    focus: list[str] = []
    if active_alerts(runtime):
        focus.extend(alert.service for alert in active_alerts(runtime))

    task_id = runtime.spec.task_id
    if task_id == "payments_worker_backlog" and "worker_restarted" not in runtime.completed_milestones:
        focus.append("Restart payments-worker after evidence confirms the deadlock.")
    elif task_id == "checkout_flag_regression" and "flag_disabled" not in runtime.completed_milestones:
        focus.append("Disable reco_shadow_launch on checkout-api once evidence lines up.")
    elif task_id == "auth_token_rollover_cascade":
        if "auth_rolled_back" not in runtime.completed_milestones:
            focus.append("Rollback auth-service to the stable release.")
        if "cache_scaled" not in runtime.completed_milestones:
            focus.append("Scale session-cache to at least 4 replicas.")

    if "status_update_sent" not in runtime.completed_milestones:
        focus.append("Send a brief external status update before resolution.")
    if runtime.incident_status == "mitigated":
        focus.append("Resolve the incident only after confirming all alerts are cleared.")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in focus:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered[:4]


def build_summary(runtime: EpisodeRuntime) -> str:
    """Build a compact natural-language briefing for the current state."""

    firing = active_alerts(runtime)
    if firing:
        alert_summary = ", ".join(f"{alert.service}:{alert.severity}" for alert in firing)
    else:
        alert_summary = "no active alerts"

    service_summary = ", ".join(
        f"{service.name}={service.status}"
        for service in sorted(runtime.services.values(), key=lambda item: item.name)
    )
    return (
        f"{runtime.spec.narrative} Current status: {runtime.incident_status}. "
        f"Active alerts: {alert_summary}. Services: {service_summary}."
    )


def _record_finding(runtime: EpisodeRuntime, finding: str) -> None:
    if finding not in runtime.findings:
        runtime.findings.append(finding)


def _mark(runtime: EpisodeRuntime, milestone: str) -> None:
    runtime.completed_milestones.add(milestone)


def _apply_penalty(
    runtime: EpisodeRuntime,
    reason: str,
    amount: float = 0.05,
) -> None:
    runtime.penalty_total += amount
    runtime.penalties.append(reason)


def _get_service(runtime: EpisodeRuntime, service_name: str | None) -> ServiceRuntime:
    if not service_name:
        raise ValueError("service is required for this action")
    if service_name not in runtime.services:
        raise ValueError(
            f"Unknown service '{service_name}'. Available services: {', '.join(sorted(runtime.services))}"
        )
    return runtime.services[service_name]


def _clear_alerts_for_service(runtime: EpisodeRuntime, service_name: str) -> None:
    for alert in runtime.alerts.values():
        if alert.service == service_name:
            alert.status = "cleared"


def _set_alert_state(runtime: EpisodeRuntime, service_name: str, firing: bool) -> None:
    for alert in runtime.alerts.values():
        if alert.service == service_name:
            alert.status = "firing" if firing else "cleared"


def _sync_runtime(runtime: EpisodeRuntime) -> None:
    if runtime.incident_status in {"resolved", "timeout"}:
        return

    task_id = runtime.spec.task_id

    if task_id == "payments_worker_backlog":
        worker = runtime.services["payments-worker"]
        if worker.restart_applied:
            worker.status = "healthy"
            worker.cpu_pct = 34.0
            worker.error_rate = 0.01
            worker.latency_ms = 420
            worker.summary = "Worker pool restarted successfully; the backlog is draining."
            _clear_alerts_for_service(runtime, "payments-worker")
            runtime.incident_status = "mitigated"
        else:
            worker.status = "failing"
            _set_alert_state(runtime, "payments-worker", True)

    elif task_id == "checkout_flag_regression":
        checkout = runtime.services["checkout-api"]
        flag_disabled = checkout.feature_flags.get("reco_shadow_launch") is False
        if flag_disabled:
            checkout.status = "healthy"
            checkout.cpu_pct = 44.0
            checkout.error_rate = 0.01
            checkout.latency_ms = 230
            checkout.summary = "Checkout recovered after disabling the bad experiment flag."
            _clear_alerts_for_service(runtime, "checkout-api")
            runtime.incident_status = "mitigated"
        else:
            checkout.status = "degraded"
            _set_alert_state(runtime, "checkout-api", True)

    elif task_id == "auth_token_rollover_cascade":
        auth = runtime.services["auth-service"]
        cache = runtime.services["session-cache"]
        gateway = runtime.services["api-gateway"]

        auth_fixed = auth.rollback_applied and auth.release == auth.stable_release
        cache_fixed = cache.scale_applied and cache.replicas >= 4

        if auth_fixed:
            auth.status = "healthy"
            auth.cpu_pct = 48.0
            auth.error_rate = 0.01
            auth.latency_ms = 280
            auth.summary = "Auth rolled back to the stable release and token issuance recovered."
            _clear_alerts_for_service(runtime, "auth-service")
        else:
            auth.status = "failing"
            _set_alert_state(runtime, "auth-service", True)

        if cache_fixed:
            cache.status = "healthy"
            cache.cpu_pct = 45.0
            cache.error_rate = 0.0
            cache.latency_ms = 110
            cache.summary = "Session-cache has enough headroom after the scale-out."
            _clear_alerts_for_service(runtime, "session-cache")
        else:
            cache.status = "degraded"
            _set_alert_state(runtime, "session-cache", True)

        if auth_fixed and cache_fixed:
            gateway.status = "healthy"
            gateway.cpu_pct = 39.0
            gateway.error_rate = 0.01
            gateway.latency_ms = 190
            gateway.summary = "Gateway latency recovered after auth and cache stabilization."
            _clear_alerts_for_service(runtime, "api-gateway")
            runtime.incident_status = "mitigated"
        else:
            gateway.status = "degraded"
            gateway.error_rate = 0.07 if auth_fixed else 0.19
            gateway.latency_ms = 1200 if auth_fixed else 2500
            _set_alert_state(runtime, "api-gateway", True)


def _resolution_ready(runtime: EpisodeRuntime) -> bool:
    if "status_update_sent" not in runtime.completed_milestones:
        return False

    task_id = runtime.spec.task_id
    if task_id == "payments_worker_backlog":
        return runtime.services["payments-worker"].restart_applied and not active_alerts(runtime)
    if task_id == "checkout_flag_regression":
        checkout = runtime.services["checkout-api"]
        return (
            checkout.feature_flags.get("reco_shadow_launch") is False
            and not active_alerts(runtime)
        )
    if task_id == "auth_token_rollover_cascade":
        auth = runtime.services["auth-service"]
        cache = runtime.services["session-cache"]
        return (
            auth.rollback_applied
            and auth.release == auth.stable_release
            and cache.scale_applied
            and cache.replicas >= 4
            and not active_alerts(runtime)
        )
    return False


def execute_action(runtime: EpisodeRuntime, action: object) -> None:
    """Mutate runtime in response to an action and record grader progress."""

    signature = render_action_signature(action)
    if len(runtime.action_history) >= 2 and runtime.action_history[-1] == signature and runtime.action_history[-2] == signature:
        _apply_penalty(runtime, "Repeated the same action three times in a row.", 0.03)

    runtime.action_history.append(signature)
    runtime.last_action_error = None

    action_type = getattr(action, "action_type", None)
    task_id = runtime.spec.task_id

    try:
        if action_type == "list_alerts":
            _mark(runtime, "alerts_reviewed")
            alerts = active_alerts(runtime)
            runtime.last_action_result = (
                "Active alerts: "
                + "; ".join(f"{alert.alert_id} {alert.service} {alert.severity}" for alert in alerts)
                if alerts
                else "No active alerts remain."
            )

        elif action_type == "inspect_service":
            service = _get_service(runtime, getattr(action, "service", None))
            service.inspected = True
            if task_id == "payments_worker_backlog" and service.name == "payments-worker":
                _mark(runtime, "worker_inspected")
            elif task_id == "checkout_flag_regression" and service.name == "checkout-api":
                _mark(runtime, "checkout_inspected")
            elif task_id == "auth_token_rollover_cascade":
                if service.name == "auth-service":
                    _mark(runtime, "auth_inspected")
                elif service.name == "session-cache":
                    _mark(runtime, "cache_inspected")
            runtime.last_action_result = (
                f"{service.name}: status={service.status}, release={service.release}, "
                f"replicas={service.replicas}. {service.summary}"
            )

        elif action_type == "query_metrics":
            service = _get_service(runtime, getattr(action, "service", None))
            service.metrics_checked = True
            if task_id == "payments_worker_backlog" and service.name == "payments-worker":
                _mark(runtime, "worker_metrics_checked")
            elif task_id == "checkout_flag_regression" and service.name == "checkout-api":
                _mark(runtime, "checkout_metrics_checked")
            elif task_id == "auth_token_rollover_cascade" and service.name == "session-cache":
                _mark(runtime, "cache_metrics_checked")

            runtime.last_action_result = (
                f"{service.name} metrics: cpu={service.cpu_pct:.1f}%, "
                f"error_rate={service.error_rate:.2f}, latency_ms={service.latency_ms}, "
                f"replicas={service.replicas}"
            )

        elif action_type == "query_logs":
            service = _get_service(runtime, getattr(action, "service", None))
            service.logs_checked = True
            if task_id == "payments_worker_backlog" and service.name == "payments-worker":
                _mark(runtime, "worker_logs_checked")
            elif task_id == "checkout_flag_regression" and service.name == "checkout-api":
                _mark(runtime, "checkout_logs_checked")
            elif task_id == "auth_token_rollover_cascade" and service.name == "auth-service":
                _mark(runtime, "auth_logs_checked")

            for line in service.log_lines:
                _record_finding(runtime, f"{service.name} log: {line}")

            runtime.last_action_result = (
                "Log evidence: " + " | ".join(service.log_lines[:2])
                if service.log_lines
                else f"No recent log anomalies found for {service.name}."
            )

        elif action_type == "read_runbook":
            service = _get_service(runtime, getattr(action, "service", None))
            service.runbook_checked = True
            if task_id == "payments_worker_backlog" and service.name == "payments-worker":
                _mark(runtime, "worker_runbook_checked")
            elif task_id == "checkout_flag_regression" and service.name == "checkout-api":
                _mark(runtime, "checkout_runbook_checked")
            elif task_id == "auth_token_rollover_cascade" and service.name == "auth-service":
                _mark(runtime, "auth_runbook_checked")

            for step in service.runbook_steps:
                _record_finding(runtime, f"{service.name} runbook: {step}")

            runtime.last_action_result = (
                "Runbook guidance: " + " | ".join(service.runbook_steps[:2])
                if service.runbook_steps
                else f"No runbook entry found for {service.name}."
            )

        elif action_type == "restart_service":
            service = _get_service(runtime, getattr(action, "service", None))
            service.restart_applied = True
            if task_id == "payments_worker_backlog" and service.name == "payments-worker":
                _mark(runtime, "worker_restarted")
                runtime.last_action_result = (
                    "payments-worker restarted. Queue depth should begin draining immediately."
                )
            else:
                _apply_penalty(
                    runtime,
                    f"Restarted {service.name} even though it was not the primary remediation.",
                )
                runtime.last_action_result = (
                    f"{service.name} restarted, but the underlying incident remains unresolved."
                )

        elif action_type == "scale_service":
            service = _get_service(runtime, getattr(action, "service", None))
            target_instances = getattr(action, "target_instances", None)
            if target_instances is None:
                raise ValueError("target_instances is required for scale_service")
            service.replicas = target_instances
            service.scale_applied = True
            if task_id == "auth_token_rollover_cascade" and service.name == "session-cache" and target_instances >= 4:
                _mark(runtime, "cache_scaled")
                runtime.last_action_result = (
                    f"session-cache scaled to {target_instances} replicas to absorb retry load."
                )
            elif task_id == "payments_worker_backlog" and service.name == "payments-worker":
                runtime.last_action_result = (
                    "payments-worker has more replicas, but the deadlock still needs a restart."
                )
            else:
                _apply_penalty(
                    runtime,
                    f"Scaled {service.name} without addressing the primary fault first.",
                )
                runtime.last_action_result = f"{service.name} scaled to {target_instances} replicas."

        elif action_type == "rollback_service":
            service = _get_service(runtime, getattr(action, "service", None))
            release = getattr(action, "release", None)
            if not release:
                raise ValueError("release is required for rollback_service")
            service.rollback_applied = True
            service.release = release
            if task_id == "auth_token_rollover_cascade" and service.name == "auth-service" and release == service.stable_release:
                _mark(runtime, "auth_rolled_back")
                runtime.last_action_result = (
                    f"auth-service rolled back to stable release {release}."
                )
            else:
                _apply_penalty(
                    runtime,
                    f"Rolled back {service.name} to {release}, which is not the recommended fix.",
                    0.08,
                )
                runtime.last_action_result = f"{service.name} rolled back to {release}."

        elif action_type == "toggle_feature_flag":
            service = _get_service(runtime, getattr(action, "service", None))
            flag_name = getattr(action, "flag_name", None)
            enabled = getattr(action, "enabled", None)
            if not flag_name:
                raise ValueError("flag_name is required for toggle_feature_flag")
            if enabled is None:
                raise ValueError("enabled is required for toggle_feature_flag")
            if flag_name not in service.feature_flags:
                raise ValueError(
                    f"Unknown flag '{flag_name}' for {service.name}. Known flags: {', '.join(sorted(service.feature_flags))}"
                )

            service.feature_flags[flag_name] = enabled
            if (
                task_id == "checkout_flag_regression"
                and service.name == "checkout-api"
                and flag_name == "reco_shadow_launch"
                and enabled is False
            ):
                _mark(runtime, "flag_disabled")
                runtime.last_action_result = (
                    "Disabled checkout-api flag reco_shadow_launch. Error rate should recover quickly."
                )
            else:
                _apply_penalty(
                    runtime,
                    f"Toggled {service.name}:{flag_name} to {enabled}, which did not address the root cause.",
                    0.08,
                )
                runtime.last_action_result = (
                    f"Set feature flag {service.name}:{flag_name} to {enabled}."
                )

        elif action_type == "post_status_update":
            message = (getattr(action, "message", "") or "").strip()
            if not message:
                raise ValueError("message is required for post_status_update")
            runtime.status_updates.append(message)
            _mark(runtime, "status_update_sent")
            runtime.last_action_result = (
                "External status update posted for stakeholders and customers."
            )

        elif action_type == "resolve_incident":
            if _resolution_ready(runtime):
                _mark(runtime, "incident_resolved")
                runtime.incident_status = "resolved"
                runtime.last_action_result = (
                    "Incident resolved. All required mitigation and communication steps are complete."
                )
            else:
                _apply_penalty(
                    runtime,
                    "Attempted to resolve the incident before the system was fully recovered.",
                )
                runtime.last_action_result = (
                    "Resolution blocked. Remaining work: "
                    + "; ".join(remaining_titles(runtime)[:3])
                )

        else:
            raise ValueError(
                "Unsupported action_type. Use one of: "
                + ", ".join(item.split("(")[0] for item in AVAILABLE_ACTIONS)
            )

    except ValueError as exc:
        runtime.last_action_error = str(exc)
        runtime.last_action_result = "Action validation failed."
        _apply_penalty(runtime, f"Invalid action: {exc}", 0.04)

    _sync_runtime(runtime)
    runtime.final_score = current_score(runtime)
