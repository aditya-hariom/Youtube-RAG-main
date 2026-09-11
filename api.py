import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from app.pipeline import YouTubeRAGPipeline
from app.config import Config
import warnings
warnings.filterwarnings("ignore", message=".*Direct use of automatic function calling.*")

# Initialize pipeline once
pipeline = YouTubeRAGPipeline()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load heavy models at startup so first request is fast."""
    # Load embedding model eagerly in a background thread
    await asyncio.to_thread(pipeline.embedding_service.load_model)
    yield

app = FastAPI(title="YouTube RAG API", lifespan=lifespan)

# Allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Sources", "*"],
)

class ProcessRequest(BaseModel):
    url: str

class AskRequest(BaseModel):
    question: str
    video_id: str
    chat_history: list[dict] = []

@app.post("/process")
async def process_video(request: ProcessRequest):
    try:
        def _process():
            return pipeline.process_video(request.url)
            
        metadata, chunks = await asyncio.to_thread(_process)
        
        return {
            "video_id": metadata.video_id, 
            "title": metadata.title,
            "channel": metadata.channel,
            "description": metadata.description,
            "chapters": metadata.chapters,
            "total_chunks": len(chunks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/video/{video_id}/metadata")
async def get_video_metadata(video_id: str):
    """Returns cached video metadata (title, channel, description, chapters)."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        metadata = await asyncio.to_thread(pipeline.youtube_service.get_metadata, url, video_id)
        return {
            "video_id": metadata.video_id,
            "title": metadata.title,
            "channel": metadata.channel,
            "description": metadata.description,
            "chapters": metadata.chapters
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/ask")
async def ask_question(request: AskRequest):
    try:
        from google.genai import types

        # Prepare the query embedding and retrieve context in a background thread
        def _prepare():
            query_embedding = pipeline.embedding_service.embed_query(request.question)
            context_chunks = pipeline.vector_store.retrieve(query_embedding, request.video_id)
            return context_chunks
        
        context_chunks = await asyncio.to_thread(_prepare)
        
        if not context_chunks:
            return StreamingResponse(
                iter(["I couldn't find that information in the provided video transcript."]),
                media_type="text/plain"
            )
        
        # Build the hardened grounding prompt
        prompt = pipeline.rag_service._build_prompt(request.question, context_chunks, request.chat_history)
        
        # Create async generator that streams from Gemini in a thread
        async def async_stream():
            queue = asyncio.Queue()
            
            def _run_stream():
                """Run the sync Gemini streaming in a thread with temperature=0.0."""
                max_retries = 2
                try:
                    for attempt in range(max_retries + 1):
                        try:
                            print("="*50)
                            print("LLM is being called")
                            print("="*50)
                            stream = pipeline.rag_service.client.models.generate_content_stream(
                                model=Config.LLM_MODEL,
                                contents=prompt,
                                config=types.GenerateContentConfig(temperature=0.4)
                            )
                            for chunk in stream:
                                if chunk.text:
                                    queue.put_nowait(chunk.text)
                            return  # Success
                        except Exception as e:
                            if attempt < max_retries:
                                import time
                                time.sleep(1)
                                continue
                            queue.put_nowait(f"\n\nError: {e}")
                finally:
                    queue.put_nowait(None)  # Always signal done
            
            # Start the sync stream in a background thread
            loop = asyncio.get_event_loop()
            task = loop.run_in_executor(None, _run_stream)
            
            first_token = True
            while True:
                try:
                    timeout = 180.0 if first_token else 120.0
                    token = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    yield "\n\n[Response timed out — please try again]"
                    break
                if token is None:
                    break
                first_token = False
                yield token
            
            await task  # Ensure thread is done
        
        return StreamingResponse(
            async_stream(),
            media_type="text/plain"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount the static HTML frontend at the root
app.mount("/", StaticFiles(directory="public", html=True), name="public")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
