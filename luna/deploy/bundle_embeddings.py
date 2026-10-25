"""Release-build step: vendor pinned weights/tokenizer, never download at inference time."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import urllib.request

SPEC = Path(__file__).resolve().parents[1] / "lib/luna_core/embedding-model.json"


def bundle(destination):
    spec = json.loads(SPEC.read_text())
    destination.mkdir(parents=True, exist_ok=True)
    for name, file in spec["files"].items():
        target = destination / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == file["sha256"]:
            continue
        partial = target.with_suffix(target.suffix + ".partial")
        url = f"https://huggingface.co/{spec['export']}/resolve/{spec['revision']}/{file['path']}"
        with urllib.request.urlopen(url, timeout=120) as source, partial.open("wb") as output:
            size = 0
            while chunk := source.read(256 * 1024):
                size += len(chunk)
                if size > file["bytes"]: raise ValueError("Embedding artifact exceeds its pinned size")
                output.write(chunk)
        if size != file["bytes"] or hashlib.sha256(partial.read_bytes()).hexdigest() != file["sha256"]:
            raise ValueError("Embedding artifact failed verification")
        os.replace(partial, target)
    (destination / "model.json").write_text(json.dumps(spec, indent=2) + "\n")
    (destination / "NOTICE").write_text(
        "Luna multilingual embeddings\n"
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2\n"
        "Copyright its model contributors. Licensed under Apache License, Version 2.0.\n"
        "Generic int8 ONNX conversion: Xenova/paraphrase-multilingual-MiniLM-L12-v2.\n"
        "Model/export revisions and artifact hashes are recorded in model.json.\n"
        "Luna adds token-weighted long-document pooling and normalized vectors.\n")
    # Full license is vendored in the source; no mutable license download during builds.
    license_path = SPEC.with_name("embedding-LICENSE.txt")
    (destination / "LICENSE").write_bytes(license_path.read_bytes())
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(bundle(parser.parse_args().destination))
