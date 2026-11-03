<?php
// Smartify Kombi cloud: shared helpers. PHP 8.0+, PDO (MySQL/MariaDB or SQLite).
// No Composer, no framework: upload the folder to any shared hosting.

declare(strict_types=1);

const SMARTIFY_CLOUD_VERSION = '0.3.0';
const SMARTIFY_PROTOCOL = 1;
// Bump when schema_sql() changes; the API brings older databases up to date by
// itself on the next request, so an update is just uploading the new files.
const SMARTIFY_SCHEMA = 2;
const MIN_PHP = '8.0.0';
const PRIVATE_DIR = __DIR__ . '/../private';
const CONFIG_FILE = PRIVATE_DIR . '/config.php';

// History tables mirrored from the Pi: name => uploaded columns (plus source_id).
const HISTORY_TABLES = [
    'sensor_samples' => ['sensor', 'temperature_c', 'humidity', 'ok', 'created_at'],
    'water_level_samples' => ['level_percent', 'battery_voltage', 'ok', 'created_at'],
    'energy_samples' => [
        'battery_voltage', 'battery_current', 'battery_soc', 'solar_power',
        'solar_yield_today', 'dcdc_output_current', 'ac_out_power', 'created_at',
    ],
    'gps_fixes' => ['lat', 'lon', 'speed_kmh', 'altitude_m', 'created_at'],
    'relay_events' => ['relay_id', 'source', 'old_state', 'new_state', 'reason', 'created_at'],
];

final class HttpError extends Exception
{
    public function __construct(public int $status, string $message)
    {
        parent::__construct($message);
    }
}

function config(): array
{
    static $config = null;
    if ($config === null) {
        if (!is_file(CONFIG_FILE)) {
            throw new HttpError(503, 'Smartify cloud is not installed yet: open install.php');
        }
        $config = require CONFIG_FILE;
    }
    return $config;
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $c = config();
        $pdo = new PDO($c['db_dsn'], $c['db_user'] ?? null, $c['db_password'] ?? null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]);
        if (driver($pdo) === 'sqlite') {
            $pdo->exec('PRAGMA journal_mode=WAL');
            $pdo->exec('PRAGMA busy_timeout=10000');
        }
    }
    return $pdo;
}

function driver(PDO $pdo): string
{
    return $pdo->getAttribute(PDO::ATTR_DRIVER_NAME);
}

/** INSERT that silently skips rows whose unique key already exists. */
function insert_ignore(PDO $pdo): string
{
    return driver($pdo) === 'sqlite' ? 'INSERT OR IGNORE' : 'INSERT IGNORE';
}

function schema_sql(string $driver): array
{
    $id = $driver === 'sqlite' ? 'INTEGER PRIMARY KEY AUTOINCREMENT' : 'BIGINT AUTO_INCREMENT PRIMARY KEY';
    $text = $driver === 'sqlite' ? 'TEXT' : 'LONGTEXT';
    $key = $driver === 'sqlite' ? 'TEXT' : 'VARCHAR(64)';
    $engine = $driver === 'sqlite' ? '' : ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4';
    $sql = [
        "CREATE TABLE IF NOT EXISTS meta (k $key PRIMARY KEY, v $text NOT NULL)$engine",
        "CREATE TABLE IF NOT EXISTS commands (
            id $id,
            type $key NOT NULL,
            target $key,
            payload $text NOT NULL,
            base_revision INTEGER,
            status $key NOT NULL,
            result $text,
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            delivered_at INTEGER,
            done_at INTEGER
        )$engine",
        "CREATE TABLE IF NOT EXISTS sensor_samples (
            id $id, source_id BIGINT NOT NULL UNIQUE, sensor $key NOT NULL,
            temperature_c DOUBLE PRECISION, humidity DOUBLE PRECISION, ok INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )$engine",
        "CREATE TABLE IF NOT EXISTS water_level_samples (
            id $id, source_id BIGINT NOT NULL UNIQUE, level_percent INTEGER,
            battery_voltage DOUBLE PRECISION, ok INTEGER NOT NULL, created_at INTEGER NOT NULL
        )$engine",
        "CREATE TABLE IF NOT EXISTS energy_samples (
            id $id, source_id BIGINT NOT NULL UNIQUE, battery_voltage DOUBLE PRECISION,
            battery_current DOUBLE PRECISION, battery_soc DOUBLE PRECISION, solar_power DOUBLE PRECISION,
            solar_yield_today DOUBLE PRECISION, dcdc_output_current DOUBLE PRECISION,
            ac_out_power DOUBLE PRECISION, created_at INTEGER NOT NULL
        )$engine",
        "CREATE TABLE IF NOT EXISTS gps_fixes (
            id $id, source_id BIGINT NOT NULL UNIQUE, lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL, speed_kmh DOUBLE PRECISION, altitude_m DOUBLE PRECISION,
            created_at INTEGER NOT NULL
        )$engine",
        "CREATE TABLE IF NOT EXISTS relay_events (
            id $id, source_id BIGINT NOT NULL UNIQUE, relay_id $key NOT NULL, source $key NOT NULL,
            old_state $key, new_state $key NOT NULL, reason $text, created_at INTEGER NOT NULL
        )$engine",
    ];
    foreach (['sensor_samples', 'water_level_samples', 'energy_samples', 'gps_fixes', 'relay_events'] as $table) {
        $sql[] = $driver === 'sqlite'
            ? "CREATE INDEX IF NOT EXISTS idx_{$table}_time ON $table (created_at)"
            : null; // MySQL indexes are added below (no IF NOT EXISTS for indexes before 8.0)
    }
    return array_values(array_filter($sql));
}

