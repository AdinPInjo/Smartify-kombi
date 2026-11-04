<?php
// Smartify Kombi remote dashboard: one-file installer and updater.
//
// Upload only this file to an empty folder of your website and open it in the
// browser. It downloads the latest release from GitHub, unpacks it here and
// starts the setup. Later, open it again to update: your settings and data
// (the private/ folder) are kept, and updating needs your dashboard password.

declare(strict_types=1);

const RELEASE_ZIP = 'https://github.com/AdinPInjo/Smartify-kombi/releases/latest/download/smartify-cloud.zip';
const PACKAGE_DIR = 'smartify-cloud/';
// Never overwritten by an update: your settings and an SQLite database.
const KEEP = ['private/config.php', 'private/smartify.sqlite', 'private/smartify.sqlite-wal', 'private/smartify.sqlite-shm'];

function h(?string $s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES);
}

function download(string $url, string $target): void
{
    if (function_exists('curl_init')) {
        $fp = fopen($target, 'wb');
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_FILE => $fp, CURLOPT_FOLLOWLOCATION => true, CURLOPT_MAXREDIRS => 5,
            CURLOPT_TIMEOUT => 120, CURLOPT_USERAGENT => 'smartify-installer', CURLOPT_FAILONERROR => true,
        ]);
        $ok = curl_exec($ch);
        $error = curl_error($ch);
        $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        fclose($fp);
        if (!$ok) {
            throw new RuntimeException($status === 404
                ? 'No release found on GitHub. Is the repository public, and has a version been released?'
                : "Download failed: $error");
        }
        return;
    }
    if (!filter_var(ini_get('allow_url_fopen'), FILTER_VALIDATE_BOOLEAN)) {
        throw new RuntimeException('This hosting can\'t download files (no cURL, allow_url_fopen off). Upload smartify-cloud.zip by hand instead.');
    }
    $context = stream_context_create(['http' => ['timeout' => 120, 'user_agent' => 'smartify-installer']]);
    if (@copy($url, $target, $context) === false) {
        throw new RuntimeException('Download failed. Is the repository public, and has a version been released?');
    }
}

/** Unpack the package into this folder. Returns the number of files written. */
function unpack_package(string $zipFile, string $dest, bool $update): int
{
    $zip = new ZipArchive();
    if ($zip->open($zipFile) !== true) {
        throw new RuntimeException('The download is not a valid zip file. Try again in a minute.');
    }
    if ($zip->locateName(PACKAGE_DIR . 'install.php') === false) {
        $zip->close();
        throw new RuntimeException('This zip is not a Smartify remote dashboard package.');
    }
    $written = 0;
    for ($i = 0; $i < $zip->numFiles; $i++) {
        $name = (string)$zip->getNameIndex($i);
        if (!str_starts_with($name, PACKAGE_DIR)) continue;
        $relative = substr($name, strlen(PACKAGE_DIR));
        // Refuse anything that could escape this folder.
        if ($relative === '' || str_contains($relative, '..') || str_starts_with($relative, '/') || str_contains($relative, '\\')) continue;
        if ($update && in_array($relative, KEEP, true)) continue;
        $path = $dest . '/' . $relative;
        if (str_ends_with($name, '/')) {
            if (!is_dir($path) && !mkdir($path, 0755, true)) throw new RuntimeException("Cannot create $relative: check folder permissions.");
            continue;
        }
        if (!is_dir(dirname($path)) && !mkdir(dirname($path), 0755, true)) {
            throw new RuntimeException('Cannot create ' . dirname($relative) . ': check folder permissions.');
        }
        $data = $zip->getFromIndex($i);
        if ($data === false || file_put_contents($path, $data, LOCK_EX) === false) {
            throw new RuntimeException("Cannot write $relative: check folder permissions.");
        }
        $written++;
    }
    $zip->close();
    return $written;
}

/**
 * The first browser that opens the installer owns it (for 6 hours, or until the
 * installation is done): someone who finds the address can't finish it first.
 * Returns false when another browser owns it.
 */
function claim_installer(string $privateDir): bool
{
    $lock = $privateDir . '/install-lock.txt';
    if (!is_dir($privateDir)) @mkdir($privateDir, 0755, true);
    $mine = (string)($_SESSION['install_owner'] ?? '');
    $current = @file_get_contents($lock);
    if ($current !== false && time() - (int)@filemtime($lock) >= 6 * 3600) {
        @unlink($lock); // abandoned: start over
        $current = false;
    }
    if ($current === false) {
        $token = bin2hex(random_bytes(16));
        $handle = @fopen($lock, 'x'); // atomic: only one browser can create it
        if ($handle === false) {
            $current = (string)@file_get_contents($lock);
            return $mine !== '' && hash_equals(trim($current), $mine);
        }
        fwrite($handle, $token);
        fclose($handle);
        $_SESSION['install_owner'] = $token;
        return true;
    }
    return $mine !== '' && hash_equals(trim($current), $mine);
}

function locked_out_page(): void
{
    http_response_code(423);
    echo '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
        . '<title>Installation in progress</title><body style="font:16px/1.5 system-ui,sans-serif;background:#11130e;color:#ecebdd;max-width:520px;margin:40px auto;padding:0 16px">'
        . '<h1 style="font-size:26px">Installation in progress</h1>'
        . '<p>The remote dashboard is being installed in another browser. If that was you, continue there.</p>'
        . '<p style="color:#a3a893">To start over from this browser: in your hosting\'s file manager, delete <code>private/install-lock.txt</code> in this folder, then reload this page.</p>';
    exit;
}

