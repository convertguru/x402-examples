#!/usr/bin/env python3
"""
Convert.Guru x402 API — Complete Working Example: DOCX -> PDF
=============================================================

Demonstrates the complete asynchronous file conversion workflow using a standard
HTTP client (`requests`) + EIP-3009 USDC payment signing (`eth-account`):

  1. Upload `sample.docx` -> POST /api/x402/v1/convert-file      (0.002 USDC)
  2. Poll job status      -> GET  /api/x402/v1/convert-file/{id}/status (FREE)
  3. Pay for result       -> GET  /api/x402/v1/convert-file/{id}/result (0.02 USDC)
  4. Download `sample.pdf` from `download_url` & delete server copy     (FREE)

NOTE: Prior file-type detection is NOT required.
Convert.Guru automatically detects the true input format upon upload.
If a conversion fails, `/result` is never called and you pay 0 USDC for the result.

Quickstart:
  pip install requests eth-account
  export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"   # Wallet with USDC on Base Mainnet
  python convert-docx-to-pdf.py
"""

import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests
from eth_account import Account

API_BASE_URL = os.environ.get("API_URL", "https://convert.guru").rstrip("/")
PAYMENT_NETWORK = os.environ.get("PAYMENT_NETWORK", "eip155:8453")  # Default: Base Mainnet
INPUT_FILE = Path(__file__).parent / "sample.docx"
OUTPUT_FILE = Path(__file__).parent / "sample.pdf"
TARGET_FORMAT = "pdf"


def get_account() -> Account:
    """Load wallet from PRIVATE_KEY env var (or generate a temporary demo wallet)."""
    pk = os.environ.get("PRIVATE_KEY", "").strip()
    if not pk:
        pk = "0x" + secrets.token_hex(32)
        print("WARNING: PRIVATE_KEY not set. Using a temporary unfunded wallet.")
        print("         Signature creation will work, but on-chain USDC settlement will fail.")
        print("         Set export PRIVATE_KEY='0x...' with a funded Base USDC wallet.\n")
    elif not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def sign_x402_payment(account: Account, payment_required_b64: str, request_url: str) -> str:
    """
    Decode the HTTP 402 `PAYMENT-REQUIRED` header, sign an EIP-3009
    `TransferWithAuthorization` authorization for USDC, and return the
    Base64-encoded `PAYMENT-SIGNATURE` header value.
    """
    requirements = json.loads(base64.b64decode(payment_required_b64).decode("utf-8"))
    accepts = requirements.get("accepts", [])

    # Select preferred EVM network (Base Mainnet eip155:8453 by default, or Polygon/Arbitrum)
    accept = next((a for a in accepts if a.get("network") == PAYMENT_NETWORK), None)
    if not accept:
        accept = next(
            (a for a in accepts if str(a.get("network", "")).startswith("eip155:")),
            None,
        )
    if not accept:
        raise RuntimeError(f"No compatible EVM payment option found in: {accepts}")

    network = accept["network"]
    chain_id = int(network.split(":")[1])
    amount = str(accept["amount"])
    asset = accept["asset"]
    pay_to = accept["payTo"]
    max_timeout = int(accept.get("maxTimeoutSeconds", 300))
    extra = accept.get("extra") or {}

    now = int(time.time())
    valid_after = max(0, now - 60)
    valid_before = now + max_timeout
    nonce_bytes = secrets.token_bytes(32)
    nonce_hex = "0x" + nonce_bytes.hex()

    domain = {
        "name": extra.get("name", "USD Coin"),
        "version": extra.get("version", "2"),
        "chainId": chain_id,
        "verifyingContract": asset,
    }
    types = {
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ]
    }
    message = {
        "from": account.address,
        "to": pay_to,
        "value": int(amount),
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": nonce_bytes,
    }

    signed = Account.sign_typed_data(account.key, domain, types, message)
    sig_hex = signed.signature.hex()
    signature = sig_hex if sig_hex.startswith("0x") else f"0x{sig_hex}"

    root_resource = requirements.get("resource")
    resource_url = (
        root_resource.get("url")
        if isinstance(root_resource, dict) and root_resource.get("url")
        else request_url
    )
    description = (
        (root_resource.get("description") if isinstance(root_resource, dict) else None)
        or accept.get("description")
        or "Convert.Guru x402 API request"
    )

    payment_payload = {
        "x402Version": 2,
        "accepted": {
            "scheme": "exact",
            "network": network,
            "asset": asset,
            "amount": amount,
            "payTo": pay_to,
            "maxTimeoutSeconds": max_timeout,
            "extra": extra,
        },
        "payload": {
            "signature": signature,
            "authorization": {
                "from": account.address,
                "to": pay_to,
                "value": amount,
                "validAfter": str(valid_after),
                "validBefore": str(valid_before),
                "nonce": nonce_hex,
            },
        },
        "resource": {
            "url": resource_url,
            "description": description,
            "mimeType": "application/json",
        },
    }

    usdc_decimal = int(amount) / 1_000_000
    print(f"  -> Signing x402 payment: {usdc_decimal:.6f} USDC on {network} to {pay_to}")
    return base64.b64encode(json.dumps(payment_payload).encode("utf-8")).decode("ascii")


