"""§7.7: original walking duration, cold-start-inclusive standing fix rate."""

import pytest
from tools.verify_pipeline import run_case


@pytest.mark.parametrize("preset", ["stand_on_mat", "walk_to_cupboard"])
@pytest.mark.parametrize("clean", [True, False], ids=["clean", "all-effects"])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_pipeline_acceptance(preset, clean, seed):
    metrics = run_case(preset, clean, seed)
    assert metrics.passed, metrics
    assert metrics.tracked_fixes_per_second >= 3.2
