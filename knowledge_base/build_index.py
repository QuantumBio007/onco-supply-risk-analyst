from sentence_transformers import SentenceTransformer
import chromadb, os, glob, re

# Resolve paths absolutely so the script works from ANY cwd. Previously
# DOCS_DIR was a relative literal and the doc_type assignment at line 59
# silently mislabeled every chunk as "sim" when run from outside the repo
# root — corrupting the retrieval filter used by agent_core._execute_tool.
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

DOCS_DIR    = os.path.join(_THIS_DIR, "docs")
SIM_DIR     = os.path.join(_THIS_DIR, "sim_outputs")
CHROMA_PATH = os.path.join(_PROJECT_ROOT, "chroma_db")

CHUNK_TOKENS   = 256   # target chunk size in whitespace-split "tokens"
OVERLAP_TOKENS = 50    # overlap between adjacent chunks

EXCLUDE_FILES = {"argentina_procurement_system_es.txt"}  # Spanish duplicate

model  = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path=CHROMA_PATH)

try:
    client.delete_collection("onco_supply")
except Exception:
    pass
collection = client.create_collection("onco_supply")


def parse_header(text):
    """Split '--- header ---\nbody' and return (meta dict, body str)."""
    parts = text.split("---\n", 1)
    if len(parts) < 2:
        return {}, text
    header, body = parts
    meta = {}
    for line in header.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().lower()
    return meta, body


def chunk_text(text, chunk_size=CHUNK_TOKENS, overlap=OVERLAP_TOKENS):
    """Split text into overlapping windows by word count."""
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


ids, texts, metadatas = [], [], []

for fpath in glob.glob(f"{DOCS_DIR}/*.txt") + glob.glob(f"{SIM_DIR}/*.txt"):
    if os.path.basename(fpath) in EXCLUDE_FILES:
        print(f"Skipping: {os.path.basename(fpath)}")
        continue
    raw  = open(fpath).read()
    meta, body = parse_header(raw)
    meta["source_file"] = os.path.basename(fpath)
    # Use absolute-path containment check (DOCS_DIR is now absolute, see top).
    # Belt-and-suspenders: also test the parent directory directly.
    meta["doc_type"] = "kb" if os.path.dirname(fpath) == DOCS_DIR else "sim"

    for i, chunk in enumerate(chunk_text(body)):
        chunk_id = f"{os.path.basename(fpath)}_chunk{i}"
        ids.append(chunk_id)
        texts.append(chunk)
        metadatas.append(meta)

embeddings = model.encode(texts, show_progress_bar=True).tolist()
collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

print(f"\nIndexed {len(ids)} chunks from "
      f"{len(set(m['source_file'] for m in metadatas))} files")
