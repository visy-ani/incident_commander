---
title: Incident Commander Environment Server
emoji: "🚨"
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
  - incident-response
  - operations
  - real-world
---

# Incident Commander

Incident Commander is an OpenEnv benchmark for **real production incident response**, not a toy workflow.

The agent plays the role of an on-call incident commander responsible for triaging alerts, inspecting services, checking logs and runbooks, applying the right mitigation, posting stakeholder updates, and resolving the incident only after the system is actually healthy again.

It is designed to score well against the hackathon rubric:

- **Real-world utility**: incident response is a real operational task humans do every day.
- **Deterministic graders**: each task uses a milestone-based grader that returns scores in `[0.0, 1.0]`.
- **Reward shaping**: the environment emits partial reward for evidence gathering and correct mitigations, while harmful or looping actions reduce the achievable final score.
- **OpenEnv compliance**: typed models, `reset()`, `step()`, `state`, `openenv.yaml`, Dockerfile, Hugging Face deployment path, and a validator-friendly repo layout.

## Why this environment exists

Many agent benchmarks stop at static QA or single-action tool use. Real incident response is harder:

- information is incomplete at the start
- multiple services can be involved
- the correct action depends on evidence, not guesswork
- premature resolution is a failure
- communication matters, not just mitigation

Incident Commander makes those tradeoffs explicit while staying lightweight enough for `vcpu=2` and `8GB` memory.

## Architecture

The environment is intentionally simple to run but structured enough to model a realistic incident workflow.

### Main components

| Component | File | Responsibility |
|---|---|---|
| Typed schemas | `models.py` | Defines `IncidentCommanderAction`, `IncidentCommanderObservation`, and `IncidentCommanderState` |
| HTTP/WebSocket app | `server/app.py` | Exposes the OpenEnv server with `create_app(...)` |
| Environment runtime | `server/incident_commander_environment.py` | Implements `reset()`, `step()`, and `state` |
| Scenario engine | `server/scenarios.py` | Holds the deterministic task data, service state transitions, graders, and penalties |
| Client | `client.py` | Typed `EnvClient` wrapper for local, Docker, and remote use |
| Baseline runner | `inference.py` | Runs the benchmark across all three tasks with structured logs |

### Execution flow

1. `reset(task_id=...)` initializes a fresh task runtime from `server/scenarios.py`
2. The runtime exposes a task briefing, active alerts, service health, and remaining milestones
3. Each `step(action)` sends one typed action into the environment
4. The scenario engine validates the action and mutates the internal service state
5. The grader recomputes milestone completion, penalties, score delta, and terminal state
6. The observation returned to the agent includes both operational state and grader progress
7. `resolve_incident` only succeeds once remediation, alert clearance, and status communication are all complete

### Trajectory flow

```text
inference.py / agent
        |
        v
   client.py (EnvClient)
        |
        v
FastAPI OpenEnv server
        |
        v
IncidentCommanderEnvironment.step()
        |
        v
execute_action() in server/scenarios.py
        |
        +--> validate action
        +--> update service state
        +--> update alerts
        +--> update milestones
        +--> apply penalties
        |
        v
score + reward delta + done
        |
        v
typed observation returned to the agent
```

## Tasks

The environment ships with three deterministic tasks.

| Task ID | Difficulty | Scenario | Correct core remediation |
|---|---|---|---|
| `payments_worker_backlog` | Easy | A deadlocked background worker causes a payment settlement queue backlog. | Restart `payments-worker` after confirming deadlock evidence. |
| `checkout_flag_regression` | Medium | A bad experiment flag breaks checkout requests. | Disable `checkout-api:reco_shadow_launch`. |
| `auth_token_rollover_cascade` | Hard | A faulty auth rollout plus retry pressure causes a multi-service cascade. | Roll back `auth-service` and scale `session-cache` to at least 4 replicas. |

Each task requires the agent to:

1. inspect the right evidence
2. apply the right mitigation
3. send a status update
4. resolve only after alerts are cleared

## Graders and reward

Each task has a deterministic milestone-based grader implemented in `server/scenarios.py`.

### Final score

Final score is always clipped to `[0.0, 1.0]`:

`score = sum(completed_milestone_weights) - penalties`

### Partial reward

Per-step reward is the **score delta** after each action:

- checking the right logs or metrics gives small progress reward
- applying the correct remediation gives larger reward
- looping or harmful actions can produce negative reward and reduce the final achievable score

This keeps the step signal meaningful without turning the environment into a sparse binary benchmark.

## Action space

The environment uses a typed `IncidentCommanderAction` model with these action types:

