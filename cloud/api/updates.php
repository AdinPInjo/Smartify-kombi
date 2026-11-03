<?php
// Settings → Updates on the remote dashboard: the same idea as on the van.
//
// Every release carries versions.json (all versions with their changelog). The
// owner chooses: off, tell me (shown in Settings, and the van's notification
// mentions it), or automatic (at night, if the hosting can finish a request in
// the background). Installing downloads smartify-cloud.zip of that version,
// checks it against the release's SHA256SUMS, keeps a copy of the current files
// in private/backups/, unpacks the new files and checks that the API still
// answers. If it doesn't, the copy is put back. private/ (settings, SQLite) is
// never touched, and the database is updated automatically on the next request.

declare(strict_types=1);

const UPDATE_REPO = 'AdinPInjo/Smartify-kombi';
const UPDATE_MIN_VERSION = '0.4.0'; // first version with this updater
const UPDATE_CHECK_SECONDS = 6 * 3600;
const UPDATE_AUTO_HOURS = [3, 5];
const UPDATE_KEEP_BACKUPS = 3;
const CLOUD_ROOT = __DIR__ . '/..';

function release_base(): string
{
    // Overridable in private/config.php for testing: 'release_base' => 'http://…/releases'
    return rtrim((string)(config()['release_base'] ?? 'https://github.com/' . UPDATE_REPO . '/releases'), '/');
}

function version_key(?string $version): array
{
    if ($version === null || !preg_match('/^\d+\.\d+\.\d+$/', $version)) return [0];
    return array_map('intval', explode('.', $version));
}

function version_newer(?string $a, ?string $b): bool
{
    return version_key($a) > version_key($b);
}

/** GET a URL. Returns [status, body]; status 0 when there was no answer. */
function http_get(string $url, int $timeout = 20): array
{
    if (str_starts_with($url, 'file://')) { // tests
        $body = @file_get_contents($url);
        return $body === false ? [404, ''] : [200, $body];
    }
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => true, CURLOPT_MAXREDIRS => 5,
            CURLOPT_TIMEOUT => $timeout, CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_USERAGENT => 'smartify-cloud/' . SMARTIFY_CLOUD_VERSION,
        ]);
        $body = curl_exec($ch);
        $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        return [$body === false ? 0 : $status, $body === false ? '' : (string)$body];
    }
    $context = stream_context_create(['http' => [
        'timeout' => $timeout, 'ignore_errors' => true, 'follow_location' => 1,
        'user_agent' => 'smartify-cloud/' . SMARTIFY_CLOUD_VERSION,
    ]]);
    $stream = @fopen($url, 'rb', false, $context);
    if ($stream === false) return [0, ''];
    $body = (string)stream_get_contents($stream);
    $headers = stream_get_meta_data($stream)['wrapper_data'] ?? [];
    fclose($stream);
    $status = 0;
    foreach ((array)$headers as $line) {
        if (preg_match('#^HTTP/\S+\s+(\d{3})#', (string)$line, $m)) $status = (int)$m[1]; // last one counts
    }
    return [$status, $body];
}

function update_mode(): string
{
    $mode = meta('update_mode', 'notify');
    return in_array($mode, ['off', 'notify', 'auto'], true) ? $mode : 'notify';
}

/** Installable versions (0.4.0 and newer), newest first. */
function update_versions(): array
{
    $data = json_decode(meta('update_versions', '') ?? '', true);
    $found = [];
    foreach (is_array($data['versions'] ?? null) ? $data['versions'] : [] as $entry) {
        $version = (string)($entry['version'] ?? '');
        if (!preg_match('/^\d+\.\d+\.\d+$/', $version) || version_key($version) < version_key(UPDATE_MIN_VERSION)) continue;
        $found[$version] = [
            'version' => $version,
            'date' => is_string($entry['date'] ?? null) ? $entry['date'] : null,
            'notes' => substr((string)($entry['notes'] ?? ''), 0, 20000),
        ];
    }
    uasort($found, fn($a, $b) => version_key($b['version']) <=> version_key($a['version']));
    return array_values($found);
}

function update_latest(): ?string
{
    return update_versions()[0]['version'] ?? null;
}

