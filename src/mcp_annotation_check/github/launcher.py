"""Start GitHub's MCP server in Docker.

The token never appears on the command line (it would show in `ps` and in logs).
`docker run -e NAME` with no value makes docker copy NAME from its own environment,
so the token travels only through the environment of the docker process.

The SDK starts the child with `get_default_environment() | params.env`, which already
inherits PATH and HOME on POSIX. We still set PATH (and HOME when present) explicitly,
so the docker binary is found whatever the SDK's defaults are, and pass the docker
CLI's own settings (DOCKER_HOST and friends) when they are set.
"""

import os
import subprocess

from mcp import StdioServerParameters

from mcp_annotation_check.redact import redact

TOKEN_ENV = "MCP_ANNOTATION_CHECK_GITHUB_TOKEN"
SERVER_TOKEN_ENV = "GITHUB_PERSONAL_ACCESS_TOKEN"
# The docker CLI's own settings: passed to `docker run` when set, so it talks to the
# same daemon that `image_digest` inspects (it gets the same variables).
DOCKER_ENV = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)


def _docker_env() -> dict[str, str]:
    """PATH, HOME and the DOCKER_* settings, when set: never the token."""
    return {k: os.environ[k] for k in ("PATH", "HOME", *DOCKER_ENV) if k in os.environ}


def server_params(
    image: str,
    toolsets: list[str],
    features: list[str],
    token_env: str = TOKEN_ENV,
) -> StdioServerParameters:
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"environment variable {token_env} is not set")
    args = ["run", "-i", "--rm", "-e", SERVER_TOKEN_ENV, image, "stdio"]
    if toolsets:
        args.append(f"--toolsets={','.join(toolsets)}")
    if features:
        args.append(f"--features={','.join(features)}")
    env = {SERVER_TOKEN_ENV: token, **_docker_env()}
    return StdioServerParameters(command="docker", args=args, env=env)


def _inspect(image: str) -> str:
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        capture_output=True,
        text=True,
        check=True,
        env=_docker_env(),
    )
    return out.stdout.strip()


def image_digest(image: str) -> str:
    """The image's first repo digest, e.g. `ghcr.io/...@sha256:...`.

    An image that is not local is pulled once (`docker image inspect` and `docker pull` run
    with PATH, HOME and DOCKER_* only, never the token), then inspected again.
    """
    try:
        return _inspect(image)
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            check=True,
            env=_docker_env(),
        )
    except subprocess.CalledProcessError as error:
        secrets = [t for t in (os.environ.get(TOKEN_ENV),) if t]
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        raise RuntimeError(
            f"docker pull {image} failed: {redact(stderr.strip(), secrets)}"
        ) from None
    return _inspect(image)
