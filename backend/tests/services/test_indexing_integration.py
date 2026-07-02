import pytest
from unittest.mock import MagicMock, patch
from app.services.indexing import index_chunks
from app.models.schemas import Chunk

_CTX = dict(licitacion_id="l1", user_id="u1", document_type="pcap", filename="doc.pdf")


@pytest.fixture
def mock_chunks():
    return [
        Chunk(chunk_id="c1", pliego_id="p1", content="Contenido 1", embedding=[0.1]*1536, **_CTX),
        Chunk(chunk_id="c2", pliego_id="p1", content="Contenido 2", embedding=[0.2]*1536, **_CTX)
    ]

@patch("app.services.indexing.get_search_client")
def test_index_chunks_and_retrieve_mock(mock_get_client, mock_chunks):
    # 1. Setup mock client
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # Mock upload result
    mock_success_result = MagicMock()
    mock_success_result.succeeded = True
    mock_client.upload_documents.return_value = [mock_success_result, mock_success_result]
    
    # 2. Index
    result = index_chunks(mock_chunks)
    
    # Verify index call
    assert result.chunks_indexed == 2
    assert result.status == "success"
    assert mock_client.upload_documents.called
    
    # Capture documents passed to upload (keyword argument)
    uploaded_docs = mock_client.upload_documents.call_args.kwargs["documents"]
    assert len(uploaded_docs) == 2
    assert uploaded_docs[0]["id"] == "c1"
    assert uploaded_docs[1]["text"] == "Contenido 2"

    # 3. Simulate "Retrieval" (Search)
    # We mock the search method to return what we "indexed"
    mock_client.search.return_value = [
        {"id": "c1", "text": "Contenido 1", "pliego_id": "p1"},
        {"id": "c2", "text": "Contenido 2", "pliego_id": "p1"}
    ]
    
    # Simple search call
    search_results = list(mock_client.search(search_text="Contenido", filter="pliego_id eq 'p1'"))
    
    assert len(search_results) == 2
    assert search_results[0]["id"] == "c1"
    assert search_results[1]["text"] == "Contenido 2"
    assert mock_client.search.called
