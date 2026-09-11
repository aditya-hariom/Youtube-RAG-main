import json
import os
import re
import urllib.request
import yt_dlp
from app.config import Config
from app.models import VideoMetadata
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class YouTubeService:
    @staticmethod
    def extract_video_id(url: str) -> str:
        """Extracts the YouTube video ID from a given URL."""
        # Regex to extract YouTube video ID from various formats
        pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        
        # Another common short format
        if "youtu.be/" in url:
            return url.split("youtu.be/")[1][:11]
            
        raise ValueError(f"Could not extract video ID from URL: {url}")

    @staticmethod
    def get_metadata(url: str, video_id: str) -> VideoMetadata:
        """Extracts rich video metadata (title, channel, description, chapters) with local caching."""
        output_dir = os.path.join(Config.CACHE_DIR, video_id)
        os.makedirs(output_dir, exist_ok=True)
        metadata_cache_path = os.path.join(output_dir, "metadata.json")

        # 1. Check local cache first
        if os.path.exists(metadata_cache_path):
            try:
                with open(metadata_cache_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    return VideoMetadata(**cached_data)
            except Exception as e:
                logger.warning(f"Failed to read cached metadata for {video_id}: {e}")

        # 2. Extract with yt-dlp (fast flat extraction, no download)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                if info_dict:
                    title = info_dict.get("title") or f"YouTube Video ({video_id})"
                    channel = info_dict.get("uploader") or info_dict.get("channel") or "Unknown Channel"
                    description = info_dict.get("description") or ""
                    raw_chapters = info_dict.get("chapters") or []
                    chapters = [
                        {
                            "title": ch.get("title", f"Chapter {idx + 1}"),
                            "start_time": float(ch.get("start_time", 0.0)),
                            "end_time": float(ch.get("end_time", 0.0))
                        }
                        for idx, ch in enumerate(raw_chapters)
                    ]

                    metadata = VideoMetadata(
                        video_id=video_id,
                        url=url,
                        title=title,
                        channel=channel,
                        description=description,
                        chapters=chapters
                    )

                    # Save to cache
                    try:
                        with open(metadata_cache_path, "w", encoding="utf-8") as f:
                            json.dump(metadata.model_dump(), f, indent=2, ensure_ascii=False)
                    except Exception as ce:
                        logger.warning(f"Failed to cache metadata: {ce}")

                    return metadata
        except Exception as e:
            logger.warning(f"yt-dlp metadata extraction failed ({e}), falling back to oEmbed...")

        # 3. Fallback to oEmbed if yt-dlp encounters an error
        title = f"YouTube Video ({video_id})"
        channel = "Unknown Channel"
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        try:
            req = urllib.request.Request(
                oembed_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    title = data.get("title", title)
                    channel = data.get("author_name", channel)
        except Exception as oe:
            logger.warning(f"oEmbed fallback failed: {oe}")

        fallback_metadata = VideoMetadata(
            video_id=video_id,
            url=url,
            title=title,
            channel=channel,
            description="",
            chapters=[]
        )

        try:
            with open(metadata_cache_path, "w", encoding="utf-8") as f:
                json.dump(fallback_metadata.model_dump(), f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        return fallback_metadata

    @staticmethod
    def download_audio(url: str, video_id: str) -> tuple[str, VideoMetadata]:
        """Downloads audio and returns the path to the mp3 and video metadata."""
        output_dir = os.path.join(Config.CACHE_DIR, video_id)
        os.makedirs(output_dir, exist_ok=True)
        
        output_template = os.path.join(output_dir, "audio.%(ext)s")
        audio_path = os.path.join(output_dir, "audio.mp3")
        
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "no_warnings": True,
        }

        logger.info(f"Downloading audio for {url}...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            title = info_dict.get("title", "Unknown Title") if info_dict else "Unknown Title"
            
        metadata = VideoMetadata(
            video_id=video_id,
            url=url,
            title=title
        )
        
        logger.info("Audio downloaded successfully!")
        return audio_path, metadata
