from archive_workbench.agent import verify


def test_keeps_cited_sentences_and_drops_the_rest():
    answer = "The minute is from Dharwar [1]. This is an unsupported guess. The date is 1862 [2]."
    text, dropped = verify(answer, 2)
    assert "Dharwar" in text and "1862" in text
    assert "unsupported" not in text
    assert dropped and "unsupported" in dropped[0]
    assert "removed because they had no citation" in text


def test_strips_markers_that_do_not_exist():
    text, dropped = verify("A fact [1] and a dangling [9].", 1)
    assert "[1]" in text and "[9]" not in text
    assert dropped == []


def test_allows_an_explicit_gap():
    text, dropped = verify("The transcription does not contain a passage that answers this.", 3)
    assert "does not contain" in text
    assert dropped == []


def test_empty_answer_is_explicit():
    text, _dropped = verify("   ", 2)
    assert "No supported answer" in text


def test_periods_inside_a_quotation_stay_with_the_citation():
    answer = 'On page 1 the transcription reads: "Department, SUBJECT. Date 1862." [1].'
    text, dropped = verify(answer, 1)
    assert "Department" in text and "1862" in text and "[1]" in text
    assert dropped == []
