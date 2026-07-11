from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
DEPLOY = ROOT / "deploy"


def test_production_compose_keeps_data_services_private_and_orders_startup() -> None:
    compose = yaml.safe_load((DEPLOY / "compose.production.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {
        "postgres",
        "migrate",
        "control-plane",
        "maintenance",
        "web",
        "caddy",
    }
    assert "ports" not in services["postgres"]
    assert "ports" not in services["control-plane"]
    assert "ports" not in services["web"]
    assert services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert (
        services["control-plane"]["depends_on"]["migrate"]["condition"]
        == "service_completed_successfully"
    )
    assert services["caddy"]["depends_on"]["control-plane"]["condition"] == "service_healthy"
    assert compose["networks"]["backend"]["internal"] is True
    assert compose["networks"]["database"]["internal"] is True
    assert "database" not in services["caddy"]["networks"]
    assert services["postgres"]["networks"] == ["database"]
    assert set(services["control-plane"]["networks"]) == {"backend", "database"}
    assert "healthcheck" in services["postgres"]
    assert "healthcheck" in services["control-plane"]
    assert "healthcheck" in services["web"]
    assert "healthcheck" in services["caddy"]
    assert "/ready" in " ".join(services["control-plane"]["healthcheck"]["test"])
    assert services["maintenance"]["command"] == ["maintenance"]


def test_deployment_secrets_are_required_files_and_registry_stays_fail_closed() -> None:
    compose_text = (DEPLOY / "compose.production.yaml").read_text(encoding="utf-8")
    environment = (DEPLOY / ".env.production.example").read_text(encoding="utf-8")
    registry = json.loads((ROOT / "models/registry/models.json").read_text(encoding="utf-8"))

    assert "${MUSIC_AI_DATABASE_PASSWORD_FILE:?" in compose_text
    assert "${MUSIC_AI_TOKEN_PEPPER_FILE:?" in compose_text
    assert "${MUSIC_AI_COACH_API_KEY_FILE:?" in compose_text
    assert "POSTGRES_PASSWORD=" not in compose_text
    assert "MUSIC_AI_TOKEN_PEPPER:" not in compose_text
    assert "<immutable-release-tag>" in environment
    assert "<practice.example.com>" in environment
    assert registry["models"] == []
    assert "scoring:" not in compose_text
    assert "ingest:" not in compose_text
    assert "coach:" not in compose_text


def test_container_builds_are_non_root_and_copy_standalone_assets() -> None:
    web = (DEPLOY / "Dockerfile.web").read_text(encoding="utf-8")
    control_plane = (DEPLOY / "Dockerfile.control-plane").read_text(encoding="utf-8")
    caddy = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")

    assert "USER node" in web
    assert "/repo/apps/web/.next/standalone" in web
    assert "/repo/apps/web/.next/static ./apps/web/.next/static" in web
    assert "/repo/apps/web/public ./apps/web/public" in web
    assert "USER musicai" in control_plane
    assert "chown -R musicai:musicai /data" in control_plane
    assert "handle_path /api/*" in caddy
    assert "handle /api/coach" in caddy
    assert "X-Music-AI-Client-IP {http.request.remote.host}" in caddy
    assert "reverse_proxy web:3000" in caddy
    assert "reverse_proxy control-plane:8000" in caddy
    assert "reverse_proxy web:3000" in caddy
    assert "max_size 100MB" in caddy
    assert 'Permissions-Policy "microphone=(self)"' in caddy


def test_docker_context_excludes_operator_secrets() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "**/.env" in dockerignore
    assert "**/.env.*" in dockerignore
    assert "**/secrets" in dockerignore


def test_control_plane_runner_reads_encoded_runtime_secrets(tmp_path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "music_ai_deploy_runner",
        DEPLOY / "run-control-plane.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    password = tmp_path / "database_password"
    pepper = tmp_path / "token_pepper"
    coach_key = tmp_path / "coach_api_key"
    password.write_text("db:p@ss/word\n", encoding="utf-8")
    pepper.write_text("p" * 48, encoding="utf-8")
    coach_key.write_text("coach-key-0123456789abcdef\n", encoding="utf-8")
    monkeypatch.delenv("MUSIC_AI_DATABASE_URL", raising=False)
    monkeypatch.delenv("MUSIC_AI_TOKEN_PEPPER", raising=False)
    monkeypatch.delenv("MUSIC_AI_COACH_API_KEY", raising=False)
    monkeypatch.setenv("MUSIC_AI_DATABASE_PASSWORD_FILE", str(password))
    monkeypatch.setenv("MUSIC_AI_TOKEN_PEPPER_FILE", str(pepper))
    monkeypatch.setenv("MUSIC_AI_COACH_API_KEY_FILE", str(coach_key))

    runtime = module.runtime_environment(require_pepper=True)

    assert "db%3Ap%40ss%2Fword" in runtime["MUSIC_AI_DATABASE_URL"]
    assert runtime["MUSIC_AI_TOKEN_PEPPER"] == "p" * 48
    assert runtime["MUSIC_AI_COACH_API_KEY"] == "coach-key-0123456789abcdef"
    assert module.command_for(["migrate"])[1] is False
    assert module.command_for(["api"])[1] is True
    assert module.command_for(["maintenance"])[0][-1].endswith("maintenance")
