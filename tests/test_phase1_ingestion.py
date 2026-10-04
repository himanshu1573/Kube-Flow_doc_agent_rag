import unittest

from pipelines.docs_ingestion.components.chunker import chunk_pages
from pipelines.docs_ingestion.components.crawler import normalize_url
from pipelines.shared.embedding_utils import get_embedding_dimension


class Phase1IngestionTests(unittest.TestCase):
    def test_normalize_url_strips_query_and_fragment(self):
        self.assertEqual(
            normalize_url("https://www.kubeflow.org/docs/?q=test#section"),
            "https://www.kubeflow.org/docs",
        )

    def test_chunk_pages_produces_docs_collection_records(self):
        pages = [
            {
                "source_url": "https://www.kubeflow.org/docs/components/pipelines/overview",
                "page_title": "Kubeflow Pipelines",
                "section": "components",
                "breadcrumb_path": "Docs > Components > Pipelines > Overview",
                "crawled_at": "2026-04-09T00:00:00Z",
                "sections": [
                    {
                        "heading": "Overview",
                        "parent_heading": "Kubeflow Pipelines",
                        "heading_path": "Kubeflow Pipelines > Overview",
                        "blocks": [
                            {
                                "type": "paragraph",
                                "text": "Kubeflow Pipelines helps you build repeatable ML workflows. " * 10,
                            },
                            {
                                "type": "list_step",
                                "text": "Create the namespace and install the platform components.",
                            },
                            {
                                "type": "code",
                                "text": "kubectl apply -k manifests/",
                            },
                        ],
                        "text": "Kubeflow Pipelines helps you build repeatable ML workflows. " * 15,
                    }
                ],
            }
        ]
        chunks = chunk_pages(pages, chunk_size=300, chunk_overlap=30)
        self.assertGreaterEqual(len(chunks), 1)
        first = chunks[0]
        self.assertIn("chunk_id", first)
        self.assertEqual(first["section"], "components")
        self.assertEqual(first["heading"], "Overview")
        self.assertIn("chunk_type", first)
        self.assertIn(first["chunk_type"], {"concept", "procedure", "command", "faq"})
        self.assertIn("heading_path", first)
        self.assertIn("chunk_text", first)

    def test_embedding_dimension_defaults_match_shared_model(self):
        self.assertEqual(get_embedding_dimension(), 768)


if __name__ == "__main__":
    unittest.main()
