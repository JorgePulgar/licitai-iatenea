from unittest.mock import MagicMock, patch


@patch("app.services.indexing.get_search_client")
def test_delete_pliego_from_index_logic(mock_get_search_client):
    from app.services.indexing import delete_pliego_from_index

    # Setup mock client
    mock_search_client = MagicMock()
    mock_get_search_client.return_value = mock_search_client

    # Mock search results (chunks to delete)
    mock_search_client.search.return_value = [
        {"id": "chunk_1"},
        {"id": "chunk_2"}
    ]

    # Run service
    delete_pliego_from_index("p_123")

    # Verify search call
    mock_search_client.search.assert_called_once()
    args, kwargs = mock_search_client.search.call_args
    assert "pliego_id eq 'p_123'" in kwargs["filter"]

    # Verify delete_documents call
    mock_search_client.delete_documents.assert_called_once()
    deleted_docs = mock_search_client.delete_documents.call_args.kwargs["documents"]
    assert len(deleted_docs) == 2
    assert deleted_docs[0]["id"] == "chunk_1"
