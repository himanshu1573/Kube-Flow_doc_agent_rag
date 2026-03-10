import argparse
from pathlib import Path

from kfp import Client


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit the compiled RAG pipeline to Kubeflow Pipelines.")
    parser.add_argument("--host", default="http://127.0.0.1:8888")
    parser.add_argument(
        "--pipeline-package",
        default=str(
            Path(__file__).resolve().parents[1]
            / "pipelines"
            / "kubeflow_rag_pipeline.yaml"
        ),
    )
    parser.add_argument("--run-name", default="kubeflow-pdf-rag-run")
    parser.add_argument("--experiment-name", default="kubeflow-docs-rag")
    parser.add_argument("--docs-path", default="/data/Kubeflow_Documentation.pdf")
    parser.add_argument("--docs-config-map-name", default="kubeflow-docs-pdf")
    parser.add_argument(
        "--milvus-uri",
        default="http://milvus.docs-agent.svc.cluster.local:19530",
    )
    parser.add_argument("--collection-name", default="kubeflow_pdf_rag")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=100)
    parser.add_argument("--drop-existing", action="store_true", default=True)
    args = parser.parse_args()

    client = Client(host=args.host)
    client.create_experiment(name=args.experiment_name)

    run = client.create_run_from_pipeline_package(
        pipeline_file=args.pipeline_package,
        arguments={
            "docs_path": args.docs_path,
            "docs_config_map_name": args.docs_config_map_name,
            "milvus_uri": args.milvus_uri,
            "collection_name": args.collection_name,
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
            "drop_existing": args.drop_existing,
        },
        run_name=args.run_name,
        experiment_name=args.experiment_name,
    )
    print(f"Run submitted: {run.run_id}")


if __name__ == "__main__":
    main()
