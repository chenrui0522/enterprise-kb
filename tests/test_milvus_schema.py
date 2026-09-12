import uuid

import pytest

from app.core.config import Settings
from app.retrieval.chunk import ChunkRecord
from app.retrieval.milvus_store import MilvusStore


def _milvus_available(uri: str) -> bool:
    try:
        from pymilvus import MilvusClient

        MilvusClient(uri=uri).list_collections()
        return True
    except Exception:
        return False


def test_structure_schema_insert_and_hybrid_search() -> None:
    settings = Settings(milvus_collection=f"kb_chunks_schema_test_{uuid.uuid4().hex[:8]}")
    if not _milvus_available(settings.milvus_uri):
        pytest.skip("Milvus is not available")
    store = MilvusStore(settings)
    try:
        store.ensure_collection()
        vector = [0.01] * settings.milvus_vector_dim
        chunk = ChunkRecord(
            id="test-0",
            text="差旅制度 第一条 员工出差需提前审批。",
            title="差旅制度",
            doc_id="d1",
            version_id="v1",
            chunk_index=0,
            page=1,
            section="差旅制度",
            tenant_id="t1",
            vector=vector,
            chunk_type="policy_clause",
            heading_path="差旅制度",
            clause_no="第一条",
            chunker_version="structure-v1:policy",
        )
        assert store.insert([chunk]) == 1
        store.flush()
        hits = store.hybrid_search("第一条 出差审批", vector, "t1", 5)
        assert hits
        assert hits[0]["chunk_type"] == "policy_clause"
        assert hits[0]["clause_no"] == "第一条"
        assert hits[0]["heading_path"] == "差旅制度"
        assert hits[0]["chunker_version"] == "structure-v1:policy"
    finally:
        store.drop_collection()