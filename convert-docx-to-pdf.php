<?php
/**
 * Convert.Guru x402 API — Complete Working Example (PHP 8.1+): DOCX -> PDF
 * ========================================================================
 *
 * Demonstrates the complete asynchronous file conversion workflow using
 * standard PHP cURL + EIP-3009 USDC (`TransferWithAuthorization`) signing:
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
 *   composer require kornrunner/keccak simplito/elliptic-php
 *   export PRIVATE_KEY="0xYOUR_EVM_PRIVATE_KEY"
 *   php convert-docx-to-pdf.php
 */

declare(strict_types=1);

if (file_exists(__DIR__ . '/vendor/autoload.php')) {
    require_once __DIR__ . '/vendor/autoload.php';
}

use Elliptic\EC;
use kornrunner\Keccak;

$apiBaseUrl     = rtrim(getenv('API_URL') ?: 'https://convert.guru', '/');
$paymentNetwork = getenv('PAYMENT_NETWORK') ?: 'eip155:8453'; // Default: Base Mainnet
$inputFile      = __DIR__ . '/sample.docx';
$outputFile     = __DIR__ . '/sample.pdf';
$targetFormat   = 'pdf';

if (!file_exists($inputFile)) {
    fwrite(STDERR, "Error: Sample input file not found at {$inputFile}\n");
    exit(1);
}

if (!class_exists(Keccak::class) || !class_exists(EC::class)) {
    fwrite(STDERR, "Missing crypto dependencies. Run:\n  composer require kornrunner/keccak simplito/elliptic-php\n");
    exit(1);
}

/**
 * Derive EVM address from a 32-byte hex private key.
 */
function privateKeyToAddress(string $privateKeyHex): string
{
    $ec = new EC('secp256k1');
    $key = $ec->keyFromPrivate(ltrim($privateKeyHex, '0x'), 'hex');
    $pubHex = substr($key->getPublic(false, 'hex'), 2); // Strip 0x04 prefix
    $hash = Keccak::hash(hex2bin($pubHex), 256);
    return '0x' . substr($hash, -40);
}

/**
 * ABI-encode a 32-byte uint256 word from an integer or decimal string.
 */
function encodeUint256(string|int $value): string
{
    $hex = gmp_strval(gmp_init((string)$value, 10), 16);
    return hex2bin(str_pad($hex, 64, '0', STR_PAD_LEFT));
}

/**
 * ABI-encode an EVM address to a 32-byte word.
 */
function encodeAddress(string $address): string
{
    $clean = strtolower(ltrim($address, '0x'));
    return hex2bin(str_pad($clean, 64, '0', STR_PAD_LEFT));
}

/**
 * Sign EIP-3009 TransferWithAuthorization and return Base64 `PAYMENT-SIGNATURE` header.
 */
