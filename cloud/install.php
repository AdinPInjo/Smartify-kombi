<?php
// Smartify Kombi remote dashboard: installer.
//
// Steps: 1. check the server  2. database  3. login  4. connect the van.
// Writes private/config.php. Once installed it refuses to run again (delete
// private/config.php to start over; the data stays in the database).

declare(strict_types=1);

require __DIR__ . '/api/lib.php';

function h(?string $s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES);
}

/** Fetch a URL of this site (to test the API and the private folder). Null: could not check. */
function probe(string $url): ?array
{
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 5, CURLOPT_FOLLOWLOCATION => false]);
        $body = curl_exec($ch);
        $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        return $body === false || $status === 0 ? null : ['status' => $status, 'body' => (string)$body];
    }
    if (filter_var(ini_get('allow_url_fopen'), FILTER_VALIDATE_BOOLEAN)) {
        $context = stream_context_create(['http' => ['timeout' => 5, 'ignore_errors' => true, 'follow_location' => 0]]);
        $fp = @fopen($url, 'r', false, $context);
        if ($fp === false) return null;
        $headers = stream_get_meta_data($fp)['wrapper_data'] ?? [];
        $body = (string)stream_get_contents($fp);
        fclose($fp);
        $status = isset($headers[0]) && preg_match('/\s(\d{3})(\s|$)/', (string)$headers[0], $m) ? (int)$m[1] : 0;
        return ['status' => $status, 'body' => $body];
    }
    return null;
}

