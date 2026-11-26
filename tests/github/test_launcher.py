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