function create_schema(PDO $pdo): void
{
    foreach (schema_sql(driver($pdo)) as $statement) {
        $pdo->exec($statement);
    }
    if (driver($pdo) === 'mysql') {
        foreach (['sensor_samples', 'water_level_samples', 'energy_samples', 'gps_fixes', 'relay_events'] as $table) {
            $exists = $pdo->query("SHOW INDEX FROM $table WHERE Key_name = 'idx_time'")->fetch();
            if (!$exists) {
                $pdo->exec("CREATE INDEX idx_time ON $table (created_at)");
            }
        }
    }
    set_meta('schema_version', (string)SMARTIFY_SCHEMA);
}

/** After uploading a new version: update the database once, automatically. */
function ensure_schema(): void
{
    if ((int)meta('schema_version', '0') < SMARTIFY_SCHEMA) {
        create_schema(db());
    }
}

// --- configuration ---------------------------------------------------------------------

function write_config(array $config): void
{
    $php = "<?php\n// Written by install.php. Delete this file to run the installer again\n"
        . "// (your data stays in the database).\nreturn " . var_export($config, true) . ";\n";
    $tmp = CONFIG_FILE . '.tmp';
    if (file_put_contents($tmp, $php, LOCK_EX) === false || !rename($tmp, CONFIG_FILE)) {
        @unlink($tmp);
        throw new RuntimeException('Cannot write private/config.php: make the private folder writable.');
    }
    @chmod(CONFIG_FILE, 0600);
    if (function_exists('opcache_invalidate')) {
        @opcache_invalidate(CONFIG_FILE, true);
    }
}

/** This installation's id: tells the van when it talks to a different (or reinstalled) cloud. */
function instance_id(): string
{
    return config()['instance_id'] ?? substr(config()['device_token_hash'], 0, 16);
}

function is_https(): bool
{
    return (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https')
        || (($_SERVER['SERVER_PORT'] ?? '') === '443');
}

/** Public URL of the cloud folder, e.g. https://example.com/kombi (no trailing slash). */
function base_url(): string
{
    $script = $_SERVER['SCRIPT_NAME'] ?? '/index.php';
    $dir = rtrim(str_replace('\\', '/', dirname($script)), '/');
    if (str_ends_with($dir, '/api')) {
        $dir = substr($dir, 0, -4);
    }
    $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
    return (is_https() ? 'https' : 'http') . '://' . $host . $dir;
}

/** Folder path for <base href>, e.g. "/kombi/". */
function base_path(): string
{
    $path = parse_url(base_url(), PHP_URL_PATH) ?: '';
    return rtrim($path, '/') . '/';
}

/** One string with everything the van needs to connect: "SMK1-<base64url json>". */
function connection_code(string $token): string
{
    $json = json_encode(['u' => base_url(), 't' => $token], JSON_UNESCAPED_SLASHES);
    return 'SMK1-' . rtrim(strtr(base64_encode($json), '+/', '-_'), '=');
}

/** A new device token: the old one stops working. Returns the connection code. */
function new_device_token(): string
{
    $token = bin2hex(random_bytes(24));
    $config = config();
    $config['device_token_hash'] = hash('sha256', $token);
    write_config($config);
    return connection_code($token);
}

function meta(string $key, ?string $default = null): ?string
{
    $stmt = db()->prepare('SELECT v FROM meta WHERE k = ?');
    $stmt->execute([$key]);
    $value = $stmt->fetchColumn();
    return $value === false ? $default : $value;
}

function set_meta(string $key, string $value): void
{
    $pdo = db();
    if (driver($pdo) === 'sqlite') {
        $pdo->prepare('INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v')
            ->execute([$key, $value]);
    } else {
        $pdo->prepare('INSERT INTO meta (k, v) VALUES (?, ?) ON DUPLICATE KEY UPDATE v = VALUES(v)')
            ->execute([$key, $value]);
    }
}

// --- HTTP ----------------------------------------------------------------------------

function json_out(mixed $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);
}

function json_in(): array
{
    $raw = file_get_contents('php://input') ?: '';
    $encoding = strtolower($_SERVER['HTTP_CONTENT_ENCODING'] ?? '');
    if ($encoding === 'gzip') {
        $raw = @gzdecode($raw);
        if ($raw === false) {
            throw new HttpError(400, 'invalid gzip body');
        }
    }
    if ($raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        throw new HttpError(400, 'body must be a JSON object');
    }
    return $data;
}

function query_int(string $name, int $default, int $min, int $max): int
{
    $value = filter_var($_GET[$name] ?? $default, FILTER_VALIDATE_INT);
    if ($value === false) {
        throw new HttpError(422, "$name must be a number");
    }
    return max($min, min($max, $value));
}

// --- auth ------------------------------------------------------------------------------

function start_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    session_name('smartify_cloud');
    session_set_cookie_params([
        'lifetime' => 30 * 24 * 3600,
        'path' => base_path(),
        'secure' => is_https(),
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    ini_set('session.gc_maxlifetime', (string)(30 * 24 * 3600));
    session_start();
}

/** Fingerprint of the current password: changing it ends every session. */
function password_fingerprint(): string
{
    return substr(hash('sha256', config()['admin_password_hash']), 0, 16);
}

function require_user(): string
{
    start_session();
    $user = $_SESSION['user'] ?? null;
    if (!$user || !hash_equals(password_fingerprint(), $_SESSION['pw'] ?? '')) {
        throw new HttpError(401, 'login required');
    }
    session_write_close(); // don't hold the session lock during the request
    return $user;
}

function require_device(): void
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (!preg_match('/^Bearer\s+(\S+)$/', $header, $m)
        || !hash_equals(config()['device_token_hash'], hash('sha256', $m[1]))) {
        throw new HttpError(401, 'invalid device token');
    }
}
