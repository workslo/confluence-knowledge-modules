from bs4 import BeautifulSoup

from ckm.convert import LinkResolver, convert_content


def md(html: str, pages: dict[str, str] | None = None) -> tuple[str, LinkResolver]:
    resolver = LinkResolver(page_paths=pages or {}, attachment_dir="attachments")
    root = BeautifulSoup(f"<div id='main-content'>{html}</div>", "html.parser").div
    return convert_content(root, resolver), resolver


def test_headings_shift_down_one_level() -> None:
    out, _ = md("<h1>A</h1><h2>B</h2><h6>C</h6>")
    assert out == "## A\n\n### B\n\n###### C"


def test_nested_list_indents_to_parent_content_column() -> None:
    out, _ = md("<ol><li>one<ul><li>a</li></ul></li><li>two</li></ol>")
    assert out == "1. one\n   - a\n2. two"


def test_table_without_header_gets_empty_header_not_invented_one() -> None:
    out, _ = md("<table><tr><td>x</td><td>y</td></tr></table>")
    assert out == "|  |  |\n|---|---|\n| x | y |"


def test_table_cell_pipes_are_escaped() -> None:
    out, _ = md("<table><tr><th>h</th></tr><tr><td>a | b</td></tr></table>")
    assert "| a \\| b |" in out


def test_code_fence_lengthens_when_body_contains_backticks() -> None:
    html = '<pre data-syntaxhighlighter-params="brush: bash">echo ```</pre>'
    out, _ = md(html)
    assert out.startswith("````bash\n") and out.endswith("\n````")


def test_info_panels_become_hads_note_blocks() -> None:
    html = (
        '<div class="confluence-information-macro confluence-information-macro-warning">'
        '<div class="confluence-information-macro-body"><p>Careful.</p></div></div>'
    )
    out, _ = md(html)
    assert out == "**[NOTE]**\n**Warning:** Careful."


def test_zero_width_and_nbsp_are_cleaned() -> None:
    out, _ = md("<p>a\u200b\u00a0b</p>")
    assert out == "a b"


def test_page_links_resolve_through_the_page_map() -> None:
    html = '<a href="X_7.html" data-linked-resource-id="7" data-linked-resource-type="page">X</a>'
    out, resolver = md(f"<p>{html}</p>", pages={"7": "x.md"})
    assert out == "[X](x.md)"
    assert resolver.unresolved == []


def test_unknown_page_link_keeps_text_and_is_reported() -> None:
    html = (
        '<a href="Gone_8.html" data-linked-resource-id="8" '
        'data-linked-resource-type="page">Gone</a>'
    )
    out, resolver = md(f"<p>{html}</p>")
    assert out == "Gone"
    assert resolver.unresolved == ["page:Gone_8.html"]


def test_attachments_are_renamed_owner_underscore_file() -> None:
    out, resolver = md('<p><img src="attachments/12/34.png" alt="d"></p>')
    assert out == "![d](attachments/12_34.png)"
    assert resolver.assets == {"attachments/12/34.png": "12_34.png"}


def test_same_page_anchors_and_external_links() -> None:
    out, _ = md(
        '<p><a href="#top">Top</a> <a href="https://e.x/a">site</a> '
        '<a href="mailto:a@e.x">mailto:a@e.x</a></p>'
    )
    assert out == "Top [site](https://e.x/a) <mailto:a@e.x>"  # text == href -> autolink
