import pytest
from pydantic import ValidationError

from nanobot.config.schema import Config, ContextGraphConfig


def test_defaults_and_old_configs_without_the_section_still_load():
    config = Config.model_validate({"agents": {"defaults": {"model": "x"}}})
    assert config.context_graph == ContextGraphConfig()
    assert config.context_graph.semantic_pool == "archived"
    assert config.context_graph.semantic_top_k == 3
    assert config.context_graph.semantic_min_score == 0.15
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
