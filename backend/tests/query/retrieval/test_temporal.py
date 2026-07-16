from rag.query.retrieval.temporal import add_effective_date_scope


def test_effective_date_scope_keeps_undated_current_documents() -> None:
    scoped = add_effective_date_scope({"must": []}, "2025-12-31")

    assert scoped["must"] == [
        {
            "should": [
                {"key": "effective_date", "range": {"lte": "2025-12-31"}},
                {"is_empty": {"key": "effective_date"}},
            ]
        }
    ]
