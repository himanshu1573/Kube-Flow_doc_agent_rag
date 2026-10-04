import unittest

from agent.core.retriever import build_code_citation_url
from agent.core.router import build_system_prompt, classify_question


class Phase2RouterTests(unittest.TestCase):
    def test_docs_question_routes_to_docs_or_hybrid(self):
        decision = classify_question("What is Kubeflow Pipelines and how does it work?")
        self.assertIn(decision.target, {"docs", "hybrid"})

    def test_code_question_routes_to_code(self):
        decision = classify_question("How do I configure the mutating webhook YAML for notebooks?")
        self.assertEqual(decision.target, "code")

    def test_install_question_with_code_request_routes_to_hybrid(self):
        decision = classify_question("How do I install Kubeflow? Give me the kubectl commands.")
        self.assertEqual(decision.target, "hybrid")

    def test_system_prompt_includes_route_hint(self):
        decision = classify_question("Explain Kubeflow architecture")
        prompt = build_system_prompt(decision)
        self.assertIn("Router decision:", prompt)
        self.assertIn("Answer format guidance:", prompt)

    def test_code_citation_url_uses_line_anchor(self):
        url = build_code_citation_url("apps/example/deployment.yaml", 42)
        self.assertTrue(url.endswith("apps/example/deployment.yaml#L42"))


if __name__ == "__main__":
    unittest.main()
