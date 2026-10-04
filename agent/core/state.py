"""Lightweight in-memory thread store for Phase 2 stateful chat flows."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

ChatMessage = Dict[str, Any]


@dataclass
class ConversationThread:
    thread_id: str
    messages: List[ChatMessage] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    """In-memory thread store with TTL pruning and bounded history."""

    def __init__(self, ttl_seconds: int = 3600, max_messages: int = 16):
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages
        self._threads: Dict[str, ConversationThread] = {}
        self._lock = threading.Lock()

    def _prune_locked(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        expired = [
            thread_id
            for thread_id, thread in self._threads.items()
            if thread.updated_at < cutoff
        ]
        for thread_id in expired:
            self._threads.pop(thread_id, None)

    def ensure_thread(self, system_prompt: str, thread_id: str | None = None) -> str:
        with self._lock:
            self._prune_locked()
            resolved_id = thread_id or str(uuid.uuid4())
            thread = self._threads.get(resolved_id)
            if thread is None:
                thread = ConversationThread(
                    thread_id=resolved_id,
                    messages=[{"role": "system", "content": system_prompt}],
                )
                self._threads[resolved_id] = thread
            elif thread.messages:
                thread.messages[0] = {"role": "system", "content": system_prompt}
            else:
                thread.messages.append({"role": "system", "content": system_prompt})
            thread.updated_at = time.time()
            return resolved_id

    def append(self, thread_id: str, role: str, content: str) -> None:
        if not content:
            return
        with self._lock:
            thread = self._threads.setdefault(
                thread_id, ConversationThread(thread_id=thread_id)
            )
            thread.messages.append({"role": role, "content": content})
            thread.updated_at = time.time()

            system_message = thread.messages[:1]
            body = thread.messages[1:]
            if len(body) > self.max_messages:
                body = body[-self.max_messages :]
            thread.messages = system_message + body

    def get_messages(self, thread_id: str) -> List[ChatMessage]:
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                return []
            thread.updated_at = time.time()
            return [message.copy() for message in thread.messages]

    def clear(self, thread_id: str) -> None:
        with self._lock:
            self._threads.pop(thread_id, None)


THREAD_STORE = ConversationStore(
    ttl_seconds=int(os.getenv("THREAD_TTL_SECONDS", "3600")),
    max_messages=int(os.getenv("THREAD_MAX_MESSAGES", "16")),
)
