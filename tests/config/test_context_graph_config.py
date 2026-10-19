import pytest
from pydantic import ValidationError

from nanobot.config.schema import Config, ContextGraphConfig


def test_defaults_and_old_configs_without_the_section_still_load():
    config = Config.model_validate({"agents": {"defaults": {"model": "x"}}})
    assert config.context_graph == ContextGraphConfig()
    assert config.context_graph.semantic_pool == "archived"
    assert config.context_graph.semantic_top_k == 3
    assert config.context_graph.semantic_min_score is None  # unset: the embedder's own default
    assert config.context_graph.recall_token_budget == 1500


def test_camel_case_aliases_load_and_dump():
    config = Config.model_validate(
        {
            "contextGraph": {
                "semanticPool": "family",
                "semanticTopK": 5,
                "semanticMinScore": 0.3,
                "recallTokenBudget": 800,
            }
        }
    )
    cg = config.context_graph
    assert (cg.semantic_pool, cg.semantic_top_k, cg.semantic_min_score, cg.recall_token_budget) == (
        "family",
        5,
        0.3,
        800,
    )
    assert config.model_dump(mode="json", by_alias=True)["contextGraph"]["semanticPool"] == "family"


def test_invalid_values_are_rejected():
    with pytest.raises(ValidationError):
        ContextGraphConfig(semantic_pool="everything")
    with pytest.raises(ValidationError):
        ContextGraphConfig(semantic_top_k=0)
    with pytest.raises(ValidationError):
        ContextGraphConfig(semantic_min_score=1.5)


def test_embedder_fields_have_defaults_and_camel_case_aliases():
    cg = Config.model_validate({"agents": {"defaults": {"model": "x"}}}).context_graph
    assert cg.semantic_embedder == "auto"
    assert cg.semantic_model == "minishlab/potion-base-8M"
    loaded = Config.model_validate(
        {"contextGraph": {"semanticEmbedder": "hash", "semanticModel": "org/other"}}
    ).context_graph
    assert (loaded.semantic_embedder, loaded.semantic_model) == ("hash", "org/other")
    with pytest.raises(ValidationError):
        ContextGraphConfig(semantic_embedder="gpt")


def test_model_validate_works_when_context_graph_was_imported_before_the_schema():
    """Regression: ``Config.model_validate`` skips ``__init__``, so the lazy tool-config
    resolution never ran and a fresh process that imported ``nanobot.context_graph`` first
    failed with "Config is not fully defined"."""
    import subprocess
    import sys

    code = (
        "import nanobot.context_graph.embed\n"
        "from nanobot.config.schema import Config\n"
        "print(Config.model_validate({}).context_graph.semantic_embedder)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-400:]
    assert done.stdout.strip() == "auto"


def test_summary_limits_have_defaults_and_aliases():
    cg = Config.model_validate({"agents": {"defaults": {"model": "x"}}}).context_graph
    assert (cg.summary_max_messages, cg.summary_max_tokens) == (80, 300)
    loaded = Config.model_validate({"contextGraph": {"summaryMaxMessages": 10, "summaryMaxTokens": 120}}).context_graph
    assert (loaded.summary_max_messages, loaded.summary_max_tokens) == (10, 120)
    with pytest.raises(ValidationError):
        ContextGraphConfig(summary_max_messages=0)
