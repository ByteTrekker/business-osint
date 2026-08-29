"""Budżet grafu — bez niego jedno kliknięcie w hub kładzie bazę i przeglądarkę."""

from __future__ import annotations

from business_osint.domain.graph_budget import DEFAULT_HUB_DEGREE, ExpansionState, GraphBudget


def test_free_plan_is_limited_to_one_level() -> None:
    assert GraphBudget.for_plan("free").max_depth == 1
    assert GraphBudget.for_plan("pro").max_depth == 3
    assert GraphBudget.for_plan("b2b").max_depth == 4


def test_depth_is_clamped_to_plan() -> None:
    budget = GraphBudget.for_plan("free")
    assert budget.clamp_depth(4) == 1
    assert budget.clamp_depth(None) == 1
    assert budget.clamp_depth(0) == 1


def test_node_budget_is_hard_limit() -> None:
    budget = GraphBudget(max_depth=3, max_nodes=5, fanout_per_node=100)
    state = ExpansionState.start("root", budget)
    accepted = state.accept([f"n{i}" for i in range(20)])
    assert len(accepted) == 4  # root zajmuje jedno miejsce z pięciu
    assert state.truncated is True


def test_duplicates_do_not_consume_budget() -> None:
    state = ExpansionState.start("root", GraphBudget(max_nodes=10))
    state.accept(["a", "b"])
    assert state.accept(["a", "b"]) == []
    assert state.truncated is False


def test_hub_is_not_expanded() -> None:
    state = ExpansionState.start("root", GraphBudget())
    assert state.should_expand("normal", degree=10) is True
    assert state.should_expand("hub", degree=DEFAULT_HUB_DEGREE + 1) is False
    assert state.suppressed_hubs == 1
