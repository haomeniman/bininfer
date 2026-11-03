# Profile format and the demo container

`bininfer` is driven by a JSON profile that describes a container grammar.
The engine itself is format-agnostic; everything format-specific lives in the
profile.

## Profile reference

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

| Key | Meaning | Constraints |
|---|---|---|
| `magic` | byte string expected at `offset` | any length; compared verbatim |
| `header.string_count.offset` | where the pool entry count is stored | absolute offset from file start |
| `string_pool.start` | first byte of the first pool entry | absolute offset |
| `string_pool.entry` | layout of one pool entry | `length` is a u32le; text is UTF-8; the trailing u32 must equal the entry's index |
| `record.count.after` | where the field count is stored | only `"string_pool"` is supported today: count = u32 at the end of the pool |
| `record.entry` | layout of one field entry | `u32 name_length`, ASCII identifier (`[A-Za-z_][A-Za-z0-9_]*`, ≤ 64 bytes), `u32 tag`, then the value |
| `record.size_candidates` | sizes tried when no evidence or schema entry exists | ascending order is not required |
| `record.seed_sizes` | known `tag → size` pairs to start from | hex strings or integers |
| `record.max_entries` | sanity cap for the field count | a count outside `[0, max]` aborts the file |
| `record.min_votes` | votes required before a learned size is accepted | keeps one-off observations out of the schema |

Only little-endian u32 fields are supported by the built-in reader. Anything
else needs a code change, not a profile change.

## The demo container (e903-demo)

An exporter format that stores a string pool and a list of named fields, each
with a compiler type tag but **no size**:

```
0x00  u32   magic = 0x000003E9            (bytes E9 03 00 00)
0x04  u32   total file length
0x08  u64   0x0000000000000000
0x10  u32   string_count
0x14  ...   string_count × { u32 byte_length; utf8 bytes; u32 index }
            (index must equal the entry's ordinal, 0-based)
      u32   field_count
      ...   field_count × {
              u32 name_length;
              ascii identifier;
              u32 tag;
              value            <- size implied by tag, not stored
            }
      ...   optional tail (length-prefixed strings, other sections)
```

Notes:

- `total file length` is not trusted by the parser; only used by the writer.
- Empty records (`field_count = 0`) and empty pools (`string_count = 0`) are
  valid variants seen in the reference corpus.
- A value can also be a length-prefixed UTF-8 string; when the
  `{u32 len, utf8[len]}` heuristic fires it wins over every candidate size,
  regardless of the tag.
- Fields are separated only by *knowing the previous value's size* — this is
  exactly the ambiguity the engine resolves by voting across a corpus.

### Tags observed on the reference corpus

Inferred from evidence, not documented anywhere in the format:

| tag | size | likely semantic |
|---|---|---|
| `0x72f31961` | 12 | 3 × f32 (vector) |
| `0x738fb290` | 12 | 3 × f32 (vector) |
| `0x798c7be8` | 16 | 16-byte blob / 4 × f32 |
| `0xedf2fc57` | 4 | int / f32 |
| `0xd58a0ae8` | 4 | int / f32 |
| `0x05427470` | 1 | bool / byte |
| `0x7a7225b8` | variable | length-prefixed string (schema default 4 when the heuristic misses) |

The `size` column is what `learn` converges on; the semantic column is
eyeballing, included to show what the numbers mean in practice.

## How inference works

**Evidence.** For field `k`, the correct value size is the one at which field
`k+1` parses (valid name length, identifier charset, tag). Candidates are tried
in this order: length-prefixed string heuristic, previously learned size for the
tag, then `size_candidates`.

**Voting.** `learn` walks the whole corpus and, for every non-final field,
records the size that satisfied the evidence check into `votes[tag][size]`.
After each pass the most common size per tag becomes the new size map, and the
pass repeats (default 3 iterations) until nothing changes. A size must receive
`min_votes` votes to be accepted.

**Confidence.** `confidence[tag] = top_votes / total_votes`. Values below ~0.95
mean the tag has conflicting evidence — usually a variable-length type or two
different types sharing a tag.

**Last field.** There is no following entry to anchor on, so the size comes from
the string heuristic or the schema; otherwise it defaults to 0 and the rest of
the file is reported as `tail`.

**Parsing** re-runs the same evidence checks per file. The schema is not blindly
trusted: it reseeds the candidate order and resolves the last field. A file that
does not fit the grammar raises `ParseError` instead of producing garbage.

## Writing a profile for a new format

Checklist:

1. Locate the magic and copy its bytes into `magic.hex`.
2. Find the string pool: where the count lives and how each entry is framed.
   No pool? Set `string_count.offset` to a `u32 0` and `string_pool.start` to
   the byte after it.
3. Confirm the field entry shape is `name(+length) + type tag + value`. If names
   are fixed-width or absent, the built-in entry reader does not fit — write a
   custom profile reader.
4. Collect plausible value sizes into `size_candidates` (include 0, 1, 2, 4, 8,
   12, 16, ... and any odd sizes you have seen).
5. Seed one or two known tags in `seed_sizes` to speed convergence.
6. Run `bininfer learn`, check confidence and the report's failure count, then
   adjust the candidate list.

## Verification

`tools/gen_corpus.py` generates a corpus with a known `truth.json`
(tag→size, per-field names and sizes). The test suite asserts that `learn`
recovers the exact size map and that `dump` reproduces the ground truth, so the
engine is checked against data where the answer is known.
