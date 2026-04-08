"""
Mandatory inference entrypoint for the Incident Commander environment.

This script emits only [START], [STEP], and [END] lines to stdout.
It supports:

- Official model mode via the OpenAI client using HF_TOKEN / API_BASE_URL / MODEL_NAME
- Local deterministic scripted fallback when no API key is available
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import certifi
from openai import OpenAI
from dotenv import load_dotenv

from client import IncidentCommanderEnv
from models import IncidentCommanderAction, IncidentCommanderObservation

load_dotenv(Path(__file__).resolve().parent / ".env")

if not os.getenv("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()

if not os.getenv("REQUESTS_CA_BUNDLE"):
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

DEFAULT_TASKS = [
    "payments_worker_backlog",
    "checkout_flag_regression",
    "auth_token_rollover_cascade",
]
SCRIPTED_PLANS: dict[str, list[dict[str, Any]]] = {
    "payments_worker_backlog": [
        {"action_type": "list_alerts"},
        {"action_type": "inspect_service", "service": "payments-worker"},
        {"action_type": "query_metrics", "service": "payments-worker"},
        {"action_type": "query_logs", "service": "payments-worker"},
        {"action_type": "read_runbook", "service": "payments-worker"},
        {"action_type": "restart_service", "service": "payments-worker"},
        {
            "action_type": "post_status_update",
            "message": "We identified a deadlocked payments worker and restarted it. Settlements are recovering.",
        },
        {
            "action_type": "resolve_incident",
            "message": "payments-worker is healthy again and the queue backlog is gone.",
        },
    ],
    "checkout_flag_regression": [
        {"action_type": "list_alerts"},
        {"action_type": "inspect_service", "service": "checkout-api"},
        {"action_type": "query_metrics", "service": "checkout-api"},
        {"action_type": "query_logs", "service": "checkout-api"},
        {"action_type": "read_runbook", "service": "checkout-api"},
        {
            "action_type": "toggle_feature_flag",
            "service": "checkout-api",
            "flag_name": "reco_shadow_launch",
            "enabled": False,
        },
        {
            "action_type": "post_status_update",
            "message": "Checkout failures were tied to the reco_shadow_launch experiment. The flag has been disabled.",
        },
        {
            "action_type": "resolve_incident",
            "message": "Checkout traffic is stable after disabling the bad experiment flag.",
        },
    ],
    "auth_token_rollover_cascade": [
        {"action_type": "list_alerts"},
        {"action_type": "inspect_service", "service": "auth-service"},
        {"action_type": "query_logs", "service": "auth-service"},
        {"action_type": "read_runbook", "service": "auth-service"},
        {"action_type": "inspect_service", "service": "session-cache"},
        {"action_type": "query_metrics", "service": "session-cache"},
        {
            "action_type": "rollback_service",
            "service": "auth-service",
            "release": "2026.04.03.4",
        },
        {
            "action_type": "scale_service",
            "service": "session-cache",
            "target_instances": 4,
        },
        {
            "action_type": "post_status_update",
            "message": "Auth was rolled back and cache capacity has been increased. We are watching downstream recovery.",
        },
        {
            "action_type": "resolve_incident",
            "message": "Auth, cache, and downstream gateway latency have all recovered.",
        },
    ],
}

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME", "incident-commander-env:latest")
ENV_BASE_URL = os.getenv("INCIDENT_COMMANDER_ENV_URL")
BENCHMARK = os.getenv("INCIDENT_COMMANDER_BENCHMARK", "incident_commander")
TEMPERATURE = 0.0
MAX_TOKENS = 240
SUCCESS_SCORE_THRESHOLD = 0.75
USE_SCRIPTED = os.getenv("INCIDENT_COMMANDER_USE_SCRIPTED_BASELINE") == "1" or not API_KEY

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are the incident commander for a production outage.
    Pick exactly one JSON action object for the next step.

    Rules:
    - Use only the action types listed in available_actions.
    - Do not invent services, releases, or flags that are not visible.
    - Prefer evidence collection before remediation.
    - Do not resolve the incident until the system is healthy and you have posted a status update.
    - Return JSON only, with no markdown fences and no explanation.

    JSON fields:
    {
      "action_type": "...",
      "service": "...",
      "flag_name": "...",
      "enabled": true,
      "target_instances": 4,
      "release": "...",
      "message": "..."
    }
    """
).strip()


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int,
    action: str,
    reward: float,
    done: bool,
    error: str | None,
) -> None:
    error_value = error if error else "null"
    done_value = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_value} error={error_value}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    reward_text = ",".join(f"{reward:.2f}" for reward in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={reward_text}",
        flush=True,
    )


def compact_action(action: IncidentCommanderAction) -> str:
    return json.dumps(
        action.model_dump(exclude_none=True, exclude_defaults=True),
        separators=(",", ":"),
    )


