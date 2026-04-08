"""Incident Commander OpenEnv client."""

from __future__ import annotations

from typing import Any

from openenv.core.client_types import StepResult
from openenv.core.env_client import EnvClient

try:
    from .models import (
        IncidentCommanderAction,
        IncidentCommanderObservation,
        IncidentCommanderState,
    )
except ImportError:
    from models import (
        IncidentCommanderAction,
        IncidentCommanderObservation,
        IncidentCommanderState,
    )


class IncidentCommanderEnv(
    EnvClient[
        IncidentCommanderAction,
        IncidentCommanderObservation,
        IncidentCommanderState,
    ]
):
    """Typed client for the Incident Commander environment."""

    def _step_payload(self, action: IncidentCommanderAction) -> dict[str, Any]:
        return action.model_dump(exclude_none=True, exclude_defaults=True)

    def _parse_result(
        self,
        payload: dict[str, Any],
    ) -> StepResult[IncidentCommanderObservation]:
        observation = IncidentCommanderObservation(**payload.get("observation", {}))
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: dict[str, Any]) -> IncidentCommanderState:
        return IncidentCommanderState(**payload)
