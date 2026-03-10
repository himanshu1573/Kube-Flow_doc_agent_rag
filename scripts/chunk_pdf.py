import argparse
import json
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def chunk_pdf(
    pdf_path: Path,
    output_path: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> int:
    text = extract_pdf_text(pdf_path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_text(text)

    with output_path.open("w", encoding="utf-8") as output_file:
        for index, chunk in enumerate(chunks):
            output_file.write(
                json.dumps(
                    {
                        "source_file": str(pdf_path),
                        "chunk_index": index,
                        "content_text": chunk,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and chunk a PDF for RAG.")
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument(
        "--output",
        default="chunks/kubeflow_documentation_chunks.jsonl",
        help="Path to the output JSONL file",
    )
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=100)
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = chunk_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    print(f"Wrote {count} chunks to {output_path}")


if __name__ == "__main__":
    main()
