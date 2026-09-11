import os
import time
import numpy as np
from app.config import Config
from app.models import DocumentChunk
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

_LOCAL_MODEL_CACHE = {}


class EmbeddingService:
    def __init__(self):
        self.co_client = None
        self.local_model = None

    def _is_cohere(self) -> bool:
        """Determines if the configured model should use the Cohere API."""
        return bool(
            Config.COHERE_API_KEY
            and (
                "embed-" in Config.EMBEDDING_MODEL.lower()
                or "cohere" in Config.EMBEDDING_MODEL.lower()
            )
        )

    def _get_cohere_client(self):
        if self.co_client is None:
            if not Config.COHERE_API_KEY:
                raise ValueError("COHERE_API_KEY not found. Please set it in your .env file.")
            import cohere
            self.co_client = cohere.Client(api_key=Config.COHERE_API_KEY)
            logger.info("Initialized Cohere API client.")
        return self.co_client

    def _load_local_model(self):
        global _LOCAL_MODEL_CACHE
        if self.local_model is None:
            if Config.EMBEDDING_MODEL not in _LOCAL_MODEL_CACHE:
                from sentence_transformers import SentenceTransformer
                device = Config.get_embedding_device()
                logger.info(f"Loading local embedding model '{Config.EMBEDDING_MODEL}' on device: {device}")
                _LOCAL_MODEL_CACHE[Config.EMBEDDING_MODEL] = SentenceTransformer(
                    Config.EMBEDDING_MODEL,
                    device=device
                )
                logger.info(f"Local embedding model loaded successfully on {device}.")
            self.local_model = _LOCAL_MODEL_CACHE[Config.EMBEDDING_MODEL]

    def load_model(self):
        """Eager initialization used during startup/lifespan."""
        if self._is_cohere():
            self._get_cohere_client()
        else:
            self._load_local_model()

    def generate_embeddings(self, chunks: list[DocumentChunk], video_id: str) -> np.ndarray:
        """Generates embeddings for chunks using Cohere API or local model. Uses cache if available."""
        output_dir = os.path.join(Config.CACHE_DIR, video_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # Include model name in cache identity to prevent reusing incompatible embeddings
        model_safe_name = Config.EMBEDDING_MODEL.replace('/', '_').replace('\\', '_')
        embeddings_path = os.path.join(output_dir, f"embeddings_{model_safe_name}.npy")
        
        if os.path.exists(embeddings_path):
            logger.info(f"Using cached embeddings for model '{Config.EMBEDDING_MODEL}'.")
            return np.load(embeddings_path)
            
        texts = [chunk.text for chunk in chunks]
        start_time = time.perf_counter()

        if self._is_cohere():
            logger.info(f"Generating embeddings via Cohere API ({Config.EMBEDDING_MODEL}) for {len(chunks)} chunks...")
            client = self._get_cohere_client()
            all_embeddings = []
            
            # Batch in Config.EMBEDDING_BATCH_SIZE (up to 96 per call)
            for i in range(0, len(texts), Config.EMBEDDING_BATCH_SIZE):
                batch = texts[i : i + Config.EMBEDDING_BATCH_SIZE]
                response = client.embed(
                    texts=batch,
                    model=Config.EMBEDDING_MODEL,
                    input_type="search_document"
                )
                all_embeddings.extend(response.embeddings)
            
            embeddings = np.array(all_embeddings, dtype=np.float32)
        else:
            self._load_local_model()
            logger.info(f"Generating embeddings via local model for {len(chunks)} chunks (batch_size={Config.EMBEDDING_BATCH_SIZE})...")
            embeddings = self.local_model.encode(
                texts,
                batch_size=Config.EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True
            )

        elapsed = time.perf_counter() - start_time
        
        # Cache embeddings
        np.save(embeddings_path, embeddings)
        logger.info(f"Embeddings generated in {elapsed:.2f}s and cached. Shape: {embeddings.shape}")
        return embeddings

    def embed_query(self, query: str) -> list[float]:
        """Embeds a single search query."""
        if self._is_cohere():
            client = self._get_cohere_client()
            response = client.embed(
                texts=[query],
                model=Config.EMBEDDING_MODEL,
                input_type="search_query"
            )
            return response.embeddings[0]
        else:
            self._load_local_model()
            query_embedding = self.local_model.encode(
                query,
                normalize_embeddings=True
            )
            return query_embedding.tolist()

