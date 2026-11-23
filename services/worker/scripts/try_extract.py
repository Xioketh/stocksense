"""Try the REAL Gemini extractor on one file, from your laptop.

It uses your Application Default Credentials (gcloud auth application-default
login), so it calls Gemini as YOUR developer account, billed to --project.
No database, no Pub/Sub: just file -> Gemini -> validated lines.

Usage (from services/worker):
    python -m scripts.try_extract FILE --project PROJECT_ID
e.g.
    python -m scripts.try_extract samples/invoices/not-an-invoice.pdf --project stocksense-dev-kr84
"""

import argparse
import json
import sys
from pathlib import Path

from google.auth.exceptions import DefaultCredentialsError

from app.config import Settings
from app.extraction import ExtractionFailed, ExtractionUnavailable
from app.extraction.gemini import GeminiExtractor, build_client
from app.logging_config import setup_logging

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def default(name: str):
    """Use the same defaults as the worker's Settings, so the script matches Cloud Run."""
    return Settings.model_fields[name].default


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Gemini invoice extractor on one file.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--project", required=True, help="e.g. stocksense-dev-kr84")
    parser.add_argument("--location", default=default("gemini_location"))
    parser.add_argument("--model", default=default("gemini_model"))
    parser.add_argument("--thinking", default=default("gemini_thinking_level"))
    args = parser.parse_args()

    setup_logging("INFO")  # shows the "gemini extraction finished" line with token counts
    mime_type = MIME_TYPES.get(args.file.suffix.lower(), "application/octet-stream")

    client = build_client(
        project=args.project,
        location=args.location,
        timeout_seconds=default("gemini_timeout_seconds"),
        max_attempts=default("gemini_max_attempts"),
    )
    extractor = GeminiExtractor(client, model=args.model, thinking_level=args.thinking)

    try:
        result = extractor.extract(args.file.read_bytes(), mime_type)
    except ExtractionFailed as exc:
        print(f"\nFAILED (permanent -> invoice would be 'failed'): {exc}")
        return 1
    except ExtractionUnavailable as exc:
        print(f"\nUNAVAILABLE (temporary -> Pub/Sub would retry): {exc}")
        return 2
    except DefaultCredentialsError:
        print("\nNo credentials: run 'gcloud auth application-default login' first.")
        return 3

    print(json.dumps(result.model_dump()["lines"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
