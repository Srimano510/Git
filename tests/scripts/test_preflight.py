import json
import threading

import pytest

from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager
from scripts.mock_llm import make_server
from scripts.preflight import (
    check_chats,
    check_demo_config,
    check_embedder,
    check_ports,
    check_provider,
    check_webui,
    main,
    run_checks,
)

SECRET = "sk-THIS-MUST-NEVER-BE-PRINTED"


def config(**overrides) -> Config:
    data = {
        "agents": {"defaults": {"model": "gpt-4o", "provider": "openai", "idleCompactAfterMinutes": 0}},
        "providers": {"openai": {"apiKey": SECRET}},
        "channels": {"websocket": {"enabled": True, "port": 18765}},
        "gateway": {"port": 18791},
        "contextGraph": {"graphTokenBudget": 200, "semanticEmbedder": "hash"},
    }
    for key, value in overrides.items():
        data[key] = value
    return Config.model_validate(data)


def status(checks, name):
    return next(c for c in checks if c.name == name).status


def test_provider_with_a_key_passes_and_never_shows_it():
    (check,) = check_provider(config())
    assert check.status == "PASS" and "gpt-4o" in check.detail and SECRET not in check.detail


def test_provider_without_a_key_fails_with_a_hint():
    cfg = config(providers={"openai": {}})
    (check,) = check_provider(cfg)
    assert check.status == "FAIL" and "key" in check.detail.lower()


@pytest.fixture
def mock_server(tmp_path):
    srv = make_server(0, None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_a_local_mock_provider_is_recognised_and_must_be_reachable(mock_server):
    up = config(providers={"openai": {"apiKey": "any", "apiBase": f"http://127.0.0.1:{mock_server}/v1"}})
    (check,) = check_provider(up)
    assert check.status == "PASS" and "mock" in check.detail.lower()

    down = config(providers={"openai": {"apiKey": "any", "apiBase": "http://127.0.0.1:9/v1"}})
    (check,) = check_provider(down)
    assert check.status == "FAIL" and "scripts.mock_llm" in check.detail


def test_embedder_reports_what_will_really_run():
    assert check_embedder(config()).status == "PASS"  # "hash" configured on purpose
    auto = config(contextGraph={"semanticEmbedder": "auto"})
    got = check_embedder(auto)  # the test environment has no downloaded model
    assert got.status == "WARN" and "nanobot.context_graph.embed" in got.detail


def test_webui_build_must_exist(tmp_path):
    assert check_webui(tmp_path).status == "FAIL"
    (tmp_path / "index.html").write_text("<html></html>")
    assert check_webui(tmp_path).status == "PASS"


def test_ports_in_use_are_a_warning_not_a_failure():
    checks = check_ports(config(), lambda host, port: port == 18765)
    assert [(c.name, c.status) for c in checks] == [("port 18765 (WebUI)", "WARN"), ("port 18791 (gateway)", "PASS")]


def test_demo_config_warnings():
    assert all(c.status == "PASS" for c in check_demo_config(config()))
    bad = config(
        agents={"defaults": {"model": "gpt-4o", "provider": "openai"}},  # idle compaction left at 15 minutes
        contextGraph={"semanticEmbedder": "hash", "recordComparison": False},
    )
    got = {c.name: c for c in check_demo_config(bad)}
    assert got["idle compaction"].status == "WARN" and "idleCompactAfterMinutes" in got["idle compaction"].detail
    assert got["graph token budget"].status == "WARN"
    assert got["recorded comparison"].status == "WARN"


def test_chats_must_be_seeded(tmp_path):
    from scripts.seed_demo import seed, seed_noise

    manager = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    (check,) = check_chats(manager)
    assert check.status == "WARN" and "scripts.seed_demo" in check.detail
    seed(manager)
    seed_noise(manager)
    (check,) = check_chats(manager)
    assert check.status == "PASS"


def test_main_prints_a_report_never_leaks_the_key_and_sets_the_exit_code(tmp_path, capsys):
    cfg = {
        "agents": {"defaults": {"model": "gpt-4o", "provider": "openai", "workspace": str(tmp_path / "ws")}},
        "providers": {"openai": {"apiKey": SECRET}},
        "channels": {"websocket": {"enabled": True, "port": 18765}},
        "contextGraph": {"semanticEmbedder": "hash"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    dist = tmp_path / "dist"
    assert main(["-c", str(path), "--dist", str(dist)]) == 1  # no WebUI build: a FAIL
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "FAIL  WebUI build" in out and "PASS  provider" in out and "failed" in out

    dist.mkdir()
    (dist / "index.html").write_text("x")
    assert main(["-c", str(path), "--dist", str(dist)]) == 0  # warnings alone do not fail


def test_run_checks_covers_everything(tmp_path):
    manager = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    names = {c.name for c in run_checks(config(), manager=manager, dist=tmp_path, port_in_use=lambda h, p: False)}
    assert {"provider", "embedder", "WebUI build", "idle compaction", "graph token budget",
            "recorded comparison", "demo chats"} <= names
    assert any(n.startswith("port ") for n in names)


def test_an_unresolved_environment_reference_is_not_a_key():
    cfg = config(providers={"openai": {"apiKey": "${OPENCODE_API_KEY}"}})
    (check,) = check_provider(cfg)
    assert check.status == "FAIL" and "OPENCODE_API_KEY" in check.detail


def test_main_resolves_the_key_from_the_environment_and_names_a_missing_variable(tmp_path, capsys, monkeypatch):
    from scripts.demo_setup import main as setup

    inst = tmp_path / "demo"
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    setup([str(inst), "--provider", "zen", "--model", "some-free-model"])
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    capsys.readouterr()

    assert main(["-c", str(inst / "config.json"), "--dist", str(dist)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  environment" in out and "OPENCODE_API_KEY" in out and "FAIL  provider" in out

    monkeypatch.setenv("OPENCODE_API_KEY", SECRET)
    assert main(["-c", str(inst / "config.json"), "--dist", str(dist)]) == 0
    out = capsys.readouterr().out
    assert "PASS  provider: opencode_zen / opencode/some-free-model" in out and SECRET not in out


def test_live_check_makes_one_real_call_through_the_configured_provider(mock_server):
    from scripts.preflight import check_live

    up = config(providers={"openai": {"apiKey": SECRET, "apiBase": f"http://127.0.0.1:{mock_server}/v1"}})
    (ok,) = check_live(up)
    assert ok.status == "PASS" and "answered" in ok.detail


def test_a_failing_live_call_is_a_fail_and_scrubs_the_key_from_the_error(monkeypatch):
    from scripts.preflight import check_live

    def boom(*a, **k):
        raise RuntimeError(f"401 Unauthorized for key {SECRET}")

    monkeypatch.setattr("nanobot.providers.factory.make_provider", boom)
    (bad,) = check_live(config())
    assert bad.status == "FAIL" and "401 Unauthorized" in bad.detail and SECRET not in bad.detail
