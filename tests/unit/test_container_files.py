"""The container files, checked statically because they cannot be built here.

Docker is not installed on this machine, which is deferred item D-001. Its third alternative route was to
validate the artefacts by parsing rather than by building, and that is what this does. It is weaker than
`docker build` and it is not nothing: every check here corresponds to a property that would be wrong in a
way an operator would not notice until production.

What this cannot tell you: whether the image builds, whether Chromium runs, or whether uvicorn starts.
Those need Docker and stay with the operator. What it can tell you is that the Dockerfile does not
reference an extra that does not exist, does not run as root, has an init process, and that compose and
the Dockerfile agree about the port and the health check.

The specific failure this was written after: `uv sync --extra observability` was added to the project and
not to the Dockerfile, so a container with AUSPICE_SENTRY_DSN set would log "configured but not installed"
and report nothing. Nothing else in the repository would have caught that.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

import pytest
import yaml

from auspice.config import REPO_ROOT

DOCKERFILE = REPO_ROOT / "infra" / "Dockerfile.api"
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
CADDYFILE = REPO_ROOT / "infra" / "Caddyfile"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def instructions(dockerfile: str) -> list[tuple[str, str]]:
    """Every instruction as (verb, argument), with line continuations joined."""
    joined: list[str] = []
    buffer = ""
    for raw in dockerfile.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        buffer += line[:-1] + " " if line.endswith("\\") else line
        if not line.endswith("\\"):
            joined.append(buffer)
            buffer = ""
    parsed: list[tuple[str, str]] = []
    for line in joined:
        match = re.match(r"^([A-Z]+)\s+(.*)$", line)
        if match:
            parsed.append((match.group(1), match.group(2)))
    return parsed


class TestTheFilesExist:
    def test_every_container_artefact_is_present(self) -> None:
        for path in (DOCKERFILE, COMPOSE, DOCKERIGNORE, CADDYFILE):
            assert path.exists(), f"{path} is referenced by the deployment and is missing"

    def test_the_dockerignore_excludes_the_heavy_directories(self) -> None:
        """The build context was about 4000 MB before this file existed and is now about 7.8 MB."""
        content = DOCKERIGNORE.read_text(encoding="utf-8")
        for pattern in ("node_modules", ".venv", "var", ".git"):
            assert pattern in content, f".dockerignore does not exclude {pattern}"


class TestTheBuildInstallsWhatTheCodeNeeds:
    def test_every_extra_named_in_the_dockerfile_exists_in_pyproject(self, dockerfile: str) -> None:
        """A typo in an extra name makes `uv sync` fail at build time rather than silently, which is
        good, but only if someone builds. This catches it without building."""
        declared = set(
            tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
                "optional-dependencies"
            ]
        )
        used = set(re.findall(r"--extra\s+([a-z-]+)", dockerfile))
        assert used, "the Dockerfile installs no extras, which cannot be right for this project"
        unknown = used - declared
        assert not unknown, f"the Dockerfile installs extras that do not exist: {sorted(unknown)}"

    def test_the_api_extra_is_installed(self, dockerfile: str) -> None:
        assert "--extra api" in dockerfile, "without it there is no fastapi and no uvicorn"

    def test_the_observability_extra_is_installed(self, dockerfile: str) -> None:
        """The failure this file was written after.

        With the extra absent, a container that has AUSPICE_SENTRY_DSN set logs "configured but not
        installed" and reports nothing. The service still serves, which is why nobody would notice.
        """
        assert "--extra observability" in dockerfile, (
            "sentry-sdk would be absent, so setting a DSN in the container would report nothing"
        )

    def test_the_memo_extra_is_installed_and_the_browser_is_fetched(self, dockerfile: str) -> None:
        """Installing playwright is not enough. It downloads its browser separately."""
        assert "--extra memo" in dockerfile
        assert "playwright install" in dockerfile

    def test_the_lockfile_is_frozen(self, dockerfile: str) -> None:
        """A deploy that silently resolves a different version than the one tested is untested."""
        assert "--frozen" in dockerfile

    def test_development_dependencies_are_left_out(self, dockerfile: str) -> None:
        assert "--no-dev" in dockerfile


class TestItDoesNotRunAsRoot:
    def test_a_user_is_set(self, instructions: list[tuple[str, str]]) -> None:
        users = [argument for verb, argument in instructions if verb == "USER"]
        assert users, "no USER instruction, so the container runs as root"
        assert users[-1].strip() not in {"root", "0"}, f"the final USER is {users[-1]}"

    def test_the_user_is_set_before_the_command(self, instructions: list[tuple[str, str]]) -> None:
        verbs = [verb for verb, _ in instructions]
        assert "USER" in verbs
        assert verbs.index("USER") < verbs.index("CMD"), (
            "USER must come before CMD, or the process starts as root"
        )


class TestProcessSupervision:
    def test_an_init_process_is_the_entrypoint(self, instructions: list[tuple[str, str]]) -> None:
        """uvicorn as PID 1 does not reap zombies and does not forward SIGTERM, so a container stop
        becomes a nine second wait and a kill."""
        entrypoints = [argument for verb, argument in instructions if verb == "ENTRYPOINT"]
        assert entrypoints, "no ENTRYPOINT, so the application is PID 1"
        assert "tini" in entrypoints[0], entrypoints[0]

    def test_a_single_worker_is_requested(self, dockerfile: str) -> None:
        """The rate limiter is in process. Two workers would give each client twice its allowance."""
        assert "--workers" in dockerfile
        assert re.search(r'"--workers",\s*"1"', dockerfile), (
            "the in process rate limiter caps this deployment at one worker"
        )

    def test_a_health_check_is_declared_and_points_at_healthz(self, dockerfile: str) -> None:
        assert "HEALTHCHECK" in dockerfile
        assert "/healthz" in dockerfile


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


class TestComposeAgreesWithTheDockerfile:
    def test_the_compose_file_parses(self, compose: dict[str, Any]) -> None:
        assert "services" in compose

    def test_the_database_and_the_api_are_both_defined(self, compose: dict[str, Any]) -> None:
        services = set(compose["services"])
        assert "db" in services
        assert "api" in services

    def test_the_api_builds_from_the_dockerfile_this_test_checked(
        self, compose: dict[str, Any]
    ) -> None:
        build = compose["services"]["api"].get("build")
        assert build, "the api service does not build, so this file describes a different image"
        dockerfile_ref = build["dockerfile"] if isinstance(build, dict) else ""
        assert "Dockerfile.api" in str(dockerfile_ref)

    def test_the_exposed_port_matches(self, compose: dict[str, Any], dockerfile: str) -> None:
        assert "EXPOSE 8000" in dockerfile
        ports = str(compose["services"]["api"].get("ports", ""))
        assert "8000" in ports, f"compose publishes {ports} and the image exposes 8000"

    def test_production_cors_does_not_inherit_the_localhost_default(
        self, compose: dict[str, Any]
    ) -> None:
        """The audit finding. An unset value meant the localhost default reached production."""
        environment = str(compose["services"]["api"].get("environment", ""))
        assert "AUSPICE_API_CORS_ORIGINS" in environment

    def test_the_api_waits_for_a_healthy_database(self, compose: dict[str, Any]) -> None:
        """Alembic against a database that is listening but not ready fails in a confusing way."""
        depends = compose["services"]["api"].get("depends_on", {})
        assert depends, "the api does not depend on the database"
        if isinstance(depends, dict):
            assert depends.get("db", {}).get("condition") == "service_healthy"


class TestTheTlsProxy:
    def test_the_caddyfile_names_the_api_upstream(self) -> None:
        content = CADDYFILE.read_text(encoding="utf-8")
        assert "api:8000" in content or "api:8000" in content.replace(" ", "")

    def test_it_sets_the_transport_security_header(self) -> None:
        content = CADDYFILE.read_text(encoding="utf-8").lower()
        assert "strict-transport-security" in content
