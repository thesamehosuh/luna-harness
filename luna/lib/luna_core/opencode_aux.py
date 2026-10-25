# SPDX-License-Identifier: Apache-2.0
# Attribution and inherited MIT notices: OPENCODE_NOTICES.txt
"""Text auxiliary calls (titles/compression) stay on the chosen free native model."""
from __future__ import annotations

import asyncio
import uuid
import warnings
from types import SimpleNamespace

from luna_core.opencode_client import OpenCodeServer
from luna_core.opencode_attachments import prompt_parts


class OpenCodeAuxClient:
    api_key = "no-key-required"
    base_url = "opencode://local"
    _hermes_aux_effective_provider = "opencode-engine"

    def __init__(self, model: str):
        self.model = model
        self.chat = SimpleNamespace(completions=self)

    def close(self):
        pass

    def with_options(self, **kwargs):
        unknown = set(kwargs) - {"timeout", "max_retries"}
        if unknown:
            raise ValueError("Unsupported native client options: " + ", ".join(sorted(unknown)))
        cloned = OpenCodeAuxClient(self.model)
        cloned.timeout = kwargs.get("timeout", getattr(self, "timeout", 180))
        return cloned

    def create(self, *, messages, model=None, stream=False, tools=None, **_kwargs):
        # Native protocol 2.1 has no per-call sampler/output-cap contract. Surface this
        # explicitly to callers instead of pretending to enforce OpenAI-shaped parameters.
        unsupported = sorted(key for key, value in _kwargs.items() if value is not None)
        if unsupported:
            warnings.warn("OpenCode native auxiliary protocol does not enforce: " + ", ".join(unsupported), RuntimeWarning, stacklevel=2)
        if tools:
            raise ValueError("OpenCode auxiliary calls cannot execute tools. Use a Luna conversation for tools.")
        instructions, prompt_rows, files = [], [], []
        for row in messages:
            text, attachments = prompt_parts(row.get("content", ""))
            if row.get("role") in {"system", "developer"}:
                if attachments:
                    raise ValueError("System instructions cannot contain image attachments.")
                instructions.append(text)
            else:
                prompt_rows.append(f"{row['role']}: {text}")
                files.extend(attachments)
        prompt = "\n\n".join(prompt_rows)
        instructions = "\n\n".join(instructions)
        with OpenCodeServer(workspace_key="aux-" + uuid.uuid4().hex, ephemeral=True) as server:
            result = server.run(model=model or self.model, prompt=prompt, files=files,
                                instructions=instructions + "\nReply with the requested text. Do not use tools.", max_steps=3, timeout=_kwargs.get("timeout", getattr(self, "timeout", 180)))
        # Use the SDK's ordinary response types so downstream JSON/usage helpers work unchanged.
        from openai.types.chat import ChatCompletion, ChatCompletionChunk
        usage = {"prompt_tokens": int(result.input_tokens), "completion_tokens": int(result.output_tokens),
                 "total_tokens": int(result.input_tokens + result.output_tokens)}
        response_id = "luna-opencode-" + uuid.uuid4().hex
        if stream:
            return iter([
                ChatCompletionChunk(id=response_id, created=0, model=model or self.model, object="chat.completion.chunk",
                    choices=[{"index": 0, "delta": {"content": result.text}, "finish_reason": None}]),
                ChatCompletionChunk(id=response_id, created=0, model=model or self.model, object="chat.completion.chunk",
                    choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}], usage=usage),
            ])
        return ChatCompletion(id=response_id, created=0, model=model or self.model, object="chat.completion", luna_unsupported_options=unsupported,
            choices=[{"index": 0, "message": {"role": "assistant", "content": result.text}, "finish_reason": "stop"}], usage=usage)


class AsyncOpenCodeAuxClient:
    def __init__(self, client: OpenCodeAuxClient):
        self.client = client
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        response = await asyncio.to_thread(self.client.create, **kwargs)
        if kwargs.get("stream"):
            async def chunks():
                for chunk in response:
                    yield chunk
            return chunks()
        return response

    async def close(self):
        self.client.close()
