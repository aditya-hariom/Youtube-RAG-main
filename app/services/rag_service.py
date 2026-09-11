from typing import Generator
from google import genai
from google.genai import types
from app.config import Config
from app.models import RetrievedChunk, RAGResponse
from app.utils.logging_utils import get_logger
import warnings

# Suppress the AFC warning from the google.genai SDK
warnings.filterwarnings("ignore", message=".*Direct use of automatic function calling.*")

logger = get_logger(__name__)

class RAGService:
    def __init__(self):
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)

    def _build_prompt(self, question: str, context_chunks: list[RetrievedChunk], chat_history: list[dict] = None) -> str:
        """Constructs a strict grounding prompt with timestamped context and optional chat history."""
        context_parts = []
        for chunk in context_chunks:
            time_tag = f"[{chunk.start_timestamp} - {chunk.end_timestamp}]" if chunk.start_timestamp else ""
            ch_tag = f"[{chunk.chapter_title}] " if getattr(chunk, "chapter_title", None) else ""
            context_parts.append(f"{ch_tag}{time_tag} {chunk.text}")
            
        context = "\n\n---\n\n".join(context_parts)

        history_text = ""
        if chat_history:
            recent_turns = chat_history[-6:]  # Keep last 3-4 turns
            formatted_turns = []
            for msg in recent_turns:
                role = "User" if msg.get("role") in ["user", "human"] else "Assistant"
                formatted_turns.append(f"{role}: {msg.get('content', '')}")
            if formatted_turns:
                history_text = "RECENT CONVERSATION HISTORY:\n" + "\n".join(formatted_turns) + "\n\n"

        prompt = f"""You are a strict, faithful, and comprehensive YouTube video question-answering assistant.

GROUNDING & EXPLANATION RULES:
1. Answer ONLY using information explicitly stated in the VIDEO CONTEXT below.
2. Under NO circumstances should you use your own pre-existing general knowledge or training data to answer or fill in missing details.
3. If the answer is not explicitly mentioned or cannot be directly proven from the CONTEXT, you MUST state strictly:
   "I couldn't find that information in the provided video transcript."
4. Do NOT assume, extrapolate, speculate, or guess.
5. Provide a THOROUGH, IN-DEPTH, and DETAILED explanation based on all available information in the context:
   - Do NOT give one-line or overly brief answers when asked to explain a topic.
   - Break down complex concepts step-by-step, explaining all architecture stages, technical components, workflow steps, and examples discussed in the video.
   - Structure your response using clear Markdown formatting (structured headings, bullet points, bold key terms).
6. STRICT CODE FORMATTING RULES:
   - NEVER insert timestamps (e.g. [MM:SS]) INSIDE code blocks (```...```) or inside code snippets.
   - Code blocks must contain ONLY clean, valid, executable programming code without any timestamp interruptions.
   - If citing a timestamp for a piece of code, place the timestamp in the explanatory text OUTSIDE (before or after) the code block.
7. Whenever you cite specific facts in the explanatory text, include the timestamp in format [MM:SS] (e.g. [02:15]) using the timestamps provided in the context.
8. Do not mention "chunks", "embeddings", "retrieval", or "vector database".

{history_text}VIDEO CONTEXT:
{context}

QUESTION:
{question}
"""
        return prompt

    def answer_question(self, question: str, context_chunks: list[RetrievedChunk], chat_history: list[dict] = None) -> RAGResponse:
        """Generates an answer synchronously based on the provided context chunks."""
        if not context_chunks:
            return RAGResponse(
                answer="I couldn't find that information in the provided video transcript.",
                sources=[]
            )
            
        prompt = self._build_prompt(question, context_chunks, chat_history)
        logger.info("Generating answer using LLM...")
        
        try:
            response = self.client.models.generate_content(
                model=Config.LLM_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0)
            )
            answer_text = response.text.strip()
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            answer_text = "An error occurred while communicating with the LLM."
            
        return RAGResponse(
            answer=answer_text,
            sources=context_chunks
        )

    def answer_question_stream(self, question: str, context_chunks: list[RetrievedChunk], chat_history: list[dict] = None) -> Generator[str, None, None]:
        """Streams the LLM response token-by-token in real time."""
        if not context_chunks:
            yield "I couldn't find that information in the provided video transcript."
            return

        prompt = self._build_prompt(question, context_chunks, chat_history)
        logger.info("Streaming answer using LLM...")

        try:
            stream = self.client.models.generate_content_stream(
                model=Config.LLM_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0)
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Error streaming from LLM: {e}")
            yield f"\n\nAn error occurred while communicating with the LLM: {e}"
