<?php
// One-time installer: creates the database tables, the admin login and the
// device token, and writes private/config.php. Refuses to run once installed.

declare(strict_types=1);

require __DIR__ . '/api/lib.php';

$installed = is_file(CONFIG_FILE);
$error = null;
$token = null;

function h(?string $s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES);
}

if (!$installed && ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    try {
        $driver = $_POST['driver'] ?? 'mysql';
        $user = trim($_POST['admin_user'] ?? '');
        $password = $_POST['admin_password'] ?? '';
        if ($user === '' || strlen($password) < 10) {
            throw new RuntimeException('Choose a username and a password of at least 10 characters.');
        }
        if ($password !== ($_POST['admin_password2'] ?? '')) {
            throw new RuntimeException('The two passwords differ.');
        }
        if ($driver === 'sqlite') {
            $dsn = 'sqlite:' . realpath(PRIVATE_DIR) . '/smartify.sqlite';
            $dbUser = $dbPassword = null;
        } else {
            $dsn = sprintf(
                'mysql:host=%s;dbname=%s;charset=utf8mb4',
                $_POST['db_host'] ?: 'localhost',
                $_POST['db_name'] ?? ''
            );
            $dbUser = $_POST['db_user'] ?? '';
            $dbPassword = $_POST['db_password'] ?? '';
        }
        $pdo = new PDO($dsn, $dbUser, $dbPassword, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        foreach (schema_sql(driver($pdo)) as $statement) {
            $pdo->exec($statement);
        }

        $token = bin2hex(random_bytes(24));
        $config = [
            'db_dsn' => $dsn,
            'db_user' => $dbUser,
            'db_password' => $dbPassword,
            'admin_user' => $user,
            'admin_password_hash' => password_hash($password, PASSWORD_DEFAULT),
            'device_token_hash' => hash('sha256', $token),
            'command_ttl_seconds' => 900,
            'history_days' => 90,
        ];
        $php = "<?php\n// Written by install.php. Delete this file to run the installer again.\nreturn "
            . var_export($config, true) . ";\n";
        if (file_put_contents(CONFIG_FILE, $php, LOCK_EX) === false) {
            throw new RuntimeException('Cannot write private/config.php: check the folder permissions.');
        }
        @chmod(CONFIG_FILE, 0600);
        create_schema(db());
    } catch (Throwable $e) {
        $error = $e->getMessage();
        $token = null;
    }
}
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Install Smartify Kombi cloud</title>
<style>
  body { margin: 0; background: #11130e; color: #ecebdd; font: 16px/1.5 system-ui, sans-serif; }
  main { max-width: 560px; margin: 40px auto; padding: 0 16px; }
  h1 { font-size: 28px; margin: 0 0 8px; }
  form, .box { background: #1a1d16; border: 1px solid #2e3327; border-radius: 16px; padding: 20px; display: grid; gap: 14px; }
  label { display: grid; gap: 6px; color: #a3a893; font-size: 14px; }
  input, select { min-height: 44px; border-radius: 10px; border: 1px solid #3a4032; background: #11130e; color: #ecebdd; padding: 0 12px; font: inherit; }
  button { min-height: 48px; border: 0; border-radius: 10px; background: #f0a43a; color: #1b1407; font: 600 16px system-ui, sans-serif; cursor: pointer; }
  code { background: #22261d; padding: 2px 6px; border-radius: 6px; word-break: break-all; }
  .error { background: rgba(239, 90, 76, .14); border: 1px solid rgba(239, 90, 76, .5); padding: 12px; border-radius: 10px; }
  .muted { color: #a3a893; font-size: 14px; }
  fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: 14px; }
</style>
</head>
<body>
<main>
<h1>Smartify Kombi cloud</h1>
<?php if ($token): ?>
  <div class="box">
    <p><strong>Installed.</strong> Put these two lines in <code>backend/.env</code> on the Raspberry Pi and restart Smartify:</p>
    <p><code>SMARTIFY_CLOUD_URL=<?= h((isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off' ? 'https' : 'http') . '://' . ($_SERVER['HTTP_HOST'] ?? 'your-domain') . rtrim(dirname($_SERVER['SCRIPT_NAME'] ?? '/'), '/')) ?></code></p>
    <p><code>SMARTIFY_CLOUD_TOKEN=<?= h($token) ?></code></p>
    <p class="muted">The token is shown only now. Lost it? Delete <code>private/config.php</code> and install again.
       For safety you can also delete <code>install.php</code> from the server.</p>
    <p><a href="./" style="color:#f0a43a">Open the dashboard</a></p>
  </div>
<?php elseif ($installed): ?>
  <div class="box"><p>Already installed. To start over, delete <code>private/config.php</code>.</p><p><a href="./" style="color:#f0a43a">Open the dashboard</a></p></div>
<?php else: ?>
  <p class="muted">Creates the tables, your login for the remote dashboard, and the token the van uses to sync.
     Create an empty MySQL database (and a user with access to it) in your hosting panel first.</p>
  <?php if ($error): ?><div class="error"><?= h($error) ?></div><?php endif; ?>
  <form method="post">
    <label>Database
      <select name="driver" onchange="document.getElementById('mysql').style.display = this.value === 'mysql' ? 'grid' : 'none'">
        <option value="mysql">MySQL / MariaDB (recommended)</option>
        <option value="sqlite"<?= extension_loaded('pdo_sqlite') ? '' : ' disabled' ?>>SQLite file (no database server needed)</option>
      </select>
    </label>
    <fieldset id="mysql">
      <label>Host <input name="db_host" value="localhost"></label>
      <label>Database name <input name="db_name" value="<?= h($_POST['db_name'] ?? '') ?>"></label>
      <label>Database user <input name="db_user" value="<?= h($_POST['db_user'] ?? '') ?>" autocomplete="off"></label>
      <label>Database password <input name="db_password" type="password" autocomplete="off"></label>
    </fieldset>
    <label>Dashboard username <input name="admin_user" value="<?= h($_POST['admin_user'] ?? 'admin') ?>" required></label>
    <label>Dashboard password (10+ characters) <input name="admin_password" type="password" minlength="10" required></label>
    <label>Repeat password <input name="admin_password2" type="password" minlength="10" required></label>
    <button type="submit">Install</button>
  </form>
<?php endif; ?>
</main>
</body>
</html>
