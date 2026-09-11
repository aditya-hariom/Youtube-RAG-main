from typing import Callable, Any
from app.models import VideoMetadata, RAGResponse
from app.services.youtube_service import YouTubeService
from app.services.transcript_service import TranscriptService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.services.rag_service import RAGService
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class YouTubeRAGPipeline:
    def __init__(self):
        self.youtube_service = YouTubeService()
        self.transcript_service = TranscriptService()
        self.chunking_service = ChunkingService()
        self.embedding_service = EmbeddingService()
        self.vector_store = VectorStore()
        self.rag_service = RAGService()

    def process_video(self, url: str, progress_callback: Callable[[str, float], None] = None) -> tuple[VideoMetadata, list]:
        """
        Orchestrates the optimized ingestion pipeline:
        1. Extract ID & fast metadata + transcript (parallel)
        2. Create timestamped chunks
        3. Embed
        4. Store
        """
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def update_progress(msg, val):
            if progress_callback:
                progress_callback(msg, val)
        
        try:
            pipeline_start = time.perf_counter()
            
            # 1. Extract video ID (instant)
            video_id = self.youtube_service.extract_video_id(url)
            
            # 2. Fetch metadata & transcript IN PARALLEL (they only need video_id, not each other)
            update_progress("Fetching metadata & transcript...", 0.1)
            metadata = None
            segments = None
            
            def _fetch_metadata():
                return self.youtube_service.get_metadata(url, video_id)
            
            def _fetch_transcript():
                return self.transcript_service.get_transcript_segments(video_id)
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                meta_future = executor.submit(_fetch_metadata)
                transcript_future = executor.submit(_fetch_transcript)
                
                metadata = meta_future.result()
                
                try:
                    segments = transcript_future.result()
                except Exception as e:
                    logger.info(f"Online transcript unavailable ({e}), downloading audio for Whisper...")
                    update_progress("Downloading audio for transcription...", 0.4)
                    audio_path, _ = self.youtube_service.download_audio(url, video_id)
                    update_progress("Transcribing with local Whisper...", 0.5)
                    segments = self.transcript_service.get_transcript_segments(video_id, audio_path)

            if not segments:
                raise ValueError("Transcript could not be extracted.")
            
            step1_time = time.perf_counter() - pipeline_start
            logger.info(f"[Pipeline] Metadata + Transcript fetched in {step1_time:.1f}s")
                
            # 3. Timestamp-aware Chunking
            update_progress("Creating timestamped chunks...", 0.65)
            step_start = time.perf_counter()
            chunks = self.chunking_service.create_chunks(segments, video_id, url, metadata=metadata)
            logger.info(f"[Pipeline] Chunking completed in {time.perf_counter() - step_start:.1f}s")
            
            # 4. Embedding
            update_progress("Generating embeddings...", 0.8)
            step_start = time.perf_counter()
            embeddings = self.embedding_service.generate_embeddings(chunks, video_id)
            logger.info(f"[Pipeline] Embedding completed in {time.perf_counter() - step_start:.1f}s")
            
            # 5. Storing
            update_progress("Indexing in Vector Database...", 0.95)
            step_start = time.perf_counter()
            self.vector_store.store_embeddings(chunks, embeddings, video_id)
            logger.info(f"[Pipeline] Vector store indexing completed in {time.perf_counter() - step_start:.1f}s")
            
            total_time = time.perf_counter() - pipeline_start
            update_progress("Processing complete!", 1.0)
            logger.info(f"Successfully processed video {video_id} ('{metadata.title}') — {len(chunks)} chunks in {total_time:.1f}s total.")
            return metadata, chunks
            
        except Exception as e:
            logger.error(f"Error processing video {url}: {e}")
            raise

    def ask_question(self, question: str, video_id: str, chat_history: list[dict] = None) -> RAGResponse:
        """Synchronous question answering with context chunks."""
        logger.info(f"Answering question for video {video_id}: {question}")
        query_embedding = self.embedding_service.embed_query(question)
        context_chunks = self.vector_store.retrieve(query_embedding, video_id)
        return self.rag_service.answer_question(question, context_chunks, chat_history)

    def ask_question_stream(self, question: str, video_id: str, chat_history: list[dict] = None):
        """Streaming question answering returning the token generator and retrieved chunks."""
        logger.info(f"Streaming answer for video {video_id}: {question}")
        query_embedding = self.embedding_service.embed_query(question)
        context_chunks = self.vector_store.retrieve(query_embedding, video_id)
        stream_gen = self.rag_service.answer_question_stream(question, context_chunks, chat_history)
        return stream_gen, context_chunks

    def clear_video(self, video_id: str):
        """Clears all data associated with a specific video_id from vector store and cache."""
        import os
        import shutil
        from app.config import Config
        
        logger.info(f"Clearing data for video {video_id}...")
        
        # 1. Remove from Vector Store (ChromaDB)
        self.vector_store.delete_video(video_id)
        
        # 2. Remove cache directory for this video
        output_dir = os.path.join(Config.CACHE_DIR, video_id)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
            logger.info(f"Cleared cache directory: {output_dir}")
        else:
            logger.info(f"No cache directory found to clear for video {video_id}.")

