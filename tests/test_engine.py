import json
from pathlib import Path

import pytest

from bininfer.engine import ParseError, Schema, learn, parse_blob, report
from bininfer.profile import Profile
from bininfer.synth import generate

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profiles" / "e903-demo.json"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus")
    truth = generate(str(out), files=40, tags=6, fields=8, seed=7)
    return sorted(out.glob("*.bin")), truth


@pytest.fixture(scope="module")
def profile():
    return Profile.load(PROFILE_PATH)


@pytest.fixture(scope="module")
def schema(corpus, profile):
    paths, _truth = corpus
    return learn(paths, profile)


def test_learn_recovers_all_sizes(schema, corpus):
    _paths, truth = corpus
    expected = {int(key, 16): size for key, size in truth["tag_sizes"].items()}
    for tag, size in expected.items():
        assert schema.sizes[tag] == size
    # Profile seeds stay in the schema even when the corpus never exercises them.
    assert schema.sizes[0x72F31961] == 12
    assert schema.parsed_files == schema.corpus_files
    for tag in expected:
        assert schema.confidence[tag] >= 0.95


def test_parse_matches_ground_truth(schema, corpus, profile):
    paths, truth = corpus
    result = parse_blob(paths[0].read_bytes(), profile, schema)
    got = [(item.name, f"0x{item.tag:08x}", item.size) for item in result.fields]
    want = [(name, tag, size) for name, tag, size in truth["fields"]]
    assert got == want
    assert result.tail_bytes == 0


def test_parse_without_schema_still_works(corpus, profile):
    paths, truth = corpus
    result = parse_blob(paths[0].read_bytes(), profile, None)
    assert len(result.fields) == len(truth["fields"])


def test_report_covers_corpus(corpus, schema, profile):
    paths, _truth = corpus
    stats = report(paths, profile, schema)
    assert stats["parsed"] == stats["files"]
    assert stats["failed"] == 0


def test_schema_json_roundtrip(schema, tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema.to_dict()), encoding="utf-8")
    loaded = Schema.load(path)
    assert loaded.sizes == schema.sizes


def test_bad_magic_rejected(profile):
    with pytest.raises(ParseError):
        parse_blob(b"\x00" * 64, profile)


def test_truncated_blob_raises(profile, corpus):
    paths, _truth = corpus
    with pytest.raises(ParseError):
        parse_blob(paths[0].read_bytes()[:20], profile)
