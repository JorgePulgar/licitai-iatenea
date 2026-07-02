import asyncio
from typing import List
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from openai import AsyncAzureOpenAI
import openai

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import Chunk

logger = get_logger(__name__)

# Configuración
BATCH_SIZE = 100
MAX_RETRIES = 3
INITIAL_BACKOFF = 1  # segundos

def get_openai_client() -> AsyncAzureOpenAI | None:
    if not settings.AZURE_OPENAI_ENDPOINT:
        return None
        
    # Si hay KEY, usamos API Key. Si no, usamos Entra ID (DefaultAzureCredential)
    # Por defecto openai SDK prefiere api_key o azure_ad_token_provider
    if settings.AZURE_OPENAI_KEY:
        return AsyncAzureOpenAI(
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-15-preview",
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
        )
    else:
        # Autenticación basada en identidad de Azure (Identity)
        credential = DefaultAzureCredential()
        async def get_token():
            # OpenAI espera un token para el recurso de Cognitive Services
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            return token.token
            
        return AsyncAzureOpenAI(
            azure_ad_token_provider=get_token,
            api_version="2024-02-15-preview",
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
        )

async def _embed_batch_with_retry(client: AsyncAzureOpenAI, texts: List[str]) -> List[List[float]]:
    """Genera embeddings para un batch de textos con reintentos exponenciales."""
    for attempt in range(MAX_RETRIES):
        try:
            # Reemplazar retornos de carro por espacios (buena práctica para embeddings)
            clean_texts = [text.replace("\n", " ") for text in texts]
            
            response = await client.embeddings.create(
                input=clean_texts,
                model="text-embedding-3-small"
            )
            # Retornamos los embeddings ordenados
            return [data.embedding for data in response.data]
            
        except openai.RateLimitError as e:
            if attempt == MAX_RETRIES - 1:
                logger.error("Se superó el límite de tasa de OpenAI tras reintentos.")
                raise e
            sleep_time = INITIAL_BACKOFF * (2 ** attempt)
            logger.warning(f"Rate limit de OpenAI. Reintentando en {sleep_time}s...")
            await asyncio.sleep(sleep_time)
        except Exception as e:
            logger.error(f"Error generando embeddings: {e}")
            raise e
            
    return []

async def embed_text(text: str) -> list[float] | None:
    """Genera el embedding de una cadena de texto individual (p.ej. una query RAG)."""
    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — no se puede generar embedding de la query.")
        return None
    clean = text.replace("\n", " ")
    response = await client.embeddings.create(input=[clean], model="text-embedding-3-small")
    return response.data[0].embedding


async def embed_chunks(chunks: List[Chunk]) -> List[Chunk]:
    """
    Toma una lista de chunks, extrae su texto y obtiene los embeddings de Azure OpenAI.
    Devuelve los mismos chunks pero con un campo extra `embedding` si se decidiera
    modificar el esquema Pydantic, o en este caso devuelve un objeto mapeado para AI Search.
    (Como la salida irá directo a index_chunks, lo devolvemos como dict o mantenemos la lista)
    """
    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no está configurado. Se omitirá la generación de embeddings.")
        return chunks

    if not chunks:
        return chunks

    logger.info(f"Generando embeddings para {len(chunks)} chunks en batches de {BATCH_SIZE}...")

    # Separar en batches
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [chunk.content for chunk in batch]
        
        embeddings = await _embed_batch_with_retry(client, texts)
        
        # Asignar a los chunks (se asume que se le añade un atributo dinámicamente
        # o que el proceso posterior leerá `chunk.embedding`)
        for chunk, emb in zip(batch, embeddings):
            chunk.embedding = emb
            
    logger.info("Generación de embeddings completada.")
    return chunks
