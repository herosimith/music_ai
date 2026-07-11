from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote


def read_secret(variable: str) -> str:
    path_value = os.environ.get(variable)
    if not path_value:
        raise RuntimeError(f"{variable} must point to a mounted secret file")
    value = Path(path_value).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{variable} points to an empty secret")
    return value


def runtime_environment(*, require_pepper: bool) -> dict[str, str]:
    environment = os.environ.copy()
    if "MUSIC_AI_DATABASE_URL" not in environment:
        password = read_secret("MUSIC_AI_DATABASE_PASSWORD_FILE")
        user = quote(environment.get("MUSIC_AI_DATABASE_USER", "music_ai_api"), safe="")
        host = environment.get("MUSIC_AI_DATABASE_HOST", "postgres")
        port = environment.get("MUSIC_AI_DATABASE_PORT", "5432")
        database = quote(environment.get("MUSIC_AI_DATABASE_NAME", "music_ai"), safe="")
        environment["MUSIC_AI_DATABASE_URL"] = (
            f"postgresql+psycopg://{user}:{quote(password, safe='')}@{host}:{port}/{database}"
        )
    if require_pepper and "MUSIC_AI_TOKEN_PEPPER" not in environment:
        environment["MUSIC_AI_TOKEN_PEPPER"] = read_secret("MUSIC_AI_TOKEN_PEPPER_FILE")
    if (
        "MUSIC_AI_COACH_API_KEY" not in environment
        and "MUSIC_AI_COACH_API_KEY_FILE" in environment
    ):
        environment["MUSIC_AI_COACH_API_KEY"] = read_secret(
            "MUSIC_AI_COACH_API_KEY_FILE"
        )
    return environment


def command_for(arguments: list[str]) -> tuple[list[str], bool]:
    if not arguments:
        raise RuntimeError("a control-plane role is required")
    role, *extra = arguments
    if role == "api":
        return (
            [
                "uvicorn",
                "music_ai_control_plane.api:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--proxy-headers",
                "--forwarded-allow-ips=*",
            ],
            True,
        )
    if role == "migrate":
        return (["alembic", "-c", "services/control-plane/alembic.ini", "upgrade", "head"], False)
    if role == "maintenance":
        return (["python", "-m", "music_ai_control_plane.maintenance"], True)
    if role == "provision":
        return (["python", "-m", "music_ai_control_plane.provision", *extra], True)
    raise RuntimeError(f"unknown control-plane role: {role}")


def main() -> int:
    command, require_pepper = command_for(sys.argv[1:])
    os.execvpe(command[0], command, runtime_environment(require_pepper=require_pepper))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
