"""Offline, CPU-only multilingual embeddings using a release-bundled ONNX model."""
from pathlib import Path
import base64
import hashlib
import json
import threading
import os

MODEL = json.loads(Path(__file__).with_name("embedding-model.json").read_text())


def model_directory():
    return Path(os.environ.get("LUNA_EMBEDDING_BUNDLE") or Path(__file__).resolve().parents[3] / "luna/assets/embeddings")


class Embedder:
    def __init__(self, directory=None):
        directory = Path(directory or model_directory())
        for name, spec in MODEL["files"].items():
            path = directory / name
            if not path.is_file() or path.stat().st_size != spec["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
                raise ValueError("The bundled memory model is missing or damaged. Repair Luna's runtime in Setup.")
        # These libraries load only local files. No Transformers/Hugging Face hub client.
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(directory / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        self.inputs = {value.name for value in self.session.get_inputs()}
        self.lock = threading.Lock()

    def vectors(self, texts):
        import numpy as np
        result, count = [], 0
        if not texts or len(texts) > 256 or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("Embeddings require 1–256 non-empty strings; token id arrays are not supported")
        if sum(len(t.encode()) for t in texts) > 512_000:
            raise ValueError("Embedding batch is too large")
        with self.lock:
            for text in texts:
                encoding = self.tokenizer.encode(text, add_special_tokens=False)
                ids = encoding.ids
                if len(ids) > MODEL["max_document_tokens"]:
                    raise ValueError("Memory text exceeds 8192 model tokens; split it before embedding")
                count += len(ids)
                sums, weights = [], []
                # Every token contributes, instead of silently truncating long room messages.
                for offset in range(0, len(ids), MODEL["sequence_tokens"] - 2):
                    chunk = ids[offset:offset + MODEL["sequence_tokens"] - 2]
                    tokens = [self.tokenizer.token_to_id("<s>"), *chunk, self.tokenizer.token_to_id("</s>")]
                    values = {"input_ids": np.asarray([tokens], dtype=np.int64),
                              "attention_mask": np.ones((1, len(tokens)), dtype=np.int64),
                              "token_type_ids": np.zeros((1, len(tokens)), dtype=np.int64)}
                    hidden = self.session.run(None, {k: v for k, v in values.items() if k in self.inputs})[0]
                    sums.append(hidden[0].mean(axis=0))
                    weights.append(len(chunk))
                vector = np.average(np.stack(sums), axis=0, weights=weights)
                norm = np.linalg.norm(vector)
                if vector.shape != (MODEL["dimensions"],) or not np.isfinite(norm) or norm <= 0:
                    raise ValueError("The local embedding runtime returned an invalid vector")
                result.append((vector / norm).astype(np.float32).tolist())
        return result, count

    def response(self, body):
        if body.get("model") != MODEL["id"]:
            raise ValueError("Embedding model does not match this memory database")
        if body.get("dimensions", MODEL["dimensions"]) != MODEL["dimensions"]:
            raise ValueError("Embedding dimension mismatch; migrate the memory index before changing models")
        texts = body.get("input")
        texts = [texts] if isinstance(texts, str) else texts
        if not isinstance(texts, list): raise ValueError("Embeddings require text input")
        fmt = body.get("encoding_format", "float")
        if fmt not in {"float", "base64"}: raise ValueError("Unsupported embedding encoding")
        vectors, tokens = self.vectors(texts)
        if fmt == "base64":
            import numpy as np
            vectors = [base64.b64encode(np.asarray(v, dtype="<f4").tobytes()).decode() for v in vectors]
        return {"object": "list", "model": MODEL["id"], "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens}}