/** [label, state ok|warn|fail, explanation] */
function checks(): array
{
    $list = [];
    $phpOk = version_compare(PHP_VERSION, MIN_PHP, '>=');
    $list[] = ['PHP ' . PHP_VERSION, $phpOk ? 'ok' : 'fail', $phpOk ? '' : 'Needs PHP 8.0 or newer: choose it in your hosting panel (PHP version / PHP selector).'];

    $mysql = extension_loaded('pdo_mysql');
    $sqlite = extension_loaded('pdo_sqlite');
    $list[] = ['Database support', $mysql || $sqlite ? 'ok' : 'fail',
        ($mysql ? 'MySQL' : '') . ($mysql && $sqlite ? ' and ' : '') . ($sqlite ? 'SQLite' : '')
        . ($mysql || $sqlite ? ' available.' : 'Enable the PHP extension pdo_mysql in your hosting panel.')];

    $zlib = function_exists('gzdecode') && function_exists('json_decode');
    $list[] = ['PHP extensions (zlib, json)', $zlib ? 'ok' : 'fail', $zlib ? '' : 'Enable the zlib extension in your hosting panel.'];

    $writable = is_dir(PRIVATE_DIR) && is_writable(PRIVATE_DIR);
    $list[] = ['private/ folder writable', $writable ? 'ok' : 'fail', $writable ? '' : 'Set the permissions of the private folder to 755 (or 775) in your file manager.'];

    $https = is_https();
    $list[] = ['HTTPS', $https ? 'ok' : 'warn', $https ? '' : 'Without HTTPS your password and the van\'s data travel unencrypted. Turn on a free Let\'s Encrypt certificate in your hosting panel, then open this page with https://.'];

    $api = probe(base_url() . '/api/health');
    if ($api === null) {
        $list[] = ['Web server rules (.htaccess)', 'warn', 'Could not test from here. If the dashboard shows errors later, your host needs mod_rewrite (Apache/LiteSpeed).'];
    } else {
        $works = $api['status'] === 503 || $api['status'] === 200;
        $list[] = ['Web server rules (.htaccess)', $works ? 'ok' : 'fail', $works ? '' : 'The API is not reachable (HTTP ' . $api['status'] . '). Upload the hidden .htaccess file too, and make sure your host supports it (Apache or LiteSpeed).'];
    }

    @file_put_contents(PRIVATE_DIR . '/probe.txt', 'smartify-probe');
    $private = probe(base_url() . '/private/probe.txt');
    @unlink(PRIVATE_DIR . '/probe.txt');
    if ($private !== null) {
        $exposed = $private['status'] === 200 && str_contains($private['body'], 'smartify-probe');
        $list[] = ['private/ folder protected', $exposed ? 'fail' : 'ok', $exposed ? 'Anyone could download your settings. Upload private/.htaccess too; on nginx hosting ask your host to deny access to /private/.' : ''];
    }
    return $list;
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

function blocking(array $checks): bool
{
    foreach ($checks as [, $state]) {
        if ($state === 'fail') return true;
    }
    return false;
}

session_name('smartify_install');
session_set_cookie_params(['path' => base_path(), 'secure' => is_https(), 'httponly' => true, 'samesite' => 'Lax']);
session_start();

$installed = is_file(CONFIG_FILE);
if (!$installed && !claim_installer(PRIVATE_DIR)) {
    locked_out_page();
}
$step = $_GET['step'] ?? 'check';
$error = null;
$code = $_SESSION['code'] ?? null;

// Right after installing, this browser may still see the "connect" step.
if ($installed && !($step === 'connect' && $code)) {
    $step = 'installed';
}
if (!$installed && $step === 'connect') {
    $step = 'check';
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && !$installed) {
    try {
        if ($step === 'database') {
            $driver = $_POST['driver'] ?? 'mysql';
            if ($driver === 'sqlite') {
                if (!extension_loaded('pdo_sqlite')) throw new RuntimeException('SQLite is not available on this hosting.');
                $db = ['dsn' => 'sqlite:' . realpath(PRIVATE_DIR) . '/smartify.sqlite', 'user' => null, 'password' => null];
            } else {
                $name = trim($_POST['db_name'] ?? '');
                if ($name === '') throw new RuntimeException('Enter the database name from your hosting panel.');
                $db = [
                    'dsn' => sprintf('mysql:host=%s;dbname=%s;charset=utf8mb4', trim($_POST['db_host'] ?? '') ?: 'localhost', $name),
                    'user' => trim($_POST['db_user'] ?? ''),
                    'password' => $_POST['db_password'] ?? '',
                ];
            }
            try {
                new PDO($db['dsn'], $db['user'], $db['password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_TIMEOUT => 5]);
            } catch (PDOException $e) {
                $why = $e->getMessage();
                $hint = str_contains($why, 'Access denied') ? 'The database user or password is wrong, or the user has no access to this database (add it in your hosting panel).'
                    : (str_contains($why, 'Unknown database') ? 'There is no database with that name. Create it first in your hosting panel (MySQL Databases).'
                    : (str_contains($why, 'getaddrinfo') || str_contains($why, 'Connection refused') || str_contains($why, 'No such file') ? 'No database server found at that host. It is usually "localhost" (sometimes "127.0.0.1" or a name shown in your hosting panel).'
                    : $why));
                throw new RuntimeException('Could not connect to the database. ' . $hint);
            }
            $_SESSION['db'] = $db;
            header('Location: install.php?step=account');
            exit;
        }

        if ($step === 'account') {
            $db = $_SESSION['db'] ?? null;
            if (!$db) {
                header('Location: install.php?step=database');
                exit;
            }
            $user = trim($_POST['admin_user'] ?? '');
            $password = $_POST['admin_password'] ?? '';
            if ($user === '' || preg_match('/\s/', $user)) throw new RuntimeException('Choose a username without spaces.');
            if (strlen($password) < 10) throw new RuntimeException('The password needs at least 10 characters: this dashboard is on the internet.');
            if ($password !== ($_POST['admin_password2'] ?? '')) throw new RuntimeException('The two passwords are not the same.');

            $token = bin2hex(random_bytes(24));
            write_config([
                'db_dsn' => $db['dsn'],
                'db_user' => $db['user'],
                'db_password' => $db['password'],
                'admin_user' => $user,
                'admin_password_hash' => password_hash($password, PASSWORD_DEFAULT),
                'device_token_hash' => hash('sha256', $token),
                'instance_id' => bin2hex(random_bytes(8)),
                'command_ttl_seconds' => 900,
                'history_days' => 90,
            ]);
            create_schema(db());
            unset($_SESSION['db']);
            $_SESSION['code'] = connection_code($token);
            @unlink(PRIVATE_DIR . '/install-lock.txt'); // installed: the lock has done its job
            header('Location: install.php?step=connect');
            exit;
        }
    } catch (Throwable $e) {
        $error = $e->getMessage();
    }
}

$checks = $step === 'check' ? checks() : [];
$steps = ['check' => 'Server', 'database' => 'Database', 'account' => 'Login', 'connect' => 'Your van'];
$stepIndex = array_search($step, array_keys($steps), true);
$dbPost = $_POST + ['driver' => extension_loaded('pdo_mysql') ? 'mysql' : 'sqlite', 'db_host' => 'localhost', 'db_name' => '', 'db_user' => ''];
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Install · Smartify Kombi</title>
<link rel="icon" href="logo.svg" type="image/svg+xml">
<style>
  :root { --ground:#11130e; --surface:#1a1d16; --surface-2:#22261d; --line:#2e3327; --line-strong:#3a4032; --text:#ecebdd; --muted:#a3a893; --faint:#6f7562; --accent:#f0a43a; --ok:#8cc07a; --danger:#ef5a4c; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: radial-gradient(120% 80% at 20% 0%, #20241b, var(--ground) 60%); color: var(--text); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 560px; margin: 0 auto; padding: 32px 16px 60px; }
  .brand { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
  .brand img { width: 52px; height: 52px; }
  .kicker { font: 600 12px/1 ui-monospace, monospace; letter-spacing: .18em; color: var(--muted); text-transform: uppercase; }
  h1 { font-size: 30px; line-height: 1.1; margin: 6px 0 0; }
  h2 { font-size: 22px; margin: 0; }
  .steps { display: flex; gap: 6px; margin: 0 0 18px; }
  .steps span { flex: 1; font: 500 12px/1 system-ui; color: var(--faint); padding-top: 8px; border-top: 4px solid var(--line-strong); }
  .steps span.done { color: var(--muted); border-color: var(--accent); }
  .card { background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 22px; display: grid; gap: 16px; }
  label { display: grid; gap: 6px; color: var(--muted); font-size: 14px; }
  input, select { min-height: 46px; border-radius: 12px; border: 1px solid var(--line-strong); background: var(--ground); color: var(--text); padding: 0 12px; font: inherit; width: 100%; }
  input:focus, select:focus { outline: none; border-color: var(--accent); }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 48px; padding: 0 18px; border-radius: 12px; border: 1px solid var(--line-strong); background: var(--surface-2); color: var(--text); font: 600 16px system-ui, sans-serif; cursor: pointer; text-decoration: none; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #1b1407; }
  .btn:disabled { opacity: .5; cursor: default; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .muted { color: var(--muted); } .small { font-size: 14px; } .tiny { font-size: 12.5px; color: var(--faint); }
  .error { background: rgba(239,90,76,.12); border: 1px solid rgba(239,90,76,.45); padding: 12px 14px; border-radius: 12px; }
  .ok-box { background: rgba(140,192,122,.12); border: 1px solid rgba(140,192,122,.45); padding: 12px 14px; border-radius: 12px; }
  .checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
  .checks li { display: grid; grid-template-columns: 24px 1fr; gap: 10px; }
  .checks .ok::before { content: "✓"; color: var(--ok); font-weight: 700; }
  .checks .warn::before { content: "!"; color: var(--accent); font-weight: 700; }
  .checks .fail::before { content: "✗"; color: var(--danger); font-weight: 700; }
  .code { font: 15px/1.4 ui-monospace, monospace; background: var(--ground); border: 1px dashed var(--line-strong); border-radius: 12px; padding: 14px; overflow-wrap: anywhere; user-select: all; }
  details summary { cursor: pointer; color: var(--muted); font-size: 14px; min-height: 32px; }
  .seg { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; background: var(--ground); padding: 4px; border-radius: 12px; }
  .seg label { display: block; cursor: pointer; }
  .seg input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  .seg span { display: block; text-align: center; padding: 10px 8px; border-radius: 9px; color: var(--muted); font-size: 15px; }
  .seg input:checked + span { background: var(--line-strong); color: var(--text); font-weight: 600; }
  .seg input:disabled + span { opacity: .4; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; background: var(--accent); animation: pulse 1.4s infinite; }
  .dot.on { background: var(--ok); animation: none; }
  @keyframes pulse { 50% { opacity: .3; } }
  a { color: var(--accent); }
</style>
</head>
<body>
<main>
  <div class="brand">
    <img src="logo.svg" alt="">
    <div>
      <div class="kicker">Smartify Kombi</div>
      <h1><?= $step === 'installed' ? 'Remote dashboard' : 'Install the remote dashboard' ?></h1>
    </div>
  </div>

<?php if ($step !== 'installed'): ?>
  <div class="steps" aria-label="Progress">
    <?php $i = 0; foreach ($steps as $key => $label): ?>
      <span class="<?= $stepIndex !== false && $i <= $stepIndex ? 'done' : '' ?>"><?= ++$i ?>. <?= h($label) ?></span>
    <?php endforeach; ?>
  </div>
<?php endif; ?>

<?php if ($error): ?><div class="error" role="alert" style="margin-bottom:14px"><?= h($error) ?></div><?php endif; ?>

<?php if ($step === 'check'): ?>
  <div class="card">
    <h2>Checking your hosting</h2>
    <p class="muted" style="margin:0">See your van from anywhere: this puts the dashboard on your own website, and your van connects to it over the internet.</p>
    <ul class="checks">
      <?php foreach ($checks as [$label, $state, $note]): ?>
        <li class="<?= h($state) ?>"><span></span><span><?= h($label) ?><?php if ($note): ?><br><span class="small muted"><?= h($note) ?></span><?php endif; ?></span></li>
      <?php endforeach; ?>
    </ul>
    <?php if (blocking($checks)): ?>
      <p class="small" style="margin:0">Fix the items marked ✗, then <a href="install.php">check again</a>.</p>
    <?php else: ?>
      <a class="btn primary" href="install.php?step=database">Continue</a>
    <?php endif; ?>
  </div>

<?php elseif ($step === 'database'): ?>
  <form class="card" method="post" action="install.php?step=database">
    <h2>Database</h2>
    <p class="muted small" style="margin:0">Where the van's history is kept on your hosting.</p>
    <div class="seg" role="radiogroup" aria-label="Database type">
      <label><input type="radio" name="driver" value="mysql" <?= $dbPost['driver'] === 'mysql' ? 'checked' : '' ?> <?= extension_loaded('pdo_mysql') ? '' : 'disabled' ?> onchange="toggleDb()"><span>MySQL / MariaDB</span></label>
      <label><input type="radio" name="driver" value="sqlite" <?= $dbPost['driver'] === 'sqlite' ? 'checked' : '' ?> <?= extension_loaded('pdo_sqlite') ? '' : 'disabled' ?> onchange="toggleDb()"><span>SQLite (no setup)</span></label>
    </div>
    <div id="mysql" style="display:grid;gap:14px">
      <details>
        <summary>Where do I get these?</summary>
        <ol class="small muted" style="margin:8px 0 0;padding-left:20px;display:grid;gap:4px">
          <li>In your hosting panel (cPanel, Plesk…) open <strong>MySQL Databases</strong>.</li>
          <li>Create a database, e.g. <code>kombi</code>. Many hosts add a prefix: <code>user_kombi</code>.</li>
          <li>Create a user with a password and <strong>add it to the database</strong> with all privileges.</li>
          <li>Enter the full names here. The host is almost always <code>localhost</code>.</li>
        </ol>
      </details>
      <label>Database name <input name="db_name" value="<?= h($dbPost['db_name']) ?>" autocomplete="off" placeholder="user_kombi"></label>
      <label>Database user <input name="db_user" value="<?= h($dbPost['db_user']) ?>" autocomplete="off"></label>
      <label>Database password <input name="db_password" type="password" autocomplete="off"></label>
      <label>Host <input name="db_host" value="<?= h($dbPost['db_host']) ?>"></label>
    </div>
    <p id="sqlite" class="small muted" style="margin:0;display:none">A single file in the private folder. Nothing to create in your hosting panel; plenty for one van.</p>
    <button class="btn primary" type="submit">Test and continue</button>
  </form>
  <script>
    function toggleDb() {
      var sqlite = document.querySelector('input[name=driver][value=sqlite]').checked;
      document.getElementById('mysql').style.display = sqlite ? 'none' : 'grid';
      document.getElementById('sqlite').style.display = sqlite ? 'block' : 'none';
    }
    toggleDb();
  </script>

<?php elseif ($step === 'account'): ?>
  <form class="card" method="post" action="install.php?step=account">
    <h2>Your login</h2>
    <p class="muted small" style="margin:0">For this remote dashboard. It is on the internet, so pick a long password (at least 10 characters). It can differ from the van's own login.</p>
    <label>Username <input name="admin_user" value="<?= h($_POST['admin_user'] ?? 'admin') ?>" autocomplete="username" autocapitalize="off" required></label>
    <label>Password <input name="admin_password" type="password" minlength="10" autocomplete="new-password" required></label>
    <label>Repeat password <input name="admin_password2" type="password" minlength="10" autocomplete="new-password" required></label>
    <button class="btn primary" type="submit">Install</button>
  </form>

<?php elseif ($step === 'connect'): ?>
  <div class="card">
    <h2>Connect your van</h2>
    <div class="ok-box small">✓ Installed. Now tell your van where its remote dashboard is.</div>
    <div>
      <strong>Easiest: with your phone on the van's WiFi</strong>
      <p class="small muted" style="margin:4px 0 10px">This opens your van's dashboard with everything filled in. Tap <em>Connect</em> there.</p>
      <div class="row">
        <input id="van" value="smartify.local" aria-label="Your van's address" style="flex:1;min-width:160px">
        <a id="open" class="btn primary" href="#" target="_blank" rel="noopener">Connect my van</a>
      </div>
      <p class="tiny" style="margin:6px 0 0">The address you use at home or in the van, usually smartify.local.</p>
    </div>
    <details>
      <summary>Or copy the connection code</summary>
      <p class="small muted">On the van's dashboard: <strong>Settings → Remote dashboard</strong>, paste it and tap Connect.</p>
      <div class="code" id="code"><?= h($code) ?></div>
      <button class="btn" type="button" style="margin-top:10px" onclick="navigator.clipboard && navigator.clipboard.writeText(document.getElementById('code').textContent).then(function(){ this.textContent='Copied' }.bind(this))">Copy code</button>
    </details>
    <div class="row small" aria-live="polite"><span id="dot" class="dot"></span><span id="status">Waiting for your van…</span></div>
    <a id="done" class="btn" href="./">Open the remote dashboard</a>
    <p class="tiny" style="margin:0">The code works like a key to your van: don't share it. Lost it? Make a new one any time in the remote dashboard under Settings.</p>
  </div>
  <script>
    var code = <?= json_encode($code) ?>;
    function link() {
      var host = document.getElementById('van').value.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '') || 'smartify.local';
      document.getElementById('open').href = 'http://' + host + '/settings#connect=' + encodeURIComponent(code);
    }
    document.getElementById('van').addEventListener('input', link);
    link();
    function poll() {
      fetch('api/health', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (h) {
        if (h.device && h.device.online) {
          document.getElementById('dot').className = 'dot on';
          document.getElementById('status').textContent = 'Connected: your van is online.';
          document.getElementById('done').className = 'btn primary';
        } else { setTimeout(poll, 3000); }
      }).catch(function () { setTimeout(poll, 5000); });
    }
    poll();
  </script>

<?php else: ?>
  <div class="card">
    <h2>Already installed</h2>
    <p class="muted" style="margin:0">This remote dashboard is set up.</p>
    <a class="btn primary" href="./">Open the remote dashboard</a>
    <p class="tiny" style="margin:0">To start over, delete <code>private/config.php</code> (your data stays in the database) and open this page again. Connecting the van again: in the remote dashboard, Settings → Van connection → New connection code.</p>
  </div>
<?php endif; ?>
</main>
</body>
</html>
