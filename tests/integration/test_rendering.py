# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from html.parser import HTMLParser
from typing import override
from urllib.parse import urlsplit

import pytest
from readme_renderer.markdown import render

from tests.support import FIXTURES, RAW, TRANSFORMER, UI, prepare

CORPUS = FIXTURES / "corpus"
REPOSITORIES = sorted(path.name for path in CORPUS.iterdir() if path.is_dir())
pytestmark = pytest.mark.integration


class Rendered(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.images: list[dict[str, str | None]] = []
        self.feed(text)

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(str(attributes["href"]))
        if tag == "img":
            self.images.append(attributes)


def rendered(text: str) -> Rendered:
    result = render(text)
    assert result is not None
    return Rendered(result)


@pytest.mark.parametrize("repository", REPOSITORIES)
@pytest.mark.parametrize("mode", ["default", "simplified", "badges", "header"])
def test_every_corpus_readme_renders_without_repository_relative_urls(
    repository: str, mode: str
) -> None:
    source = (CORPUS / repository / "README.md").read_text(encoding="utf-8")
    prepared = TRANSFORMER.prepare_markdown(
        source,
        raw_base=f"https://raw.githubusercontent.com/foundata/{repository}/refs/heads/main",
        ui_base=f"https://github.com/foundata/{repository}/blob/main",
        simplify=mode == "simplified",
        simplify_badges=mode == "badges",
        collapse_header=mode == "header",
        strict=True,
    )
    page = rendered(prepared)
    assert page.links
    for value in [*page.links, *(str(image["src"]) for image in page.images)]:
        assert value.startswith(("#", "//")) or urlsplit(value).scheme, value
    if mode in {"default", "header"}:
        assert len(page.images) == len(rendered(source).images)


def test_real_html_screenshot_keeps_dimensions_and_navigation_target() -> None:
    page = rendered(
        prepare('[<img src="./shot.png" alt="Screenshot" height="128" />](./shot.png)')
    )
    assert page.links == [UI + "/shot.png"]
    assert page.images == [
        {"src": RAW + "/shot.png", "alt": "Screenshot", "height": "128"}
    ]


def test_reference_images_fragments_and_code_render_with_expected_semantics() -> None:
    text = "[guide][manual]\n\n![logo][brand]\n\n`[code](./unchanged.md)`\n\n[manual]: ./docs.md#part\n[brand]: ./logo.avif\n"
    page = rendered(prepare(text))
    assert page.links == [UI + "/docs.md#part"]
    assert page.images[0]["src"] == RAW + "/logo.avif"


def test_renderer_check_can_detect_a_missed_relative_link() -> None:
    page = rendered("[unprepared](./relative.md#anchor)")
    assert page.links == ["./relative.md#anchor"]
    assert not urlsplit(page.links[0]).scheme


@pytest.mark.parametrize("simplify_badges", [False, True])
def test_mixed_content_renders_expected_links_and_images(simplify_badges: bool) -> None:
    source = (FIXTURES / "mixed-content.md").read_text(encoding="utf-8")
    page = rendered(prepare(source, simplify_badges=simplify_badges))
    assert page.links == [
        "#user-content-mixed-content",
        UI + "/docs/guide.md#intro",
        UI + "/docs/guide.md#intro",
        UI + "/docs/guide.md?plain=1#shot",
        UI + "/docs/guide.md#intro",
        UI + "/docs/guide.md#html",
        UI + "/docs/a%28b%29.md",
        "#user-content-mixed-content",
        "https://example.org/docs",
        "mailto:docs@example.org",
    ]
    assert [image["src"] for image in page.images] == [
        *([] if simplify_badges else [RAW + "/assets/logo.svg#mark"]),
        RAW + "/assets/shot.avif",
        RAW + "/assets/logo.svg#mark",
    ]
    screenshot = next(
        image for image in page.images if image["src"] == RAW + "/assets/shot.avif"
    )
    assert screenshot["height"] == "128"
