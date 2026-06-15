import json
import asyncio
import logging
import httpx
from typing import List, Dict, Any
from bson import ObjectId
from pydantic import BaseModel, Field
from app.config import settings
from app.database import Database
from app.services.vector_service import search_similar_chunks
from app.services.llm_service import get_llm_client
from langchain_core.messages import HumanMessage

logger = logging.getLogger("app.agent_service")

# 1. Structured Output Schemas using Pydantic
class RiskItem(BaseModel):
    category: str = Field(description="Risk category (Termination, Liability, IP Ownership, Indemnity, Jurisdiction, Other)")
    clause_text: str = Field(description="Exact risk clause text extracted from the document")
    severity: str = Field(description="Severity level: HIGH, MEDIUM, or LOW")
    severity_color: str = Field(description="Color associated: red (for HIGH), yellow (for MEDIUM), green (for LOW)")
    explanation: str = Field(description="Why this clause is risky and its legal implications")
    citation: str = Field(description="Legal precedent, law code (e.g. Indian Contract Act), or web search validation findings")
    suggestion: str = Field(description="How the user should negotiate or rewrite this clause")

class ContractAuditReport(BaseModel):
    overall_score: int = Field(description="Safety score from 0 (very risky) to 100 (perfectly safe)")
    summary: str = Field(description="A brief 2-3 sentence overall summary of the contract's risk profile")
    risks: List[RiskItem] = Field(default=[], description="List of identified risk items")


# 2. Tavily Search Client Integration
class TavilySearchClient:
    @staticmethod
    async def search(query: str, max_results: int = 3) -> str:
        """
        Executes a web search query on the Tavily API and returns formatted snippets.
        """
        if not settings.TAVILY_API_KEY:
            logger.warning("TAVILY_API_KEY is not configured. Web search tool is disabled.")
            return "No Tavily Search API key configured. Standard general precedents applied."
        
        try:
            url = "https://api.tavily.com/search"
            headers = {
                "Content-Type": "application/json"
            }
            payload = {
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results
            }
            
            logger.info(f"Triggering Tavily Search API for query: '{query}'")
            print(f"\n[TAVILY SEARCH] Querying: '{query}'...")
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=12.0)
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    print(f"    - Found {len(results)} web search results.")
                    
                    if not results:
                        return f"No web search results found for query: '{query}'"
                        
                    snippets = []
                    for idx, res in enumerate(results):
                        title = res.get("title", "No Title")
                        url_link = res.get("url", "")
                        desc = res.get("content", "No description available.")
                        snippets.append(f"[{idx+1}] Source: {url_link}\nTitle: {title}\nSnippet: {desc}")
                    
                    return "\n\n".join(snippets)
                else:
                    logger.error(f"Tavily Search API returned error code {response.status_code}")
                    print(f"    [ERROR] Tavily Search API error: HTTP {response.status_code}")
                    return f"Tavily Search API error: HTTP {response.status_code}"
                    
        except Exception as e:
            logger.error(f"Tavily Search HTTP request failed: {e}")
            print(f"    [ERROR] Tavily Search failed: {str(e)}")
            return f"Tavily Search failed: {str(e)}"



# 3. Clean JSON Output Parser
def clean_json_response(text: str) -> Dict[str, Any]:
    """
    Cleans markdown formatting and extracts a raw JSON string to load as a dictionary.
    """
    text_clean = text.strip()
    if text_clean.startswith("```"):
        lines = text_clean.split("\n")
        if lines[0].startswith("```json"):
            text_clean = "\n".join(lines[1:-1])
        elif lines[0].startswith("```"):
            text_clean = "\n".join(lines[1:-1])
    
    # Strip any potential leading/trailing non-json noise
    start_idx = text_clean.find("{")
    end_idx = text_clean.rfind("}")
    if start_idx != -1 and end_idx != -1:
        text_clean = text_clean[start_idx:end_idx + 1]
        
    return json.loads(text_clean)


