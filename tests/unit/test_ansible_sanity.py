# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from dataclasses import replace
from pathlib import Path

import pytest

from releasing import artifacts, publish
from releasing._ansible_sanity import _check_report, _sessions
from releasing._source_export import BuildError
from tests.support import with_sanity

LANE = "ansible-test-sanity-2.19"


def test_discovery_requires_concrete_lanes() -> None:
    assert _sessions(
        json.dumps([{"session": "ansible-test-sanity"}, {"session": LANE}])
    ) == (LANE,)
    cases: list[object] = [
        {},
        [],
        [{"session": "ansible-test-sanity"}],
        [{"session": LANE}, {"session": LANE}],
    ]
    for data in cases:
        with pytest.raises(BuildError):
            _sessions(json.dumps(data))


@pytest.mark.parametrize("status", ["skipped", "aborted", "failed", "error"])
def test_report_rejects_unsuccessful_lanes_even_when_nox_exits_zero(
    status: str,
) -> None:
    with pytest.raises(BuildError, match="skips are refused"):
        _check_report(
            json.dumps(
                {
                    "result": 1,
                    "sessions": [
                        {"name": LANE, "result": status},
                    ],
                }
            ),
            (LANE,),
        )


@pytest.mark.parametrize(
    "names",
    [
        [],
        [LANE],
        [LANE, LANE],
        ["ansible-test-sanity"],
        [LANE, "ansible-test-sanity", "unexpected"],
    ],
)
def test_report_requires_exact_session_set(names: list[str]) -> None:
    with pytest.raises(BuildError):
        _check_report(
            json.dumps(
                {
                    "result": 1,
                    "sessions": [{"name": name, "result": "success"} for name in names],
                }
            ),
            (LANE,),
        )


def test_successful_report() -> None:
    _check_report(
        json.dumps(
            {
                "result": 1,
                "sessions": [
                    {"name": name, "result": "success"}
                    for name in (LANE, "ansible-test-sanity")
                ],
            }
        ),
        (LANE,),
    )


def manifest(tmp_path: Path) -> artifacts.Manifest:
    path = tmp_path / "foundata-example-1.0.0.tar.gz"
    path.write_bytes(b"artifact")
    return artifacts.build_manifest(
        [path], repository="foundata/example", version="1.0.0", source_revision="a" * 40
    )


def test_evidence_round_trip_and_publication(tmp_path: Path) -> None:
    original = with_sanity(manifest(tmp_path))
    loaded = artifacts.parse_manifest(artifacts.dump_manifest(original))
    assert loaded == original
    assert publish.plan(loaded, tmp_path, index="galaxy").files
    with pytest.raises(artifacts.ArtifactError, match="shadows"):
        artifacts.dump_manifest(original, extra={"ansibleSanity": {}})


def test_missing_evidence_only_blocks_galaxy(tmp_path: Path) -> None:
    original = manifest(tmp_path)
    with pytest.raises(artifacts.ArtifactError, match="evidence is missing"):
        publish.plan(original, tmp_path, index="galaxy")
    assert publish.plan(original, tmp_path, index="pypi").files


def test_revision_and_digest_must_match(tmp_path: Path) -> None:
    original = with_sanity(manifest(tmp_path))
    assert original.ansible_sanity is not None
    for changed in (
        replace(original, source_revision="b" * 40),
        replace(
            original,
            ansible_sanity=replace(
                original.ansible_sanity, artifacts={"x.tar.gz": "b" * 64}
            ),
        ),
    ):
        with pytest.raises(artifacts.ArtifactError, match="different"):
            publish.plan(changed, tmp_path, index="galaxy")


@pytest.mark.parametrize(
    "key,value",
    [
        ("result", "failed"),
        ("sourceRevision", "HEAD"),
        ("sessions", []),
        ("sessions", [LANE, LANE]),
        ("sessions", ["ansible-test-sanity"]),
        ("sessions", [None]),
        ("tools", {}),
        ("tools", {"nox": ""}),
        ("artifacts", {}),
        ("artifacts", {"../x": "a" * 64}),
        ("artifacts", {"x.tar.gz": "bad"}),
    ],
)
def test_malformed_evidence_is_refused(tmp_path: Path, key: str, value: object) -> None:
    document = json.loads(artifacts.dump_manifest(with_sanity(manifest(tmp_path))))
    document["ansibleSanity"][key] = value
    with pytest.raises(artifacts.ArtifactError):
        artifacts.parse_manifest(json.dumps(document))


def test_null_evidence_is_not_an_absent_optional_field(tmp_path: Path) -> None:
    document = json.loads(artifacts.dump_manifest(manifest(tmp_path)))
    document["ansibleSanity"] = None
    with pytest.raises(artifacts.ArtifactError):
        artifacts.parse_manifest(json.dumps(document))
