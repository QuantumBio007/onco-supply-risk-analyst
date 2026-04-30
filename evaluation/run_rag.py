"""
run_rag.py — Generate RAG-augmented briefs for evaluation Cases 1-3.
Mirrors app.py logic exactly, runs from CLI without Streamlit.

Run from Project root:
    python3 evaluation/run_rag.py

Outputs:
    evaluation/outputs/case1_rag.txt
    evaluation/outputs/case2_rag.txt
    evaluation/outputs/case3_rag.txt
"""
import anthropic
import chromadb
import os
from sentence_transformers import SentenceTransformer

os.makedirs("evaluation/outputs", exist_ok=True)

CASES = [
    ("cisplatin",    "Argentina", "Baseline",              "case1_rag.txt"),
    ("trastuzumab",  "Venezuela", "Baseline",              "case2_rag.txt"),
    ("cisplatin",    "Argentina", "API export restriction", "case3_rag.txt"),
    ("doxorubicin",  "Colombia",  "Currency devaluation",  "case4_rag.txt"),
    ("carboplatin",  "Venezuela", "Combined shock",         "case5_rag.txt"),
]

SYSTEM_PROMPT = """You are an expert supply-chain analyst at JCNB Biotech Consulting \
specializing in oncology drug shortage risk in Latin America.

You produce structured Drug Shortage Risk Briefs based ONLY on the retrieved context provided.

Output format — use exactly these section headers:
## Drug Profile
## Supply Chain Vulnerability
## Scenario Impact Analysis
## Policy Recommendations
## Confidence & Limitations

Rules:
- Base all claims on the provided context. Do not invent statistics.
- If the context does not contain enough information for a section, say so explicitly.
- Never provide clinical advice or drug substitution recommendations.
- The Confidence & Limitations section must honestly state what is uncertain.
- In the ## Drug Profile section, if the retrieved context confirms it, explicitly state: (a) whether the drug is included on the WHO Model List of Essential Medicines (EML), and (b) the primary country or countries of origin for API manufacturing (e.g., India, China). Only make these claims if the context supports them.
- For platinum-based drugs (cisplatin, carboplatin), if the retrieved context mentions a shared API supply chain with another platinum agent, note this explicitly in the Supply Chain Vulnerability section."""

FEW_SHOT = """Example of a well-formatted brief (tone and structure reference only):

## Drug Profile
Cisplatin is a platinum-based chemotherapy agent on the WHO Model List of Essential Medicines. \
It is generic and off-patent, with API manufacturing concentrated in India and China.

## Supply Chain Vulnerability
Argentina has no domestic API manufacturing and is fully import-dependent. The multi-channel \
procurement landscape (public hospitals, obras sociales, provincial systems, private) creates \
visibility gaps — no single entity tracks national stock levels.

## Scenario Impact Analysis
Under baseline conditions, modeled service levels exceed 94%. Under an API export restriction \
scenario (lead time tripling to 30 days), stockout days increase to 49/year, reducing service \
level to 85%.

## Policy Recommendations
1. Establish a national strategic reserve of 60-day buffer stock for cisplatin.
2. Coordinate procurement across public and obras sociales channels to reduce fragmentation.

## Confidence & Limitations
Stockout figures are from a simplified inventory model and are illustrative, not actuarial. \
Procurement data reflects publicly available sources as of 2024."""

embed_model = SentenceTransformer("all-mpnet-base-v2")
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_collection("onco_supply")
claude = anthropic.Anthropic()


def retrieve(drug, country, scenario, n=5):
    # Triple-query strategy: each query contributes a fixed quota so no source type is crowded out.
    # Profile query runs first to guarantee EML/API facts are in context.
    q_context  = f"{drug} {country} procurement supply chain shortage regulatory"
    q_scenario = f"{drug} {country} {scenario} simulation stockout inventory risk"
    q_profile  = f"{drug} WHO essential medicines EML API manufacturing India China generic patent"

    def _query(q, doc_type, k):
        emb = embed_model.encode([q]).tolist()
        res = collection.query(query_embeddings=emb, n_results=k, where={"doc_type": doc_type})
        return list(zip(res["documents"][0], res["metadatas"][0]))

    seen, merged = set(), []
    # Profile chunks first (guaranteed slots) then context and sim
    for chunk_list in [_query(q_profile, "kb", 3),
                       _query(q_context, "kb", n),
                       _query(q_scenario, "sim", n)]:
        for doc, meta in chunk_list:
            key = meta.get("source_file", "") + doc[:40]
            if key not in seen:
                seen.add(key)
                merged.append((doc, meta))

    return merged[:n + 6]


def generate_brief(drug, country, scenario, chunks):
    context = "\n\n".join(
        f"[Source: {meta.get('source_file', '?')}]\n{doc}"
        for doc, meta in chunks
    )
    user_msg = (
        f"Generate a Drug Shortage Risk Brief for:\n"
        f"- Drug: {drug}\n- Country: {country}\n- Scenario: {scenario}\n\n"
        f"Retrieved context:\n{context}\n\n{FEW_SHOT}\n\n"
        f"Now write the brief for {drug} in {country} under the {scenario} scenario."
    )
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text, chunks


for drug, country, scenario, outfile in CASES:
    print(f"Generating RAG: {drug} / {country} / {scenario} ...")
    chunks = retrieve(drug, country, scenario)
    brief, used_chunks = generate_brief(drug, country, scenario, chunks)

    outpath = os.path.join("evaluation", "outputs", outfile)
    with open(outpath, "w") as f:
        f.write(f"CASE: {drug} / {country} / {scenario}\n")
        f.write("SOURCE: RAG (ChromaDB retrieval + Claude generation)\n")
        f.write("=" * 60 + "\n\n")
        f.write(brief)
        f.write("\n\n" + "=" * 60 + "\n")
        f.write("RETRIEVED SOURCES:\n")
        for i, (doc, meta) in enumerate(used_chunks):
            f.write(f"\n[{i+1}] {meta.get('source_file','?')}\n")
            f.write(doc[:300] + ("..." if len(doc) > 300 else "") + "\n")

    print(f"  Saved → {outpath}")
    print(f"  Sources: {[m.get('source_file','?') for _, m in chunks]}")

print("\nDone. Run evaluation/run_judge.py to score outputs.")
