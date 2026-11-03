#!/usr/bin/env python3
"""
Convert.Guru x402 API — Optional File-Type Detection Example
============================================================

For standard file conversions (`POST /api/x402/v1/convert-file`), prior file-type
detection is NOT required because Convert.Guru automatically detects the input format.

However, if your agent receives an unknown or misnamed file (e.g. `attachment.bin`
or `document.001`) and wants to inspect ONLY the first 200 bytes before uploading
a large file, you can call `POST /api/x402/v1/detect-file-type` (0.002 USDC).
It identifies ~15,000 file formats and returns all supported `convertible_to` targets.

Quickstart:
  pip install requests eth-account
  export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"
  python detect-and-convert.py
"""

import base64
import json
import sys
from pathlib import Path
from typing import Any, Dict

from importlib.machinery import SourceFileLoader

base_example = SourceFileLoader(
    "convert_docx_to_pdf",
    str(Path(__file__).parent / "convert-docx-to-pdf.py"),
).load_module()

API_BASE_URL = base_example.API_BASE_URL
INPUT_FILE = Path(__file__).parent / "sample.docx"


def main() -> None:
    if not INPUT_FILE.exists():
        sys.exit(f"Error: Sample input file not found at {INPUT_FILE}")

    account = base_example.get_account()
    file_bytes = INPUT_FILE.read_bytes()
    first_200_b64 = base64.b64encode(file_bytes[:200]).decode("ascii")

    detect_url = f"{API_BASE_URL}/api/x402/v1/detect-file-type"
    print(f"Inspecting first 200 bytes of '{INPUT_FILE.name}' via {detect_url} (0.002 USDC)...")

    def build_detect_kwargs() -> Dict[str, Any]:
        return {
            "json": {
                "filename": "unknown_attachment.001",
                "size_bytes": len(file_bytes),
                "header_first_200_bytes_base64": first_200_b64,
            }
        }

    res = base_example.request_with_x402(account, "POST", detect_url, build_detect_kwargs)
    if not res.ok:
        sys.exit(f"Detection failed ({res.status_code}): {res.text}")

    info = res.json()
    print("\nDetection Result:")
    print(json.dumps(info, indent=2))

    detected_fmt = info.get("detected_format", {}).get("format")
    targets = info.get("convertible_to", [])
    print(f"\nDetected format: {detected_fmt}")
    print(f"Convertible to:  {', '.join(targets)}")


if __name__ == "__main__":
    main()
