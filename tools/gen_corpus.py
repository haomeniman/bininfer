"""Generate a synthetic corpus for experiments: python tools/gen_corpus.py --out corpus-demo"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bininfer.synth import generate


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic corpus for bininfer.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--files", type=int, default=40)
    parser.add_argument("--tags", type=int, default=6)
    parser.add_argument("--fields", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tail-bytes", type=int, default=0)
    args = parser.parse_args()
    truth = generate(
        args.out,
        files=args.files,
        tags=args.tags,
        fields=args.fields,
        seed=args.seed,
        tail_bytes=args.tail_bytes,
    )
    print(f"wrote {truth['files']} files + truth.json -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