function update_check(bool $force = false): void
{
    if (!$force && update_mode() === 'off') return;
    if (!$force && (int)meta('update_checked_at', '0') > time() - UPDATE_CHECK_SECONDS) return;
    set_meta('update_checked_at', (string)time());
    [$status, $body] = http_get(release_base() . '/latest/download/versions.json', 15);
    $data = $status === 200 ? json_decode($body, true) : null;
    if (is_array($data) && is_array($data['versions'] ?? null)) {
        set_meta('update_versions', $body);
        set_meta('update_check_error', '');
    } else {
        set_meta('update_check_error', match (true) {
            $status === 0 => 'no connection to GitHub from this hosting',
            $status === 404 => 'no release with update information yet',
            $status === 200 => 'the update information is not valid',
            default => "GitHub answered HTTP $status",
        });
    }
}

/** Can this hosting update itself? Returns null when it can, or the reason it can't. */
function update_blocker(): ?string
{
    if (!class_exists('ZipArchive')) return 'The PHP zip extension is missing on this hosting (enable it in the hosting panel).';
    if (!function_exists('curl_init') && !filter_var(ini_get('allow_url_fopen'), FILTER_VALIDATE_BOOLEAN)) {
        return 'This hosting can\'t download files (no cURL, allow_url_fopen off). Update by uploading installer.php.';
    }
    foreach ([CLOUD_ROOT, CLOUD_ROOT . '/api', CLOUD_ROOT . '/assets', PRIVATE_DIR] as $dir) {
        if (is_dir($dir) && !is_writable($dir)) return 'The files are not writable by PHP here. Update by uploading installer.php.';
    }
    return null;
}

function update_status(): ?array
{
    $status = json_decode(meta('update_status', '') ?? '', true);
    if (!is_array($status)) return null;
    if (($status['state'] ?? '') === 'running' && time() - (int)($status['started_at'] ?? 0) > 600) {
        $status['state'] = 'failed';
        $status['message'] = 'The update stopped without finishing (the hosting may have a short time limit). Update by uploading installer.php.';
    }
    return $status;
}

function update_view(): array
{
    $latest = update_latest();
    $blocker = update_blocker();
    $error = meta('update_check_error', '');
    return [
        'current' => SMARTIFY_CLOUD_VERSION,
        'mode' => update_mode(),
        'checked_at' => ((int)meta('update_checked_at', '0')) ?: null,
        'check_error' => $error === '' ? null : $error,
        'latest' => $latest,
        'update_available' => version_newer($latest, SMARTIFY_CLOUD_VERSION),
        'versions' => update_versions(),
        'can_install' => $blocker === null,
        'reason' => $blocker,
        'status' => update_status(),
        'history' => array_slice(json_decode(meta('update_history', '[]') ?? '[]', true) ?: [], 0, 10),
        'remote' => null,
        'auto_hours' => UPDATE_AUTO_HOURS,
        'background' => background_capable(),
    ];
}

function background_capable(): bool
{
    return function_exists('fastcgi_finish_request') || function_exists('litespeed_finish_request');
}

function update_finish(array $status, string $state, string $message): array
{
    $status = array_merge($status, ['state' => $state, 'message' => $message, 'finished_at' => time(), 'step' => null]);
    set_meta('update_status', json_encode($status));
    $history = json_decode(meta('update_history', '[]') ?? '[]', true) ?: [];
    array_unshift($history, array_intersect_key($status, array_flip(['state', 'from', 'target', 'by', 'message', 'started_at', 'finished_at'])));
    set_meta('update_history', json_encode(array_slice($history, 0, 20)));
    return $status;
}

