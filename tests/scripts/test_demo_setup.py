import json

import pytest

from nanobot.config.loader import load_config, resolve_config_env_vars
from scripts.demo_setup import main
from scripts.preflight import check_chats, check_demo_config, check_ports


def read(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))


def test_mock_setup_writes_a_loadable_config_and_seeds_the_chats(tmp_path):
    inst = tmp_path / "demo"
    assert main([str(inst), "--provider", "mock"]) == 0
    raw = read(inst)
    assert raw["providers"]["openai"]["apiBase"].startswith("http://127.0.0.1:")
    assert raw["agents"]["defaults"]["idleCompactAfterMinutes"] == 0
    assert raw["contextGraph"]["graphTokenBudget"] == 200 and raw["contextGraph"]["recordComparison"] is True

    config = load_config(inst / "config.json")
    assert config.resolve_preset().model == "gpt-4o" and config.workspace_path == inst / "workspace"
    assert all(c.status == "PASS" for c in check_demo_config(config))
    from nanobot.session.manager import SessionManager
    assert check_chats(SessionManager(config.workspace_path))[0].status == "PASS"
    assert check_ports(config, lambda h, p: False)[0].name == "port 8775 (WebUI)"


def test_zen_setup_references_the_key_by_environment_variable_never_by_value(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-REAL-KEY-VALUE")
    inst = tmp_path / "demo"
    assert main([str(inst), "--provider", "zen", "--model", "glm-5.3-flash-free"]) == 0
    text = (inst / "config.json").read_text(encoding="utf-8")
    assert "sk-REAL-KEY-VALUE" not in text and "${OPENCODE_API_KEY}" in text
    raw = json.loads(text)
    preset = raw["modelPresets"]["primary"]
    assert preset["provider"] == "opencode_zen" and preset["model"] == "opencode/glm-5.3-flash-free"
    assert raw["agents"]["defaults"]["modelPreset"] == "primary"
    config = resolve_config_env_vars(load_config(inst / "config.json"))  # what the gateway does
    assert config.get_provider_name(preset=config.resolve_preset()) == "opencode_zen"
    assert config.get_api_key(preset=config.resolve_preset()) == "sk-REAL-KEY-VALUE"  # resolved only in memory


def test_zen_needs_a_model_and_an_existing_instance_is_never_overwritten(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main([str(tmp_path / "a"), "--provider", "zen"])  # no --model
    inst = tmp_path / "demo"
    assert main([str(inst), "--provider", "mock"]) == 0
    before = (inst / "config.json").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(inst), "--provider", "mock"])
    assert (inst / "config.json").read_text(encoding="utf-8") == before


def test_the_websocket_password_is_printed_for_the_login_screen(tmp_path, capsys):
    main([str(tmp_path / "demo"), "--provider", "mock"])
    out = capsys.readouterr().out
    assert "password" in out.lower() and "nanobot gateway" in out and "scripts.preflight" in out
    assert "nanobot.context_graph.embed --config" in out
