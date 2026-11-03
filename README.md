# bininfer

Corpus-driven schema inference for **self-describing binary records** — formats
where every field carries a name and a numeric type tag, but the *size* of each
value is never written down.

One file alone is ambiguous: if you don't know how many bytes `hp` occupies, the
parser cannot find where the next field starts. But a corpus of files produced by
the same exporter is not ambiguous. `bininfer` resolves field sizes by evidence:

1. for each field, try candidate sizes;
2. accept the size at which the **next entry parses**;
3. vote across the whole corpus, per type tag;
4. iterate until the size map is stable.

The result is a schema (`tag → size` + confidence) that parses every file in the
corpus and every file the exporter produces next time.

This is the practical way to open undocumented config/asset formats used by
desktop and mobile software, firmware, and proprietary editors — no disassembly
required, and no hand-written parser for each revision.

## Install

```bash
git clone https://github.com/<you>/bininfer
cd bininfer
pip install -e .
```

Python 3.10+, standard library only.

## Quick start (synthetic corpus, known ground truth)

```bash
python tools/gen_corpus.py --out corpus-demo

bininfer learn  corpus-demo -p profiles/e903-demo.json -o schema.json
bininfer report corpus-demo -p profiles/e903-demo.json -s schema.json
bininfer dump   corpus-demo/0000.bin -p profiles/e903-demo.json -s schema.json
```

`learn` prints a schema like:

```json
{
  "profile": "e903-demo",
  "corpus_files": 40,
  "parsed_files": 40,
  "tags": {
    "0x72f31961": { "size": 12, "votes": 280, "confidence": 1.0 },
    "0xedf2fc57": { "size": 4,  "votes": 279, "confidence": 1.0 }
  }
}
```

The generator ships the ground truth in `truth.json`; the test suite asserts the
learned sizes match it exactly.

## A profile is the container grammar

`bininfer` is not tied to one format. A profile describes where the string pool,
record count and entries live:

```json
{
  "name": "e903-demo",
  "magic": { "offset": 0, "hex": "e9030000" },
  "header": { "string_count": { "offset": 16, "type": "u32le" } },
  "string_pool": {
    "start": 20,
    "entry": { "length": "u32le", "encoding": "utf-8", "trailer_index": "u32le" }
  },
  "record": {
    "count": { "after": "string_pool", "type": "u32le" },
    "entry": { "name_length": "u32le", "name": "identifier", "tag": "u32le" },
    "size_candidates": [0, 1, 2, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 48, 56, 64, 96, 128],
    "seed_sizes": { "0x72f31961": 12 },
    "max_entries": 512,
    "min_votes": 2
  }
}
```

Profiles are plain JSON; adding support for a new format is usually a matter of
describing its header and entry layout, not writing code.

## Validation on a real corpus

The engine was validated on **19,819 real files** produced by one proprietary
exporter (the `e903-demo` profile is the grammar of that container):

| Metric | Result |
|---|---|
| Files parsed end-to-end | **18,595 / 19,819 (93.8%)** |
| Files with at least one field | 14,940 (75.4%) |
| Empty-record variants (field table present, count = 0) | 3,655 |
| Fields extracted | 30,158 |
| Learn time / report time (single-threaded) | 6.5 s / 3.6 s |
| Dominant tag | 12,757 votes at 0.999 confidence |

The remaining 1,224 files are variants outside the grammar (blueprint-graph
containers with GUID-prefixed sections), not parser failures. Only 3 field
occurrences used tags the learner had never seen, and all were parsed anyway
through the evidence check.

## Command reference

| Command | Purpose |
|---|---|
| `bininfer learn <corpus> -p profile.json -o schema.json` | infer the tag→size map |
| `bininfer dump <file> -p profile.json [-s schema.json]` | parse one blob to JSON |
| `bininfer report <corpus> -p profile.json -s schema.json` | coverage over a corpus |

`dump` works without a schema too — the per-file evidence check alone resolves
all but the last field; the schema mainly resolves the last field and keeps
ambiguous candidates stable.

Useful flags: `--glob` (default `*.bin`), `--iterations` (default 3),
`--min-votes` (default from the profile), `--out` for `dump`.

## Limitations

- The format must have the "name + type tag" entry shape. Pure positional
  records (no names) are a different problem.
- Value sizes must fall inside the profile's candidate list; arbitrary sizes are
  not inferred.
- Values are returned as opaque blobs plus a best-effort decode (`u32`, `f32`,
  `u64`, `vec3`, string). Nested structures are not rebuilt.
- Compressed or encrypted containers need to be decoded first.
- A tag that only ever appears in the last position of a record has no evidence
  to vote on; it is resolved by `seed_sizes` or defaults to size 0.

Use it on data you are allowed to analyze.

## Support

If this tool saves you time, a star helps. Sponsorship links can be enabled
through the repository's Sponsor button.

## 中文简介

面向“自描述二进制记录”的结构推断引擎：这类格式每个字段都带名字和类型 tag，
但值的大小不写进文件。单看一个文件无法确定边界，而同一个导出器产出的语料可以
——引擎用“下一个条目能否解析”作为证据，按 tag 全语料投票，几轮收敛出
`tag → 大小` 的 schema，再逐文件校验解析。

在 19,819 个真实配置文件的语料上：93.8% 端到端解析，30,158 个字段，学习耗时
6.5 秒，单线程。换一个私有格式通常只需要写一个新的 profile JSON，不用改代码。

```bash
bininfer learn <语料目录> -p profiles/e903-demo.json -o schema.json
bininfer dump  某个文件.bin -p profiles/e903-demo.json -s schema.json
```

## License

MIT
