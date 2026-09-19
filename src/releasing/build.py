# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build distributions from an exported revision, never from the working tree.

A release is a commit, not a working tree. The revision is exported with
``git archive``, which honours ``export-ignore`` in ``.gitattributes`` and
carries no developer litter. The package-index Markdown is prepared inside
that export, so the rewritten links ship in the artifacts while the committed
files stay untouched and no `git restore` is needed afterwards. What the
export produces is checked and recorded in a manifest, so exactly those bytes
can be published and later compared with what the index serves.
"""

import shutil
import tarfile
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from releasing import artifacts, changelog, markdown, processes, version
from releasing.config import ReleaseConfig, load_release_config
from releasing.forges import Forge, forge_for

MANIFEST = "artifacts.json"


class BuildError(RuntimeError):
    """The revision cannot be exported, prepared or built."""


@dataclass(frozen=True)
class BuildResult:
    """What one build produced."""

    directory: Path
    files: tuple[Path, ...]
    manifest: Path
    revision: str
    version: str
    prepared: tuple[str, ...]
    local_sources: tuple[str, ...] = ()


def local_path_sources(root: Path, config: ReleaseConfig) -> list[str]:
    """Dependencies this tree resolves from a local directory.

    A ``[tool.uv.sources]`` entry with a ``path`` records an absolute or
    relative directory in ``pyproject.toml`` and in the lockfile. Both ship in
    a source distribution, so a release built from such a tree publishes a
    path from the machine that built it. Workspace sources name no directory
    and are not reported.
    """
    found: list[str] = []
    for relative in dict.fromkeys(["pyproject.toml", *config.version_files]):
        path = root / relative
        if path.name != "pyproject.toml" or not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise BuildError(f"cannot read {relative}: {exc}") from exc
        sources = data.get("tool", {}).get("uv", {}).get("sources", {})
        if not isinstance(sources, dict):
            continue
        found.extend(
            f"{relative}: {name} = {entry['path']}"
            for name, entry in sources.items()
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        )
    return found


def export(root: Path, revision: str, destination: Path) -> None:
    """Extract ``revision`` of the repository at ``root`` into ``destination``."""
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="releasing-export-") as value:
        archive = Path(value) / "source.tar"
        processes.git(root, "archive", "--format=tar", revision, stdout=archive)
        try:
            with tarfile.open(archive, mode="r:") as stream:
                members = stream.getmembers()
                for member in members:
                    _safe_member(member.name)
                    if member.issym() or member.islnk():
                        continue
                    if not (member.isfile() or member.isdir()):
                        raise BuildError(f"unsupported archive member {member.name}")
                stream.extractall(destination, members=members, filter="tar")
        except (OSError, tarfile.TarError) as exc:
            raise BuildError(f"cannot extract the exported revision: {exc}") from exc


def prepare_readmes(
    root: Path, config: ReleaseConfig, *, version_string: str, forge: Forge
) -> list[str]:
    """Rewrite every declared Markdown document in ``root`` for the index.

    ``root`` is an exported tree, not a checkout. Relative destinations are
    validated against it, rewritten against the forge and, where the
    declaration says so, copied over the documents of workspace members.
    Return the paths that changed.
    """
    tag = config.tag(version_string)
    touched: list[str] = []
    for readme in config.readmes:
        ref = readme.ref.format(version=version_string, tag=tag)
        source = root / readme.source_path
        try:
            original = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BuildError(f"cannot read {readme.source_path}: {exc}") from exc
        try:
            markdown.validate_local_files(
                original, repo_root=root, source_path=readme.source_path
            )
            prepared = markdown.prepare_markdown(
                original,
                raw_base=forge.raw_base(ref),
                ui_base=forge.blob_base(ref),
                source_path=readme.source_path,
                simplify_badges=readme.simplify_badges,
                collapse_header=readme.collapse_header,
                strict=True,
            )
        except ValueError as exc:
            raise BuildError(f"{readme.source_path}: {exc}") from exc
        source.write_text(prepared, encoding="utf-8", newline="")
        touched.append(readme.source_path)
        for copy in readme.copies:
            target = root / copy
            if not target.is_file():
                raise BuildError(f"cannot copy the prepared document over {copy}")
            target.write_text(prepared, encoding="utf-8", newline="")
            touched.append(copy)
    return touched


def build(
    root: Path,
    *,
    revision: str = "HEAD",
    out: Path,
    expect: str | None = None,
    allow_local_sources: bool = False,
) -> BuildResult:
    """Export, prepare, build, check and record one revision's distributions."""
    root = root.resolve()
    if out.exists():
        raise BuildError(f"output directory must not already exist: {out}")
    resolved = _resolve(root, revision)
    with tempfile.TemporaryDirectory(prefix="releasing-build-") as value:
        workspace = Path(value)
        exported = workspace / "source"
        export(root, resolved, exported)
        config = load_release_config(exported)
        local = local_path_sources(exported, config)
        if local and not allow_local_sources:
            raise BuildError(
                "this revision resolves dependencies from local directories, so "
                "its artifacts would publish a path from this machine:\n  "
                + "\n  ".join(local)
                + "\nReplace them with published requirements. Pass "
                "--allow-local-sources to build anyway, for a throwaway build "
                "that must never be uploaded."
            )
        found = version.check(exported, config, expect=expect)
        _check_changelog(exported, config, found)
        prepared = prepare_readmes(
            exported, config, version_string=found, forge=forge_for(config)
        )
        staged = workspace / "artifacts"
        staged.mkdir()
        files = _build_artifacts(exported, config, staged)
        inspected = [artifacts.inspect(path) for path in files]
        names = tuple(version.project_names(exported, config).values())
        problems = artifacts.check(inspected, version=found, names=names)
        if problems:
            raise BuildError(
                "the built distributions are not publishable:\n  "
                + "\n  ".join(problems)
            )
        manifest = artifacts.build_manifest(
            files, repository=config.repository, version=found, source_revision=resolved
        )
        produced = _retain(files, manifest, out)
    return BuildResult(
        directory=out,
        files=produced,
        manifest=out / MANIFEST,
        revision=resolved,
        version=found,
        prepared=tuple(prepared),
        local_sources=tuple(local),
    )


