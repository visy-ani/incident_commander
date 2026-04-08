"""Direct environment tests for Incident Commander."""

from server.incident_commander_environment import IncidentCommanderEnvironment
from models import IncidentCommanderAction


def test_easy_task_reaches_perfect_score():
    env = IncidentCommanderEnvironment()
    env.reset(task_id="payments_worker_backlog")

    actions = [
        IncidentCommanderAction(action_type="list_alerts"),
        IncidentCommanderAction(action_type="inspect_service", service="payments-worker"),
        IncidentCommanderAction(action_type="query_metrics", service="payments-worker"),
        IncidentCommanderAction(action_type="query_logs", service="payments-worker"),
        IncidentCommanderAction(action_type="read_runbook", service="payments-worker"),
        IncidentCommanderAction(action_type="restart_service", service="payments-worker"),
        IncidentCommanderAction(
            action_type="post_status_update",
            message="Investigating payment settlement delays. Worker restart is in progress.",
        ),
        IncidentCommanderAction(
            action_type="resolve_incident",
            message="payments-worker recovered and the queue is draining normally.",
        ),
    ]

    result = None
    for action in actions:
        result = env.step(action)

    assert result is not None
    assert result.done is True
    assert result.final_score == 0.999


def test_medium_task_penalizes_wrong_remediation():
    env = IncidentCommanderEnvironment()
    env.reset(task_id="checkout_flag_regression")

    env.step(
        IncidentCommanderAction(
            action_type="rollback_service",
            service="cart-api",
            release="2026.04.01.0",
        )
    )
    state = env.state

    assert state.partial_score == 0.0
    assert state.penalties


def test_hard_task_requires_two_remediations():
    env = IncidentCommanderEnvironment()
    env.reset(task_id="auth_token_rollover_cascade")

    actions = [
        IncidentCommanderAction(action_type="list_alerts"),
        IncidentCommanderAction(action_type="inspect_service", service="auth-service"),
        IncidentCommanderAction(action_type="query_logs", service="auth-service"),
        IncidentCommanderAction(action_type="read_runbook", service="auth-service"),
        IncidentCommanderAction(action_type="inspect_service", service="session-cache"),
        IncidentCommanderAction(action_type="query_metrics", service="session-cache"),
        IncidentCommanderAction(
            action_type="rollback_service",
            service="auth-service",
            release="2026.04.03.4",
        ),
        IncidentCommanderAction(
            action_type="scale_service",
            service="session-cache",
            target_instances=4,
        ),
        IncidentCommanderAction(
            action_type="post_status_update",
            message="Auth rollback is complete and cache capacity has been increased. Monitoring recovery.",
        ),
        IncidentCommanderAction(
            action_type="resolve_incident",
            message="Auth, cache, and downstream gateway latency have recovered.",
        ),
    ]

    result = None
    for action in actions:
        result = env.step(action)

    assert result is not None
    assert result.done is True
    assert result.final_score == 0.999