CLASSIFIER_SYSTEM_PROMPT = """You are a document type classifier. Your ONLY job is to 
determine whether the uploaded document is a legal contract 
or agreement that requires risk analysis.

Read the first 500 words of the document and classify it 
into EXACTLY one of these categories:

CONTRACT       → Any agreement, NDA, MOU, service agreement, 
                 employment contract, lease deed, terms of 
                 service, or any document where two or more 
                 parties agree to binding legal obligations.

GOVERNMENT_FORM → Police forms, tax filings, registration 
                  certificates, government applications, 
                  licenses, permits.

POLICY_DOCUMENT → Company policies, HR handbooks, privacy 
                  policies, compliance guidelines.

FINANCIAL_DOC   → Invoices, receipts, financial statements, 
                  bank statements, audit reports.

INFORMATIONAL   → Research papers, news articles, brochures, 
                  manuals, academic documents.

OTHER           → Anything that does not fit above.

STRICT RULES:
1. Return ONLY a JSON object, nothing else.
2. Do NOT perform any risk analysis in this step.
3. If you are even 30% unsure it is a CONTRACT, classify 
   it as the more specific category.

Return exactly this format:
{
  "document_type": "CONTRACT",
  "confidence": 0.95,
  "reason": "Document contains parties, obligations, and 
             signature blocks typical of a legal agreement",
  "proceed_with_analysis": true
}

If document_type is NOT CONTRACT, set:
  "proceed_with_analysis": false"""


async def classify_document(text: str) -> dict:
    """
    Classify document type before risk analysis based on the first ~600 words of text.
    """
    # Only send first 600 words to save tokens
    preview = " ".join(text.split()[:600])
    
    prompt = f"""{CLASSIFIER_SYSTEM_PROMPT}

Classify this document:

{preview}
"""
    chat = get_llm_client(temperature=0.1)
    try:
        response = await chat.ainvoke([HumanMessage(content=prompt)])
        result = clean_json_response(response.content)
        return result
    except Exception as e:
        logger.error(f"Error during document classification: {e}")
        # If JSON parse fails, default to safe — don't analyze
        return {
            "document_type": "UNKNOWN",
            "confidence": 0.0,
            "proceed_with_analysis": False,
            "reason": f"Could not classify document type: {str(e)}"
        }


async def analyze_category_risk(
    document_id: str, 
    category_db_names: List[str],
    display_name: str,
    description: str, 
    default_search_query: str,
    chunks_collection
) -> List[Dict[str, Any]]:
    """
    Checks if a specific risk category is present in the document by fetching the relevant 
    categorized chunks and prompting the LLM to inspect them specifically.
    """
    # Fetch categorized chunks
    cursor = chunks_collection.find({
        "document_id": ObjectId(document_id),
        "category": {"$in": category_db_names}
    })
    
    clauses = []
    async for chunk in cursor:
        clauses.append(chunk)
        
    # Fallback to vector search if no chunks were categorized with this label
    if not clauses:
        from app.services.vector_service import search_similar_chunks
        logger.info(f"No structured chunks for category {display_name}. Running vector fallback...")
        clauses = await search_similar_chunks(query_text=display_name, limit=4, document_id=document_id)
        
    if not clauses:
        return []
        
    # Compile text context
    context_str = ""
    for idx, c in enumerate(clauses):
        page = c.get("metadata", {}).get("page_number", "Unknown") if "metadata" in c else c.get("page_number", "Unknown")
        ref = c.get("clause_reference", "N/A")
        text = c.get("text", "")
        context_str += f"--- Clause Option {idx + 1} (Page {page}) [Ref: {ref}] ---\n{text}\n\n"
        
    prompt = f"""You are a corporate legal compliance auditor.
Your job is to analyze the provided clauses extracted from a contract and inspect them for the risk area: "{display_name}".
Risk Description to look for: {description}

CRITICAL GROUNDING RULES:
1. You may ONLY flag a risk if a clause is EXPLICITLY present as quoted text in the provided clauses.
2. If the clauses do not contain any compliance warning signs, unfavorable terms, or risks for this category, you MUST return an empty list of identified_risks. Do not make up or infer any risks.
3. You must quote the clause EXACTLY. Do not paraphrase or summarize.

Respond ONLY in valid JSON format containing a list of objects.
Example response format if a risk is found:
{{
  "identified_risks": [
    {{
      "category": "{display_name}",
      "clause_text": "Vendor shall have unlimited liability for...",
      "risk_description": "Imposes unlimited liability on the Vendor, creating asymmetric commercial risk.",
      "search_query": "{default_search_query}"
    }}
  ]
}}

Example response format if NO risk is found:
{{
  "identified_risks": []
}}

Contract Clauses:
{context_str}

Respond in the exact JSON format, do not include any other text, explanations, or code blocks."""

    try:
        chat = get_llm_client(temperature=0.1)
        response = await chat.ainvoke([HumanMessage(content=prompt)])
        data = clean_json_response(response.content)
        risks = data.get("identified_risks", [])
        return risks
    except Exception as e:
        logger.error(f"Error checking risk category {display_name}: {e}")
        return []


