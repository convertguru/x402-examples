#!/usr/bin/env node
/**
 * Convert.Guru x402 API — Complete Working Example (Node.js 18+): DOCX -> PDF
 * ===========================================================================
 *
 * Demonstrates the complete asynchronous file conversion workflow using
 * Node.js built-in `fetch` / `FormData` and `viem` for EIP-3009 USDC signing:
 *
 *   1. Upload `sample.docx` -> POST /api/x402/v1/convert-file           (0.002 USDC)
 *   2. Poll job status      -> GET  /api/x402/v1/convert-file/{id}/status (FREE)
 *   3. Pay for result       -> GET  /api/x402/v1/convert-file/{id}/result (0.02 USDC)
 *   4. Download `sample.pdf` from `download_url` & delete server copy     (FREE)
 *
 * NOTE: Prior file-type detection is NOT required.
 * Convert.Guru automatically detects the true input format upon upload.
 *
 * Quickstart:
 *   npm install viem
 *   export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"
 *   node convert-docx-to-pdf.mjs
 */

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { generatePrivateKey, privateKeyToAccount } from 'viem/accounts';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const API_BASE_URL = (process.env.API_URL || 'https://convert.guru').replace(/\/$/, '');
const PAYMENT_NETWORK = process.env.PAYMENT_NETWORK || 'eip155:8453'; // Default: Base Mainnet
const INPUT_FILE = path.join(__dirname, 'sample.docx');
const OUTPUT_FILE = path.join(__dirname, 'sample.pdf');
const TARGET_FORMAT = 'pdf';

function getAccount() {
  let pk = (process.env.PRIVATE_KEY || '').trim();
  if (!pk) {
    pk = generatePrivateKey();
    console.log('WARNING: PRIVATE_KEY not set. Using a temporary unfunded wallet.');
    console.log('         Signature creation will work, but on-chain USDC settlement will fail.');
    console.log('         Set export PRIVATE_KEY="0x..." with a funded Base USDC wallet.\n');
  } else if (!pk.startsWith('0x')) {
    pk = `0x${pk}`;
  }
  return privateKeyToAccount(pk);
}

async function signX402Payment(account, paymentRequiredB64, requestUrl) {
  const requirements = JSON.parse(Buffer.from(paymentRequiredB64, 'base64').toString('utf-8'));
  const accepts = Array.isArray(requirements.accepts) ? requirements.accepts : [];

  const accept =
    accepts.find((a) => a.network === PAYMENT_NETWORK) ||
    accepts.find((a) => String(a.network || '').startsWith('eip155:'));

  if (!accept) {
    throw new Error(`No compatible EVM payment option found in: ${JSON.stringify(accepts)}`);
  }

  const { network, amount, asset, payTo, maxTimeoutSeconds = 300, extra = {} } = accept;
  const chainId = Number(String(network).split(':')[1]);
  const nowSeconds = Math.floor(Date.now() / 1000);
  const validAfter = BigInt(Math.max(0, nowSeconds - 60));
  const validBefore = BigInt(nowSeconds + Number(maxTimeoutSeconds));
  const nonce = `0x${crypto.randomBytes(32).toString('hex')}`;

  const signature = await account.signTypedData({
    domain: {
      name: extra.name || 'USD Coin',
      version: extra.version || '2',
      chainId,
      verifyingContract: asset,
    },
    types: {
      TransferWithAuthorization: [
        { name: 'from', type: 'address' },
        { name: 'to', type: 'address' },
        { name: 'value', type: 'uint256' },
        { name: 'validAfter', type: 'uint256' },
        { name: 'validBefore', type: 'uint256' },
        { name: 'nonce', type: 'bytes32' },
      ],
    },
    primaryType: 'TransferWithAuthorization',
    message: {
      from: account.address,
      to: payTo,
      value: BigInt(amount),
      validAfter,
      validBefore,
      nonce,
    },
  });

  const resourceUrl = requirements.resource?.url || requestUrl;
  const description =
    requirements.resource?.description || accept.description || 'Convert.Guru x402 API request';

  const paymentPayload = {
    x402Version: 2,
    accepted: {
      scheme: 'exact',
      network,
      asset,
      amount: String(amount),
      payTo,
      maxTimeoutSeconds: Number(maxTimeoutSeconds),
      extra,
    },
    payload: {
      signature,
      authorization: {
        from: account.address,
        to: payTo,
        value: String(amount),
        validAfter: validAfter.toString(),
        validBefore: validBefore.toString(),
        nonce,
      },
    },
    resource: {
      url: resourceUrl,
      description,
      mimeType: 'application/json',
    },
  };

  console.log(
    `  -> Signing x402 payment: ${(Number(amount) / 1e6).toFixed(6)} USDC on ${network} to ${payTo}`
  );
  return Buffer.from(JSON.stringify(paymentPayload)).toString('base64');
}

