"""A chain reservation must account for all model calls, including interrupted calls."""
from core.evolution.budget import BudgetTracker, BudgetConfig


def test_multi_call_reservation_settles_actual_calls_and_persists(tmp_path):
    path = tmp_path / "budget.sqlite"
    budget = BudgetTracker(BudgetConfig(max_api_calls=7), path)
    reservation = budget.reserve(8000, 2000, api_call_cap=6, run_id="chain")
    assert not budget.can_reserve(100, 10, api_call_cap=2)
    budget.settle(reservation, {"input_tokens": 140, "output_tokens": 30, "api_calls": 3})
    assert budget.total_api_calls == 3
    assert budget.get_run_usage("chain")["api_calls"] == 3
    budget.reserve(100, 10, api_call_cap=2, run_id="interrupted")
    resumed = BudgetTracker(BudgetConfig(max_api_calls=7), path)
    assert resumed.total_api_calls == 5
    assert not resumed.can_reserve(100, 10, api_call_cap=3)


def test_chain_missing_provider_usage_is_not_reported_as_free_tokens(tmp_path):
    from core.evolution.agent_provider import KageChainProvider
    from core.model_provider import ModelResponse
    class UnmeteredModel:
        def generate(self, **kwargs):
            return ModelResponse(text="finished")
    provider = KageChainProvider(UnmeteredModel())
    result = provider.generate_step({"task_id": "unmetered", "instruction": "Finish now."}, 1, [], tmp_path)
    assert result["usage"] == {"api_calls": 1}
