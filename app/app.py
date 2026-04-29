import streamlit as st
import anthropic
import chromadb
from sentence_transformers import SentenceTransformer
import os

ALLOWED_DRUGS     = ["cisplatin", "doxorubicin", "carboplatin", "trastuzumab"]
ALLOWED_COUNTRIES = ["Argentina", "Venezuela", "Colombia"]
ALLOWED_SCENARIOS = ["Baseline", "API export restriction", "Currency devaluation", "Combined shock"]
MODEL             = "claude-haiku-4-5-20251001"

@st.cache_resource
def load_retriever():
    model = SentenceTransformer("all-mpnet-base-v2")
    client = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_collection("onco_supply")
    return model, collection

@st.cache_resource
def load_client():
    return anthropic.Anthropic()

def retrieve(drug, country, scenario, n=5):
    embed_model, collection = load_retriever()

    # Dual-query: a single query ranked scenario keywords over institutional KB docs,
    # causing country procurement docs (obras sociales, ANMAT, MPPS) to be missed.
    # Query 1 surfaces institutional/regulatory context; Query 2 surfaces sim data.
    q_context  = f"{drug} {country} procurement supply chain shortage regulatory"
    q_scenario = f"{drug} {country} {scenario} simulation stockout inventory risk"

    def _query(q, doc_type):
        emb = embed_model.encode([q]).tolist()
        res = collection.query(query_embeddings=emb, n_results=n, where={"doc_type": doc_type})
        return list(zip(res["documents"][0], res["metadatas"][0]))

    seen, merged = set(), []
    for chunk_list in [_query(q_context, "kb"), _query(q_scenario, "sim")]:
        for doc, meta in chunk_list:
            key = meta.get("source_file", "") + doc[:40]
            if key not in seen:
                seen.add(key)
                merged.append((doc, meta))

    return merged[:n + 2]  # slightly more than n to ensure both context types covered

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
- The Confidence & Limitations section must honestly state what is uncertain."""

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

def generate_brief(drug, country, scenario, chunks):
    client = load_client()
    context = "\n\n".join(
        f"[Source: {meta.get('source_file', '?')}]\n{doc}"
        for doc, meta in chunks
    )
    user_msg = f"""Generate a Drug Shortage Risk Brief for:
- Drug: {drug}
- Country: {country}
- Scenario: {scenario}

Retrieved context:
{context}

{FEW_SHOT}

Now write the brief for {drug} in {country} under the {scenario} scenario."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}]
    )
    return response.content[0].text

# --- UI ---
st.set_page_config(page_title="OncoSupply Risk Analyst", layout="wide")
st.title("OncoSupply Risk Analyst")
st.caption("AI-powered oncology drug shortage risk briefs for Latin America · JCNB Biotech Consulting")

with st.sidebar:
    st.header("Parameters")
    drug     = st.selectbox("Drug",     ALLOWED_DRUGS)
    country  = st.selectbox("Country",  ALLOWED_COUNTRIES)
    scenario = st.selectbox("Scenario", ALLOWED_SCENARIOS)
    generate = st.button("Generate Risk Brief", type="primary")

if generate:
    with st.spinner("Retrieving context and generating brief..."):
        chunks = retrieve(drug, country, scenario)
        brief  = generate_brief(drug, country, scenario, chunks)

    st.markdown(f"## {drug.title()} — {country} — {scenario}")
    st.markdown(brief)

    with st.expander("Sources (retrieved context chunks)"):
        for i, (doc, meta) in enumerate(chunks):
            st.markdown(f"**Source {i+1}: `{meta.get('source_file', '?')}`**")
            st.text(doc[:400] + ("..." if len(doc) > 400 else ""))
