from pathlib import Path

from kfp import compiler
from kfp import dsl
from kfp import kubernetes


@dsl.component(
    base_image="python:3.11",
    packages_to_install=["beautifulsoup4>=4.12.0", "pypdf>=5.0.0"],
)
def collect_docs(
    input_dir: str,
    docs_data: dsl.Output[dsl.Dataset],
    allowed_extensions: str = ".md,.html,.pdf",
):
    import json
    import os
    from pathlib import Path

    from bs4 import BeautifulSoup
    from pypdf import PdfReader

    extensions = {ext.strip().lower() for ext in allowed_extensions.split(",") if ext.strip()}
    skipped_dirs = {".git", ".hg", ".svn", "__pycache__", "node_modules", "venv", ".venv"}
    collected = 0

    def read_document(full_path: str, suffix: str):
        try:
            if suffix == ".pdf":
                reader = PdfReader(full_path)
                pages = [page.extract_text() or "" for page in reader.pages]
                return "\n\n".join(pages)

            with open(full_path, "r", encoding="utf-8", errors="ignore") as source_file:
                raw_content = source_file.read()

            if suffix == ".html":
                return BeautifulSoup(raw_content, "html.parser").get_text(separator=" ", strip=True)

            return raw_content
        except Exception as exc:
            print(f"Skipping {full_path}: {exc}")
            return None

    with open(docs_data.path, "w", encoding="utf-8") as output_file:
        input_path = Path(input_dir)

        if input_path.is_file():
            suffix = input_path.suffix.lower()
            if suffix not in extensions:
                raise ValueError(f"Unsupported file type: {input_path}")

            text = read_document(str(input_path), suffix)
            if text:
                record = {
                    "path": str(input_path),
                    "title": input_path.name,
                    "content": text,
                    "citation_url": f"file://{input_path}",
                }
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                collected += 1
        else:
            for root, dirs, files in os.walk(input_dir):
                dirs[:] = [name for name in dirs if name not in skipped_dirs]

                for filename in files:
                    suffix = os.path.splitext(filename)[1].lower()
                    if suffix not in extensions:
                        continue

                    full_path = os.path.join(root, filename)
                    text = read_document(full_path, suffix)
                    if text is None:
                        continue

                    record = {
                        "path": full_path,
                        "title": filename,
                        "content": text,
                        "citation_url": f"file://{full_path}",
                    }
                    output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    collected += 1

    print(f"Collected {collected} documentation files from {input_dir}")


@dsl.component(
    base_image="python:3.11",
    packages_to_install=[
        "sentence-transformers>=3.0.0",
        "langchain-text-splitters>=0.3.0",
        "torch>=2.2.0",
    ],
)
def chunk_and_embed(
    docs_data: dsl.Input[dsl.Dataset],
    embedded_data: dsl.Output[dsl.Dataset],
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
):
    import json

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(embedding_model)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    chunks_written = 0

    with open(docs_data.path, "r", encoding="utf-8") as input_file, open(
        embedded_data.path, "w", encoding="utf-8"
    ) as output_file:
        for line in input_file:
            record = json.loads(line)
            content = record["content"]
            path = record["path"]
            title = record["title"]
            citation_url = record["citation_url"]

            chunks = splitter.split_text(content)
            for chunk_index, chunk in enumerate(chunks):
                vector = encoder.encode(chunk).tolist()
                output_file.write(
                    json.dumps(
                        {
                            "file_path": path,
                            "title": title,
                            "citation_url": citation_url,
                            "chunk_index": chunk_index,
                            "content_text": chunk,
                            "vector": vector,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                chunks_written += 1

    print(f"Wrote {chunks_written} chunk embeddings")


@dsl.component(
    base_image="python:3.11",
    packages_to_install=["pymilvus>=2.4.0"],
)
def upsert_to_milvus(
    embedded_data: dsl.Input[dsl.Dataset],
    milvus_uri: str,
    collection_name: str = "kubeflow_docs_rag",
    drop_existing: bool = True,
    batch_size: int = 64,
):
    import json

    from pymilvus import MilvusClient

    client = MilvusClient(uri=milvus_uri)

    if client.has_collection(collection_name):
        if drop_existing:
            client.drop_collection(collection_name)
        else:
            print(f"Collection {collection_name} already exists, appending new rows")

    if not client.has_collection(collection_name):
        client.create_collection(
            collection_name=collection_name,
            dimension=384,
            primary_field_name="id",
            id_type="int",
            auto_id=True,
            metric_type="IP",
        )

    buffer = []
    inserted = 0

    with open(embedded_data.path, "r", encoding="utf-8") as input_file:
        for line in input_file:
            record = json.loads(line)
            buffer.append(record)

            if len(buffer) >= batch_size:
                result = client.insert(collection_name=collection_name, data=buffer)
                inserted += result.get("insert_count", len(buffer))
                buffer = []

    if buffer:
        result = client.insert(collection_name=collection_name, data=buffer)
        inserted += result.get("insert_count", len(buffer))

    print(f"Inserted {inserted} chunks into Milvus collection {collection_name}")


@dsl.pipeline(
    name="kubeflow-docs-agent-rag",
    description="Simple Kubeflow Pipeline that indexes documentation into Milvus for RAG.",
)
def kubeflow_docs_agent_rag_pipeline(
    docs_path: str = "/data/kubeflow-docs",
    milvus_uri: str = "http://milvus.docs-agent.svc.cluster.local:19530",
    collection_name: str = "kubeflow_docs_rag",
    docs_config_map_name: str = "",
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    drop_existing: bool = True,
):
    collect_task = collect_docs(input_dir=docs_path)
    if docs_config_map_name:
        kubernetes.use_config_map_as_volume(
            collect_task,
            config_map_name=docs_config_map_name,
            mount_path="/data",
        )

    embed_task = chunk_and_embed(
        docs_data=collect_task.outputs["docs_data"],
        embedding_model=embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    upsert_to_milvus(
        embedded_data=embed_task.outputs["embedded_data"],
        milvus_uri=milvus_uri,
        collection_name=collection_name,
        drop_existing=drop_existing,
    )


if __name__ == "__main__":
    output_path = Path(__file__).with_suffix(".yaml")
    compiler.Compiler().compile(
        pipeline_func=kubeflow_docs_agent_rag_pipeline,
        package_path=str(output_path),
    )
    print(f"Pipeline compiled to {output_path}")
