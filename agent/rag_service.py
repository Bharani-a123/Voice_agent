"""
rag_service.py — Multi-tenant Retrieval-Augmented Generation (RAG) service.
Uses Qdrant local storage and FastEmbed for zero-dependency local vector search.
Enforces clinic_id tenant isolation at query time.
"""

import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import TextEmbedding

# Local persistent Qdrant storage path
QDRANT_PATH = os.path.join("db", "qdrant_db")
COLLECTION_NAME = "clinic_faqs"


class RAGService:
    """Provides local embedding generation, vector indexing, and multi-tenant search."""

    def __init__(self):
        import sys
        # If running inside pytest, use an in-memory database to prevent storage lock conflicts
        is_testing = "pytest" in sys.modules or os.environ.get("TESTING") == "true"
        if is_testing:
            print("[RAG] [TEST] Running in testing environment. Using in-memory Qdrant database.")
            self.client = QdrantClient(location=":memory:")
        else:
            self.client = QdrantClient(path=QDRANT_PATH)

        # Initialize FastEmbed CPU-optimized local embedding model
        # Default model is 'BAAI/bge-small-en-v1.5' (384-dimensional, highly accurate and fast)
        self.encoder = TextEmbedding()
        self.vector_size = 384  # bge-small-en-v1.5 dimension

        self._ensure_collection_exists()

    def _ensure_collection_exists(self):
        """Creates the Qdrant collection if it does not already exist."""
        collections = self.client.get_collections().collections
        exists = any(c.name == COLLECTION_NAME for c in collections)

        if not exists:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE
                )
            )
            print(f"[RAG] Collection '{COLLECTION_NAME}' created successfully.")

    def ingest_faq_text(self, clinic_id: str, source_name: str, faq_text: str):
        """
        Ingests raw text. Breaks it down into chunks, embeds them,
        and saves them to Qdrant with clinic_id metadata filter tags.
        """
        # Split text by double newlines into distinct Q&A blocks/paragraphs
        paragraphs = [p.strip() for p in faq_text.split("\n\n") if p.strip()]

        if not paragraphs:
            return

        # Generate embeddings in a single batch
        embeddings = list(self.encoder.embed(paragraphs))

        points = []
        for i, (text, vector) in enumerate(zip(paragraphs, embeddings)):
            import uuid
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{clinic_id}_{source_name}_{i}"))

            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector.tolist(),
                    payload={
                        "clinic_id": clinic_id,
                        "source": source_name,
                        "text": text
                    }
                )
            )

        # Upsert into Qdrant
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
        print(f"[RAG] Ingested {len(points)} chunks for clinic {clinic_id} ({source_name}).")

    def query(self, clinic_id: str, query_text: str, limit: int = 2) -> list[str]:
        """
        Embeds the query text and searches the local Qdrant collection.
        Uses a metadata filter on clinic_id to guarantee multi-tenant security boundary.
        """
        # Generate query vector (takes first output of embedding generator)
        query_vector = next(self.encoder.embed([query_text])).tolist()

        # Query Qdrant with a metadata filter on clinic_id using query_points (modern API)
        results = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="clinic_id",
                        match=models.MatchValue(value=clinic_id)
                    )
                ]
            ),
            limit=limit
        )

        # Extract text content from hits
        passages = [point.payload["text"] for point in results.points if point.payload]
        return passages


# Singleton instance
rag = RAGService()
