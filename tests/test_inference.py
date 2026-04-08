"""Targeted inference runner tests for validator-facing behavior."""

from __future__ import annotations

import asyncio

import inference


def test_create_env_requires_explicit_docker_opt_in(monkeypatch):
    monkeypatch.setattr(inference, "ENV_BASE_URL", None)
    monkeypatch.setattr(inference, "LOCAL_IMAGE_NAME", None)
    monkeypatch.setattr(inference, "env_url_candidates", lambda: [])

    async def unexpected_docker_call(*args, **kwargs):
        raise AssertionError("from_docker_image should not be called without LOCAL_IMAGE_NAME")

    monkeypatch.setattr(
        inference.IncidentCommanderEnv,
        "from_docker_image",
        unexpected_docker_call,
    )

    with_error = None
    try:
        asyncio.run(inference.create_env())
    except RuntimeError as exc:
        with_error = str(exc)

    assert with_error is not None
    assert "LOCAL_IMAGE_NAME was not set" in with_error


def test_run_task_handles_env_startup_failures_without_crashing(monkeypatch, capsys):
    monkeypatch.setattr(inference, "USE_SCRIPTED", True)

    async def failing_create_env():
        raise RuntimeError("docker exited with status 125")

    monkeypatch.setattr(inference, "create_env", failing_create_env)

    summary = asyncio.run(inference.run_task(client=None, task_id="payments_worker_backlog"))

    assert summary["success"] is False
    assert summary["steps"] == 0
    assert summary["score"] == 0.001
    assert summary["error"] == "docker exited with status 125"

    stdout_lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(stdout_lines) == 2
    assert stdout_lines[0].startswith("[START]")
    assert stdout_lines[1].startswith("[END] success=false")
    assert "score=0.001" in stdout_lines[1]


def test_main_ignores_summary_write_failures(monkeypatch):
    async def successful_run_task(client, task_id):
        return {
            "task_id": task_id,
            "success": True,
            "steps": 1,
            "score": 1.0,
            "rewards": [1.0],
            "mode": "scripted",
            "model": "scripted-fallback",
            "error": None,
        }

    def failing_write(*args, **kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(inference, "run_task", successful_run_task)
    monkeypatch.setattr(inference.Path, "write_text", failing_write)

    asyncio.run(inference.main())
