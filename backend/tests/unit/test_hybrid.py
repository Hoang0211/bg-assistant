from app.retrieval.hybrid import reciprocal_rank_fusion


def test_reciprocal_rank_fusion_ranks_ids_found_by_both_searches_first() -> None:
    assert reciprocal_rank_fusion([[1, 2, 3], [3, 4]], k=60) == [3, 1, 2, 4]


def test_reciprocal_rank_fusion_keeps_the_first_seen_order_on_ties() -> None:
    assert reciprocal_rank_fusion([[1, 2], [3, 4]], k=60) == [1, 3, 2, 4]


def test_reciprocal_rank_fusion_returns_nothing_for_empty_rankings() -> None:
    assert reciprocal_rank_fusion([[], []], k=60) == []