# 4. Agentic Auditing Loop
async def run_contract_audit(document_id: str) -> Dict[str, Any]:
    """
    Two-stage agentic contract audit runner:
    Stage 1: Scan retrieved contract context and generate Brave search queries for suspicious clauses.
    Stage 2: Run searches in parallel, merge snippets, synthesize final compliance report, and compute score.
    """
    logger.info(f"Initiating Agentic Legal Audit for document {document_id}...")
    
    # Fetch Document Metadata
    documents_collection = Database.get_documents_collection()
    doc = await documents_collection.find_one({"_id": ObjectId(document_id)})
    if not doc:
        raise ValueError(f"Document with ID {document_id} not found in database.")
    
    filename = doc.get("filename", "Unknown Document")
    print(f"\n[LEGAL EAGLE] Starting compliance risk audit for contract: '{filename}'...")

    # Fetch first few chunks in order to construct a ~600-word preview text
    chunks_collection = Database.get_chunks_collection()
    cursor = chunks_collection.find({"document_id": ObjectId(document_id)}).sort([("metadata.page_number", 1), ("metadata.chunk_index", 1)])
    preview_texts = []
    word_count = 0
    async for chunk in cursor:
        chunk_text = chunk.get("text", "")
        preview_texts.append(chunk_text)
        word_count += len(chunk_text.split())
        if word_count >= 600:
            break
            
    document_preview = " ".join(preview_texts)
    
    # Classify the document type
    classification = await classify_document(document_preview)
    logger.info(f"Document {document_id} classification result: {classification}")
    
    if not classification.get("proceed_with_analysis", False):
        doc_type = classification.get("document_type", "UNKNOWN")
        print(f"    [WARN] [LEGAL EAGLE] Document is not a legal contract (type: {doc_type}). Skipping compliance audit.")
        return {
            "is_contract": False,
            "document_type": doc_type,
            "confidence": classification.get("confidence", 0.0),
            "reason": classification.get("reason", "Not classified as a contract"),
            "overall_score": 100,
            "summary": f"This document appears to be a {doc_type}, not a legal contract. "
                       f"LegalEagle only analyzes binding legal agreements between parties.",
            "risks": []
        }
    
    # Define checklist for systematic risk discovery based on the 10 core risks:
    # liability, indemnification, confidentiality, non-compete, non-solicitation, 
    # ip_assignment, termination, governing_law, arbitration, renewal.
    LEGAL_CHECKLIST = {
        "liability": {
            "display_name": "Liability",
            "db_categories": ["Liability", "liability"],
            "description": "Limitation of liability caps, asymmetric liability limits where one party has unlimited liability while the other is heavily capped, or liability exclusions.",
            "search_term": "standard software contract limitation of liability cap India"
        },
        "indemnification": {
            "display_name": "Indemnification",
            "db_categories": ["Indemnification", "indemnification", "Indemnity", "indemnity"],
            "description": "One-sided indemnification requirements, obligations to defend and hold harmless, or extreme indemnity triggers.",
            "search_term": "standard indemnity clause enforceability India"
        },
        "confidentiality": {
            "display_name": "Confidentiality",
            "db_categories": ["Confidentiality", "confidentiality"],
            "description": "Perpetual confidentiality durations (obligations surviving forever or indefinitely), which can be highly problematic or unenforceable in Indian law.",
            "search_term": "perpetual NDA duration enforceability India"
        },
        "non-compete": {
            "display_name": "Non-Compete",
            "db_categories": ["Non-Compete", "non-compete", "Non-compete"],
            "description": "Covenants in restraint of trade, geographic non-compete limits, global non-competes, or post-employment restrict covenants void under Section 27 of the Indian Contract Act.",
            "search_term": "Section 27 Indian Contract Act non-compete clause validity"
        },
        "non-solicitation": {
            "display_name": "Non-Solicitation",
            "db_categories": ["Non-Solicitation", "non-solicitation", "Non-solicitation"],
            "description": "Restrictions on soliciting employees, clients, or customers after termination, including duration and geographic scope.",
            "search_term": "non-solicitation clause enforceability validity India"
        },
        "ip_assignment": {
            "display_name": "IP Assignment",
            "db_categories": ["IP Assignment", "ip_assignment", "IP assignment", "Intellectual Property", "intellectual_property"],
            "description": "Unfavorable Intellectual property assignment, copyright transfers, proprietary patent assignment, or loss of background intellectual property.",
            "search_term": "IP assignment clause standard Indian software contract"
        },
        "termination": {
            "display_name": "Termination",
            "db_categories": ["Termination", "termination"],
            "description": "Unilateral termination without cause, auto-renewal notification traps (e.g. 90-day notify window), or excessive notice periods.",
            "search_term": "notice period for termination without cause standard contracts"
        },
        "governing_law": {
            "display_name": "Governing Law",
            "db_categories": ["Governing Law", "governing_law", "Governing law", "Jurisdiction", "jurisdiction"],
            "description": "Unfavorable choice of governing law, non-local jurisdictions, or waivers of local judicial resort.",
            "search_term": "choice of governing law validity Indian contracts"
        },
        "arbitration": {
            "display_name": "Arbitration",
            "db_categories": ["Arbitration", "arbitration", "Dispute Resolution", "dispute_resolution", "Dispute resolution"],
            "description": "Mandatory arbitration clauses, choice of seat and venue, split arbitration costs, and waiver of class actions or right to sue in court.",
            "search_term": "arbitration clause validity seat venue Indian arbitration act"
        },
        "renewal": {
            "display_name": "Renewal",
            "db_categories": ["Renewal", "renewal"],
            "description": "Auto-renewal terms, notice period for non-renewal, and pricing escalation/increase clauses upon renewal.",
            "search_term": "contract auto-renewal clause standard notice period"
        }
    }

    # 1. Run structured checklist risk check in parallel
    logger.info("Executing checklist-based risk discovery in parallel...")
    print("[LEGAL EAGLE] Scanning contract checklist for structured risks in parallel...")
    
    checklist_tasks = [
        analyze_category_risk(
            document_id=document_id,
            category_db_names=info["db_categories"],
            display_name=info["display_name"],
            description=info["description"],
            default_search_query=info["search_term"],
            chunks_collection=chunks_collection
        )
        for cat_key, info in LEGAL_CHECKLIST.items()
    ]
    
    checklist_results = await asyncio.gather(*checklist_tasks)
    
    # Flatten and deduplicate identified risks
    identified_risks = []
    seen_risks = set()
    for res in checklist_results:
        for r in res:
            risk_key = f"{r.get('category')}_{r.get('clause_text', '')[:50]}"
            if risk_key not in seen_risks and r.get('clause_text'):
                seen_risks.add(risk_key)
                identified_risks.append(r)
                
    logger.info(f"Structured checklist scanning complete. Identified {len(identified_risks)} potential risks.")
    print(f"[LEGAL EAGLE] Scan complete. Identified {len(identified_risks)} potential risk points to verify.")

    # 2. Build unified context_str for final synthesis
    all_db_categories = []
    for info in LEGAL_CHECKLIST.values():
        all_db_categories.extend(info["db_categories"])
        
    cursor = chunks_collection.find({
        "document_id": ObjectId(document_id),
        "category": {"$in": all_db_categories}
    })
    
    context_clauses = []
    seen_c_keys = set()
    async for chunk in cursor:
        chunk_key = f"{chunk['metadata']['page_number']}_{chunk['text'][:100]}"
        if chunk_key not in seen_c_keys:
            seen_c_keys.add(chunk_key)
            context_clauses.append(chunk)
            
    if not context_clauses:
        # Fallback to all chunks
        cursor = chunks_collection.find({"document_id": ObjectId(document_id)})
        async for chunk in cursor:
            chunk_key = f"{chunk['metadata']['page_number']}_{chunk['text'][:100]}"
            if chunk_key not in seen_c_keys:
                seen_c_keys.add(chunk_key)
                context_clauses.append(chunk)
                
    context_str = ""
    for idx, c in enumerate(context_clauses):
        page = c.get("metadata", {}).get("page_number", "Unknown") if "metadata" in c else c.get("page_number", "Unknown")
        ref = c.get("clause_reference", "N/A")
        cat = c.get("category", "General")
        context_str += f"--- Clause Option {idx + 1} (Page {page}) [Ref: {ref}, Category: {cat}] ---\n{c['text']}\n\n"
        
    # --- STAGE 2: Execute Web Search in Parallel ---
    web_context_str = ""
    if identified_risks and settings.TAVILY_API_KEY:
        logger.info("Executing Stage 2: Performing parallel Tavily Web Searches...")
        print(f"[LEGAL EAGLE] Stage 2: Running parallel Tavily Web Search queries for {min(len(identified_risks), 8)} risks...")
        search_tasks = []
        queries_executed = []
        
        for risk in identified_risks[:8]:  # Limit to top 8 risks to protect API rate limits
            query = risk.get("search_query")
            if query:
                search_tasks.append(TavilySearchClient.search(query))
                queries_executed.append(query)
                
        if search_tasks:
            search_results = await asyncio.gather(*search_tasks)
            
            for idx, res_text in enumerate(search_results):
                web_context_str += f"=== Web Search for: '{queries_executed[idx]}' ===\n{res_text}\n\n"
        else:
            web_context_str = "No specific queries generated."
    else:
        logger.info("Skipping Tavily Web Search (no key configured or no risks identified).")
        web_context_str = "Web search is disabled. Analyzing based on default legal knowledge guidelines."
        
    # --- STAGE 3: Final Synthesis & Scoring ---
    logger.info("Executing Stage 3: LLM Synthesis and Compliance Audit Compilation...")
    
    stage2_prompt = f"""You are a senior corporate compliance lawyer. 
Review the contract file '{filename}' and compile the final legal risk audit report.
You must combine:
1. The raw contract text clauses.
2. The initial risk findings.
3. The Tavily Web Search results (precedents, enforceability rules, and standard practices under Indian law).

CRITICAL GROUNDING RULES — READ BEFORE EVERY ANALYSIS:

RULE 1 — QUOTE BEFORE YOU FLAG:
Before flagging ANY risk, you MUST find the exact sentence 
in the document that supports it. If you cannot quote it 
verbatim, DO NOT flag it. No exceptions.

RULE 2 — NO INFERENCE OF MISSING CLAUSES:
If a clause does not exist in the document, do not flag 
its absence as a risk unless specifically asked.
"This contract lacks X" is only valid if X is legally 
required. Do not invent missing clauses.

RULE 3 — VERIFY CLAUSE NUMBERS:
When citing a clause, verify the clause number matches 
the quoted text. Do not guess clause locations.

RULE 4 — NO CROSS-DOCUMENT CONTAMINATION:
Do not apply knowledge of previous documents analysed 
in this session to the current document. Each document 
is independent.

SELF-CHECK before each flagged risk, ask yourself:
  Q1: Can I paste the exact sentence from the document?
  Q2: Is this sentence actually in THIS document?
  Q3: Would a human lawyer agree this is risky?
  
If any answer is NO → do not flag it.

If the document is not a legal contract (e.g. a government form, invoice, policy, receipt), respond with exactly:
{{
  "overall_score": 100,
  "summary": "This does not appear to be a legal contract. Risk analysis is not applicable.",
  "risks": []
}}

CRITICAL INSTRUCTIONS FOR RISK SCREENING:
1. EXHAUSTIVE SCREENING REQUIRED: Analyze every clause. Do not omit any risk. List ALL identified legal warning signs.
2. CHECK FOR LIABILITY CAPS: Carefully look for liability asymmetry (e.g. one party having unlimited liability or capped at contract value, while the other party limits their liability to a nominal amount like ₹500 or $100). Flag this as HIGH risk.
3. CHECK FOR INDEMNIFICATION: Flag one-sided indemnities, obligations to defend and hold harmless, or extreme indemnity triggers as HIGH or MEDIUM risk.
4. CHECK FOR PERPETUAL CONFIDENTIALITY: Flag infinite or perpetual NDA durations (e.g. confidentiality obligations remaining in force forever or surviving indefinitely) as MEDIUM or HIGH risk.
5. CHECK FOR NON-COMPETE: Flag covenants in restraint of trade, post-employment non-competes, and geographic restrictions which are void under Section 27 of the Indian Contract Act as HIGH risk.
6. CHECK FOR NON-SOLICITATION: Flag aggressive employee, customer, or client non-solicit covenants as MEDIUM risk.
7. CHECK FOR IP ASSIGNMENT: Flag unfavorable intellectual property assignments, broad copyright/patent assignments, or forfeiture of background intellectual property as HIGH or MEDIUM risk.
8. CHECK FOR TERMINATION: Flag unilateral termination without cause, auto-renewal notification traps (e.g. 90-day notify window), or excessive notice periods as HIGH or MEDIUM risk.
9. CHECK FOR GOVERNING LAW: Flag unfavorable choice of governing law, non-local jurisdictions, or waivers of local judicial resort as MEDIUM risk.
10. CHECK FOR ARBITRATION: Flag one-sided arbitration clauses, inconvenient seats/venues, split arbitration costs, and waiver of class actions or right to sue in court as MEDIUM risk.
11. CHECK FOR RENEWAL: Flag auto-renewal traps, unilateral price escalation terms upon renewal, and notice duration limits as MEDIUM risk.

Provide a finalized list of audit risks. 
For each risk, assign:
- Severity: HIGH, MEDIUM, or LOW.
- Severity Color: "red" (HIGH), "yellow" (MEDIUM), "green" (LOW).
- Citation: Reference specific legal precedents, Indian Contract Act sections (such as Section 27 for restraints of trade, or Section 124 for indemnity), or search results found in the provided web context.
- Suggestion: Concrete advice on how the user should rewrite this clause.

Also, calculate an overall Safety Score (from 0 to 100) for the contract. 
- 100 means completely safe/standard.
- Less than 50 means extremely risky/one-sided contract.
Provide a 2-3 sentence overall summary.

You must respond ONLY with a valid JSON document matching the following keys:
{{
  "overall_score": 75,
  "summary": "Overall contract risk summary text...",
  "risks": [
    {{
      "category": "Liability",
      "clause_text": "Vendor shall have unlimited liability...",
      "severity": "HIGH",
      "severity_color": "red",
      "explanation": "This clause imposes unlimited liability on you, which is highly risky...",
      "citation": "Indian courts usually look for balanced liability caps, but unilateral clauses are enforceable if signed unless unconscionable.",
      "suggestion": "Request to cap liability at 100% of the contract value or fees paid in the last 12 months."
    }}
  ]
}}

Contract Clauses:
{context_str}

Web Search Precedents & Legal Context:
{web_context_str}

Respond strictly in the JSON format above, with no markdown formatting, no introductory text, and no concluding words. Must be a clean JSON document."""

    print("[LEGAL EAGLE] Stage 3: Synthesizing search results and compiling final audit report...")
    chat = get_llm_client(temperature=0.1)
    response_stage2 = await chat.ainvoke([HumanMessage(content=stage2_prompt)])
    
    try:
        final_audit_data = clean_json_response(response_stage2.content)
        
        # Validate and sanitize overall score
        score = final_audit_data.get("overall_score", 100)
        try:
            score = int(score)
            score = max(0, min(100, score))
        except Exception:
            score = 75
            
        final_audit_data["overall_score"] = score
        final_audit_data["is_contract"] = True
        final_audit_data["document_type"] = "CONTRACT"
        
        # Verify risks list exists
        if "risks" not in final_audit_data:
            final_audit_data["risks"] = []
            
        logger.info(f"Legal Audit compiled successfully. Safety Score: {score}/100. Risks identified: {len(final_audit_data['risks'])}")
        print(f"[LEGAL EAGLE] Stage 3 complete. Overall Safety Score: {score}/100. Flagged risks: {len(final_audit_data['risks'])}")
        return final_audit_data
        
    except Exception as parse_err2:
        logger.error(f"Failed to parse Stage 3 final audit JSON: {parse_err2}. Content: {response_stage2.content}")
        # Return fallback audit structure
        return {
            "overall_score": 50,
            "summary": "Failed to parse final compliance audit from LLM. Please re-run the analysis.",
            "risks": [
                {
                    "category": "Other",
                    "clause_text": "Audit execution encountered a parsing error.",
                    "severity": "MEDIUM",
                    "severity_color": "yellow",
                    "explanation": f"The LLM response could not be parsed as valid JSON: {str(parse_err2)}",
                    "citation": "N/A",
                    "suggestion": "Please retry the audit or upload the document again."
                }
            ]
        }