def request_with_x402(
    account: Account,
    method: str,
    url: str,
    request_kwargs_factory: Optional[Callable[[], Dict[str, Any]]] = None,
) -> requests.Response:
    """
    Send an HTTP request. If the server responds with `402 Payment Required`,
    automatically sign the x402 challenge and retry with `PAYMENT-SIGNATURE`.
    """
    kwargs = request_kwargs_factory() if request_kwargs_factory else {}
    response = requests.request(method, url, timeout=60, **kwargs)

    if response.status_code == 402:
        payment_req_header = response.headers.get("PAYMENT-REQUIRED")
        if not payment_req_header:
            raise RuntimeError("Received HTTP 402 without PAYMENT-REQUIRED header.")

        payment_sig = sign_x402_payment(account, payment_req_header, url)

        # Rebuild kwargs (e.g. fresh file stream for multipart uploads) and attach payment header
        retry_kwargs = request_kwargs_factory() if request_kwargs_factory else {}
        headers = dict(retry_kwargs.get("headers") or {})
        headers["PAYMENT-SIGNATURE"] = payment_sig
        retry_kwargs["headers"] = headers

        response = requests.request(method, url, timeout=60, **retry_kwargs)

    return response


def main() -> None:
    if not INPUT_FILE.exists():
        sys.exit(f"Error: Sample input file not found at {INPUT_FILE}")

    account = get_account()
    print(f"Using wallet: {account.address}")
    print(f"Input file:   {INPUT_FILE.name} ({INPUT_FILE.stat().st_size} bytes)")
    print("Note:         Prior file-type detection is not required.\n")

    # -------------------------------------------------------------------------
    # Step 1: Upload file and start conversion job (0.002 USDC)
    # -------------------------------------------------------------------------
    convert_url = f"{API_BASE_URL}/api/x402/v1/convert-file"
    print(f"[1/4] Uploading {INPUT_FILE.name} -> {TARGET_FORMAT.upper()} ({convert_url})...")

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

    start_res = request_with_x402(account, "POST", convert_url, build_upload_kwargs)
    if not start_res.ok:
        sys.exit(f"Upload failed ({start_res.status_code}): {start_res.text}")

    job_info = start_res.json()
    job_id = job_info["job_id"]
    status_url = job_info["status_url"]
    print(f"  -> Job created: {job_id}")

    # -------------------------------------------------------------------------
    # Step 2: Poll job status for free until "done" or "failed" (0 USDC)
    # -------------------------------------------------------------------------
    print(f"\n[2/4] Polling status for free ({status_url})...")
    result_url = None
    while True:
        status_res = requests.get(status_url, timeout=30)
        status_res.raise_for_status()
        status_data = status_res.json()
        status = status_data.get("status")
        print(f"  -> status: {status}")

        if status == "done":
            result_url = status_data["result_url"]
            price_info = status_data.get("price_for_result", {})
            print(
                f"  -> Conversion finished! Result price: "
                f"{price_info.get('amount', '0.020000')} {price_info.get('currency', 'USDC')}"
            )
            break
        if status == "failed":
            sys.exit(f"Conversion failed (0 USDC charged for result): {status_data}")

        time.sleep(float(status_data.get("retry_after_seconds", 2)))

    # -------------------------------------------------------------------------
    # Step 3: Pay for the finished conversion result (0.02 USDC for <= 10 MB)
    # -------------------------------------------------------------------------
    print(f"\n[3/4] Purchasing conversion result ({result_url})...")
    result_res = request_with_x402(account, "GET", result_url)
    if not result_res.ok:
        sys.exit(f"Result purchase failed ({result_res.status_code}): {result_res.text}")

    result_data = result_res.json()
    download_url = result_data["download_url"]
    tx_id = result_data.get("payment", {}).get("transaction_id", "-")
    print(f"  -> Payment settled (tx: {tx_id})")
    print(f"  -> Download URL: {download_url}")

    # -------------------------------------------------------------------------
    # Step 4: Download the converted PDF and optionally delete server files
    # -------------------------------------------------------------------------
    print(f"\n[4/4] Downloading converted file to {OUTPUT_FILE.name}...")
    dl_res = requests.get(download_url, timeout=60)
    dl_res.raise_for_status()
    OUTPUT_FILE.write_bytes(dl_res.content)
    print(f"  -> Saved {OUTPUT_FILE} ({len(dl_res.content)} bytes)")

    # Optional: immediately delete conversion files from server storage (free)
    delete_url = f"{API_BASE_URL}/api/x402/v1/convert-file/{job_id}/delete"
    requests.delete(delete_url, timeout=15)
    print("  -> Cleaned up temporary job files on server.")


if __name__ == "__main__":
    main()
