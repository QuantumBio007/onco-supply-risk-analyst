"""
agent_core.py — Agentic supply chain analyst using raw Anthropic tool use.

Tools:
  1. search_kb       — retrieves from ChromaDB
  2. run_simulation  — runs live Monte Carlo via supply_sim.simulate()
  3. web_search      — searches for current country/drug data

Usage:
    from agent_core import run_agent
    brief, trace = run_agent("cisplatin", "Argentina", "API export restriction")
"""

import json
import httpx
import anthropic
import chromadb
from pathlib import Path
from sentence_transformers import SentenceTransformer
from supply_sim import simulate, result_to_text
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

MODEL = "claude-haiku-4-5-20251001"

# ── Cached resources ──────────────────────────────────────────────────────────
_embed_model = None
_collection  = None

def _get_retriever():
    global _embed_model, _collection
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-mpnet-base-v2")
        client      = chromadb.PersistentClient(path="./chroma_db")
        _collection = client.get_collection("onco_supply")
    return _embed_model, _collection

# ── Tool definitions (Anthropic format) ──────────────────────────────────────
TOOLS = [
    {
        "name": "search_kb",
        "description": (
            "Retrieve relevant context from the oncology supply chain knowledge base. "
            "Call with doc_type='kb' for institutional/regulatory docs, "
            "doc_type='sim' for pre-computed simulation outputs. "
            "Call twice — once for each doc_type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "description": "Search query"},
                "doc_type": {"type": "string", "enum": ["kb", "sim"],
                             "description": "kb = institutional docs, sim = simulation outputs"}
            },
            "required": ["query", "doc_type"]
        }
    },
    {
        "name": "run_simulation",
        "description": (
            "Run live Monte Carlo inventory simulation for a drug-country-scenario triple. "
            "Returns stockout days, service level, risk rating, and optimal (Q,r) policy. "
            "Always call this — do not rely on pre-computed text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug":     {"type": "string",
                             "enum": ["cisplatin","doxorubicin","carboplatin","trastuzumab"]},
                "country":  {"type": "string",
                             "enum": ["Argentina","Venezuela","Colombia"]},
                "scenario": {"type": "string",
                             "enum": ["Baseline","API export restriction",
                                      "Currency devaluation","Combined shock"]}
            },
            "required": ["drug", "country", "scenario"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Search for current pharmaceutical supply chain data, government reports, "
            "or drug shortage news. Use ONLY when KB context is stale or missing. "
            "Example: 'Venezuela oncology drug shortage 2024 MSF'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }
]

# ── Tool execution ────────────────────────────────────────────────────────────
def _execute_tool(name: str, inputs: dict) -> str:
    if name == "search_kb":
        embed_model, collection = _get_retriever()
        emb     = embed_model.encode([inputs["query"]]).tolist()
        results = collection.query(
            query_embeddings=emb,
            n_results=5,
            where={"doc_type": inputs["doc_type"]}
        )
        docs    = results["documents"][0]
        sources = [m.get("source_file", "?") for m in results["metadatas"][0]]
        return "\n\n".join(f"[{s}]\n{d}" for s, d in zip(sources, docs))

    elif name == "run_simulation":
        result = simulate(inputs["drug"], inputs["country"], inputs["scenario"], n_runs=500)
        return result_to_text(result)

    elif name == "web_search":
        try:
            resp = httpx.get(
                "https://api.duckduckgo.com/",
                params={"q": inputs["query"], "format": "json", "no_redirect": "1"},
                timeout=10,
            )
            data     = resp.json()
            abstract = data.get("AbstractText", "")
            related  = [r.get("Text", "") for r in data.get("RelatedTopics", [])[:3]
                        if isinstance(r, dict)]
            text     = abstract + "\n" + "\n".join(related)
            return text.strip() or "No results found."
        except Exception as e:
            return f"Search failed: {e}"

    return f"Unknown tool: {name}"

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert oncology supply chain analyst at JCNB Biotech Consulting.

You produce structured Drug Shortage Risk Briefs for Latin America.

Use your tools in this order:
1. search_kb with doc_type='kb' — retrieve institutional and regulatory context
2. search_kb with doc_type='sim' — retrieve pre-computed simulation context
3. run_simulation — get live quantitative stockout risk estimates
4. web_search — ONLY if KB context is clearly insufficient or outdated

Output format — use exactly these section headers:
## Drug Profile
## Supply Chain Vulnerability
## Scenario Impact Analysis
## Policy Recommendations
## Confidence & Limitations

Rules:
- Base all factual claims (statistics, timelines, drug parameters) on tool results. Do not invent data.
- Cite which tool provided each key fact.
- Policy Recommendations is an analytical section — always write 2-3 concrete recommendations derived from the vulnerability analysis. Recommendations do not require simulation data to support them; they require reasoning.
- Confidence & Limitations must state what is uncertain."""

# ── Agentic loop ──────────────────────────────────────────────────────────────
def run_agent(drug: str, country: str, scenario: str):
    """
    Run the agentic brief generation pipeline.
    Returns (brief_text, trace) where trace is a list of tool call steps.
    """
    client   = anthropic.Anthropic()
    messages = [{
        "role": "user",
        "content": (
            f"Generate a Drug Shortage Risk Brief for {drug} in {country} "
            f"under scenario: {scenario}. "
            f"Use search_kb (both doc types), run_simulation, "
            f"and web_search if needed. Cite your sources."
        )
    }]

    trace = []  # visible tool call log for Streamlit

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    step = f"**{block.name}** `{json.dumps(block.input)}`"
                    trace.append(step)
                    result = _execute_tool(block.name, block.input)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",      "content": tool_results})

        else:
            brief = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            return brief, trace


if __name__ == "__main__":
    brief, trace = run_agent("cisplatin", "Argentina", "Baseline")
    print("\n--- TOOL TRACE ---")
    for step in trace:
        print(step)
    print("\n--- BRIEF ---")
    print(brief)
