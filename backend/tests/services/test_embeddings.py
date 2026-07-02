import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.embeddings import embed_chunks
from app.models.schemas import Chunk

_CTX = dict(licitacion_id="l1", user_id="u1", document_type="pcap", filename="doc.pdf")


@pytest.fixture
def mock_chunks():
    return [
        Chunk(chunk_id="1", pliego_id="p1", content="Texto 1", **_CTX),
        Chunk(chunk_id="2", pliego_id="p1", content="Texto 2", **_CTX),
        Chunk(chunk_id="3", pliego_id="p1", content="Texto 3", **_CTX)
    ]

@patch("app.services.embeddings.get_openai_client")
@pytest.mark.asyncio
async def test_embed_chunks_success(mock_get_client, mock_chunks):
    # Setup mock client
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    
    # Mock response from Azure OpenAI
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1, 0.2, 0.3]),
        MagicMock(embedding=[0.4, 0.5, 0.6]),
        MagicMock(embedding=[0.7, 0.8, 0.9])
    ]
    mock_client.embeddings.create.return_value = mock_response
    
    # Run service
    result = await embed_chunks(mock_chunks)
    
    # Verify
    assert len(result) == 3
    assert result[0].embedding == [0.1, 0.2, 0.3]
    assert result[1].embedding == [0.4, 0.5, 0.6]
    assert result[2].embedding == [0.7, 0.8, 0.9]
    assert mock_client.embeddings.create.called

@patch("app.services.embeddings.get_openai_client")
@pytest.mark.asyncio
async def test_embed_chunks_batching(mock_get_client):
    # Setup mock client
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    
    # Mock 150 chunks
    large_batch = [Chunk(chunk_id=str(i), pliego_id="p1", content=f"Texto {i}", **_CTX) for i in range(150)]
    
    # Mock responses for 2 batches (100 + 50)
    mock_response_1 = MagicMock()
    mock_response_1.data = [MagicMock(embedding=[0.1]*1536) for _ in range(100)]
    
    mock_response_2 = MagicMock()
    mock_response_2.data = [MagicMock(embedding=[0.2]*1536) for _ in range(50)]
    
    mock_client.embeddings.create.side_effect = [mock_response_1, mock_response_2]
    
    # Run service
    result = await embed_chunks(large_batch)
    
    # Verify
    assert len(result) == 150
    assert mock_client.embeddings.create.call_count == 2
    assert result[0].embedding == [0.1]*1536
    assert result[149].embedding == [0.2]*1536

@patch("app.services.embeddings.get_openai_client")
@patch("app.services.embeddings.INITIAL_BACKOFF", 0.01) # Faster test
@pytest.mark.asyncio
async def test_embed_chunks_retry(mock_get_client, mock_chunks):
    # Setup mock client
    mock_client = AsyncMock()
    mock_get_client.return_value = mock_client
    
    import openai
    # Mock failure then success
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1]*1536) for _ in range(len(mock_chunks))]
    
    mock_client.embeddings.create.side_effect = [
        openai.RateLimitError(message="Rate limit reached", response=MagicMock(), body={}),
        mock_response
    ]
    
    # Run service
    result = await embed_chunks(mock_chunks)
    
    # Verify
    assert len(result) == 3
    assert mock_client.embeddings.create.call_count == 2
    assert result[0].embedding == [0.1]*1536
