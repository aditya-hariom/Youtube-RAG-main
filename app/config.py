import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # API Keys
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    COHERE_API_KEY = os.getenv("COHERE_API_KEY")

    # Data Paths
    DATA_DIR = "data"
    CACHE_DIR = os.path.join(DATA_DIR, "cache")
    CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")

    # Embedding and LLM Settings
    # Cohere Models: "embed-multilingual-v3.0" (1024-dim, high quality) or "embed-multilingual-light-v3.0" (384-dim, fast)
    EMBEDDING_MODEL = "embed-multilingual-v3.0"
    LLM_MODEL = "gemini-3.6-flash"
    EMBEDDING_BATCH_SIZE = 96  # Cohere supports up to 96 items per API call
    
    @staticmethod
    def get_embedding_device() -> str:
        """Auto-detect best available device: CUDA GPU > Apple MPS > CPU."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    # Chunking Settings
    # Cohere multilingual-v3 supports up to 512 tokens (~1500 chars). 800 chars provides rich context.
    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 120

    # Retrieval Settings
    TOP_K = 8
    MAX_DISTANCE = 0.70  # Cosine distance threshold (allows comprehensive multi-chunk retrieval)

    @classmethod
    def setup_directories(cls):
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.CACHE_DIR, exist_ok=True)
        os.makedirs(cls.CHROMA_PATH, exist_ok=True)

# Ensure directories exist on load
Config.setup_directories()
