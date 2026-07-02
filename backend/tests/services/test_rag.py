import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.embeddings import embed_chunks
from app.services.indexing import index_chunks, delete_pliego_from_index
from app.models.schemas import Chunk


@pytest.fixture
def sample_chunks():
    return [
        Chunk(
            chunk_id="chunk-1",
            pliego_id="pliego-1",
            licitacion_id="licitacion-1",
            user_id="user-1",
            document_type="pcap",
            filename="pcap.pdf",
            content="Este es el chunk 1",
            page_number=1,
        ),
        Chunk(
            chunk_id="chunk-2",
            pliego_id="pliego-1",
            licitacion_id="licitacion-1",
            user_id="user-1",
            document_type="pcap",
            filename="pcap.pdf",
            content="Este es el chunk 2",
            page_number=2,
        ),
    ]


@pytest.mark.asyncio
async def test_embed_chunks_success(sample_chunks, mocker):
    mocker.patch("app.services.embeddings.settings.AZURE_OPENAI_ENDPOINT", "https://mock.openai.azure.com/")
    mocker.patch("app.services.embeddings.settings.AZURE_OPENAI_KEY", "mock-key")

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2, 0.3]),
        MagicMock(embedding=[0.4, 0.5, 0.6]),
    ]
    mock_client.embeddings.create.return_value = mock_response
    mocker.patch("app.services.embeddings.get_openai_client", return_value=mock_client)

    result_chunks = await embed_chunks(sample_chunks)

    assert len(result_chunks) == 2
    assert result_chunks[0].embedding == [0.1, 0.2, 0.3]
    assert result_chunks[1].embedding == [0.4, 0.5, 0.6]
    mock_client.embeddings.create.assert_called_once()


def test_index_chunks_success(sample_chunks, mocker):
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_ENDPOINT", "https://mock.search.windows.net")
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_KEY", "mock-key")

    mock_client = MagicMock()
    mock_client.upload_documents.return_value = [MagicMock(succeeded=True), MagicMock(succeeded=True)]
    mocker.patch("app.services.indexing.get_search_client", return_value=mock_client)

    for chunk in sample_chunks:
        chunk.embedding = [0.1, 0.2, 0.3]

    result = index_chunks(sample_chunks)

    assert result.pliego_id == "pliego-1"
    assert result.chunks_indexed == 2
    assert result.status == "success"

    # Verify the uploaded documents include the new fields
    call_args = mock_client.upload_documents.call_args
    uploaded = call_args.kwargs["documents"] if call_args.kwargs else call_args[1]["documents"]
    assert uploaded[0]["licitacion_id"] == "licitacion-1"
    assert uploaded[0]["user_id"] == "user-1"
    assert uploaded[0]["document_type"] == "pcap"
    assert uploaded[0]["filename"] == "pcap.pdf"


def test_delete_pliego_from_index(mocker):
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_ENDPOINT", "https://mock.search.windows.net")
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_KEY", "mock-key")

    mock_client = MagicMock()
    # Primera pasada devuelve docs, segunda vacía → bucle termina.
    mock_client.search.side_effect = [[{"id": "chunk-1"}, {"id": "chunk-2"}], []]
    mocker.patch("app.services.indexing.get_search_client", return_value=mock_client)

    delete_pliego_from_index("pliego-1")

    assert mock_client.search.call_count == 2
    mock_client.delete_documents.assert_called_once_with(documents=[{"id": "chunk-1"}, {"id": "chunk-2"}])


def test_index_chunks_batches_over_1000(mocker):
    """>1000 chunks deben subirse en lotes de ≤1000 (límite de Azure AI Search)."""
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_ENDPOINT", "https://mock.search.windows.net")
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_KEY", "mock-key")

    mock_client = MagicMock()
    # upload_documents devuelve un resultado "succeeded" por documento del lote.
    mock_client.upload_documents.side_effect = lambda documents: [MagicMock(succeeded=True) for _ in documents]
    mocker.patch("app.services.indexing.get_search_client", return_value=mock_client)

    chunks = [
        Chunk(
            chunk_id=f"c{i}", pliego_id="p1", licitacion_id="l1", user_id="u1",
            document_type="pcap", filename="d.pdf", content="x", page_number=1,
            seq=i, embedding=[0.1, 0.2, 0.3],
        )
        for i in range(1500)
    ]
    result = index_chunks(chunks)

    # 1500 → lotes de 1000 + 500 = 2 llamadas; todos indexados.
    assert mock_client.upload_documents.call_count == 2
    assert result.chunks_indexed == 1500
    assert result.status == "success"


def test_delete_pliego_loops_until_empty(mocker):
    """El borrado pagina (≤1000 por pasada) hasta vaciar el pliego."""
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_ENDPOINT", "https://mock.search.windows.net")
    mocker.patch("app.services.indexing.settings.AZURE_SEARCH_KEY", "mock-key")

    mock_client = MagicMock()
    pass1 = [{"id": f"c{i}"} for i in range(1000)]
    pass2 = [{"id": f"c{i}"} for i in range(1000, 1200)]
    mock_client.search.side_effect = [pass1, pass2, []]
    mocker.patch("app.services.indexing.get_search_client", return_value=mock_client)

    delete_pliego_from_index("pliego-big")

    assert mock_client.search.call_count == 3
    assert mock_client.delete_documents.call_count == 2
