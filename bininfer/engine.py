"""Core engine: corpus-driven size learning and evidence-checked parsing."""
from __future__ import annotations

import json
import re
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .profile import Profile

IDENT = re.compile(rb"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_NAME = 64
MAX_POOL_STRING = 4096
MAX_POOL_COUNT = 200_000


class ParseError(ValueError):
    """Raised when a blob does not match the profile's container grammar."""


@dataclass
class Field:
    name: str
    tag: int
    size: int
    offset: int
    value: dict


@dataclass
class ParseResult:
    fields: list
    tail_bytes: int
    tail_hex: str
    pool: list


@dataclass
class Schema:
    profile: str
    sizes: dict
    confidence: dict = field(default_factory=dict)
    votes: dict = field(default_factory=dict)
    corpus_files: int = 0
    parsed_files: int = 0

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "corpus_files": self.corpus_files,
            "parsed_files": self.parsed_files,
            "tags": {
                f"0x{tag:08x}": {
                    "size": size,
                    "votes": self.votes.get(tag, 0),
                    "confidence": round(self.confidence.get(tag, 0.0), 4),
                }
                for tag, size in sorted(self.sizes.items())
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Schema":
        sizes, confidence, votes = {}, {}, {}
        for key, info in raw.get("tags", {}).items():
            tag = int(key, 16)
            sizes[tag] = int(info["size"])
            confidence[tag] = float(info.get("confidence", 0.0))
            votes[tag] = int(info.get("votes", 0))
        return cls(
            profile=str(raw.get("profile", "")),
            sizes=sizes,
            confidence=confidence,
            votes=votes,
            corpus_files=int(raw.get("corpus_files", 0)),
            parsed_files=int(raw.get("parsed_files", 0)),
        )

    @classmethod
    def load(cls, path) -> "Schema":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def _u32(data: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(data):
        raise ParseError(f"read past end of file at {off:#x}")
    return struct.unpack_from("<I", data, off)[0]


def _is_text(blob: bytes) -> bool:
    if not blob:
        return False
    if any(c < 0x20 and c not in (9, 10, 13) for c in blob):
        return False
    try:
        blob.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def check_magic(data: bytes, profile: Profile) -> None:
    end = profile.magic_offset + len(profile.magic)
    if data[profile.magic_offset:end] != profile.magic:
        raise ParseError(
            f"magic mismatch: expected {profile.magic.hex()} at {profile.magic_offset:#x}"
        )


def parse_pool(data: bytes, profile: Profile) -> tuple:
    count = _u32(data, profile.string_count_offset)
    if not 0 <= count < MAX_POOL_COUNT:
        raise ParseError(f"implausible string pool size {count}")
    off = profile.pool_start
    pool = []
    for index in range(count):
        length = _u32(data, off)
        if not 1 <= length <= MAX_POOL_STRING:
            raise ParseError(f"string {index} has implausible length {length}")
        start = off + 4
        end = start + length
        if end + 4 > len(data):
            raise ParseError(f"string {index} runs past end of file")
        payload = data[start:end]
        if not _is_text(payload):
            raise ParseError(f"string {index} is not text")
        trailer = struct.unpack_from("<I", data, end)[0]
        if trailer != index:
            raise ParseError(f"string {index} trailer is {trailer}, expected {index}")
        pool.append(payload.decode("utf-8"))
        off = end + 4
    return pool, off


def read_entry(data: bytes, off: int):
    """Return (name, tag, value_offset) or None if no entry starts at ``off``."""
    if off < 0 or off + 8 > len(data):
        return None
    length = struct.unpack_from("<I", data, off)[0]
    if not 1 <= length <= MAX_NAME:
        return None
    name_end = off + 4 + length
    if name_end + 4 > len(data):
        return None
    raw_name = data[off + 4:name_end]
    if not IDENT.match(raw_name):
        return None
    tag = struct.unpack_from("<I", data, name_end)[0]
    return raw_name.decode("ascii"), tag, name_end + 4


def string_value_size(data: bytes, off: int) -> Optional[int]:
    if off + 8 > len(data):
        return None
    length = struct.unpack_from("<I", data, off)[0]
    if not 1 <= length <= MAX_POOL_STRING:
        return None
    end = off + 4 + length
    if end > len(data):
        return None
    if not _is_text(data[off + 4:end]):
        return None
    return 4 + length


def _candidates(data: bytes, off: int, tag: int, sizes: dict, profile: Profile) -> list:
    ordered = []
    string_size = string_value_size(data, off)
    if string_size is not None:
        ordered.append(string_size)
    if tag in sizes:
        ordered.append(sizes[tag])
    ordered.extend(profile.size_candidates)
    seen = set()
    unique = []
    for size in ordered:
        if size not in seen:
            seen.add(size)
            unique.append(size)
    return unique


def _walk(data: bytes, profile: Profile, sizes: dict, votes) -> bool:
    """Walk all entries in a blob. Returns True if the whole record parsed."""
    try:
        _pool, off = parse_pool(data, profile)
        count = _u32(data, off)
        if not 0 <= count <= profile.max_entries:
            return False
        off += 4
        for index in range(count):
            entry = read_entry(data, off)
            if entry is None:
                return False
            _name, tag, value_off = entry
            if index < count - 1:
                chosen = None
                for size in _candidates(data, value_off, tag, sizes, profile):
                    if read_entry(data, value_off + size) is not None:
                        chosen = size
                        break
                if chosen is None:
                    return False
                if votes is not None:
                    votes[tag][chosen] += 1
                off = value_off + chosen
            else:
                size = string_value_size(data, value_off)
                if size is None:
                    size = sizes.get(tag, 0)
                off = value_off + size
        return True
    except ParseError:
        return False


def learn(paths, profile: Profile, iterations: int = 3, min_votes: Optional[int] = None) -> Schema:
    sizes = dict(profile.seed_sizes)
    min_votes = profile.min_votes if min_votes is None else min_votes
    votes = defaultdict(Counter)
    parsed = 0
    for _iteration in range(iterations):
        votes = defaultdict(Counter)
        parsed = 0
        for path in paths:
            with open(path, "rb") as fh:
                data = fh.read()
            if _walk(data, profile, sizes, votes):
                parsed += 1
        proposed = {}
        for tag, counter in votes.items():
            size, count = counter.most_common(1)[0]
            if count >= min_votes:
                proposed[tag] = size
        changed = {t: s for t, s in proposed.items() if sizes.get(t) != s}
        sizes.update(proposed)
        if not changed:
            break

    confidence = {}
    total_votes = {}
    for tag, counter in votes.items():
        _size, top = counter.most_common(1)[0]
        confidence[tag] = top / sum(counter.values()) if counter else 0.0
        total_votes[tag] = sum(counter.values())
    return Schema(
        profile=profile.name,
        sizes=sizes,
        confidence=confidence,
        votes=total_votes,
        corpus_files=len(paths),
        parsed_files=parsed,
    )


def _decode_value(data: bytes, off: int, size: int) -> dict:
    blob = data[off:off + size]
    value = {"size": size, "hex": blob[:32].hex()}
    if size == 4:
        value["u32"] = struct.unpack("<I", blob)[0]
        number = struct.unpack("<f", blob)[0]
        if number == number and abs(number) < 1e12:
            value["f32"] = round(number, 6)
    elif size == 8:
        value["u64"] = struct.unpack("<Q", blob)[0]
    elif size == 12:
        floats = struct.unpack("<3f", blob)
        if all(x == x and abs(x) < 1e9 for x in floats):
            value["f3"] = [round(x, 4) for x in floats]
        value["u3"] = list(struct.unpack("<3I", blob))
    elif size > 4 and blob[:4] and struct.unpack_from("<I", blob, 0)[0] == size - 4 and _is_text(blob[4:]):
        value["str"] = blob[4:].decode("utf-8")
    elif 0 < size <= 2:
        value["u"] = int.from_bytes(blob, "little")
    return value


def parse_blob(data: bytes, profile: Profile, schema: Optional[Schema] = None) -> ParseResult:
    sizes = schema.sizes if schema is not None else {}
    check_magic(data, profile)
    pool, off = parse_pool(data, profile)
    count = _u32(data, off)
    if not 0 <= count <= profile.max_entries:
        raise ParseError(f"implausible field count {count} at {off:#x}")
    off += 4
    fields = []
    for index in range(count):
        entry = read_entry(data, off)
        if entry is None:
            raise ParseError(f"field {index} does not start with a name+tag entry")
        name, tag, value_off = entry
        if index < count - 1:
            size = None
            for candidate in _candidates(data, value_off, tag, sizes, profile):
                if read_entry(data, value_off + candidate) is not None:
                    size = candidate
                    break
            if size is None:
                raise ParseError(f"cannot determine the size of field {name!r} (field {index})")
        else:
            size = string_value_size(data, value_off)
            if size is None:
                size = sizes.get(tag, 0)
        fields.append(
            Field(
                name=name,
                tag=tag,
                size=size,
                offset=value_off,
                value=_decode_value(data, value_off, size),
            )
        )
        off = value_off + size
    return ParseResult(
        fields=fields,
        tail_bytes=max(0, len(data) - off),
        tail_hex=data[off:off + 16].hex(),
        pool=pool,
    )


def report(paths, profile: Profile, schema: Schema) -> dict:
    parsed = failed = 0
    field_count = 0
    unknown = Counter()
    for path in paths:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            result = parse_blob(data, profile, schema)
        except ParseError:
            failed += 1
            continue
        parsed += 1
        field_count += len(result.fields)
        for item in result.fields:
            if item.tag not in schema.sizes:
                unknown[item.tag] += 1
    return {
        "files": len(paths),
        "parsed": parsed,
        "failed": failed,
        "fields": field_count,
        "unknown_tags": {f"0x{tag:08x}": count for tag, count in unknown.most_common(20)},
    }