function signX402Payment(
    string $privateKeyHex,
    string $walletAddress,
    string $paymentRequiredB64,
    string $requestUrl,
    string $preferredNetwork
): string {
    $requirements = json_decode((string)base64_decode($paymentRequiredB64), true, 512, JSON_THROW_ON_ERROR);
    $accepts = $requirements['accepts'] ?? [];

    $accept = null;
    foreach ($accepts as $option) {
        if (($option['network'] ?? '') === $preferredNetwork) {
            $accept = $option;
            break;
        }
    }
    if (!$accept) {
        foreach ($accepts as $option) {
            if (str_starts_with((string)($option['network'] ?? ''), 'eip155:')) {
                $accept = $option;
                break;
            }
        }
    }
    if (!$accept) {
        throw new RuntimeException('No compatible EVM payment option found in 402 challenge.');
    }

    $network    = (string)$accept['network'];
    $chainId    = (int)explode(':', $network)[1];
    $amount     = (string)$accept['amount'];
    $asset      = (string)$accept['asset'];
    $payTo      = (string)$accept['payTo'];
    $maxTimeout = (int)($accept['maxTimeoutSeconds'] ?? 300);
    $extra      = $accept['extra'] ?? ['name' => 'USD Coin', 'version' => '2'];

    $now         = time();
    $validAfter  = max(0, $now - 60);
    $validBefore = $now + $maxTimeout;
    $nonceBytes  = random_bytes(32);
    $nonceHex    = '0x' . bin2hex($nonceBytes);

    // EIP-712 Domain Separator
    $domainTypeHash = hex2bin(Keccak::hash(
        'EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)',
        256
    ));
    $nameHash    = hex2bin(Keccak::hash((string)($extra['name'] ?? 'USD Coin'), 256));
    $versionHash = hex2bin(Keccak::hash((string)($extra['version'] ?? '2'), 256));
    $domainSeparator = hex2bin(Keccak::hash(
        $domainTypeHash . $nameHash . $versionHash . encodeUint256($chainId) . encodeAddress($asset),
        256
    ));

    // EIP-3009 TransferWithAuthorization Struct Hash
    $transferTypeHash = hex2bin(Keccak::hash(
        'TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)',
        256
    ));
    $structHash = hex2bin(Keccak::hash(
        $transferTypeHash
        . encodeAddress($walletAddress)
        . encodeAddress($payTo)
        . encodeUint256($amount)
        . encodeUint256($validAfter)
        . encodeUint256($validBefore)
        . $nonceBytes,
        256
    ));

    // EIP-712 Digest: keccak256("\x19\x01" || domainSeparator || structHash)
    $digestHex = Keccak::hash("\x19\x01" . $domainSeparator . $structHash, 256);

    $ec  = new EC('secp256k1');
    $key = $ec->keyFromPrivate(ltrim($privateKeyHex, '0x'), 'hex');
    $sig = $key->sign($digestHex, ['canonical' => true]);

    $r = str_pad($sig->r->toString(16), 64, '0', STR_PAD_LEFT);
    $s = str_pad($sig->s->toString(16), 64, '0', STR_PAD_LEFT);
    $v = dechex((int)$sig->recoveryParam + 27);
    $signature = '0x' . $r . $s . str_pad($v, 2, '0', STR_PAD_LEFT);

    $resourceUrl = $requirements['resource']['url'] ?? $requestUrl;
    $description = $requirements['resource']['description']
        ?? $accept['description']
        ?? 'Convert.Guru x402 API request';

    $payload = [
        'x402Version' => 2,
        'accepted' => [
            'scheme'            => 'exact',
            'network'           => $network,
            'asset'             => $asset,
            'amount'            => $amount,
            'payTo'             => $payTo,
            'maxTimeoutSeconds' => $maxTimeout,
            'extra'             => $extra,
        ],
        'payload' => [
            'signature' => $signature,
            'authorization' => [
                'from'        => $walletAddress,
                'to'          => $payTo,
                'value'       => $amount,
                'validAfter'  => (string)$validAfter,
                'validBefore' => (string)$validBefore,
                'nonce'       => $nonceHex,
            ],
        ],
        'resource' => [
            'url'         => $resourceUrl,
            'description' => $description,
            'mimeType'    => 'application/json',
        ],
    ];

    $usdc = number_format(((int)$amount) / 1_000_000, 6);
    echo "  -> Signing x402 payment: {$usdc} USDC on {$network} to {$payTo}\n";

    return base64_encode((string)json_encode($payload, JSON_UNESCAPED_SLASHES));
}

/**
 * Execute an HTTP request via cURL and automatically handle HTTP 402 x402 payment challenges.
 */
function requestWithX402(
    string $method,
    string $url,
    string $privateKeyHex,
    string $walletAddress,
    string $preferredNetwork,
    ?array $postFields = null
): array {
    $execute = static function (array $extraHeaders = []) use ($method, $url, $postFields): array {
        $respHeaders = [];
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST  => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 60,
            CURLOPT_HTTPHEADER     => $extraHeaders,
            CURLOPT_HEADERFUNCTION => static function ($ch, string $headerLine) use (&$respHeaders): int {
                $parts = explode(':', $headerLine, 2);
                if (count($parts) === 2) {
                    $respHeaders[strtolower(trim($parts[0]))] = trim($parts[1]);
                }
                return strlen($headerLine);
            },
        ]);
        if ($postFields !== null) {
            curl_setopt($ch, CURLOPT_POSTFIELDS, $postFields);
        }
        $body   = (string)curl_exec($ch);
        $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        return ['status' => $status, 'headers' => $respHeaders, 'body' => $body];
    };

    $res = $execute();
    if ($res['status'] === 402) {
        $paymentReqB64 = $res['headers']['payment-required'] ?? '';
        if ($paymentReqB64 === '') {
            throw new RuntimeException('Received HTTP 402 without PAYMENT-REQUIRED header.');
        }
        $paymentSig = signX402Payment($privateKeyHex, $walletAddress, $paymentReqB64, $url, $preferredNetwork);
        $res = $execute(["PAYMENT-SIGNATURE: {$paymentSig}"]);
    }

    return $res;
}

