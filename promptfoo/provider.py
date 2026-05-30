"""Promptfoo custom provider: runs the Claude extraction agent on one email.

Promptfoo calls `call_api` per test; we return the ExtractedCase as JSON so the
assertions (and the local dashboard) can show the model's direct output.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from forgeflow.agent import extract_case  # noqa: E402  (LLM only)
from forgeflow.parser import parse_email_file  # noqa: E402


def call_api(prompt, options, context):
    email_file = context["vars"]["email_file"]
    message = parse_email_file(ROOT / email_file)
    extracted = extract_case([message])
    return {"output": json.dumps(asdict(extracted), indent=2)}
