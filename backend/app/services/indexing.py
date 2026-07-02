from typing import List, Any
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SimpleField,
    SearchableField,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration,
    HnswParameters,
    SemanticConfiguration,
    SemanticPrioritizedFields,
    SemanticField,
    SemanticSearch
)

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import Chunk, IndexResult

logger = get_logger(__name__)


def get_search_client() -> SearchClient | None:
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    return SearchClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=settings.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY)
    )


def get_index_client() -> SearchIndexClient | None:
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    return SearchIndexClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY)
    )


def create_index_if_not_exists() -> None:
    """
    Creates the Azure AI Search index if it doesn't exist.
    Supports hybrid search (keyword + vector) and semantic reranking.
    Fields are tagged per licitacion, user, and document type for strict isolation.
    """
    client = get_index_client()
    if not client:
        logger.warning("AI Search credentials not configured. Skipping index creation.")
        return

    index_name = settings.AZURE_SEARCH_INDEX_NAME

    fields = [
        SimpleField(name="id", type="Edm.String", key=True),
        SimpleField(name="chunk_id", type="Edm.String"),
        # Isolation fields — always used in search filters
        SimpleField(name="pliego_id", type="Edm.String", filterable=True),
        SimpleField(name="licitacion_id", type="Edm.String", filterable=True, facetable=True),
        SimpleField(name="user_id", type="Edm.String", filterable=True),
        SimpleField(name="document_type", type="Edm.String", filterable=True),
        SearchableField(name="filename", type="Edm.String"),
        # Content
        SearchableField(name="text", type="Edm.String", analyzer_name="es.microsoft"),
        SearchableField(name="section_heading", type="Edm.String", analyzer_name="es.microsoft"),
        SimpleField(name="page_number", type="Edm.Int32", filterable=True),
        # Ordinal de lectura dentro del pliego — sortable/filterable para la expansión
        # por vecinos (recuperar seq±1 del mismo pliego_id).
        SimpleField(name="seq", type="Edm.Int32", filterable=True, sortable=True),
        SearchField(
            name="embedding",
            type="Collection(Edm.Single)",
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="licitai-vector-profile"
        )
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name="licitai-hnsw",
                parameters=HnswParameters(metric="cosine")
            )
        ],
        profiles=[
            VectorSearchProfile(
                name="licitai-vector-profile",
                algorithm_configuration_name="licitai-hnsw"
            )
        ]
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="licitai-semantic-config",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="filename"),
                    content_fields=[
                        SemanticField(field_name="section_heading"),
                        SemanticField(field_name="text"),
                    ],
                    keywords_fields=[SemanticField(field_name="text")]
                )
            )
        ]
    )

    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search
    )

    try:
        client.create_or_update_index(index)
        logger.info(f"Index '{index_name}' synced with Azure AI Search.")
    except Exception as e:
        logger.error(f"Failed to create index '{index_name}': {e}")


# Azure AI Search limita cada petición de indexación a 1000 documentos y cada
# consulta a 1000 resultados. Subidas/borrados deben trocearse o se pierden docs
# de forma silenciosa (pliegos grandes quedaban con chunks viejos sin borrar).
SEARCH_BATCH = 1000
# Tope de pasadas del borrado por lotes: protege contra el lag de consistencia
# eventual de Azure (un search inmediato tras delete puede ver docs ya marcados).
DELETE_MAX_PASSES = 50


def index_chunks(chunks: List[Chunk]) -> IndexResult:
    """
    Uploads chunks to the Azure AI Search index in batches of SEARCH_BATCH.
    Assumes chunks already have the `embedding` field populated.
    """
    if not chunks:
        return IndexResult(pliego_id="unknown", chunks_indexed=0, status="no chunks")

    pliego_id = chunks[0].pliego_id
    client = get_search_client()
    if not client:
        logger.warning(f"Azure Search not configured. Simulating indexing of {len(chunks)} chunks.")
        return IndexResult(pliego_id=pliego_id, chunks_indexed=len(chunks), status="simulated")

    documents: list[dict[str, Any]] = []
    for c in chunks:
        doc: dict[str, Any] = {
            "id": c.chunk_id,
            "chunk_id": c.chunk_id,
            "pliego_id": c.pliego_id,
            "licitacion_id": c.licitacion_id.lower(),
            "user_id": c.user_id.lower(),
            "document_type": c.document_type,
            "filename": c.filename,
            "text": c.content,
            "section_heading": c.section_heading or "",
            "page_number": c.page_number or 1,
            "seq": c.seq,
        }
        if c.embedding:
            doc["embedding"] = c.embedding
        documents.append(doc)

    logger.info(f"Uploading {len(documents)} chunks to AI Search for pliego {pliego_id}...")

    succeeded = 0
    failed = 0
    try:
        for i in range(0, len(documents), SEARCH_BATCH):
            batch = documents[i:i + SEARCH_BATCH]
            results = client.upload_documents(documents=batch)
            for r in results:
                if r.succeeded:
                    succeeded += 1
                else:
                    failed += 1
                    logger.error(f"Doc {r.key} failed: status={r.status_code} error={r.error_message}")

        if failed > 0:
            logger.error(f"{failed} documents failed to index for pliego {pliego_id}.")

        logger.info(f"Indexed {succeeded} chunks successfully.")
        return IndexResult(
            pliego_id=pliego_id,
            chunks_indexed=succeeded,
            status="success" if failed == 0 else "partial_error"
        )

    except Exception as e:
        logger.error(f"Error uploading documents to AI Search: {e}")
        return IndexResult(pliego_id=pliego_id, chunks_indexed=0, status="error")


def delete_pliego_from_index(pliego_id: str) -> None:
    """Deletes all chunks for a given pliego_id from the index.

    Borra por pasadas (search ≤1000 → delete ≤1000) hasta no quedar ninguno: una
    sola consulta nunca devuelve más de 1000 resultados, así que pliegos con más
    chunks dejaban restos. El tope DELETE_MAX_PASSES evita un bucle infinito si el
    lag de consistencia hace reaparecer docs ya borrados.
    """
    client = get_search_client()
    if not client:
        logger.info(f"Simulating AI Search deletion for pliego {pliego_id}")
        return

    logger.info(f"Deleting chunks for pliego {pliego_id} from AI Search...")
    try:
        total_deleted = 0
        for _ in range(DELETE_MAX_PASSES):
            results = client.search(
                search_text="*",
                filter=f"pliego_id eq '{pliego_id.lower()}'",
                select=["id"],
                top=SEARCH_BATCH,
            )
            docs_to_delete = [{"id": doc["id"]} for doc in results]
            if not docs_to_delete:
                break
            client.delete_documents(documents=docs_to_delete)
            total_deleted += len(docs_to_delete)

        if total_deleted == 0:
            logger.info(f"No chunks found in AI Search for pliego {pliego_id}.")
        else:
            logger.info(f"Deleted {total_deleted} chunks for pliego {pliego_id}.")

    except Exception as e:
        logger.error(f"Error deleting chunks for pliego {pliego_id} from AI Search: {e}")
