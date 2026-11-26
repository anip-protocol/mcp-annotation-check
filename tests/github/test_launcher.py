import subprocess

import pytest

from mcp_annotation_check import cli
from mcp_annotation_check.github import launcher
from mcp_annotation_check.github.safety import SafetyRefusal

TOKEN = "github_pat_dummy0000000000000000"
ENV = "MCP_ANNOTATION_CHECK_GITHUB_TOKEN"


def test_server_params_has_no_token_in_args(monkeypatch):
    monkeypatch.setenv(ENV, TOKEN)
    params = launcher.server_params("img:1", ["default"], [])
    assert all(TOKEN not in a for a in params.args)
    assert params.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == TOKEN
    assert params.args[:5] == ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN"]
    assert "PATH" in params.env
    assert params.command == "docker"


def test_features_flag_rendered_only_when_given(monkeypatch):
    monkeypatch.setenv(ENV, TOKEN)
    without = launcher.server_params("img:1", ["a", "b"], [])
    assert "--toolsets=a,b" in without.args
    assert not any(a.startswith("--features") for a in without.args)
    with_features = launcher.server_params("img:1", ["a"], ["x", "y"])
    assert "--features=x,y" in with_features.args


def test_server_params_requires_token(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    with pytest.raises(RuntimeError):
        launcher.server_params("img:1", ["a"], [])


def test_image_digest_uses_docker_inspect(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="img@sha256:abc\n", stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    assert launcher.image_digest("img:1") == "img@sha256:abc"
    assert calls[0][:3] == ["docker", "image", "inspect"]
    assert "{{index .RepoDigests 0}}" in calls[0]


def _run_args(tmp_path):
    return [
        "run", "--pack", "packs/fake.yaml", "--image", "img:1", "--toolsets", "default",
        "--login", "test-account", "--out", str(tmp_path),
    ]  # fmt: skip


def test_run_refuses_before_starting_server_when_preflight_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV, TOKEN)
    started = []

    async def bad_preflight(*a, **k):
        raise SafetyRefusal(f"nope, token {TOKEN}")

    monkeypatch.setattr(cli, "preflight", bad_preflight)
    monkeypatch.setattr(cli, "server_params", lambda *a, **k: started.append("params"))
    monkeypatch.setattr(cli, "image_digest", lambda *a, **k: started.append("digest"))
    code = cli.main(_run_args(tmp_path))
    assert code != 0
    assert started == []
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert "nope" in captured.out + captured.err


def test_run_without_token_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(ENV, raising=False)
    assert cli.main(_run_args(tmp_path)) != 0
    assert ENV in capsys.readouterr().err


def test_list_tools_failure_is_redacted(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV, TOKEN)

    def boom(*a, **k):
        raise RuntimeError(f"cannot start with {TOKEN}")

    monkeypatch.setattr(cli, "server_params", boom)
    code = cli.main(
        ["list-tools", "--image", "img:1", "--toolsets", "default", "--out", str(tmp_path / "t.json")]
    )
    assert code != 0
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


def test_keyboard_interrupt_gives_130_and_no_traceback(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV, TOKEN)

    async def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "preflight", interrupted)
    assert cli.main(_run_args(tmp_path)) == 130
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert TOKEN not in err


def test_system_exit_inside_run_is_redacted(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV, TOKEN)

    async def exits(*a, **k):
        raise SystemExit(f"bye {TOKEN}")

    monkeypatch.setattr(cli, "preflight", exits)
    assert cli.main(_run_args(tmp_path)) != 0
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


# --- operator diagnostics and the run success path (final fix wave) ------------


async def _passing_preflight(*a, **k):
    return {"login": "test-account", "repositories": [], "organizations": []}


def test_exception_group_is_unwrapped_and_redacted(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV, TOKEN)

    async def grouped(*a, **k):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [
                ExceptionGroup("nested", [RuntimeError(f"docker said no to {TOKEN}")]),
                ValueError("second cause"),
            ],
        )

    monkeypatch.setattr(cli, "preflight", grouped)
    assert cli.main(_run_args(tmp_path)) != 0
    err = capsys.readouterr().err
    assert "RuntimeError: docker said no to" in err
    assert "ValueError: second cause" in err
    assert TOKEN not in err
    assert "Traceback" not in err


def test_called_process_error_shows_stderr_redacted(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV, TOKEN)
    monkeypatch.setattr(cli, "preflight", _passing_preflight)

    def no_image(image):
        raise subprocess.CalledProcessError(
            1, ["docker", "image", "inspect"], stderr=f"Error: No such image: img:1 {TOKEN}\n"
        )

    monkeypatch.setattr(cli, "image_digest", no_image)
    assert cli.main(_run_args(tmp_path)) != 0
    err = capsys.readouterr().err
    assert "No such image: img:1" in err
    assert TOKEN not in err


def test_run_success_path_passes_secrets_closes_rest_and_keeps_token_off_args(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv(ENV, TOKEN)
    seen: dict = {}

    class FakeRest:
        def __init__(self, token):
            seen["rest_token"] = token
            seen["closed"] = False

        async def aclose(self):
            seen["closed"] = True

    class FakeClient:
        def __init__(self, params):
            seen["params"] = params

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_run(client, reader, pack, context, before_call=None, **kwargs):
        seen["run_kwargs"] = kwargs
        seen["context"] = context
        return "header", []

    monkeypatch.setattr(cli, "GitHubRest", FakeRest)
    monkeypatch.setattr(cli, "Client", FakeClient)
    monkeypatch.setattr(cli, "preflight", _passing_preflight)
    monkeypatch.setattr(cli, "image_digest", lambda image: "img@sha256:abc")
    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "write_reports", lambda h, r, out: seen.setdefault("written", out))

    assert cli.main(_run_args(tmp_path)) == 0
    assert seen["rest_token"] == TOKEN
    assert seen["closed"] is True
    assert seen["run_kwargs"]["secrets"] == [TOKEN]
    assert seen["context"]["image_digest"] == "img@sha256:abc"
    params = seen["params"]
    assert params.command == "docker"
    assert all(TOKEN not in a for a in params.args)
    assert seen["written"] == tmp_path
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
