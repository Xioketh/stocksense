"""Unit tests for invoice extraction. No real Gemini: the client is a stub."""

from types import SimpleNamespace

import httpx2
import pytest
from google.genai import errors

from app import extraction
from app.extraction import ExtractionFailed, ExtractionUnavailable, get_extractor
from app.extraction.gemini import GeminiExtractor
from app.extraction.schemas import MAX_QTY, parse_gemini_output

NIMAL_JSON = """{
  "is_invoice": true,
  "lines": [
    {"sku": " rice-5 ", "name": "Rice 5kg", "quantity": 20},
    {"sku": "SUGAR-1", "name": "Sugar 1kg", "quantity": 25},
    {"sku": "", "name": "Coconut oil 750ml", "quantity": 10}
  ]
}"""


# ---------- parse_gemini_output: our rules for accepting AI output ----------


def test_valid_answer_is_accepted_and_skus_are_cleaned():
    result = parse_gemini_output(NIMAL_JSON)

    assert [(ln.sku, ln.qty) for ln in result.lines] == [
        ("RICE-5", 20),  # trimmed + uppercased
        ("SUGAR-1", 25),
        (None, 10),  # an empty code counts as "no code"
    ]


def test_not_an_invoice_fails():
    with pytest.raises(ExtractionFailed, match="does not look like a supplier invoice"):
        parse_gemini_output('{"is_invoice": false, "lines": []}')


def test_zero_quantity_fails_and_says_which_line():
    bad = NIMAL_JSON.replace('"quantity": 25', '"quantity": 0')

    with pytest.raises(ExtractionFailed, match="line 2, qty"):
        parse_gemini_output(bad)


def test_absurd_quantity_fails():
    bad = NIMAL_JSON.replace('"quantity": 20', f'"quantity": {MAX_QTY + 1}')

    with pytest.raises(ExtractionFailed, match="line 1, qty"):
        parse_gemini_output(bad)


def test_invoice_with_no_lines_fails():
    with pytest.raises(ExtractionFailed, match="failed validation"):
        parse_gemini_output('{"is_invoice": true, "lines": []}')


def test_answer_that_is_not_json_fails():
    with pytest.raises(ExtractionFailed, match="not in the expected JSON format"):
        parse_gemini_output("Sure! Here are the items: rice, sugar...")


# ---------- GeminiExtractor, with a stub instead of the real client ----------


def make_extractor(answer=None, error: Exception | None = None):
    """A GeminiExtractor whose client returns `answer` or raises `error`."""
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        usage = SimpleNamespace(
            prompt_token_count=1200, candidates_token_count=80, thoughts_token_count=40
        )
        return SimpleNamespace(text=answer, usage_metadata=usage, model_version="gemini-test")

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return GeminiExtractor(client, model="gemini-test", thinking_level="low"), calls


def api_error(code: int, status: str) -> errors.APIError:
    error_class = errors.ClientError if code < 500 else errors.ServerError
    return error_class(code, {"error": {"code": code, "message": "test", "status": status}})


def test_extractor_sends_the_file_and_asks_for_json():
    extractor, calls = make_extractor(answer=NIMAL_JSON)

    result = extractor.extract(b"%PDF-1.7 fake", "application/pdf")

    assert len(result.lines) == 3
    request = calls[0]
    assert request["model"] == "gemini-test"
    file_part = request["contents"][0]
    assert file_part.inline_data.mime_type == "application/pdf"
    assert file_part.inline_data.data == b"%PDF-1.7 fake"
    assert request["config"].response_mime_type == "application/json"
    assert request["config"].temperature == 0


def test_unsupported_file_type_fails_without_calling_gemini():
    extractor, calls = make_extractor(answer=NIMAL_JSON)

    with pytest.raises(ExtractionFailed, match="Unsupported file type"):
        extractor.extract(b"MZ...", "application/x-msdownload")
    assert calls == []  # no tokens spent on a file we can't use


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (429, "RESOURCE_EXHAUSTED"),  # busy: try later
        (503, "UNAVAILABLE"),  # outage: try later
        (403, "PERMISSION_DENIED"),  # missing IAM role: fixable, try later
    ],
)
def test_temporary_api_errors_mean_try_again_later(code, status):
    extractor, _ = make_extractor(error=api_error(code, status))

    with pytest.raises(ExtractionUnavailable):
        extractor.extract(b"%PDF", "application/pdf")


def test_rejected_file_is_a_permanent_failure():
    extractor, _ = make_extractor(error=api_error(400, "INVALID_ARGUMENT"))

    with pytest.raises(ExtractionFailed, match="400"):
        extractor.extract(b"%PDF", "application/pdf")


def test_timeout_means_try_again_later():
    extractor, _ = make_extractor(error=httpx2.ReadTimeout("timed out"))

    with pytest.raises(ExtractionUnavailable, match="ReadTimeout"):
        extractor.extract(b"%PDF", "application/pdf")


# ---------- get_extractor: choosing the backend ----------


def test_fake_extractor_is_refused_on_cloud_run(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("EXTRACTOR_BACKEND", "fake")
    extraction.get_settings.cache_clear()
    get_extractor.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="not allowed"):
            get_extractor()
    finally:
        # Put the cached test settings back for the other tests.
        monkeypatch.undo()
        extraction.get_settings.cache_clear()
        get_extractor.cache_clear()