import chromadb
import numpy as np
from app.config import Config
from app.models import DocumentChunk, RetrievedChunk
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class VectorStore:
    def __init__(self):
        import re
        self.client = chromadb.PersistentClient(path=Config.CHROMA_PATH)
        # Create a unique collection name based on the embedding model
        # to seamlessly prevent mixing different dimensions.
        safe_model_name = re.sub(r'[^a-zA-Z0-9_-]', '-', Config.EMBEDDING_MODEL)
        collection_name = f"youtube_rag_{safe_model_name}"
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def _validate_dimension(self, embedding_dim: int):
        """Checks that the given embedding dimension matches the existing collection's dimension."""
        sample = self.collection.get(limit=1, include=["embeddings"])
        if sample and sample.get("embeddings") is not None and len(sample["embeddings"]) > 0:
            collection_dim = len(sample["embeddings"][0])
            if collection_dim != embedding_dim:
                raise ValueError(
                    f"Collection expecting embedding with dimension of {collection_dim}, got {embedding_dim}. "
                    "The ChromaDB collection was created with a different embedding model/dimension."
                )

    def store_embeddings(self, chunks: list[DocumentChunk], embeddings: np.ndarray, video_id: str):
        """Stores chunks and embeddings in ChromaDB."""
        # Check if video_id already exists to avoid duplicate work
        existing = self.collection.get(where={"video_id": video_id}, limit=1)
        if existing and existing.get("ids") is not None and len(existing["ids"]) > 0:
            logger.info(f"Embeddings for {video_id} already exist in vector store.")
            return
            
        if len(embeddings) > 0:
            self._validate_dimension(len(embeddings[0]))
            
        logger.info(f"Storing {len(chunks)} embeddings in ChromaDB for video {video_id}...")
        
        ids = [f"{video_id}_{chunk.chunk_id}" for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "chunk_id": chunk.chunk_id,
                "video_id": chunk.video_id,
                "url": chunk.url,
                "start_time": float(chunk.start_time),
                "end_time": float(chunk.end_time)
            }
            for chunk in chunks
        ]
        
        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings.tolist(),
            metadatas=metadatas
        )
        
        logger.info("Embeddings successfully stored in Vector Store!")

    def retrieve(self, query_embedding: list[float], video_id: str) -> list[RetrievedChunk]:
        """Retrieves top K similar chunks for a specific video."""
        logger.info(f"Retrieving context from vector store for {video_id}...")
        
        self._validate_dimension(len(query_embedding))
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=Config.TOP_K,
            where={"video_id": video_id}
        )
        
        if not results["documents"] or not results["documents"][0]:
            return []
            
        retrieved = []
        documents = results["documents"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]
        
        for document, distance, metadata in zip(documents, distances, metadatas):
            if distance <= Config.MAX_DISTANCE:
                chunk = RetrievedChunk(
                    chunk_id=metadata["chunk_id"],
                    text=document,
                    video_id=metadata["video_id"],
                    url=metadata["url"],
                    start_time=float(metadata.get("start_time", 0.0)),
                    end_time=float(metadata.get("end_time", 0.0)),
                    similarity_score=float(distance)
                )
                retrieved.append(chunk)
                
        best_dist = f"{distances[0]:.4f}" if distances else "N/A"
        if retrieved:
            logger.info(f"Retrieved {len(retrieved)} chunks within distance threshold {Config.MAX_DISTANCE} (best distance: {best_dist}).")
        else:
            logger.warning(f"Retrieved 0 chunks within threshold {Config.MAX_DISTANCE}. Closest candidate distance was: {best_dist}")
        return retrieved

    def delete_video(self, video_id: str):
        """Deletes all chunks associated with a video_id from the vector store."""
        logger.info(f"Deleting vector store data for video {video_id}...")
        self.collection.delete(where={"video_id": video_id})
        logger.info(f"Successfully deleted vector store data for video {video_id}.")