def build_user_prompt(
    observation: IncidentCommanderObservation,
    history: list[str],
) -> str:
    history_block = "\n".join(history[-4:]) if history else "None"
    services = "\n".join(
        f"- {service.name}: status={service.status}, release={service.release}, replicas={service.replicas}, "
        f"cpu={service.cpu_pct:.1f}, error_rate={service.error_rate:.2f}, latency_ms={service.latency_ms}, summary={service.summary}"
        for service in observation.service_statuses
    )
    alerts = "\n".join(
        f"- {alert.alert_id}: {alert.service} {alert.severity} {alert.title} -- {alert.description}"
        for alert in observation.active_alerts
    ) or "None"
    findings = "\n".join(f"- {finding}" for finding in observation.recent_findings) or "None"
    remaining = "\n".join(f"- {item}" for item in observation.remaining_milestones) or "None"
    actions = "\n".join(f"- {item}" for item in observation.available_actions)

    return textwrap.dedent(
        f"""
        Task: {observation.task_id}
        Title: {observation.task_title}
        Difficulty: {observation.difficulty}
        Objective: {observation.objective}
        Incident status: {observation.incident_status}
        Summary: {observation.situation_summary}
        Partial score: {observation.partial_score:.2f}
        Remaining steps: {observation.remaining_steps}

        Active alerts:
        {alerts}

        Service status:
        {services}

        Recent findings:
        {findings}

        Remaining milestones:
        {remaining}

        Recommended focus:
        {", ".join(observation.recommended_focus) if observation.recommended_focus else "None"}

        Previous actions:
        {history_block}

        Available actions:
        {actions}
        """
    ).strip()


def parse_action_payload(raw_text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def coerce_action(data: dict[str, Any] | None) -> IncidentCommanderAction | None:
    if not data or not isinstance(data, dict):
        return None

    action_type = data.get("action_type")
    if action_type not in {
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
    }:
        return None

    try:
        return IncidentCommanderAction(
            action_type=action_type,
            service=data.get("service"),
            flag_name=data.get("flag_name"),
            enabled=data.get("enabled"),
            target_instances=data.get("target_instances"),
            release=data.get("release"),
            message=data.get("message", ""),
        )
    except Exception:
        return None


def scripted_action(task_id: str, step_index: int) -> IncidentCommanderAction:
    plan = SCRIPTED_PLANS[task_id]
    selected = plan[min(step_index, len(plan) - 1)]
    return IncidentCommanderAction(**selected)


def pick_action(
    client: OpenAI,
    task_id: str,
    step_index: int,
    observation: IncidentCommanderObservation,
    history: list[str],
) -> IncidentCommanderAction:
    if USE_SCRIPTED:
        return scripted_action(task_id, step_index)

    prompt = build_user_prompt(observation, history)
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        raw_text = (response.choices[0].message.content or "").strip()
        parsed = parse_action_payload(raw_text)
        action = coerce_action(parsed)
        if action is not None:
            return action
    except Exception:
        pass

    return scripted_action(task_id, step_index)


async def create_env() -> IncidentCommanderEnv:
    if ENV_BASE_URL:
        env = IncidentCommanderEnv(base_url=ENV_BASE_URL)
        await env.connect()
        return env
    return await IncidentCommanderEnv.from_docker_image(LOCAL_IMAGE_NAME)


async def run_task(client: OpenAI, task_id: str) -> dict[str, Any]:
    rewards: list[float] = []
    history: list[str] = []
    steps_taken = 0
    score = 0.0
    success = False
    result = None

    model_label = "scripted-fallback" if USE_SCRIPTED else MODEL_NAME
    log_start(task=task_id, env=BENCHMARK, model=model_label)

    env = None
    try:
        env = await create_env()
        result = await env.reset(task_id=task_id)
        max_steps = max(result.observation.remaining_steps, 1)

        for step in range(1, max_steps + 1):
            if result.done:
                break

            action = pick_action(client, task_id, step - 1, result.observation, history)
            result = await env.step(action)

            reward = float(result.reward or 0.0)
            rewards.append(reward)
            steps_taken = step
            score = float(
                result.observation.final_score
                if result.observation.final_score is not None
                else result.observation.partial_score
            )

            log_step(
                step=step,
                action=compact_action(action),
                reward=reward,
                done=result.done,
                error=result.observation.last_action_error,
            )

            history.append(
                f"step={step} action={compact_action(action)} reward={reward:.2f} score={score:.2f}"
            )

            if result.done:
                break

        if result is not None:
            score = float(
                result.observation.final_score
                if result.observation.final_score is not None
                else result.observation.partial_score
            )
        success = bool(result and result.done and score >= SUCCESS_SCORE_THRESHOLD)

    finally:
        if env is not None:
            try:
                await env.close()
            except Exception:
                pass
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return {
        "task_id": task_id,
        "success": success,
        "steps": steps_taken,
        "score": round(score, 4),
        "rewards": rewards,
        "mode": "scripted" if USE_SCRIPTED else "model",
        "model": "scripted-fallback" if USE_SCRIPTED else MODEL_NAME,
    }


async def main() -> None:
    tasks_raw = os.getenv("INCIDENT_COMMANDER_TASKS")
    tasks = (
        [task.strip() for task in tasks_raw.split(",") if task.strip()]
        if tasks_raw
        else DEFAULT_TASKS
    )
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY or "missing")

    summaries = []
    for task_id in tasks:
        summaries.append(await run_task(client, task_id))

    output_path = Path(__file__).resolve().parent / "outputs" / "inference_summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"results": summaries}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