def _build_artifacts(exported: Path, config: ReleaseConfig, staged: Path) -> list[Path]:
    if config.ecosystem == "python":
        return _build_python(exported, staged)
    if config.ecosystem == "ansible-collection":
        return _build_collection(exported, staged)
    raise BuildError(f"the {config.ecosystem} ecosystem builds no artifacts")


def _build_python(exported: Path, staged: Path) -> list[Path]:
    uv = str(processes.executable("uv"))
    processes.run([uv, "build", "--sdist", "--out-dir", str(staged), str(exported)])
    sdist = _one(staged, "*.tar.gz")
    # The wheel comes from the source distribution, so what is published is what
    # a consumer installing from source would get.
    processes.run([uv, "build", "--wheel", "--out-dir", str(staged), str(sdist)])
    return _distributions(staged)


def _build_collection(exported: Path, staged: Path) -> list[Path]:
    galaxy = str(processes.executable("ansible-galaxy"))
    processes.run(
        [galaxy, "collection", "build", "--output-path", str(staged), str(exported)]
    )
    return _distributions(staged)


def _distributions(staged: Path) -> list[Path]:
    """The distributions in a build directory; build tools also drop other files."""
    found = sorted(
        path
        for path in staged.iterdir()
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    )
    if not found:
        raise BuildError(f"no distributions were produced in {staged}")
    return found


def _retain(
    files: Sequence[Path], manifest: artifacts.Manifest, out: Path
) -> tuple[Path, ...]:
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.releasing-", dir=out.parent))
    try:
        for path in files:
            shutil.copyfile(path, staging / path.name)
            (staging / path.name).chmod(0o644)
        (staging / MANIFEST).write_text(
            artifacts.dump_manifest(manifest), encoding="utf-8"
        )
        problems = artifacts.verify_manifest(manifest, staging)
        if problems:
            raise BuildError(
                "retained files differ from the manifest:\n  " + "\n  ".join(problems)
            )
        staging.rename(out)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise BuildError(
            f"cannot retain the built distributions at {out}: {exc}"
        ) from exc
    except BuildError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return tuple(sorted(out / path.name for path in files))


def _check_changelog(exported: Path, config: ReleaseConfig, found: str) -> None:
    if config.changelog_format == "antsibull":
        text = (exported / "changelogs" / "changelog.yaml").read_text(encoding="utf-8")
        if not changelog.antsibull_has_release(text, found):
            raise BuildError(f"changelogs/changelog.yaml has no release {found}")
        return
    problems = changelog.check(
        (exported / config.changelog).read_text(encoding="utf-8"),
        forge=forge_for(config),
        tag_format=config.tag_format,
        version=found,
    )
    if problems:
        raise BuildError(f"{config.changelog}:\n  " + "\n  ".join(problems))


def _resolve(root: Path, revision: str) -> str:
    if not processes.is_checkout(root):
        raise BuildError(f"not a Git checkout: {root}")
    resolved = processes.git(
        root, "rev-parse", "--verify", f"{revision}^{{commit}}"
    ).strip()
    if len(resolved) != 40 or not all(char in "0123456789abcdef" for char in resolved):
        raise BuildError(f"cannot resolve revision {revision}")
    return resolved


def _one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise BuildError(f"expected exactly one {pattern}, found {len(matches)}")
    return matches[0]


def _safe_member(name: str) -> None:
    member = PurePosixPath(name)
    if (
        "\x00" in name
        or "\\" in name
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in member.parts)
    ):
        raise BuildError(f"unsafe archive member {name!r}")
