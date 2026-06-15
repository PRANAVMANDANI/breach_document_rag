import json
import logging
from typing import List, Dict, Any, AsyncGenerator
from langchain_core.messages import HumanMessage
from app.config import settings

logger = logging.getLogger("app.llm_service")

SYSTEM_PROMPT = """You are Sara, a highly professional, expert Document Q&A assistant. 
Your task is to answer the user's question using the provided text chunks extracted from an uploaded document.

Instructions:
1. Base your answer on the provided Context. You may make reasonable inferences, summarize, and synthesize the information presented.
2. Do not fabricate facts. If the context does not contain any information related to the question, state that you cannot find the answer in the document.
3. Be helpful, clear, and comprehensive. Structure your answer logically to provide a complete response.
4. Always cite the page number(s) (e.g. "[Page X]") where the facts were found in the Context.
5. DO NOT use any Markdown formatting in your response (such as bolding via `**`, headers via `#`, or markdown bullet lists). The response must be strictly in simple plain text, as the frontend client only displays unformatted normal text.
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


def get_llm_client(temperature: float = 0.1):
    """
    Helper to resolve the LangChain LLM chat client depending on settings.
    Supports OpenRouter, Groq, and Ollama.
    """
    if settings.LLM_PROVIDER == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is not configured in settings.")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            openai_api_key=settings.OPENROUTER_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            model_name=settings.OPENROUTER_MODEL or "meta-llama/llama-3-8b-instruct:free",
            temperature=temperature,
            default_headers={
                "HTTP-Referer": "https://github.com/PRANAVMANDANI/rag-pdf-contextual-retrieval",
                "X-Title": "AskPDF RAG Engine"
            }
        )
    elif settings.LLM_PROVIDER == "groq":
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not configured in settings.")
        from langchain_groq import ChatGroq
        return ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model="llama-3.3-70b-versatile",
            temperature=temperature
        )
    elif settings.LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            temperature=temperature,
            num_ctx=16384
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")


async def generate_document_summary(whole_document: str) -> str:
    """
    Generates a brief high-level summary of the overall document using the selected provider.
    This summary is prepended to individual chunks to bypass token-per-minute rate limits.
    """
    if settings.LLM_PROVIDER == "openrouter" and not settings.OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not defined. Skipping summary generation.")
        return "No document summary available."
    elif settings.LLM_PROVIDER == "groq" and not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY is not defined. Skipping summary generation.")
        return "No document summary available."
    
    # Truncate whole_document to first ~30,000 characters to protect rate limits and context window
    truncated_doc = whole_document[:30000]
    
    prompt = f"""You are a document analyzer. Read the following text from a document and generate a brief, high-level summary (1-2 sentences) of the document's main subject, title/name (if identifiable), author/entity, and core purpose.
    
Document text:
{truncated_doc}
 
Respond with ONLY the 1-2 sentence summary, direct and clear, without any introductory words or formatting."""

    try:
        chat = get_llm_client(temperature=0.1)
        response = await chat.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as e:
        logger.error(f"Error generating document summary via LangChain: {e}")
        return "Document containing technical text."


async def generate_chunk_context(document_summary: str, chunk_text: str) -> str:
    """
    Generates a brief 1-2 sentence context to situate a chunk within the overall document.
    Uses a pre-generated document summary to stay within tokens-per-minute (TPM) rate limits.
    """
    if settings.LLM_PROVIDER == "openrouter" and not settings.OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not defined. Skipping context generation.")
        return ""
    elif settings.LLM_PROVIDER == "groq" and not settings.GROQ_API_KEY:
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
        chat = get_llm_client(temperature=0.1)
        response = await chat.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as e:
        logger.error(f"Error generating chunk context via LangChain: {e}")
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
    Async generator that streams the LLM-generated answer text word-by-word via LangChain.
    """
    prompt = build_prompt(query, chunks, history)

    try:
        chat = get_llm_client(temperature=0.1)
        is_first_chunk = True
        accumulated_leading = ""
        
        async for chunk in chat.astream([HumanMessage(content=prompt)]):
            if chunk.content:
                # Remove markdown formatting characters to keep text plain and clean
                content = chunk.content.replace("**", "").replace("*", "").replace("#", "").replace("`", "").replace("__", "")
                
                # Strip leading whitespace/newlines at the start of the stream
                if is_first_chunk:
                    accumulated_leading += content
                    stripped = accumulated_leading.lstrip()
                    if stripped:
                        is_first_chunk = False
                        yield stripped
                else:
                    yield content
    except Exception as e:
        logger.error(f"LangChain streaming failed: {e}")
        yield f"\n[Error generating response: {str(e)}]"


