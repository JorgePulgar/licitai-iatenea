from unittest.mock import MagicMock, patch


@patch("app.services.indexing.get_search_client")
def test_delete_pliego_from_index_logic(mock_get_search_client):
    """El borrado es por pasadas (search ≤1000 → delete) hasta que no quedan chunks."""
    from app.services.indexing import delete_pliego_from_index

    mock_search_client = MagicMock()
    mock_get_search_client.return_value = mock_search_client

    # 1ª pasada: quedan 2 chunks; 2ª pasada: ya no queda ninguno → fin del bucle.
    mock_search_client.search.side_effect = [
        [{"id": "chunk_1"}, {"id": "chunk_2"}],
        [],
    ]

    delete_pliego_from_index("p_123")

    # Dos búsquedas (la segunda confirma que no quedan restos), filtradas por pliego.
    assert mock_search_client.search.call_count == 2
    for call in mock_search_client.search.call_args_list:
        assert "pliego_id eq 'p_123'" in call.kwargs["filter"]

    # Un único delete con los 2 chunks de la primera pasada.
    mock_search_client.delete_documents.assert_called_once()
    deleted_docs = mock_search_client.delete_documents.call_args.kwargs["documents"]
    assert [d["id"] for d in deleted_docs] == ["chunk_1", "chunk_2"]
