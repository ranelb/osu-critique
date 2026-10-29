"""The markdown subset the web frontend renders stored answers with.

Pure string work, no web extra: the point of keeping it dependency-free is that
it is testable in the core suite. ``tests/test_web.py`` asserts the wiring
(the template no longer prints the body in a ``<pre>``).
"""
from __future__ import annotations

from osu_critique.markdown import inline, render


# ---------------------------------------------------------------- blocks ----

def test_headings_keep_their_level_and_strip_trailing_hashes():
    assert render("## The answer") == "<h2>The answer</h2>"
    assert render("###### deep ######") == "<h6>deep</h6>"
    assert render("#no space is not a heading") == "<p>#no space is not a heading</p>"


def test_paragraphs_join_soft_wrapped_lines():
    assert render("one line\nstill the same para\n\nsecond")
    assert render("one line\nstill the same para") == "<p>one line still the same para</p>"


def test_unordered_list_with_continuation_line():
    page = render("- first, which the model\n  wrapped onto a second line\n- second")
    assert page == ("<ul><li>first, which the model wrapped onto a second line</li>"
                    "<li>second</li></ul>")


def test_ordered_list_survives_the_two_numbering_styles():
    assert render("1. one\n2. two") == "<ol><li>one</li><li>two</li></ol>"
    assert render("1) one\n2) two") == "<ol><li>one</li><li>two</li></ol>"


def test_a_list_inside_a_paragraph_splits_the_paragraph():
    page = render("The misses are far:\n\n- note r 1.98\n- gaps 6.3r")
    assert page.startswith("<p>The misses are far:</p>")
    assert "<ul><li>note r 1.98</li><li>gaps 6.3r</li></ul>" in page


def test_fenced_code_is_literal_and_closes_at_eof():
    page = render("```python\nx = '<b>' * 2\nprint(x)\n```")
    assert page == ('<pre class="md-code"><code class="language-python">'
                    "x = '&lt;b&gt;' * 2\nprint(x)</code></pre>")
    # an unclosed fence still renders, because a truncated model answer is normal
    assert "&lt;b&gt;" in render("```\n<b>")


def test_blockquote_recurses():
    assert render("> **bold** point") == "<blockquote><p><strong>bold</strong> point</p></blockquote>"


def test_horizontal_rule_and_its_lookalikes():
    assert render("---") == "<hr>"
    assert render("- - -") == "<hr>"
    # a bullet list must not be eaten by the rule
    assert render("- -") == "<ul><li>-</li></ul>"


def test_table_gets_columns_and_rows():
    page = render("| family | n | rate |\n|---|---|---|\n| jump | 59 | 13.6% |")
    assert '<div class="md-table">' in page
    assert "<th>family</th><th>n</th><th>rate</th>" in page
    assert "<td>jump</td><td>59</td><td>13.6%</td>" in page


def test_an_empty_answer_is_empty_not_a_crash():
    assert render("") == ""
    assert render("\n\n") == ""


# ---------------------------------------------------------------- inline ----

def test_bold_italic_code_and_strike():
    assert inline("**stable** and *swings*") == "<strong>stable</strong> and <em>swings</em>"
    assert inline("_swings_ too") == "<em>swings</em> too"
    assert inline("`4 / snap`") == "<code>4 / snap</code>"
    assert inline("~~gone~~") == "<del>gone</del>"


def test_snake_case_is_not_italicised():
    assert inline("circle_1/2_jump") == "circle_1/2_jump"


def test_code_span_protects_its_contents_from_the_other_rules():
    # this is the case that used to garble answers: **`**`**
    assert inline("**`a*b`**") == "<strong><code>a*b</code></strong>"


def test_maths_asterisks_stay_literal():
    assert inline("2 * 3 * 4") == "2 * 3 * 4"


# ------------------------------------------------------------------ safety ----

def test_raw_html_is_escaped_not_executed():
    page = render("<script>alert(1)</script>")
    assert page == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
    assert "<script>" not in page
    # an image-markdown attempt with a handler in the URL: no tag is produced,
    # the whole thing stays a text node
    page = render('![x](y" onerror="alert(1))')
    assert page == '<p>![x](y" onerror="alert(1))</p>'
    assert "<img" not in page


def test_javascript_and_data_links_are_left_as_text():
    assert inline("[click](javascript:alert(1))") == "[click](javascript:alert(1))"
    assert inline("[click](data:text/html,x)") == "[click](data:text/html,x)"


def test_http_mailto_and_relative_links_render_with_rel():
    assert ('<a href="https://example.com/x?a=1&amp;b=2" rel="noopener noreferrer">'
            "site</a>") == inline("[site](https://example.com/x?a=1&b=2)")
    assert 'href="mailto:a@b.c"' in inline("[mail](mailto:a@b.c)")
    assert 'href="/ask"' in inline("[ask](/ask)")


# ------------------------------------------------------------- the corpus ----

def test_a_real_answer_shape_renders_without_leaking_markup():
    """The sections the model actually writes, in the order it writes them."""
    body = """## 1. What this selection is
Four runs on 2026-10-27 between 16:52 and 19:59.

## 2. Verdict
The loss is not rhythm: 90–100% of whiffs are "off-target".

## 3. Stable
The one finding that holds in all four runs is **long jumps with a hard
direction change**.

- Bigjump miss rate is the worst pattern: 7.8% (10/128).
- Reversal × spacing ≥150° misses every time (6/102); plain `jump` is 0.9%.

1. First step.
2. Second step."""
    page = render(body)
    assert page.count("<h2>") == 3
    assert "<strong>long jumps with a hard direction change</strong>" in page
    assert "<code>jump</code>" in page
    assert "<li>Bigjump miss rate is the worst pattern: 7.8% (10/128).</li>" in page
    assert "<ol><li>First step.</li>" in page
    # nothing unrendered survives
    for leftover in ("**", "## ", "\n\n"):
        assert leftover not in page
    assert "&amp;" not in page
