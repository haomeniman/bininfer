"""Profile loading and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


class ProfileError(ValueError):
    pass


@dataclass
class Profile:
    name: str
    magic: bytes
    magic_offset: int
    string_count_offset: int
    pool_start: int
    size_candidates: tuple
    seed_sizes: dict
    max_entries: int
    min_votes: int

    @classmethod
    def load(cls, path) -> "Profile":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def from_dict(cls, raw: dict) -> "Profile":
        try:
            magic = raw["magic"]
            header = raw["header"]["string_count"]
            pool = raw["string_pool"]
            record = raw["record"]
            return cls(
                name=str(raw["name"]),
                magic=bytes.fromhex(magic["hex"]),
                magic_offset=int(magic.get("offset", 0)),
                string_count_offset=int(header["offset"]),
                pool_start=int(pool["start"]),
                size_candidates=tuple(int(s) for s in record["size_candidates"]),
                seed_sizes={
                    int(k, 16) if isinstance(k, str) else int(k): int(v)
                    for k, v in record.get("seed_sizes", {}).items()
                },
                max_entries=int(record.get("max_entries", 512)),
                min_votes=int(record.get("min_votes", 2)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProfileError(f"invalid profile: {exc}") from exc
