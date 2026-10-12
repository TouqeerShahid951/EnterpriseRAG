from rag.abbreviations.ingestion import remove_abbreviation_source_in_transaction


def test_removing_glossary_source_prunes_terms_and_soft_deletes_document() -> None:
    connection = _Connection()

    assert remove_abbreviation_source_in_transaction(
        connection,
        document_id="document-1",
        actor_id="actor-1",
    )

    statements = "\n".join(connection.statements)
    assert "DELETE FROM abbreviation_glossary_entries" in statements
    assert "deleted_at = COALESCE(deleted_at, NOW())" in statements


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str, _parameters=None):
        self.statements.append(statement)
        removed = "DELETE FROM abbreviation_glossary_sources" in statement
        return _Result({"document_id": "document-1"} if removed else None)


class _Result:
    def __init__(self, row) -> None:
        self.row = row

    def fetchone(self):
        return self.row
