import hashlib
import json
import math
import re

from app.ai.llm import LLMError, LLMResult
from app.knowledge.embeddings import EmbeddingError, EmbedResult
from app.knowledge.vector import EMBEDDING_DIM

GOOD_REPLY = {
    "cited_article_ids": [],
    "category": "billing",
    "priority": "high",
    "summary": "Customer was charged twice and wants a refund.",
    "draft_reply": "Hi, sorry about the double charge. We are looking into it and will update you shortly.",
    "recommended_action": "reply_only",
}


class FakeLLM:
    """Stands in for the Anthropic client: records what it was sent and returns a canned answer.

    `tool_script` is a list of (tool name, arguments) the "model" asks for, in order, before it answers (each is
    executed through the real gateway callback it was given). `reply` may be a dict of fields to override in the
    default answer, or a function of the tool results (a list of (name, arguments, text, is_error)) returning one.
    """

    model = "fake-model"

    def __init__(self, reply=None, *, raw_text=None, error=None, tool_script=None):
        self._reply = reply
        self.raw_text = raw_text
        self.error = error
        self.tool_script = list(tool_script or [])
        self.tool_results: list[tuple] = []
        self.calls: list[dict] = []

    @property
    def reply(self):
        return dict(GOOD_REPLY, **(self._reply if isinstance(self._reply, dict) else {}))

    async def complete(self, *, system, user, schema, tools=None, execute_tool=None):
        self.calls.append({"system": system, "user": user, "schema": schema, "tools": tools})
        if self.error:
            raise LLMError(self.error)
        if tools and execute_tool:
            for name, arguments in self.tool_script:
                text, is_error = await execute_tool(name, arguments)
                self.tool_results.append((name, arguments, text, is_error))
        reply = self.reply
        if callable(self._reply):
            reply = dict(GOOD_REPLY, **self._reply(self.tool_results))
        text = self.raw_text if self.raw_text is not None else json.dumps(reply)
        return LLMResult(
            text=text, model=self.model, input_tokens=120, output_tokens=60, tool_rounds=len(self.tool_results)
        )


class FakeEmbedder:
    """Deterministic bag-of-words embedder: texts that share words are closer. Records every text it is given."""

    model = "fake-embed"

    def __init__(self, *, error=None, model=None):
        self.error = error
        self.model = model or self.model
        self.calls: list[dict] = []

    @staticmethod
    def vector(text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z0-9]{3,}", text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed(self, texts, *, input_type):
        self.calls.append({"texts": list(texts), "input_type": input_type})
        if self.error:
            raise EmbeddingError(self.error)
        return EmbedResult(vectors=[self.vector(t) for t in texts], model=self.model, total_tokens=sum(len(t.split()) for t in texts))