// Wallet initialization
$privateKey = trim((string)getenv('PRIVATE_KEY'));
if ($privateKey === '') {
    $privateKey = '0x' . bin2hex(random_bytes(32));
    echo "WARNING: PRIVATE_KEY not set. Using a temporary unfunded wallet.\n";
    echo "         Signature creation will work, but on-chain USDC settlement will fail.\n\n";
}
$walletAddress = privateKeyToAddress($privateKey);

echo "Using wallet: {$walletAddress}\n";
echo 'Input file:   ' . basename($inputFile) . ' (' . filesize($inputFile) . " bytes)\n";
echo "Note:         Prior file-type detection is not required.\n\n";

// 1. Upload sample.docx and start conversion job (0.002 USDC)
$convertUrl = "{$apiBaseUrl}/api/x402/v1/convert-file";
echo "[1/4] Uploading " . basename($inputFile) . " -> " . strtoupper($targetFormat) . " ({$convertUrl})...\n";

$postFields = [
    'file'          => new CURLFile($inputFile, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', basename($inputFile)),
    'target_format' => $targetFormat,
    'filename'      => basename($inputFile),
];

$startRes = requestWithX402('POST', $convertUrl, $privateKey, $walletAddress, $paymentNetwork, $postFields);
if ($startRes['status'] < 200 || $startRes['status'] >= 300) {
    fwrite(STDERR, "Upload failed ({$startRes['status']}): {$startRes['body']}\n");
    exit(1);
}

$jobInfo   = json_decode($startRes['body'], true, 512, JSON_THROW_ON_ERROR);
$jobId     = $jobInfo['job_id'];
$statusUrl = $jobInfo['status_url'];
echo "  -> Job created: {$jobId}\n\n";

// 2. Poll job status for free until "done" or "failed" (0 USDC)
echo "[2/4] Polling status for free ({$statusUrl})...\n";
$resultUrl = '';
while (true) {
    $statusJson = (string)file_get_contents($statusUrl);
    $statusData = json_decode($statusJson, true, 512, JSON_THROW_ON_ERROR);
    $status     = $statusData['status'] ?? 'unknown';
    echo "  -> status: {$status}\n";

    if ($status === 'done') {
        $resultUrl = $statusData['result_url'];
        $amount    = $statusData['price_for_result']['amount'] ?? '0.020000';
        echo "  -> Conversion finished! Result price: {$amount} USDC\n\n";
        break;
    }
    if ($status === 'failed') {
        fwrite(STDERR, "Conversion failed (0 USDC charged for result): {$statusJson}\n");
        exit(1);
    }
    sleep((int)($statusData['retry_after_seconds'] ?? 2));
}

// 3. Pay for the finished conversion result (0.02 USDC for <= 10 MB)
echo "[3/4] Purchasing conversion result ({$resultUrl})...\n";
$resultRes = requestWithX402('GET', $resultUrl, $privateKey, $walletAddress, $paymentNetwork);
if ($resultRes['status'] < 200 || $resultRes['status'] >= 300) {
    fwrite(STDERR, "Result purchase failed ({$resultRes['status']}): {$resultRes['body']}\n");
    exit(1);
}

$resultData  = json_decode($resultRes['body'], true, 512, JSON_THROW_ON_ERROR);
$downloadUrl = $resultData['download_url'];
$txId        = $resultData['payment']['transaction_id'] ?? '-';
echo "  -> Payment settled (tx: {$txId})\n";
echo "  -> Download URL: {$downloadUrl}\n\n";

// 4. Download the converted PDF and optionally delete server files
echo '[4/4] Downloading converted file to ' . basename($outputFile) . "...\n";
$pdfBytes = file_get_contents($downloadUrl);
file_put_contents($outputFile, $pdfBytes);
echo "  -> Saved {$outputFile} (" . strlen((string)$pdfBytes) . " bytes)\n";

// Optional: immediately delete conversion files from server storage (free)
$ch = curl_init("{$apiBaseUrl}/api/x402/v1/convert-file/{$jobId}/delete");
curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => 'DELETE', CURLOPT_RETURNTRANSFER => true]);
curl_exec($ch);
curl_close($ch);
echo "  -> Cleaned up temporary job files on server.\n";