| Action | Required fields | Purpose |
|---|---|---|
| `list_alerts` | none | Review the current alert feed |
| `inspect_service` | `service` | Inspect a service summary |
| `query_metrics` | `service` | Read service metrics |
| `query_logs` | `service` | Read log evidence |
| `read_runbook` | `service` | Read mitigation guidance |
| `restart_service` | `service` | Restart a service |
| `scale_service` | `service`, `target_instances` | Increase capacity |
| `rollback_service` | `service`, `release` | Roll back a release |
| `toggle_feature_flag` | `service`, `flag_name`, `enabled` | Toggle a feature flag |
| `post_status_update` | `message` | Send a stakeholder/customer update |
| `resolve_incident` | `message` | Attempt incident resolution |

## Observation space

The typed `IncidentCommanderObservation` includes:

- `task_id`, `task_title`, `difficulty`, `objective`
- `incident_status`
- `situation_summary`
- `active_alerts`
- `service_statuses`
- `recent_findings`
- `completed_milestones`
- `remaining_milestones`
- `recommended_focus`
- `last_action_result`
- `last_action_error`
- `partial_score`
- `final_score`
- `remaining_steps`

The state endpoint exposes the matching `IncidentCommanderState` model with episode metadata, penalties, and milestone progress.

## Quick start

### 1. Install dependencies

```bash
cd incident_commander
uv sync
```

If your local Homebrew `uv` build crashes while locking on macOS, generate the
lockfile inside Docker instead:

```bash
docker run --rm -v "$PWD":/work -w /work \
  ghcr.io/astral-sh/uv:0.9.27-python3.11-bookworm \
  uv lock
```

### 2. Run the server locally

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### 3. Run a direct client session

```python
from client import IncidentCommanderEnv
from models import IncidentCommanderAction

env = IncidentCommanderEnv(base_url="http://localhost:8000").sync()

with env:
    result = env.reset(task_id="payments_worker_backlog")
    print(result.observation.situation_summary)

    result = env.step(IncidentCommanderAction(action_type="list_alerts"))
    print(result.observation.last_action_result)

    result = env.step(
        IncidentCommanderAction(
            action_type="inspect_service",
            service="payments-worker",
        )
    )
    print(result.observation.partial_score)
```

## Docker

Build the local image expected by `inference.py`:

```bash
docker build -t incident-commander-env:latest .
```

Run it:

```bash
docker run --rm -p 8000:8000 incident-commander-env:latest
```

Health check:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/reset -H 'Content-Type: application/json' -d '{"task_id":"payments_worker_backlog"}'
```

## Baseline inference

The required baseline script is `inference.py`.

It supports two modes:

1. **Official LLM mode**: uses the OpenAI client with `HF_TOKEN`, `API_BASE_URL`, and `MODEL_NAME`
2. **Local scripted sanity mode**: automatically used when no API key is present or when `INCIDENT_COMMANDER_USE_SCRIPTED_BASELINE=1`

### Environment variables

```bash
export API_BASE_URL="https://router.huggingface.co/v1"
export MODEL_NAME="Qwen/Qwen2.5-72B-Instruct"
export HF_TOKEN="..."
export LOCAL_IMAGE_NAME="incident-commander-env:latest"
```

### Run the official baseline

```bash
python inference.py
```

### Connect to an already running server instead of starting Docker

```bash
export INCIDENT_COMMANDER_ENV_URL="http://localhost:8000"
python inference.py
```

## Baseline scores

Local deterministic scripted fallback baseline:

| Planner | Easy | Medium | Hard | Average |
|---|---:|---:|---:|---:|
| Scripted fallback | 1.00 | 1.00 | 1.00 | 1.00 |

The official submission path is still the LLM-based `inference.py` run with `HF_TOKEN`, `API_BASE_URL`, and `MODEL_NAME`.

### What the successful trajectories look like

- Easy task: review alerts, inspect `payments-worker`, gather evidence, restart it, post an update, resolve
- Medium task: review alerts, inspect `checkout-api`, confirm the experiment regression, disable the bad flag, post an update, resolve
- Hard task: inspect both `auth-service` and `session-cache`, rollback auth, scale cache, post an update, resolve only after all alerts clear

## Validation

### OpenEnv validation

```bash
openenv validate
```

### Pytest

```bash
pytest tests/test_incident_commander.py -q
```

### Organizer-style pre-validation

The repo includes the validator wrapper at `pre-validation.py`.

Example:

```bash
bash pre-validation.py https://your-space.hf.space .
```

## Hugging Face Spaces deployment

After validating locally:

```bash
openenv push --repo-id <your-namespace>/incident-commander
```

The root `Dockerfile` is intentionally validator-friendly so:

- `docker build .` works
- `openenv validate` works
- Hugging Face Docker Spaces can build from repo root

## Project structure

```text
incident_commander/
├── __init__.py
├── client.py
├── models.py
├── openenv.yaml
├── pyproject.toml
├── Dockerfile
├── inference.py
├── pre-validation.py
├── per-validation.py
├── README.md
├── outputs/
├── server/
│   ├── __init__.py
│   ├── app.py
│   ├── incident_commander_environment.py
│   └── scenarios.py
└── tests/
    └── test_incident_commander.py
```
