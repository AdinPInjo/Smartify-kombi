<?php
// For local development only: `php -S localhost:8080 dev-router.php`
// (PHP's built-in server ignores .htaccess, so this does its job).
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if (str_starts_with($path, '/private/')) { http_response_code(403); exit; }
if (str_starts_with($path, '/api/')) { require __DIR__ . '/api/index.php'; return true; }
if ($path === '/install.php') { require __DIR__ . '/install.php'; return true; }
if ($path === '/installer.php') { require __DIR__ . '/installer.php'; return true; }
if ($path !== '/' && $path !== '/index.html' && is_file(__DIR__ . $path)) return false;
if (is_file(__DIR__ . '/index.html')) { $_SERVER['SCRIPT_NAME'] = '/index.php'; require __DIR__ . '/index.php'; return true; }
echo 'Dashboard not built: run scripts/build-cloud.sh';