async def extract_metadata_from_text(first_page_text: str) -> Dict[str, Any]:
    """
    Uses LLM to extract title and author from the first page text of a document.
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
        if settings.LLM_PROVIDER == "openrouter" and not settings.OPENROUTER_API_KEY:
            return {}
        elif settings.LLM_PROVIDER == "groq" and not settings.GROQ_API_KEY:
            return {}
            
        chat = get_llm_client(temperature=0.1)
        response = await chat.ainvoke([HumanMessage(content=prompt)])
        text_res = response.content.strip()
            
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
        logger.error(f"Error extracting metadata via LangChain: {e}")
        return {}


async def extract_clauses_from_page(page_text: str, page_number: int) -> List[Dict[str, Any]]:
    """
    Uses LLM to perform structured clause extraction and classification from a page of text.
    """
    if not page_text:
        return []

    prompt = f"""You are an expert legal contract compliance auditor.
Read the following text from Page {page_number} of a document and extract all legal clauses.
A legal clause is any numbered section, paragraph, or clear subsection (e.g. "Clause 2.2", "Section 5.1", "4. LIABILITY", "Confidentiality:", etc.) that establishes a legal duty, right, or liability.

For each clause, you must extract:
1. Clause Reference/Number (e.g. "2.2", "Section 4.1", "Clause 7", or "N/A" if it has no number/title).
2. Category. Choose exactly one of the following:
   - Confidentiality
   - Liability
   - Indemnification
   - Non-Compete
   - Non-Solicitation
   - IP Assignment
   - Termination
   - Governing Law
   - Arbitration
   - Renewal
   - General (if it's another standard clause or general text)
3. Exact Clause Text. Quote the exact text of the clause from the page. Do not summarize or paraphrase.

Respond ONLY in valid JSON format containing a list of objects.
Example response format:
{{
  "extracted_clauses": [
    {{
      "clause_reference": "2.2",
      "category": "Confidentiality",
      "exact_text": "The receiving party shall keep all information confidential..."
    }}
  ]
}}

Page Text:
{page_text}

Respond in the exact JSON format above. Do not include any other text, markdown formatting, or explanations."""

    try:
        chat = get_llm_client(temperature=0.1)
        response = await chat.ainvoke([HumanMessage(content=prompt)])
        text_res = response.content.strip()
        
        # Clean markdown code blocks if any
        if text_res.startswith("```"):
            lines = text_res.split("\n")
            if lines[0].startswith("```json"):
                text_res = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                text_res = "\n".join(lines[1:-1])
                
        # Find start and end of JSON list/dictionary
        start_idx = text_res.find("{")
        end_idx = text_res.rfind("}")
        if start_idx != -1 and end_idx != -1:
            text_res = text_res[start_idx:end_idx + 1]
            
        data = json.loads(text_res)
        extracted = data.get("extracted_clauses", [])
        
        # Add page number to each clause
        for item in extracted:
            item["page_number"] = page_number
        return extracted
    except Exception as e:
        logger.error(f"Error extracting clauses from page {page_number}: {e}")
        return []


async def extract_and_chunk_pdf_document(pages_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Runs structured clause extraction page-by-page in parallel.
    Falls back to RecursiveTextSplitter for pages where extraction fails or returns no chunks, 
    guaranteeing that all page text is indexed.
    """
    import asyncio
    from app.services.pdf_service import RecursiveTextSplitter
    
    logger.info(f"Extracting structured clauses from {len(pages_data)} pages...")
    
    # Run page extraction in parallel with a semaphore to avoid rate limit spikes
    semaphore = asyncio.Semaphore(5)
    
    async def run_with_sem(page_text: str, page_number: int):
        async with semaphore:
            return await extract_clauses_from_page(page_text, page_number)
            
    tasks = [run_with_sem(p["text"], p["page_number"]) for p in pages_data]
    results = await asyncio.gather(*tasks)
    
    all_chunks = []
    splitter = RecursiveTextSplitter(chunk_size=600, chunk_overlap=150)
    
    for idx, page in enumerate(pages_data):
        page_num = page["page_number"]
        page_clauses = results[idx]
        
        if page_clauses:
            for c_idx, c in enumerate(page_clauses):
                clause_text = c.get("exact_text", "").strip()
                if not clause_text:
                    continue
                    
                ref = c.get("clause_reference", "N/A")
                cat = c.get("category", "General")
                
                # We save original exact_text in "text", and set category/clause_reference metadata
                all_chunks.append({
                    "text": clause_text,
                    "clause_reference": ref,
                    "category": cat,
                    "metadata": {
                        "page_number": page_num,
                        "chunk_index": len(all_chunks)
                    }
                })
        else:
            # Fallback for pages that failed to extract structured clauses
            logger.warning(f"Failed to extract structured clauses on page {page_num}. Falling back to text splitting.")
            split_chunks = splitter.split_text(page["text"])
            for split_idx, chunk_text in enumerate(split_chunks):
                all_chunks.append({
                    "text": chunk_text,
                    "clause_reference": "N/A",
                    "category": "General",
                    "metadata": {
                        "page_number": page_num,
                        "chunk_index": len(all_chunks)
                    }
                })
                
    logger.info(f"Structured extraction produced {len(all_chunks)} chunks for database storage.")
    return all_chunks

