"""Core Incident Commander environment implementation."""

from __future__ import annotations

from uuid import uuid4

from openenv.core.env_server.interfaces import Environment

try:
    from ..models import (
        IncidentAlert,
        IncidentCommanderAction,
        IncidentCommanderObservation,
        IncidentCommanderState,
        ServiceStatus,
    )
    from .scenarios import (
        AVAILABLE_ACTIONS,
        TASK_ORDER,
        active_alerts,
        build_summary,
        completed_titles,
        current_score,
        execute_action,
        initialize_runtime,
        recommended_focus,
        remaining_titles,
        render_action_signature,
    )
except ImportError:
    from models import (
        IncidentAlert,
        IncidentCommanderAction,
        IncidentCommanderObservation,
        IncidentCommanderState,
        ServiceStatus,
    )
    from server.scenarios import (
        AVAILABLE_ACTIONS,
        TASK_ORDER,
        active_alerts,
        build_summary,
        completed_titles,
        current_score,
        execute_action,
        initialize_runtime,
        recommended_focus,
        remaining_titles,
        render_action_signature,
    )


class IncidentCommanderEnvironment(
    Environment[
        IncidentCommanderAction,
        IncidentCommanderObservation,
        IncidentCommanderState,
    ]
):
    """Simulates real-world incident commander workflows across three tasks."""

    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    def __init__(self, default_task_id: str = TASK_ORDER[0]) -> None:
        super().__init__()
        self.default_task_id = default_task_id
        self._runtime = None
        self._state = IncidentCommanderState(
            episode_id=str(uuid4()),
            step_count=0,
        )

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        **kwargs,
    ) -> IncidentCommanderObservation:
        del seed

        task_id = kwargs.get("task_id", self.default_task_id)
        self._runtime = initialize_runtime(task_id)
        self._state = IncidentCommanderState(
            episode_id=episode_id or str(uuid4()),
            step_count=0,
            task_id=self._runtime.spec.task_id,
            task_title=self._runtime.spec.title,
            difficulty=self._runtime.spec.difficulty,
            incident_status=self._runtime.incident_status,
            max_steps=self._runtime.spec.max_steps,
            timeline_min=0,
            partial_score=0.0,
            final_score=0.0,
            completed_milestones=[],
            remaining_milestones=remaining_titles(self._runtime),
            penalties=[],
            last_action="reset",
            last_action_error=None,
            status_updates_sent=0,
        )
        return self._build_observation(reward=0.0, done=False)

    def step(  # type: ignore[override]
        self,
        action: IncidentCommanderAction,
        timeout_s: float | None = None,
        **kwargs,
    ) -> IncidentCommanderObservation:
        del timeout_s, kwargs

        if self._runtime is None:
            return self.reset()

        previous_score = current_score(self._runtime)
        self._state.step_count += 1
        self._runtime.timeline_min += 5

        execute_action(self._runtime, action)

        score = current_score(self._runtime)
        reward = round(score - previous_score, 4)

        done = False
        if self._runtime.incident_status == "resolved":
            done = True
        elif self._state.step_count >= self._runtime.spec.max_steps:
            self._runtime.incident_status = "timeout"
            self._runtime.last_action_result = (
                "Step budget exhausted before full resolution. Incident timed out."
            )
            done = True

        self._runtime.final_score = score
        self._state = IncidentCommanderState(
            episode_id=self._state.episode_id,
            step_count=self._state.step_count,
            task_id=self._runtime.spec.task_id,
            task_title=self._runtime.spec.title,
            difficulty=self._runtime.spec.difficulty,
            incident_status=self._runtime.incident_status,
            max_steps=self._runtime.spec.max_steps,
            timeline_min=self._runtime.timeline_min,
            partial_score=score,
            final_score=score if done else 0.0,
            completed_milestones=completed_titles(self._runtime),
            remaining_milestones=remaining_titles(self._runtime),
            penalties=list(self._runtime.penalties),
            last_action=render_action_signature(action),
            last_action_error=self._runtime.last_action_error,
            status_updates_sent=len(self._runtime.status_updates),
        )
        return self._build_observation(reward=reward, done=done)

    def _build_observation(
        self,
        reward: float,
        done: bool,
    ) -> IncidentCommanderObservation:
        assert self._runtime is not None
        firing_alerts = [
            IncidentAlert(
                alert_id=alert.alert_id,
                service=alert.service,
                severity=alert.severity,
                title=alert.title,
                description=alert.description,
                status=alert.status,
            )
            for alert in active_alerts(self._runtime)
        ]
        service_snapshots = [
            ServiceStatus(
                name=service.name,
                status=service.status,
                release=service.release,
                replicas=service.replicas,
                cpu_pct=service.cpu_pct,
                error_rate=service.error_rate,
                latency_ms=service.latency_ms,
                summary=service.summary,
                feature_flags=dict(service.feature_flags),
            )
            for service in sorted(self._runtime.services.values(), key=lambda item: item.name)
        ]

        score = current_score(self._runtime)
        return IncidentCommanderObservation(
            task_id=self._runtime.spec.task_id,
            task_title=self._runtime.spec.title,
            difficulty=self._runtime.spec.difficulty,
            objective=self._runtime.spec.objective,
            incident_status=self._runtime.incident_status,
            situation_summary=build_summary(self._runtime),
            active_alerts=firing_alerts,
            service_statuses=service_snapshots,
            recent_findings=self._runtime.findings[-5:],
            completed_milestones=completed_titles(self._runtime),
            remaining_milestones=remaining_titles(self._runtime),
            available_actions=list(AVAILABLE_ACTIONS),
            recommended_focus=recommended_focus(self._runtime),
            last_action_result=self._runtime.last_action_result,
            last_action_error=self._runtime.last_action_error,
            partial_score=score,
            final_score=score if done else None,
            remaining_steps=max(self._runtime.spec.max_steps - self._state.step_count, 0),
            done=done,
            reward=reward,
            metadata={
                "penalties": list(self._runtime.penalties),
                "status_updates": list(self._runtime.status_updates),
                "timeline_min": self._runtime.timeline_min,
            },
        )

    @property
    def state(self) -> IncidentCommanderState:
        return self._state
