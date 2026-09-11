from pydantic import BaseModel, Field
from typing import List, Optional

class VideoMetadata(BaseModel):
    video_id: str
    url: str
    title: str = "Unknown Title"
    channel: str = "Unknown Channel"
    description: str = ""
    chapters: List[dict] = Field(default_factory=list)

class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.duration

class DocumentChunk(BaseModel):
    chunk_id: int
    text: str
    video_id: str
    url: str
    start_time: float = 0.0
    end_time: float = 0.0
    chapter_title: Optional[str] = None

    @property
    def start_timestamp(self) -> str:
        mins = int(self.start_time // 60)
        secs = int(self.start_time % 60)
        return f"{mins:02d}:{secs:02d}"

    @property
    def end_timestamp(self) -> str:
        mins = int(self.end_time // 60)
        secs = int(self.end_time % 60)
        return f"{mins:02d}:{secs:02d}"

class RetrievedChunk(DocumentChunk):
    similarity_score: float

class ChatMessage(BaseModel):
    role: str
    content: str

class RAGResponse(BaseModel):
    answer: str
    sources: List[RetrievedChunk] = Field(default_factory=list)
