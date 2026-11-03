"""Command line interface."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys

from .engine import ParseError, Schema, learn, parse_blob, report
from .profile import Profile, ProfileError


def collect(corpus: str, pattern: str) -> list:
    paths = []
    for root, _dirs, files in os.walk(corpus):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                paths.append(os.path.join(root, name))
    return sorted(paths)


def cmd_learn(args) -> int:
    profile = Profile.load(args.profile)
    paths = collect(args.corpus, args.glob)
    if not paths:
        print(f"error: no files matching {args.glob!r} under {args.corpus}", file=sys.stderr)
        return 2
    schema = learn(paths, profile, iterations=args.iterations, min_votes=args.min_votes)
    payload = schema.to_dict()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        print(
            f"learned {len(schema.sizes)} tags from {schema.parsed_files}/{schema.corpus_files} "
            f"files -> {args.out}"
        )
    else:
        print(json.dumps(payload, indent=2))
    return 0


def cmd_dump(args) -> int:
    profile = Profile.load(args.profile)
    schema = Schema.load(args.schema) if args.schema else None
    with open(args.file, "rb") as fh:
        data = fh.read()
    result = parse_blob(data, profile, schema)
    payload = {
        "file": args.file,
        "pool": result.pool,
        "tail_bytes": result.tail_bytes,
        "tail_hex": result.tail_hex,
        "fields": [
            {
                "name": item.name,
                "tag": f"0x{item.tag:08x}",
                "size": item.size,
                "offset": item.offset,
                "value": item.value,
            }
            for item in result.fields
        ],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(result.fields)} fields -> {args.out}")
    else:
        print(text)
    return 0


def cmd_report(args) -> int:
    profile = Profile.load(args.profile)
    schema = Schema.load(args.schema)
    paths = collect(args.corpus, args.glob)
    if not paths:
        print(f"error: no files matching {args.glob!r} under {args.corpus}", file=sys.stderr)
        return 2
    print(json.dumps(report(paths, profile, schema), indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="bininfer",
        description="Learn field sizes for tagged binary records from a corpus, then parse them.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    learn_p = sub.add_parser("learn", help="infer a tag->size schema from a corpus")
    learn_p.add_argument("corpus")
    learn_p.add_argument("-p", "--profile", required=True)
    learn_p.add_argument("-o", "--out", help="write schema JSON here")
    learn_p.add_argument("--glob", default="*.bin")
    learn_p.add_argument("--iterations", type=int, default=3)
    learn_p.add_argument("--min-votes", type=int, default=None)
    learn_p.set_defaults(func=cmd_learn)

    dump_p = sub.add_parser("dump", help="parse a single blob to JSON")
    dump_p.add_argument("file")
    dump_p.add_argument("-p", "--profile", required=True)
    dump_p.add_argument("-s", "--schema", help="schema JSON produced by learn")
    dump_p.add_argument("-o", "--out")
    dump_p.set_defaults(func=cmd_dump)

    report_p = sub.add_parser("report", help="parse a whole corpus and report coverage")
    report_p.add_argument("corpus")
    report_p.add_argument("-p", "--profile", required=True)
    report_p.add_argument("-s", "--schema", required=True)
    report_p.add_argument("--glob", default="*.bin")
    report_p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ParseError, ProfileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
