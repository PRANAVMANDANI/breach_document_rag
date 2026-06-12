import json
import logging
import httpx
from typing import List, Dict, Any, AsyncGenerator
from groq import AsyncGroq
from app.config import settings

logger = logging.getLogger("app.llm_service")

SYSTEM_PROMPT = """You are Sara, a highly professional, expert Document Q&A assistant. 
Your task is to answer the user's question using the provided text chunks extracted from an uploaded document.

Instructions:
1. Base your answer on the provided Context. You may make reasonable inferences, summarize, and synthesize the information presented.
2. Do not fabricate facts. If the context does not contain any information related to the question, state that you cannot find the answer in the document.
3. Be helpful, clear, and comprehensive. Structure your answer logically to provide a complete response.
4. Always cite the page number(s) (e.g. "[Page X]") where the facts were found in the Context.
"""

def build_prompt(query: str, chunks: List[Dict[str, Any]], history: List[Dict[str, str]] = None) -> str:
    """
    Combines search chunks, conversation history, and user query into a structured context prompt.
    """
    context_str = ""
    for idx, chunk in enumerate(chunks):
        page_num = chunk.get("page_number", "Unknown")
        chunk_text = chunk.get("text", "")
        chunk_context = chunk.get("context", "")
        
        context_str += f"--- Chunk {idx + 1} (Page {page_num}) ---\n"
        if chunk_context:
            context_str += f"[Document Context]: {chunk_context}\n"
        context_str += f"[Chunk Content]: {chunk_text}\n\n"

    # Format the last 4 messages of history to avoid token size bloat
    history_str = ""
    if history:
        for msg in history[-4:]:
            role = "User" if msg.get("sender") == "user" else "Assistant"
            text = msg.get("text", "")
            if text:
                history_str += f"{role}: {text}\n"

    prompt = f"""{SYSTEM_PROMPT}

Context Chunks:
{context_str}
"""
    if history_str:
        prompt += f"""
Conversation History:
{history_str}
"""

    prompt += f"""
User Question: {query}

Helpful Answer:"""
    return prompt


async def generate_document_summary(whole_document: str) -> str:
    """
    Generates a brief high-level summary of the overall document using Groq.
    This summary is prepended to individual chunks to bypass token-per-minute rate limits.
    """
    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY is not defined. Skipping summary generation.")
        return "No document summary available."
    
    # Truncate whole_document to first ~30,000 characters to protect rate limits and context window
    truncated_doc = whole_document[:30000]
    
    prompt = f"""You are a document analyzer. Read the following text from a document and generate a brief, high-level summary (1-2 sentences) of the document's main subject, title/name (if identifiable), author/entity, and core purpose.
    
Document text:
{truncated_doc}

Respond with ONLY the 1-2 sentence summary, direct and clear, without any introductory words or formatting."""

    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY, max_retries=0)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error generating document summary via Groq: {e}")
        return "Document containing technical text."


async def generate_chunk_context(document_summary: str, chunk_text: str) -> str:
    """
    Generates a brief 1-2 sentence context to situate a chunk within the whole document using Groq.
    Uses a pre-generated document summary to stay within tokens-per-minute (TPM) rate limits.
    """
    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY is not defined. Skipping context generation.")
        return ""

    prompt = f"""Here is a brief summary of the overall document:
<document_summary>
{document_summary}
</document_summary>

Here is the chunk we want to situate within the overall document:
<chunk>
{chunk_text}
</chunk>

Please give a short context to situate this chunk within the overall document for the purpose of improving search retrieval of this chunk. First, identify the document, then identify the main subject/entity, and provide any necessary context.
Response must be very short (1-2 sentences) and direct, without any introductory words (like "Here is the context:") or markdown formatting. Just return the 1-2 sentence context."""

    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY, max_retries=0)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error generating chunk context via Groq: {e}")
        # Propagate rate-limit exceptions so that the caller's circuit breaker can trip
        if "429" in str(e) or "quota" in str(e).lower() or "limit" in str(e).lower():
            raise e
        return ""


async def generate_response_stream(
    query: str, 
    chunks: List[Dict[str, Any]], 
    history: List[Dict[str, str]] = None
) -> AsyncGenerator[str, None]:
    """
    Async generator that streams the LLM-generated answer text word-by-word.
    """
    prompt = build_prompt(query, chunks, history)

    if settings.LLM_PROVIDER == "groq":
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")
        
        try:
            client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                stream=True,
                temperature=0.1
            )
            
            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
                    
        except Exception as e:
            logger.error(f"Groq streaming failed: {e}")
            yield f"\n[Error generating response: {str(e)}]"
            
    elif settings.LLM_PROVIDER == "ollama":
        try:
            async with httpx.AsyncClient() as client:
                # Call Ollama API with streaming enabled
                async with client.stream(
                    "POST",
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": True
                    },
                    timeout=60.0
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            data = json.loads(line)
                            yield data.get("response", "")
                            
        except Exception as e:
            logger.error(f"Ollama streaming failed: {e}")
            yield f"\n[Error generating response: {str(e)}]"
            
    else:
        yield f"\n[Unsupported LLM provider configured: {settings.LLM_PROVIDER}]"


async def extract_metadata_from_text(first_page_text: str) -> Dict[str, Any]:
    """
    Uses LLM to extract title and author from the first page text of a document using Groq.
    """
    if not first_page_text:
        return {}
        
    prompt = f"""You are a document analyzer. Read the following text from the first page of a document and extract the Title and Author(s).
    
Text from first page:
{first_page_text[:2000]}

Respond ONLY in valid JSON format with keys "title" and "author". If they cannot be found, set the value to null.
Example response:
{{"title": "Document Title", "author": "John Doe"}}
Do not include any other text, markdown formatting, or explanation."""

    try:
        text_res = ""
        if settings.LLM_PROVIDER == "groq":
            if not settings.GROQ_API_KEY:
                return {}
            client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            # Use non-streaming completion for metadata extraction
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            text_res = response.choices[0].message.content.strip()
            
        if not text_res:
            return {}
            
        # Clean markdown code blocks if any
        if text_res.startswith("```"):
            lines = text_res.split("\n")
            if lines[0].startswith("```json"):
                text_res = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                text_res = "\n".join(lines[1:-1])
        
        data = json.loads(text_res)
        return {
            "title": data.get("title"),
            "author": data.get("author")
        }
    except Exception as e:
        logger.error(f"Error extracting metadata via LLM: {e}")
        return {}
