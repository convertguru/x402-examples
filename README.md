# Convert.Guru — x402 & MPP File Conversion Examples

Executable, self-contained examples for converting files (e.g. **DOCX → PDF**) with the [Convert.Guru x402 API](https://convert.guru/api/x402/v1/) using standard HTTP clients and USDC micropayments — **no proprietary SDK or API key required**.

> **Important:** Prior file-type detection is **not** required (`POST /api/x402/v1/detect-file-type` is completely optional). Convert.Guru automatically detects the input file's true format upon upload.

---

## Included Files

| File | Language | Description |
| :--- | :--- | :--- |
| [`convert-docx-to-pdf.py`](./convert-docx-to-pdf.py) | Python 3.9+ | **Main Example:** Upload `sample.docx` → free status polling → pay result (`0.02 USDC`) → download `sample.pdf` |
| [`convert-fast-1step.py`](./convert-fast-1step.py) | Python 3.9+ | **1-Step Fast Workflow:** Single request (`POST /api/x402/v1/convert-file/fast`), settles payment only on success |
| [`detect-and-convert.py`](./detect-and-convert.py) | Python 3.9+ | **Optional File-Type Detection:** Inspects only the first 200 bytes (`POST /api/x402/v1/detect-file-type`) for unknown/misnamed files |
| [`convert-docx-to-pdf.mjs`](./convert-docx-to-pdf.mjs) | Node.js 18+ | Complete DOCX → PDF workflow using native `fetch` + `viem` |
| [`convert-docx-to-pdf.php`](./convert-docx-to-pdf.php) | PHP 8.1+ | Complete DOCX → PDF workflow using `curl` + EIP-3009 signing |
| [`sample.docx`](./sample.docx) | Sample File | Small 2.4 KB Word document ready for immediate testing |

---

## Quickstart (Python)

```bash
pip install -r requirements.txt
export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"   # Wallet funded with USDC on Base Mainnet
python convert-docx-to-pdf.py
```

## Quickstart (Node.js 18+)

```bash
npm install
export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"
node convert-docx-to-pdf.mjs
```

## Quickstart (PHP 8.1+ with `ext-curl` & `ext-gmp`)

```bash
composer install
export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"
php convert-docx-to-pdf.php
```

---

## How the Workflow Works

1. **Upload (`POST /api/x402/v1/convert-file` — `0.002 USDC`)**  
   Send `sample.docx` and `target_format=pdf` as `multipart/form-data`. The gateway responds with `HTTP 402 Payment Required` and a `PAYMENT-REQUIRED` header. Your client signs an EIP-3009 `TransferWithAuthorization` payload and retries with `PAYMENT-SIGNATURE`. Returns `job_id` and `status_url`.
2. **Free Status Polling (`GET /api/x402/v1/convert-file/{job_id}/status` — `0 USDC`)**  
   Poll `status_url` for free until `status` is `"done"` (or `"failed"`). If a conversion fails, no result fee is charged (`0 USDC`).
3. **Pay for Result (`GET /api/x402/v1/convert-file/{job_id}/result` — `0.02 USDC` for files ≤ 10 MB)**  
   Request `result_url`, sign the `402` challenge, and receive a short-lived `download_url` plus a verifiable on-chain payment receipt.
4. **Download & Optional Cleanup (`DELETE /api/x402/v1/convert-file/{job_id}/delete` — `0 USDC`)**  
   Download the converted `sample.pdf` from `download_url`. Optionally call `/delete` to immediately remove the file from server storage (otherwise auto-deleted after 24h).

---

## Supported Payment Networks

Set `PAYMENT_NETWORK` to choose your preferred EVM chain (defaults to Base Mainnet `eip155:8453`):

- **Base Mainnet:** `eip155:8453` (USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`)
- **Polygon Mainnet:** `eip155:137` (USDC `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359`)
- **Arbitrum One:** `eip155:42161` (USDC `0xaf88d065e77c8cC2239327C5EDb3A432268e5831`)
- **Solana Mainnet (x402 SVM)** & **Tempo Mainnet (MPP `WWW-Authenticate: Payment`)** are also supported by the gateway.

---

## Links & Discovery

- **API Documentation & LLM Guide:** [https://convert.guru/llms.txt](https://convert.guru/llms.txt)
- **OpenAPI 3.1 Specification:** [https://convert.guru/openapi.json](https://convert.guru/openapi.json)
- **x402 Discovery Manifest:** [https://convert.guru/.well-known/x402.json](https://convert.guru/.well-known/x402.json)