async function fetchWithX402(account, url, initFactory = () => ({})) {
  let response = await fetch(url, initFactory());

  if (response.status === 402) {
    const paymentReqHeader = response.headers.get('PAYMENT-REQUIRED');
    if (!paymentReqHeader) {
      throw new Error('Received HTTP 402 without PAYMENT-REQUIRED header.');
    }
    await response.body?.cancel();

    const paymentSignature = await signX402Payment(account, paymentReqHeader, url);
    const retryInit = initFactory();
    retryInit.headers = {
      ...(retryInit.headers || {}),
      'PAYMENT-SIGNATURE': paymentSignature,
    };
    response = await fetch(url, retryInit);
  }

  return response;
}

async function main() {
  const fileBytes = await fs.readFile(INPUT_FILE);
  const account = getAccount();

  console.log(`Using wallet: ${account.address}`);
  console.log(`Input file:   ${path.basename(INPUT_FILE)} (${fileBytes.byteLength} bytes)`);
  console.log('Note:         Prior file-type detection is not required.\n');

  // 1. Upload sample.docx and start conversion job (0.002 USDC)
  const convertUrl = `${API_BASE_URL}/api/x402/v1/convert-file`;
  console.log(`[1/4] Uploading ${path.basename(INPUT_FILE)} -> ${TARGET_FORMAT.toUpperCase()} (${convertUrl})...`);

  const buildMultipartInit = () => {
    const form = new FormData();
    form.append(
      'file',
      new Blob([fileBytes], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      }),
      path.basename(INPUT_FILE)
    );
    form.append('target_format', TARGET_FORMAT);
    form.append('filename', path.basename(INPUT_FILE));
    return { method: 'POST', body: form };
  };

  const startRes = await fetchWithX402(account, convertUrl, buildMultipartInit);
  if (!startRes.ok) {
    throw new Error(`Upload failed (${startRes.status}): ${await startRes.text()}`);
  }

  const jobInfo = await startRes.json();
  const { job_id: jobId, status_url: statusUrl } = jobInfo;
  console.log(`  -> Job created: ${jobId}`);

  // 2. Poll job status for free until "done" or "failed" (0 USDC)
  console.log(`\n[2/4] Polling status for free (${statusUrl})...`);
  let resultUrl = '';
  while (!resultUrl) {
    const statusRes = await fetch(statusUrl, { headers: { Accept: 'application/json' } });
    if (!statusRes.ok) {
      throw new Error(`Status check failed (${statusRes.status}): ${await statusRes.text()}`);
    }
    const statusData = await statusRes.json();
    console.log(`  -> status: ${statusData.status}`);

    if (statusData.status === 'done') {
      resultUrl = statusData.result_url;
      const price = statusData.price_for_result || {};
      console.log(
        `  -> Conversion finished! Result price: ${price.amount || '0.020000'} ${price.currency || 'USDC'}`
      );
      break;
    }
    if (statusData.status === 'failed') {
      throw new Error(`Conversion failed (0 USDC charged for result): ${JSON.stringify(statusData)}`);
    }

    await new Promise((r) => setTimeout(r, (statusData.retry_after_seconds || 2) * 1000));
  }

  // 3. Pay for the finished conversion result (0.02 USDC for <= 10 MB)
  console.log(`\n[3/4] Purchasing conversion result (${resultUrl})...`);
  const resultRes = await fetchWithX402(account, resultUrl, () => ({ method: 'GET' }));
  if (!resultRes.ok) {
    throw new Error(`Result purchase failed (${resultRes.status}): ${await resultRes.text()}`);
  }

  const resultData = await resultRes.json();
  const downloadUrl = resultData.download_url;
  console.log(`  -> Payment settled (tx: ${resultData.payment?.transaction_id || '-'})`);
  console.log(`  -> Download URL: ${downloadUrl}`);

  // 4. Download the converted PDF and optionally delete server files
  console.log(`\n[4/4] Downloading converted file to ${path.basename(OUTPUT_FILE)}...`);
  const dlRes = await fetch(downloadUrl);
  if (!dlRes.ok) {
    throw new Error(`Download failed (${dlRes.status})`);
  }
  const pdfBuffer = Buffer.from(await dlRes.arrayBuffer());
  await fs.writeFile(OUTPUT_FILE, pdfBuffer);
  console.log(`  -> Saved ${OUTPUT_FILE} (${pdfBuffer.byteLength} bytes)`);

  // Optional: immediately delete conversion files from server storage (free)
  await fetch(`${API_BASE_URL}/api/x402/v1/convert-file/${jobId}/delete`, { method: 'DELETE' });
  console.log('  -> Cleaned up temporary job files on server.');
}

main().catch((err) => {
  console.error('\nError:', err.message || err);
  process.exit(1);
});
