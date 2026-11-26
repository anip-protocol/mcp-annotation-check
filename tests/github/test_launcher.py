import dataclasses
import subprocess

import pytest

from mcp_annotation_check import cli
from mcp_annotation_check.github import launcher
from mcp_annotation_check.github.safety import SafetyRefusal
from mcp_annotation_check.report import RunHeader

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
        def __init__(self, token, transport=None, write_repositories=None):
            seen["rest_token"] = token
            seen["write_repositories"] = write_repositories
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
        fields = dataclasses.fields(RunHeader)
        required = [f for f in fields if f.default_factory is dataclasses.MISSING]
        return RunHeader(**{f.name: None for f in required}), []

    monkeypatch.setattr(cli, "GitHubRest", FakeRest)
    monkeypatch.setattr(cli, "Client", FakeClient)
    monkeypatch.setattr(cli, "preflight", _passing_preflight)
    monkeypatch.setattr(cli, "image_digest", lambda image: "img@sha256:abc")
    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "write_reports", lambda h, r, out: seen.setdefault("written", out))

    assert cli.main(_run_args(tmp_path)) == 0
    assert seen["rest_token"] == TOKEN
    # The harness's own REST writes are limited to the pack's repositories.
    assert sorted(seen["write_repositories"]) == ["owner/read-repo", "owner/write-repo"]
    assert seen["closed"] is True
    assert seen["run_kwargs"]["secrets"] == [TOKEN]
    assert seen["context"]["image_digest"] == "img@sha256:abc"
    params = seen["params"]
    assert params.command == "docker"
    assert all(TOKEN not in a for a in params.args)
    assert seen["written"] == tmp_path
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


DOCKER_VARS = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)


def test_docker_client_settings_reach_docker_run(monkeypatch):
    monkeypatch.setenv(ENV, TOKEN)
    for name in DOCKER_VARS:
        monkeypatch.setenv(name, f"value-of-{name}")
    params = launcher.server_params("img:1", ["default"], [])
    for name in DOCKER_VARS:
        assert params.env[name] == f"value-of-{name}"
        assert name not in params.args  # docker's own settings, not the container's


def test_unset_docker_settings_are_not_invented(monkeypatch):
    monkeypatch.setenv(ENV, TOKEN)
    for name in DOCKER_VARS:
        monkeypatch.delenv(name, raising=False)
    params = launcher.server_params("img:1", ["default"], [])
    assert not set(DOCKER_VARS) & set(params.env)


def test_self_test_prints_pack_validation_problems(monkeypatch, tmp_path, capsys):
    text = cli.FAKE_PACK.read_text().replace(
        "argument_roles: {issue_id: id}", "argument_roles: {issue_id: id, owner: other}", 1
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text(text)
    monkeypatch.setattr(cli, "FAKE_PACK", bad)
    assert cli.main(["self-test", "--out", str(tmp_path / "out")]) == 2
    captured = capsys.readouterr()
    problem = "get_issue: role declared for 'owner', which is not an input-schema property"
    assert f"pack validation problem: {problem}" in captured.err
    assert "pack validation failed: 1 problem(s)" in captured.out
    assert problem in (tmp_path / "out" / "report.md").read_text()


def _early_stop_results(reason):
    from mcp_annotation_check.report import ToolResult
    from mcp_annotation_check.snapshot import Outcome

    def result(tool, outcome, skip_reason=None):
        return ToolResult(tool, "", None, outcome, [], skip_reason, None, [], 0.0, None, False)

    return [result("a", Outcome.PASS), result("b", Outcome.SKIPPED, reason)]


@pytest.mark.parametrize(
    "problems, reason, code",
    [
        ([], "not a claim we check", 0),
        (["x: bad"], "not a claim we check", 2),
        ([], "run stopped after a safety refusal on a", 2),
    ],
)
def test_run_exits_nonzero_after_an_early_stop(monkeypatch, tmp_path, problems, reason, code):
    monkeypatch.setenv(ENV, TOKEN)

    async def fake_run_github(args, token):
        fields = dataclasses.fields(RunHeader)
        required = [f for f in fields if f.default_factory is dataclasses.MISSING]
        header = RunHeader(**{f.name: None for f in required})
        header.pack_problems = problems
        return header, _early_stop_results(reason)

    monkeypatch.setattr(cli, "_run_github", fake_run_github)
    assert cli.main(_run_args(tmp_path)) == code
