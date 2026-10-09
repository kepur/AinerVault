from types import SimpleNamespace
import pytest
from app.pipelines.sample import select_sample


def shots(*durations):
    return [SimpleNamespace(order_no=i+1, duration_ms=d) for i,d in enumerate(durations)]


def test_budget_keeps_whole_contiguous_shots():
    chosen, duration = select_sample(shots(6100, 1200, 20000, 4000, 1000))
    assert duration == 27300
    assert [s.order_no for s in chosen] == [1,2,3]


def test_start_and_exact_budget():
    chosen, duration = select_sample(shots(2000, 15000, 15000), start_order=2)
    assert duration == 30000
    assert [s.order_no for s in chosen] == [2,3]


def test_oversize_first_shot_is_not_silently_cut():
    with pytest.raises(ValueError):
        select_sample(shots(31000, 1000))