/** Install a version (newer or older). Returns the final status. */
function update_install(string $version, string $by = 'dashboard'): array
{
    if (($blocker = update_blocker()) !== null) throw new HttpError(409, $blocker);
    if ($version === SMARTIFY_CLOUD_VERSION) throw new HttpError(422, "version $version is already installed");
    if (!in_array($version, array_column(update_versions(), 'version'), true)) {
        throw new HttpError(422, "version $version is not available (check for updates first)");
    }
    $current = update_status();
    if (($current['state'] ?? '') === 'running') throw new HttpError(409, 'an update is already running');

    @set_time_limit(300);
    ignore_user_abort(true); // closing the browser must not stop it halfway
    $status = ['state' => 'running', 'target' => $version, 'from' => SMARTIFY_CLOUD_VERSION, 'by' => $by,
               'step' => 'Downloading', 'message' => null, 'started_at' => time(), 'finished_at' => null];
    set_meta('update_status', json_encode($status));

    $work = PRIVATE_DIR . '/update-' . bin2hex(random_bytes(4));
    @mkdir($work, 0700);
    try {
        // 1. Download and check, before anything changes.
        $base = release_base() . "/download/v$version";
        [$s1, $sums] = http_get("$base/SHA256SUMS", 30);
        [$s2, $zipData] = http_get("$base/smartify-cloud.zip", 120);
        if ($s1 !== 200 || $s2 !== 200) {
            return update_finish($status, 'failed', "Not updated: the download of $version failed. Nothing was changed.");
        }
        $expected = null;
        foreach (explode("\n", $sums) as $line) {
            if (preg_match('/^([0-9a-f]{64})\s+\*?smartify-cloud\.zip$/', trim($line), $m)) $expected = $m[1];
        }
        if ($expected === null || !hash_equals($expected, hash('sha256', $zipData))) {
            return update_finish($status, 'failed', 'Not updated: the download does not match its checksum. Nothing was changed.');
        }
        $zipFile = "$work/new.zip";
        file_put_contents($zipFile, $zipData);
        unset($zipData);
        $zip = new ZipArchive();
        if ($zip->open($zipFile) !== true || $zip->locateName('smartify-cloud/api/lib.php') === false) {
            return update_finish($status, 'failed', 'Not updated: the download is not a remote dashboard package. Nothing was changed.');
        }
        $lib = (string)$zip->getFromName('smartify-cloud/api/lib.php');
        if (!str_contains($lib, "SMARTIFY_CLOUD_VERSION = '$version'")) {
            $zip->close();
            return update_finish($status, 'failed', "Not updated: the package is not version $version. Nothing was changed.");
        }

        // 2. Keep a copy of the current files.
        $status['step'] = 'Backing up the current version';
        set_meta('update_status', json_encode($status));
        $backup = backup_files(SMARTIFY_CLOUD_VERSION, $zip, 'smartify-cloud/');

        // 3. Unpack, then 4. check that the new version answers.
        $status['step'] = "Installing $version";
        set_meta('update_status', json_encode($status));
        unpack_files($zip, 'smartify-cloud/', true);
        $zip->close();
        if (function_exists('opcache_reset')) @opcache_reset();

        $status['step'] = 'Checking that everything runs';
        set_meta('update_status', json_encode($status));
        [$code, $body] = http_get(base_url() . '/api/health', 20);
        $health = json_decode($body, true);
        if ($code === 0) {
            return update_finish($status, 'done', "Updated from {$status['from']} to $version (this hosting can't check its own address, so open the dashboard once to make sure it works).");
        }
        if ($code !== 200 || ($health['version'] ?? null) !== $version) {
            $restore = new ZipArchive();
            if ($restore->open($backup) === true) {
                unpack_files($restore, '', false);
                $restore->close();
            }
            if (function_exists('opcache_reset')) @opcache_reset();
            $why = $code === 200 ? 'it did not answer properly' : "it answered with HTTP $code";
            return update_finish($status, 'rolled_back', "Version $version did not work on this hosting ($why), so the remote dashboard went back to {$status['from']}. Your data was not touched.");
        }
        return update_finish($status, 'done', "Updated from {$status['from']} to $version.");
    } catch (Throwable $e) {
        error_log('smartify cloud update: ' . $e);
        return update_finish($status, 'failed', 'The update failed: ' . $e->getMessage() . '. If the dashboard misbehaves, upload installer.php to repair it.');
    } finally {
        foreach (glob("$work/*") ?: [] as $file) @unlink($file);
        @rmdir($work);
    }
}

/**
 * The remote dashboard's own files (what the new package replaces, plus api/ and the
 * built assets) to private/backups/cloud-<version>-<time>.zip. Only these: the folder
 * may also hold other files of the website.
 */