$dir = __DIR__;
$installed = is_file("$dir/private/config.php");
if (!$installed) {
    // The same lock (and session) as install.php, which takes over after unpacking.
    $path = rtrim(str_replace('\\', '/', dirname($_SERVER['SCRIPT_NAME'] ?? '/')), '/') . '/';
    $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
    session_name('smartify_install');
    session_set_cookie_params(['path' => $path, 'secure' => $https, 'httponly' => true, 'samesite' => 'Lax']);
    session_start();
    if (!claim_installer("$dir/private")) {
        locked_out_page();
    }
}
$problems = [];
if (version_compare(PHP_VERSION, '8.0.0', '<')) $problems[] = 'PHP 8.0 or newer is needed (this server has ' . PHP_VERSION . '). Choose it in your hosting panel.';
if (!class_exists('ZipArchive')) $problems[] = 'The PHP zip extension is missing. Enable it in your hosting panel, or upload smartify-cloud.zip by hand.';
if (!is_writable($dir)) $problems[] = 'This folder is not writable. Set its permissions to 755 in your file manager.';
if (!function_exists('curl_init') && !filter_var(ini_get('allow_url_fopen'), FILTER_VALIDATE_BOOLEAN)) $problems[] = 'This hosting cannot download files. Upload smartify-cloud.zip by hand instead.';

$error = null;
$done = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !$problems) {
    try {
        if ($installed) {
            // Only the owner may update: check the dashboard password.
            $config = require "$dir/private/config.php";
            $ok = hash_equals((string)$config['admin_user'], (string)($_POST['user'] ?? ''))
                && password_verify((string)($_POST['password'] ?? ''), (string)$config['admin_password_hash']);
            if (!$ok) {
                sleep(1);
                throw new RuntimeException('Wrong username or password.');
            }
        }
        $tmp = tempnam(sys_get_temp_dir(), 'smk');
        if ($tmp === false) $tmp = "$dir/.smartify-download.zip";
        try {
            download(RELEASE_ZIP, $tmp);
            $count = unpack_package($tmp, $dir, $installed);
        } finally {
            @unlink($tmp);
        }
        if (function_exists('opcache_reset')) @opcache_reset();
        if (!$installed) {
            @unlink(__FILE__); // the setup guide takes over; update later with a fresh copy of this file
            header('Location: install.php');
            exit;
        }
        $done = "Updated: $count files replaced. Your settings and data were kept. The database is updated automatically on the next visit.";
    } catch (Throwable $e) {
        $error = $e->getMessage();
    }
}
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title><?= $installed ? 'Update' : 'Install' ?> · Smartify Kombi</title>
<style>
  body { margin: 0; min-height: 100vh; background: radial-gradient(120% 80% at 20% 0%, #20241b, #11130e 60%); color: #ecebdd; font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 520px; margin: 0 auto; padding: 40px 16px; }
  .kicker { font: 600 12px/1 ui-monospace, monospace; letter-spacing: .18em; color: #a3a893; text-transform: uppercase; }
  h1 { font-size: 30px; line-height: 1.1; margin: 8px 0 18px; }
  .card { background: #1a1d16; border: 1px solid #2e3327; border-radius: 18px; padding: 22px; display: grid; gap: 14px; }
  .btn { min-height: 48px; border: 0; border-radius: 12px; background: #f0a43a; color: #1b1407; font: 600 16px system-ui, sans-serif; cursor: pointer; }
  .btn:disabled { opacity: .6; }
  label { display: grid; gap: 6px; color: #a3a893; font-size: 14px; }
  input { min-height: 46px; border-radius: 12px; border: 1px solid #3a4032; background: #11130e; color: #ecebdd; padding: 0 12px; font: inherit; }
  .muted { color: #a3a893; } .small { font-size: 14px; }
  .error { background: rgba(239,90,76,.12); border: 1px solid rgba(239,90,76,.45); padding: 12px 14px; border-radius: 12px; }
  .ok { background: rgba(140,192,122,.12); border: 1px solid rgba(140,192,122,.45); padding: 12px 14px; border-radius: 12px; }
  a { color: #f0a43a; }
</style>
</head>
<body>
<main>
  <div class="kicker">Smartify Kombi</div>
  <h1><?= $installed ? 'Update the remote dashboard' : 'Install the remote dashboard' ?></h1>
  <div class="card">
    <?php if ($problems): ?>
      <div class="error"><strong>This hosting needs a change first:</strong><ul style="margin:8px 0 0;padding-left:20px"><?php foreach ($problems as $p): ?><li><?= h($p) ?></li><?php endforeach; ?></ul></div>
      <a href="">Check again</a>
    <?php elseif ($done): ?>
      <div class="ok"><?= h($done) ?></div>
      <a href="./">Open the remote dashboard</a>
      <p class="small muted" style="margin:0">You can delete this file now, and upload it again for the next update.</p>
    <?php else: ?>
      <?php if ($error): ?><div class="error" role="alert"><?= h($error) ?></div><?php endif; ?>
      <form method="post" style="display:grid;gap:14px" onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='Downloading… (up to a minute)'">
        <?php if ($installed): ?>
          <p class="muted" style="margin:0">Downloads the newest version from GitHub. Your settings, login and data stay as they are.</p>
          <label>Username <input name="user" autocomplete="username" required></label>
          <label>Password <input name="password" type="password" autocomplete="current-password" required></label>
          <button class="btn" type="submit">Update now</button>
        <?php else: ?>
          <p class="muted" style="margin:0">Downloads the newest version from GitHub into this folder (about 1 MB), then guides you through the setup: database, login, and connecting your van.</p>
          <button class="btn" type="submit">Download and install</button>
        <?php endif; ?>
      </form>
    <?php endif; ?>
  </div>
</main>
</body>
</html>
