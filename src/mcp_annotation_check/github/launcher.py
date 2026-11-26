"""Start GitHub's MCP server in Docker.

The token never appears on the command line (it would show in `ps` and in logs).
`docker run -e NAME` with no value makes docker copy NAME from its own environment,
so the token travels only through the environment of the docker process.

The SDK starts the child with `get_default_environment() | params.env`, which already
inherits PATH and HOME on POSIX. We still set PATH (and HOME when present) explicitly,
so the docker binary is found whatever the SDK's defaults are.
"""

import os
import subprocess

from mcp import StdioServerParameters

TOKEN_ENV = "MCP_ANNOTATION_CHECK_GITHUB_TOKEN"
SERVER_TOKEN_ENV = "GITHUB_PERSONAL_ACCESS_TOKEN"


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
    env = {SERVER_TOKEN_ENV: token}
    for key in ("PATH", "HOME"):
        if key in os.environ:
            env[key] = os.environ[key]
    return StdioServerParameters(command="docker", args=args, env=env)


def image_digest(image: str) -> str:
    """The image's first repo digest, e.g. `ghcr.io/...@sha256:...`."""
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()
