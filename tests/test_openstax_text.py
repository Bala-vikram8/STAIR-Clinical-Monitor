"""Invented XML checks the source text rules without patient data or downloads."""

from pathlib import Path

import pytest

from stair_monitor.openstax_text import parse_module


def module(body, *, title="Made-up section", metadata=""):
    return (
        '<document xmlns="http://cnx.rice.edu/cnxml" '
        'xmlns:m="http://www.w3.org/1998/Math/MathML" '
        'xmlns:md="http://cnx.rice.edu/mdml">'
        f"<title>{title}</title><metadata>{metadata}</metadata><content>{body}</content></document>"
    ).encode()


def test_inline_words_units_notes_links_and_subscripts_remain_distinct():
    parsed = parse_module(module(
        '<para>A <emphasis>made-up</emphasis> value is 5 mg; CO<sub>2</sub> and x<sup>2</sup>.</para>'
        '<para>Read <link url="https://example.org/public">the source</link>.'
        '<footnote>For this invented example only.</footnote></para>'
        '<note><para>Keep this condition with the value.</para></note>'
    ))
    assert parsed.title == "Made-up section"
    assert "A made-up value is 5 mg; CO_(2) and x^(2)." in parsed.text
    assert "the source (https://example.org/public)" in parsed.text
    assert "[Footnote: For this invented example only.]" in parsed.text
    assert "Note:\nKeep this condition with the value." in parsed.text


def test_tables_keep_cell_order_headings_span_and_following_note():
    parsed = parse_module(module(
        '<table summary="Invented comparison"><tgroup cols="2">'
        '<colspec colname="c1" colnum="1"/><colspec colname="c2" colnum="2"/>'
        '<thead><row><entry>Item</entry><entry>Unit</entry></row></thead>'
        '<tbody><row><entry>Example A</entry><entry>mg</entry></row>'
        '<row><entry namest="c1" nameend="c2">Same condition applies.</entry></row></tbody>'
        '</tgroup></table><para>* A source note follows the table.</para>'
    ))
    assert "Item | Unit" in parsed.text
    assert "Example A | mg" in parsed.text
    assert "[columns c1 to c2] Same condition applies." in parsed.text
    assert parsed.text.index("Example A") < parsed.text.index("* A source note")


def test_math_does_not_turn_fraction_or_ion_charge_into_flat_digits():
    parsed = parse_module(module(
        '<para><m:math><m:mrow><m:msubsup><m:mi>O</m:mi><m:mn>2</m:mn><m:mo>−</m:mo>'
        '</m:msubsup><m:mo> = </m:mo><m:mfrac><m:mn>1</m:mn><m:mn>3</m:mn>'
        '</m:mfrac></m:mrow></m:math></para>'
    ))
    assert "O_(2)^(−)" in parsed.text
    assert "(1)/(3)" in parsed.text


def test_numbered_answers_remain_matched_with_their_lettered_options():
    parsed = parse_module(module(
        '<exercise><problem><para>Pick an invented option.</para>'
        '<list list-type="enumerated" number-style="lower-alpha">'
        '<item>First</item><item>Second</item></list></problem>'
        '<solution><para>B</para></solution></exercise>'
    ))
    assert "a. First\nb. Second" in parsed.text
    assert "Solution:\nB" in parsed.text


def test_figures_keep_description_caption_and_source_without_claiming_image_content():
    parsed = parse_module(module(
        '<figure><title>Invented figure</title><media alt="An invented labelled shape.">'
        '<image src="../../media/example.svg"/></media><caption>Do not drop this credit.</caption></figure>'
    ))
    assert "Image description: An invented labelled shape." in parsed.text
    assert "Image not rendered; source file: ../../media/example.svg" in parsed.text
    assert "Do not drop this credit." in parsed.text
    assert any("not downloaded" in warning for warning in parsed.warnings)


def test_unique_publisher_abstract_is_kept_without_repeating_metadata_title():
    metadata = '<md:title>Made-up section</md:title><md:abstract><para>Learning goal.</para></md:abstract>'
    parsed = parse_module(module('<para>Body text.</para>', metadata=metadata))
    assert parsed.text == "Publisher summary:\nLearning goal.\n\nBody text."
    repeated = parse_module(module('<para>Learning goal.</para>', metadata=metadata))
    assert repeated.text.count("Learning goal.") == 1


def test_unknown_elements_keep_their_source_markup_and_a_visible_warning():
    parsed = parse_module(module('<para>Before <unknown flag="source">kept text</unknown> after.</para>'))
    assert "kept text" in parsed.text
    assert 'flag="source"' in parsed.text
    assert any("unknown" in warning for warning in parsed.warnings)
    assert parsed.text.count(" after.") == 1


@pytest.mark.parametrize("raw", [
    b'<document xmlns="http://cnx.rice.edu/cnxml"><title>X</title></document>',
    module('<para>Body</para>', title=" "),
    module(''),
    b'<broken>',
    b'<!DOCTYPE document [<!ENTITY injected "bad">]><document>&injected;</document>',
    '<document>bad</document>'.encode('utf-16'),
])
def test_bad_or_unsafe_source_cannot_be_accepted(raw):
    with pytest.raises(ValueError):
        parse_module(raw)


def test_real_source_samples_if_available():
    folder = Path('data/source-checks/openstax/5ae32b3f4bc24ed003e91dc38bf47dba80751044')
    sample = folder / 'openstax-m45983.cnxml'
    if not sample.exists():
        pytest.skip('The optional saved public source sample is not present.')
    parsed = parse_module(sample.read_bytes())
    assert parsed.title == "Overview of Anatomy and Physiology"
    assert "Chapter Review" in parsed.text
    assert "Review Questions" in parsed.text
    assert "Glossary" in parsed.text
    assert "Image description:" in parsed.text
    assert "University of Michigan Medical School" in parsed.text
    assert "Solution:" in parsed.text
