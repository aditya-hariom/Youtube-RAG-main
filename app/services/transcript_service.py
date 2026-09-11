import os
import re
import json
import whisper
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from app.config import Config
from app.models import TranscriptSegment
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class TranscriptService:
    def __init__(self):
        self.model = None

    def load_model(self):
        if self.model is None:
            logger.info("Loading Whisper model...")
            self.model = whisper.load_model("base")

    def _fetch_online_transcript(self, video_id: str) -> list[TranscriptSegment] | None:
        """Attempts to fetch transcripts using youtube-transcript-api."""
        try:
            logger.info(f"Checking for online transcripts for video {video_id}...")
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            
            # Prefer English or user languages, fallback to any available
            target_transcript = None
            try:
                target_transcript = transcript_list.find_transcript(["en", "en-US", "en-GB", "hi"])
            except Exception:
                # Find first available transcript
                for t in transcript_list:
                    target_transcript = t
                    break

            if target_transcript:
                logger.info(f"Found online transcript in '{target_transcript.language}' (generated={target_transcript.is_generated})")
                fetched = target_transcript.fetch()
                raw_data = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
                
                segments = []
                for item in raw_data:
                    text = item.get("text", "").strip()
                    if text:
                        segments.append(
                            TranscriptSegment(
                                text=text,
                                start=float(item.get("start", 0.0)),
                                duration=float(item.get("duration", 0.0))
                            )
                        )
                if segments:
                    return segments
        except Exception as e:
            logger.info(f"Could not fetch online transcript for {video_id}: {e}")
        return None

    def _fetch_ytdlp_subtitles(self, video_id: str) -> list[TranscriptSegment] | None:
        """
        Fallback: Extract subtitles via yt_dlp (no video download needed).
        This works even when youtube-transcript-api is IP-blocked.
        Typically completes in 3-5 seconds.
        """
        try:
            logger.info(f"Trying yt_dlp subtitle extraction for video {video_id}...")
            url = f"https://www.youtube.com/watch?v={video_id}"
            output_dir = os.path.join(Config.CACHE_DIR, video_id)
            os.makedirs(output_dir, exist_ok=True)
            sub_path = os.path.join(output_dir, "subs")

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,           # Don't download video/audio
                "writesubtitles": True,           # Download manual subs
                "writeautomaticsub": True,        # Download auto-generated subs
                "subtitleslangs": ["en", "en-US", "en-GB", "hi"],
                "subtitlesformat": "json3",       # JSON format with timestamps
                "outtmpl": sub_path,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            # Find the downloaded subtitle file
            sub_file = None
            for ext in ["json3"]:
                for lang in ["en", "en-US", "en-GB", "hi"]:
                    candidate = f"{sub_path}.{lang}.{ext}"
                    if os.path.exists(candidate):
                        sub_file = candidate
                        break
                if sub_file:
                    break

            # Also check for auto-generated subs (yt_dlp might name them differently)
            if not sub_file:
                for f in os.listdir(output_dir):
                    if f.startswith("subs.") and f.endswith(".json3"):
                        sub_file = os.path.join(output_dir, f)
                        break

            if not sub_file:
                logger.info("yt_dlp did not find any subtitle files.")
                return None

            logger.info(f"Found subtitle file: {sub_file}")

            with open(sub_file, "r", encoding="utf-8") as f:
                sub_data = json.load(f)

            segments = []
            events = sub_data.get("events", [])
            for event in events:
                # Each event can have multiple "segs" (segments)
                text_parts = []
                for seg in event.get("segs", []):
                    t = seg.get("utf8", "").strip()
                    if t and t != "\n":
                        text_parts.append(t)
                text = " ".join(text_parts).strip()
                # Clean up whitespace
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    start_ms = event.get("tStartMs", 0)
                    duration_ms = event.get("dDurationMs", 0)
                    segments.append(
                        TranscriptSegment(
                            text=text,
                            start=float(start_ms) / 1000.0,
                            duration=float(duration_ms) / 1000.0
                        )
                    )

            if segments:
                logger.info(f"Extracted {len(segments)} segments via yt_dlp subtitles.")
                return segments

        except Exception as e:
            logger.info(f"yt_dlp subtitle extraction failed for {video_id}: {e}")
        return None

    def get_transcript_segments(self, video_id: str, audio_path: str = None) -> list[TranscriptSegment]:
        """
        Retrieves transcript segments (with timestamps).
        1. Checks local cache (segments.json).
        2. Tries youtube-transcript-api for instant fetch (~1-2 seconds).
        3. Tries yt_dlp subtitle extraction (~3-5 seconds, no video download).
        4. Falls back to local Whisper transcription if audio_path is provided.
        """
        output_dir = os.path.join(Config.CACHE_DIR, video_id)
        os.makedirs(output_dir, exist_ok=True)
        segments_path = os.path.join(output_dir, "segments.json")
        transcript_txt_path = os.path.join(output_dir, "transcript.txt")

        # 1. Check cache
        if os.path.exists(segments_path):
            logger.info(f"Using cached transcript segments for {video_id}.")
            try:
                with open(segments_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return [TranscriptSegment(**item) for item in data]
            except Exception as e:
                logger.warning(f"Failed to read cached segments: {e}")

        # 2. Try online transcript (youtube-transcript-api)
        segments = self._fetch_online_transcript(video_id)
        
        # 3. Try yt_dlp subtitle extraction (fast, no video download)
        if not segments:
            logger.info("youtube-transcript-api failed, trying yt_dlp subtitles...")
            segments = self._fetch_ytdlp_subtitles(video_id)

        # 4. Fallback to Whisper if everything above failed and audio_path exists
        if not segments and audio_path and os.path.exists(audio_path):
            logger.info(f"Falling back to local Whisper transcription for {audio_path}...")
            self.load_model()
            try:
                result = self.model.transcribe(audio_path, fp16=False)
                whisper_segments = result.get("segments", [])
                if whisper_segments:
                    segments = [
                        TranscriptSegment(
                            text=s["text"].strip(),
                            start=float(s["start"]),
                            duration=float(s["end"] - s["start"])
                        )
                        for s in whisper_segments if s.get("text", "").strip()
                    ]
                elif result.get("text"):
                    segments = [
                        TranscriptSegment(
                            text=result["text"].strip(),
                            start=0.0,
                            duration=0.0
                        )
                    ]
            except Exception as e:
                logger.error(f"Whisper transcription failed: {e}")
                raise ValueError(f"Transcription failed via all methods: {e}")

        if not segments:
            raise ValueError(f"No transcript could be obtained for video {video_id}.")

        # Cache segments and full text
        try:
            with open(segments_path, "w", encoding="utf-8") as f:
                json.dump([s.model_dump() for s in segments], f, indent=2, ensure_ascii=False)
            
            full_text = " ".join(s.text for s in segments)
            with open(transcript_txt_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            logger.info(f"Saved {len(segments)} transcript segments to cache for {video_id}.")
        except Exception as e:
            logger.warning(f"Could not cache transcript: {e}")

        return segments

    def transcribe_audio(self, audio_path: str, video_id: str) -> str:
        """Backwards-compatible method returning full text."""
        segments = self.get_transcript_segments(video_id, audio_path)
        return " ".join(s.text for s in segments)
