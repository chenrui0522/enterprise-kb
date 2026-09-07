from __future__ import annotations

from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    RRFRanker,
)

from app.core.config import Settings
from app.core.logging import get_logger
from app.retrieval.chunk import ChunkRecord

logger = get_logger("retrieval.milvus")


class MilvusStore:
    """Vector + BM25 hybrid store backed by Milvus 2.5."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = MilvusClient(uri=settings.milvus_uri)
        self._collection = settings.milvus_collection
        self._ready = False

    def ensure_collection(self) -> None:
        if self._ready:
            return
        if self._client.has_collection(self._collection):
            self._ready = True
            return

        settings = self._settings
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field(
            field_name="text",
            datatype=DataType.VARCHAR,
            max_length=4096,
            enable_analyzer=True,
            analyzer_params={"type": "standard"},
        )
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="version_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="page", datatype=DataType.INT64)
        schema.add_field(field_name="section", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="tenant_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=settings.milvus_vector_dim)
        schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="text_bm25_emb",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )

        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(
            field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
        )
        self._client.create_collection(
            collection_name=self._collection, schema=schema, index_params=index_params
        )
        self._ready = True
        logger.info("Created Milvus collection %s", self._collection)

    def insert(self, chunks: list[ChunkRecord]) -> int:
        self.ensure_collection()
        rows = [
            {
                "id": chunk.id,
                "text": chunk.text,
                "title": chunk.title,
                "doc_id": chunk.doc_id,
                "version_id": chunk.version_id,
                "chunk_index": chunk.chunk_index,
                "page": chunk.page,
                "section": chunk.section,
                "tenant_id": chunk.tenant_id,
                "dense": chunk.vector,
            }
            for chunk in chunks
        ]
        if not rows:
            return 0
        result = self._client.upsert(collection_name=self._collection, data=rows)
        return int(result.get("upsert_count", len(rows)))

    def delete_by_version(self, version_id: str) -> None:
        if not self._client.has_collection(self._collection):
            return
        self._client.delete(self._collection, filter=f'version_id == "{version_id}"')

    def hybrid_search(self, query: str, query_vector: list[float], tenant_id: str, top_n: int) -> list[dict]:
        """Hybrid dense + BM25 search scoped to a tenant."""
        self.ensure_collection()
        expr = f'tenant_id == "{tenant_id}"'
        dense_req = AnnSearchRequest(
            data=[query_vector],
            anns_field="dense",
            param={"metric_type": "COSINE"},
            limit=top_n,
            expr=expr,
        )
        bm25_req = AnnSearchRequest(
            data=[query],
            anns_field="sparse",
            param={"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
            limit=top_n,
            expr=expr,
        )
        results = self._client.hybrid_search(
            collection_name=self._collection,
            reqs=[dense_req, bm25_req],
            ranker=RRFRanker(),
            limit=top_n,
            output_fields=["id", "text", "title", "doc_id", "version_id", "page", "section"],
        )
        return [_hit_to_dict(hit) for hit in (results[0] if results else [])]


def _hit_to_dict(hit) -> dict:
    entity = dict(hit.get("entity") or {})
    return {
        "id": str(entity.get("id") or hit.get("id")),
        "text": entity.get("text", ""),
        "title": entity.get("title", ""),
        "doc_id": entity.get("doc_id", ""),
        "version_id": entity.get("version_id", ""),
        "page": int(entity.get("page") or 0),
        "section": entity.get("section", ""),
        "score": float(hit.get("distance") or 0.0),
    }
