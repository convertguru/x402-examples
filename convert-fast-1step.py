#!/usr/bin/env python3
"""
Convert.Guru x402 API — Fast 1-Step Conversion Example: DOCX -> PDF
===================================================================

Demonstrates the 1-step endpoint `POST /api/x402/v1/convert-file/fast` for files <= 10 MB:
  - Verifies your 0.02 USDC x402 payment signature upfront.
  - Waits up to 15 seconds for conversion to complete.
  - Only settles payment on-chain AFTER the conversion succeeds!
  - Returns `download_url` directly in the HTTP 200 response (or falls back to
    free `/status` polling with automatic settlement if conversion takes > 15s).

NOTE: Prior file-type detection is NOT required.

Quickstart:
  pip install requests eth-account
  export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"
  python convert-fast-1step.py
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict

import requests

# Reuse the x402 signing helper from convert-docx-to-pdf.py
from importlib.machinery import SourceFileLoader

base_example = SourceFileLoader(
    "convert_docx_to_pdf",
    str(Path(__file__).parent / "convert-docx-to-pdf.py"),
).load_module()

API_BASE_URL = base_example.API_BASE_URL
INPUT_FILE = Path(__file__).parent / "sample.docx"
OUTPUT_FILE = Path(__file__).parent / "sample-fast.pdf"
TARGET_FORMAT = "pdf"


def main() -> None:
    if not INPUT_FILE.exists():
        sys.exit(f"Error: Sample input file not found at {INPUT_FILE}")

    account = base_example.get_account()
    print(f"Using wallet: {account.address}")
    print(f"Input file:   {INPUT_FILE.name} ({INPUT_FILE.stat().st_size} bytes)")
    print("Note:         Prior file-type detection is not required.\n")

    fast_url = f"{API_BASE_URL}/api/x402/v1/convert-file/fast"
    print(f"[1/2] Converting {INPUT_FILE.name} -> {TARGET_FORMAT.upper()} in 1 step ({fast_url})...")

    def build_upload_kwargs() -> Dict[str, Any]:
        return {
            "files": {
                "file": (
                    INPUT_FILE.name,
                    INPUT_FILE.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            "data": {
                "target_format": TARGET_FORMAT,
                "filename": INPUT_FILE.name,
            },
        }

    res = base_example.request_with_x402(account, "POST", fast_url, build_upload_kwargs)
    if not res.ok:
        sys.exit(f"Fast conversion failed ({res.status_code}): {res.text}")

    data = res.json()

    # If the conversion took longer than 15 seconds, the server returns HTTP 202
    # and automatically settles the pre-verified payment once /status reaches "done".
    if res.status_code == 202 or data.get("status") == "processing":
        status_url = data["status_url"]
        print(f"  -> Still processing after 15s; polling {status_url} (auto-settles on completion)...")
        while True:
            time.sleep(float(data.get("retry_after_seconds", 2)))
            poll_res = requests.get(status_url, timeout=30)
            poll_res.raise_for_status()
            data = poll_res.json()
            if data.get("status") in ("done", "paid") and data.get("download_url"):
                break
            if data.get("status") == "failed":
                sys.exit(f"Conversion failed (payment was NOT settled): {data}")

    download_url = data["download_url"]
    job_id = data["job_id"]
    tx_id = data.get("payment", {}).get("transaction_id", "-")
    print(f"  -> Done & paid! (job_id: {job_id}, tx: {tx_id})")

    print(f"\n[2/2] Downloading converted PDF to {OUTPUT_FILE.name}...")
    dl_res = requests.get(download_url, timeout=60)
    dl_res.raise_for_status()
    OUTPUT_FILE.write_bytes(dl_res.content)
    print(f"  -> Saved {OUTPUT_FILE} ({len(dl_res.content)} bytes)")

    # Optional: delete temporary files on server (free)
    requests.delete(f"{API_BASE_URL}/api/x402/v1/convert-file/{job_id}/delete", timeout=15)
    print("  -> Cleaned up temporary job files on server.")


if __name__ == "__main__":
    main()
