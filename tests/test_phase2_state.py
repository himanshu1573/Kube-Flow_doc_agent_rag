import unittest

from agent.core.retriever import build_tools_for_route
from agent.core.state import ConversationStore


class Phase2StateTests(unittest.TestCase):
    def test_conversation_store_creates_and_reuses_thread(self):
        store = ConversationStore(ttl_seconds=60, max_messages=4)
        thread_id = store.ensure_thread("system prompt")
        store.append(thread_id, "user", "hello")
        store.append(thread_id, "assistant", "hi")

        same_thread = store.ensure_thread("updated prompt", thread_id)
        self.assertEqual(thread_id, same_thread)

        messages = store.get_messages(thread_id)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "updated prompt")
        self.assertEqual(messages[-1]["content"], "hi")

    def test_conversation_store_caps_history(self):
        store = ConversationStore(ttl_seconds=60, max_messages=2)
        thread_id = store.ensure_thread("system prompt")
        store.append(thread_id, "user", "one")
        store.append(thread_id, "assistant", "two")
        store.append(thread_id, "user", "three")

        messages = store.get_messages(thread_id)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[1]["content"], "two")
        self.assertEqual(messages[2]["content"], "three")

    def test_build_tools_for_hybrid_route_exposes_all_tools(self):
        tool_names = {
            tool["function"]["name"] for tool in build_tools_for_route("hybrid")
        }
        self.assertEqual(
            tool_names,
            {
                "search_kubeflow_context",
                "search_kubeflow_docs",
                "search_kubeflow_code",
            },
        )


if __name__ == "__main__":
    unittest.main()