function backup_files(string $version, ZipArchive $package, string $prefix): string
{
    $folder = PRIVATE_DIR . '/backups';
    if (!is_dir($folder) && !mkdir($folder, 0700, true)) throw new RuntimeException('cannot create private/backups');
    $target = "$folder/cloud-$version-" . date('Ymd-His') . '.zip';
    $zip = new ZipArchive();
    if ($zip->open($target, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) throw new RuntimeException('cannot write the backup');
    $names = [];
    for ($i = 0; $i < $package->numFiles; $i++) {
        $name = (string)$package->getNameIndex($i);
        if (str_starts_with($name, $prefix)) $names[] = substr($name, strlen($prefix));
    }
    foreach (['api/*', 'assets/*'] as $pattern) {
        foreach (glob(CLOUD_ROOT . "/$pattern") ?: [] as $file) $names[] = substr($pattern, 0, -1) . basename($file);
    }
    foreach (array_unique($names) as $relative) {
        if ($relative === '' || str_starts_with($relative, 'private/') || $relative === 'installer.php') continue;
        $path = CLOUD_ROOT . "/$relative";
        if (is_file($path)) $zip->addFile($path, $relative);
    }
    $zip->close();
    $backups = glob("$folder/cloud-*.zip") ?: [];
    usort($backups, fn($a, $b) => filemtime($a) <=> filemtime($b));
    foreach (array_slice($backups, 0, max(0, count($backups) - UPDATE_KEEP_BACKUPS)) as $old) @unlink($old);
    return $target;
}

/** Write the files of a zip below $prefix into the remote dashboard folder (never private/). */
function unpack_files(ZipArchive $zip, string $prefix, bool $cleanAssets): void
{
    $root = CLOUD_ROOT;
    $written = [];
    for ($i = 0; $i < $zip->numFiles; $i++) {
        $name = (string)$zip->getNameIndex($i);
        if ($prefix !== '' && !str_starts_with($name, $prefix)) continue;
        $relative = substr($name, strlen($prefix));
        if ($relative === '' || str_ends_with($relative, '/') || str_contains($relative, '..') || str_starts_with($relative, '/') || str_contains($relative, '\\')) continue;
        if (str_starts_with($relative, 'private/') || $relative === 'installer.php') continue;
        $path = "$root/$relative";
        if (!is_dir(dirname($path)) && !mkdir(dirname($path), 0755, true)) throw new RuntimeException("cannot create " . dirname($relative));
        $data = $zip->getFromIndex($i);
        // Write next to the file and rename: a visitor never gets half a file.
        if ($data === false || file_put_contents("$path.part", $data, LOCK_EX) === false || !rename("$path.part", $path)) {
            @unlink("$path.part");
            throw new RuntimeException("cannot write $relative");
        }
        $written[$relative] = true;
    }
    if ($cleanAssets) { // old build files (their names change every version)
        foreach (glob("$root/assets/*") ?: [] as $file) {
            $name = basename($file);
            // Only build files (name-hash.ext) the new version doesn't have.
            if (is_file($file) && !isset($written["assets/$name"]) && preg_match('/-[A-Za-z0-9_-]{8}\.[a-z0-9]+$/', $name)) @unlink($file);
        }
    }
}

/** After the van's sync: check now and then, and install at night in automatic mode. */
function update_after_sync(): void
{
    $mode = update_mode();
    if ($mode === 'off') return;
    $checkDue = (int)meta('update_checked_at', '0') <= time() - UPDATE_CHECK_SECONDS;
    $hour = (int)date('G');
    $autoDue = $mode === 'auto' && $hour >= UPDATE_AUTO_HOURS[0] && $hour < UPDATE_AUTO_HOURS[1];
    if (!$checkDue && !$autoDue) return;
    // Answer the van first, then do the slow part (if the hosting allows it).
    if (function_exists('fastcgi_finish_request')) fastcgi_finish_request();
    elseif (function_exists('litespeed_finish_request')) litespeed_finish_request();
    elseif ($autoDue && !$checkDue) return;
    update_check();
    $latest = update_latest();
    if ($autoDue && background_capable() && version_newer($latest, SMARTIFY_CLOUD_VERSION)
        && meta('update_auto_version', '') !== $latest && update_blocker() === null) {
        set_meta('update_auto_version', (string)$latest); // one try per version
        try {
            update_install((string)$latest, 'automatic');
        } catch (Throwable $e) {
            error_log('smartify cloud automatic update: ' . $e->getMessage());
        }
    }
}
