import os
import json
from typing import Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import Config
from app.models import DocumentChunk, TranscriptSegment
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class ChunkingService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=Config.CHUNK_SIZE,
            chunk_overlap=Config.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def _format_timestamp(self, seconds: float) -> str:
        """Converts seconds to MM:SS format."""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _find_chapter(self, seconds: float, chapters: list[dict]) -> str | None:
        """Finds chapter title corresponding to given timestamp in seconds."""
        if not chapters:
            return None
        for ch in chapters:
            start = ch.get("start_time", 0.0)
            end = ch.get("end_time", 0.0)
            if end > start:
                if start <= seconds < end:
                    return ch.get("title")
            else:
                if seconds >= start:
                    return ch.get("title")
        return None

    def _create_chunks_from_segments(self, segments: list[TranscriptSegment], video_id: str, url: str, chapters: list[dict] = None) -> list[DocumentChunk]:
        """Creates chunks while embedding per-segment timestamps and chapter titles for precise LLM citations."""
        if not segments:
            return []

        document_chunks = []
        current_texts = []       # Timestamped text lines
        current_raw_texts = []   # Raw text for overlap calculation
        current_char_len = 0
        current_start = segments[0].start
        current_end = segments[0].end
        chunk_id = 0
        current_chapter = None

        i = 0
        while i < len(segments):
            seg = segments[i]
            ts = self._format_timestamp(seg.start)
            ch_title = self._find_chapter(seg.start, chapters)
            if ch_title and ch_title != current_chapter:
                current_chapter = ch_title
                timestamped_text = f"[{ch_title}] [{ts}] {seg.text}"
            else:
                timestamped_text = f"[{ts}] {seg.text}"

            current_texts.append(timestamped_text)
            current_raw_texts.append(seg.text)
            current_char_len += len(timestamped_text) + 1
            current_end = max(current_end, seg.end)

            # Once target chunk size reached or at end of segments
            if current_char_len >= Config.CHUNK_SIZE or i == len(segments) - 1:
                chunk_text = " ".join(current_texts).strip()
                if chunk_text:
                    document_chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            text=chunk_text,
                            video_id=video_id,
                            url=url,
                            start_time=round(current_start, 2),
                            end_time=round(current_end, 2),
                            chapter_title=current_chapter
                        )
                    )
                    chunk_id += 1

                if i < len(segments) - 1:
                    overlap_chars = 0
                    backtrack_count = 0
                    for k in range(len(current_raw_texts) - 1, -1, -1):
                        overlap_chars += len(current_raw_texts[k])
                        backtrack_count += 1
                        if overlap_chars >= Config.CHUNK_OVERLAP:
                            break

                    overlap_start_idx = max(0, i - backtrack_count + 1)
                    current_texts = [
                        f"[{self._format_timestamp(s.start)}] {s.text}"
                        for s in segments[overlap_start_idx : i + 1]
                    ]
                    current_raw_texts = [s.text for s in segments[overlap_start_idx : i + 1]]
                    current_char_len = sum(len(t) + 1 for t in current_texts)
                    current_start = segments[overlap_start_idx].start
                    current_end = segments[i].end
                else:
                    break

            i += 1

        return document_chunks

    def create_chunks(self, transcript: list[TranscriptSegment] | str, video_id: str, url: str, metadata: Any = None) -> list[DocumentChunk]:
        """Splits transcript into DocumentChunks. Preserves timestamps, chapters, and uses cache if available."""
        output_dir = os.path.join(Config.CACHE_DIR, video_id)
        os.makedirs(output_dir, exist_ok=True)
        chunks_path = os.path.join(output_dir, "chunks.json")
        
        if os.path.exists(chunks_path):
            try:
                with open(chunks_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    has_timestamps = any(c.get("end_time", 0.0) > 0.0 for c in data) if data else False
                    if has_timestamps or not isinstance(transcript, list):
                        logger.info("Using cached chunks.")
                        return [DocumentChunk(**chunk) for chunk in data]
                    logger.info("Cached chunks lacked timestamps; regenerating timestamp-aware chunks...")
            except Exception as e:
                logger.warning(f"Failed to read cached chunks: {e}")
                
        logger.info(f"Chunking transcript for video {video_id}...")
        
        chapters = metadata.chapters if metadata and hasattr(metadata, "chapters") else []

        if isinstance(transcript, list):
            document_chunks = self._create_chunks_from_segments(transcript, video_id, url, chapters)
        else:
            raw_chunks = self.text_splitter.split_text(transcript)
            document_chunks = [
                DocumentChunk(
                    chunk_id=i,
                    text=text,
                    video_id=video_id,
                    url=url,
                    start_time=0.0,
                    end_time=0.0
                )
                for i, text in enumerate(raw_chunks)
            ]

        # Add a rich Video Overview chunk at chunk_id 0 if metadata is available
        if metadata and (metadata.title or metadata.description or chapters):
            overview_parts = [f"VIDEO TITLE: {metadata.title}"]
            if metadata.channel and metadata.channel != "Unknown Channel":
                overview_parts.append(f"CREATOR / CHANNEL: {metadata.channel}")
            if chapters:
                ch_summary = ", ".join(f"{c.get('title')} ({self._format_timestamp(c.get('start_time', 0))})" for c in chapters[:12])
                overview_parts.append(f"VIDEO CHAPTERS: {ch_summary}")
            if metadata.description:
                desc_snippet = metadata.description[:500].strip().replace("\n", " ")
                overview_parts.append(f"DESCRIPTION: {desc_snippet}")

            overview_text = " | ".join(overview_parts)
            overview_chunk = DocumentChunk(
                chunk_id=0,
                text=overview_text,
                video_id=video_id,
                url=url,
                start_time=0.0,
                end_time=0.0,
                chapter_title="Overview"
            )
            # Re-index all chunks: overview first, then transcript chunks
            for idx, c in enumerate(document_chunks):
                c.chunk_id = idx + 1
            document_chunks.insert(0, overview_chunk)

        # Cache chunks
        with open(chunks_path, "w", encoding="utf-8") as file:
            json.dump([chunk.model_dump() for chunk in document_chunks], file, indent=2, ensure_ascii=False)
            
        logger.info(f"Created {len(document_chunks)} timestamp-aware chunks and cached them.")
        return document_chunks
