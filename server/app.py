"""FastAPI app for the Incident Commander environment."""

try:
    from openenv.core.env_server.http_server import create_app
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "openenv is required to run Incident Commander. Install dependencies with `uv sync`."
    ) from exc

try:
    from ..models import IncidentCommanderAction, IncidentCommanderObservation
    from .incident_commander_environment import IncidentCommanderEnvironment
except ImportError:
    from models import IncidentCommanderAction, IncidentCommanderObservation
    from server.incident_commander_environment import IncidentCommanderEnvironment


app = create_app(
    IncidentCommanderEnvironment,
    IncidentCommanderAction,
    IncidentCommanderObservation,
    env_name="incident_commander",
    max_concurrent_envs=1,
)


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Local entry point used by `uv run server` and container startup."""

    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
