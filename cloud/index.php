<?php
// Serves the dashboard. Like WordPress: before the installation is done,
// every visit goes to the installer.

declare(strict_types=1);

require __DIR__ . '/api/lib.php';

if (!is_file(CONFIG_FILE)) {
    header('Location: ' . base_path() . 'install.php', true, 302);
    exit;
}

$html = @file_get_contents(__DIR__ . '/index.html');
if ($html === false) {
    http_response_code(500);
    echo 'The dashboard files are missing: upload the whole smartify-cloud folder again.';
    exit;
}
// The dashboard can live in any folder: tell it where (assets, API and links are relative to this).
$base = htmlspecialchars(base_path(), ENT_QUOTES);
$html = str_replace('<base href="/" />', '<base href="' . $base . '" />', $html);
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: strict-origin-when-cross-origin'); // map tiles need a Referer
echo $html;
