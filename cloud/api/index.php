<?php
// Smartify Kombi cloud API.
//
// The same URL shapes as the API on the Pi (backend/smartify/api), so one
// dashboard build works in both places. Reads come from the latest state the
// van uploaded; changes become commands the van picks up on its next sync.

declare(strict_types=1);

require __DIR__ . '/lib.php';
require __DIR__ . '/updates.php';

const OFFLINE_AFTER = 90;        // seconds without a sync before the van counts as offline
const RESULT_TIMEOUT = 300;      // delivered command without a result: assume applied
const NOT_HERE = 'Only available on the van\'s own dashboard (connect to its WiFi)';

function state(): array
{
    static $state = null;
    if ($state === null) {
        $state = json_decode(meta('state', '{}') ?? '{}', true) ?: [];
    }
    return $state;
}

function last_seen(): ?int
{
    $value = meta('last_seen');
    return $value === null ? null : (int)$value;
}

function van_online(): bool
{
    $seen = last_seen();
    return $seen !== null && time() - $seen < OFFLINE_AFTER;
}

function ago(int $seconds): string
{
    if ($seconds < 90) return "$seconds s";
    if ($seconds < 5400) return round($seconds / 60) . ' min';
    if ($seconds < 172800) return round($seconds / 3600) . ' h';
    return round($seconds / 86400) . ' days';
}

/** Commands still on their way, and recent failures, per target id. */
function command_notes(): array
{
    $stmt = db()->prepare(
        "SELECT target, status, result, created_at FROM commands
         WHERE status IN ('pending', 'delivered') OR (status IN ('failed', 'rejected', 'expired') AND done_at > ?)
         ORDER BY id"
    );
    $stmt->execute([time() - 600]);
    $notes = [];
    foreach ($stmt as $row) {
        if (in_array($row['status'], ['pending', 'delivered'], true)) {
            $notes[$row['target']] = van_online()
                ? 'Sent ' . ago(time() - (int)$row['created_at']) . ' ago, waiting for the van'
                : 'Queued: the van is offline, it applies this when it reconnects';
        } else {
            $result = json_decode($row['result'] ?? '{}', true) ?: [];
            $notes[$row['target']] = ucfirst($row['status']) . ': ' . ($result['error'] ?? 'not applied');
        }
    }
    return $notes;
}

function relays_with_notes(): array
{
    $notes = command_notes();
    return array_map(function (array $relay) use ($notes) {
        $relay['remote'] = $notes[$relay['id']] ?? null;
        return $relay;
    }, state()['relays'] ?? []);
}

function find_relay(string $id): array
{
    foreach (relays_with_notes() as $relay) {
        if ($relay['id'] === $id) return $relay;
    }
    throw new HttpError(404, "relay $id not found");
}

function find_rule(string $id): array
{
    foreach (state()['rules'] ?? [] as $relayRules) {
        foreach ($relayRules['rules'] ?? [] as $rule) {
            if ($rule['id'] === $id) return $rule;
        }
    }
    throw new HttpError(404, "rule $id not found");
}

function queue(string $type, string $target, array $payload, ?int $baseRevision = null, ?int $ttl = null): int
{
    $now = time();
    db()->prepare(
        'INSERT INTO commands (type, target, payload, base_revision, status, created_at, expires_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)'
    )->execute([
        $type, $target, json_encode($payload, JSON_UNESCAPED_UNICODE), $baseRevision, 'pending', $now,
        $ttl === null ? null : $now + $ttl,
    ]);
    return (int)db()->lastInsertId();
}

function history(string $table, array $columns, int $hours, string $where = '', array $params = []): array
{
    $sql = 'SELECT ' . implode(', ', $columns) . " FROM $table WHERE created_at >= ?" . ($where ? " AND $where" : '')
        . ' ORDER BY created_at';
    $stmt = db()->prepare($sql);
    $stmt->execute(array_merge([time() - $hours * 3600], $params));
    $rows = $stmt->fetchAll();
    foreach ($rows as &$row) {
        foreach ($row as $key => $value) {
            if (is_string($value) && is_numeric($value) && $key !== 'sensor') {
                $row[$key] = $value + 0;
            }
        }
    }
    return $rows;
}

// --- device sync -------------------------------------------------------------------------

function device_sync(): array
{
    require_device();
    $body = json_in();
    if (($body['protocol'] ?? null) !== SMARTIFY_PROTOCOL) {
        throw new HttpError(400, 'unsupported protocol version, update the cloud files');
    }
    $pdo = db();
    $now = time();
    $pdo->beginTransaction();
    try {
        // 1. Results of commands the van applied.
        $update = $pdo->prepare('UPDATE commands SET status = ?, result = ?, done_at = ? WHERE id = ?');
        foreach ($body['results'] ?? [] as $result) {
            $status = in_array($result['status'] ?? '', ['done', 'failed', 'rejected'], true) ? $result['status'] : 'failed';
            $update->execute([$status, json_encode($result), $now, (int)$result['id']]);
        }
        $lastCommand = (int)($body['last_command_id'] ?? 0);
        // Applied by the van but the result got lost (e.g. a reboot): assume done.
        $pdo->prepare("UPDATE commands SET status = 'done', done_at = ? WHERE status = 'delivered' AND id <= ? AND delivered_at < ?")
            ->execute([$now, $lastCommand, $now - RESULT_TIMEOUT]);
        // Switching commands are only useful while fresh.
        $pdo->prepare("UPDATE commands SET status = 'expired', done_at = ? WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?")
            ->execute([$now, $now]);

        // 2. Live state.
        if (isset($body['state']) && is_array($body['state'])) {
            set_meta('state', json_encode($body['state'], JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION));
            set_meta('state_at', (string)$now);
        }
        set_meta('last_seen', (string)$now);

        // 3. History rows (idempotent on the van's row id).
        $accepted = [];
        foreach ($body['history'] ?? [] as $table => $rows) {
            if (!isset(HISTORY_TABLES[$table]) || !is_array($rows) || !$rows) continue;
            $columns = HISTORY_TABLES[$table];
            $sql = insert_ignore($pdo) . " INTO $table (source_id, " . implode(', ', $columns) . ') VALUES ('
                . implode(', ', array_fill(0, count($columns) + 1, '?')) . ')';
            $insert = $pdo->prepare($sql);
            $max = 0;
            foreach ($rows as $row) {
                $values = [(int)$row['id']];
                foreach ($columns as $column) $values[] = $row[$column] ?? null;
                $insert->execute($values);
                $max = max($max, (int)$row['id']);
            }
            $accepted[$table] = $max;
        }

        // 4. Commands for the van.
        $stmt = $pdo->prepare(
            "SELECT id, type, target, payload, base_revision, created_at FROM commands
             WHERE status IN ('pending', 'delivered') AND id > ? ORDER BY id LIMIT 50"
        );
        $stmt->execute([$lastCommand]);
        $commands = [];
        $mark = $pdo->prepare("UPDATE commands SET status = 'delivered', delivered_at = ? WHERE id = ?");
        foreach ($stmt->fetchAll() as $row) {
            $commands[] = [
                'id' => (int)$row['id'],
                'type' => $row['type'],
                'target' => $row['target'],
                'payload' => json_decode($row['payload'], true),
                'base_revision' => $row['base_revision'] === null ? null : (int)$row['base_revision'],
                'created_at' => (int)$row['created_at'],
            ];
            $mark->execute([$now, $row['id']]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    cleanup_if_due();
    return [
        'commands' => $commands,
        'accepted' => (object)$accepted,
        'server_time' => $now,
        // A new id (fresh install) tells the van to send everything again.
        'instance' => instance_id(),
        // Lets the van mention in its update notification that this needs an update too.
        'version' => SMARTIFY_CLOUD_VERSION,
    ];
}

function cleanup_if_due(): void
{
    $now = time();
    if ((int)meta('last_cleanup', '0') > $now - 3600) return;
    $cutoff = $now - (int)(config()['history_days'] ?? 90) * 86400;
    foreach (array_keys(HISTORY_TABLES) as $table) {
        db()->prepare("DELETE FROM $table WHERE created_at < ?")->execute([$cutoff]);
    }
    db()->prepare("DELETE FROM commands WHERE created_at < ?")->execute([$now - 30 * 86400]);
    set_meta('last_cleanup', (string)$now);
}

// --- routes -------------------------------------------------------------------------------

function route(string $method, string $path): mixed
{
    $seg = array_values(array_filter(explode('/', $path), 'strlen'));
    $route = $method . ' /' . implode('/', array_map(fn($s, $i) => preg_match('/^[a-z-]+$/', $s) && !($i > 0 && in_array($seg[$i - 1], ['relays', 'rules', 'climate', 'archive', 'devices', 'scenes', 'heaters'], true)) ? $s : '*', $seg, array_keys($seg)));
    $state = fn(string $key, mixed $default = null) => state()[$key] ?? $default;

    switch ($route) {
        case 'GET /health':
            $seen = last_seen();
            return [
                'ok' => true,
                'version' => SMARTIFY_CLOUD_VERSION,
                'mode' => 'cloud',
                'hardware' => $state('system', [])['hardware'] ?? 'pi',
                'schema_version' => (int)meta('schema_version', '0'),
                'server_time' => time(),
                'setup_required' => false,
                'device' => ['last_seen' => $seen, 'online' => van_online(), 'version' => $state('version')],
            ];

        case 'POST /device/sync':
            return device_sync();

        case 'POST /auth/login':
            $body = json_in();
            $c = config();
            $okUser = hash_equals($c['admin_user'], (string)($body['username'] ?? ''));
            $okPass = password_verify((string)($body['password'] ?? ''), $c['admin_password_hash']);
            if (!$okUser || !$okPass) {
                sleep(1); // slows down password guessing
                throw new HttpError(401, 'wrong username or password');
            }
            start_session();
            session_regenerate_id(true);
            $_SESSION['user'] = $c['admin_user'];
            $_SESSION['pw'] = password_fingerprint();
            return ['user' => $c['admin_user']];

        case 'POST /auth/logout':
            start_session();
            $_SESSION = [];
            session_destroy();
            return ['ok' => true];

        case 'GET /auth/me':
            return ['user' => require_user(), 'default_credentials' => false, 'login_source' => 'cloud'];

        case 'GET /setup':
            return ['required' => false];
    }

    require_user();

    switch ($route) {
        case 'GET /relays':
            return ['relays' => relays_with_notes()];
        case 'GET /relays/*':
            return find_relay($seg[1]);
        case 'GET /relays/*/events':
            $stmt = db()->prepare('SELECT source_id AS id, relay_id, source, NULL AS rule_id, old_state, new_state, reason, created_at
                                   FROM relay_events WHERE relay_id = ? ORDER BY created_at DESC, id DESC LIMIT ?');
            $stmt->bindValue(1, $seg[1]);
            $stmt->bindValue(2, query_int('limit', 50, 1, 500), PDO::PARAM_INT);
            $stmt->execute();
            return ['events' => array_map(fn($r) => array_merge($r, ['id' => (int)$r['id'], 'created_at' => (int)$r['created_at']]), $stmt->fetchAll())];
        case 'GET /relays/*/rules':
            find_relay($seg[1]);
            return $state('rules', [])[$seg[1]] ?? ['rules' => [], 'decision' => ['state' => null, 'reason' => 'no data yet'], 'mode' => 'auto'];
        case 'POST /relays/*/manual':
            $relay = find_relay($seg[1]);
            $body = json_in();
            if (!in_array($body['state'] ?? null, ['on', 'off'], true)) throw new HttpError(422, 'state must be on or off');
            $minutes = isset($body['duration_minutes']) ? max(1, min(10080, (int)$body['duration_minutes'])) : null;
            queue('relay_manual', $relay['id'], ['state' => $body['state'], 'duration_minutes' => $minutes], null, (int)(config()['command_ttl_seconds'] ?? 900));
            return find_relay($seg[1]);
        case 'POST /relays/*/auto':
            $relay = find_relay($seg[1]);
            queue('relay_auto', $relay['id'], [], null, (int)(config()['command_ttl_seconds'] ?? 900));
            return find_relay($seg[1]);
        case 'PATCH /relays/*':
            $relay = find_relay($seg[1]);
            $allowed = ['label', 'gpio_pin', 'active_low', 'enabled', 'min_on_seconds', 'min_off_seconds', 'cutoff_sensor', 'cutoff_max_c'];
            $changes = array_intersect_key(json_in(), array_flip($allowed));
            queue('relay_update', $relay['id'], $changes, (int)$relay['revision']);
            return find_relay($seg[1]);
        case 'POST /relays/*/rules':
            $relay = find_relay($seg[1]);
            $body = array_intersect_key(json_in(), array_flip(['name', 'condition', 'action', 'priority', 'cooldown_seconds', 'enabled']));
            queue('rule_create', $relay['id'], $body);
            return array_merge($body, ['id' => 'pending', 'relay_id' => $relay['id'], 'pending' => true]);
        case 'PATCH /rules/*':
            $rule = find_rule($seg[1]);
            $changes = array_intersect_key(json_in(), array_flip(['name', 'condition', 'action', 'priority', 'cooldown_seconds', 'enabled']));
            queue('rule_update', $rule['id'], $changes, (int)$rule['revision']);
            return array_merge($rule, $changes, ['pending' => true]);
        case 'DELETE /rules/*':
            $rule = find_rule($seg[1]);
            queue('rule_delete', $rule['id'], [], (int)$rule['revision']);
            return array_merge($rule, ['pending' => true]);

        case 'GET /heaters':
            return $state('heaters', ['heaters' => [], 'available' => false]);
        case 'POST /heaters/*/power':
        case 'POST /heaters/*/settings':
            $heater = null;
            foreach ($state('heaters', ['heaters' => []])['heaters'] as $candidate) {
                if ($candidate['id'] === $seg[1]) $heater = $candidate;
            }
            if ($heater === null) throw new HttpError(404, 'heater not found');
            $body = json_in();
            if ($seg[2] === 'power') {
                queue('heater_power', $heater['id'], ['on' => (bool)($body['on'] ?? false)], null, (int)(config()['command_ttl_seconds'] ?? 900));
            } else {
                $settings = array_intersect_key($body, array_flip(['mode', 'temperature', 'level']));
                queue('heater_settings', $heater['id'], $settings, null, (int)(config()['command_ttl_seconds'] ?? 900));
            }
            return array_merge($heater, ['pending' => true]);

        case 'GET /scenes':
            return $state('scenes', ['scenes' => [], 'icons' => []]);
        case 'POST /scenes/*/run':
            $scene = null;
            foreach ($state('scenes', ['scenes' => []])['scenes'] as $candidate) {
                if ((string)$candidate['id'] === $seg[1]) $scene = $candidate;
            }
            if ($scene === null) throw new HttpError(404, 'scene not found');
            queue('scene_run', (string)$scene['id'], [], null, (int)(config()['command_ttl_seconds'] ?? 900));
            return ['scene' => $scene, 'applied' => [], 'skipped' => [], 'queued' => true];

        case 'GET /climate':
            return $state('climate', ['sensors' => []]);
        case 'GET /climate/*/history':
            return ['sensor' => $seg[1], 'points' => history('sensor_samples', ['created_at', 'temperature_c', 'humidity'], query_int('hours', 24, 1, 2160), 'sensor = ? AND ok = 1', [$seg[1]])];

        case 'GET /water':
            return $state('water', ['ok' => false, 'level_percent' => null, 'battery_voltage' => null, 'signal_voltage' => null, 'ratio' => null, 'error' => 'no data from the van yet', 'updated_at' => null]);
        case 'GET /water/history':
            return ['points' => history('water_level_samples', ['created_at', 'level_percent', 'battery_voltage'], query_int('hours', 24, 1, 2160), 'ok = 1')];
        case 'GET /water/settings':
            return $state('water_settings') ?? throw new HttpError(404, 'no data from the van yet');
        case 'PATCH /water/settings':
            $settings = $state('water_settings') ?? throw new HttpError(409, 'no data from the van yet');
            queue('water_settings', 'water', json_in(), (int)$settings['revision']);
            return $settings;

        case 'GET /gps':
            return $state('gps', ['status' => 'no_fix', 'fix' => null, 'fix_at' => null, 'error' => null]);
        case 'GET /gps/track':
            return ['points' => history('gps_fixes', ['created_at', 'lat', 'lon', 'speed_kmh'], query_int('hours', 24, 1, 2160))];
        case 'GET /gps/distance':
            return $state('gps_distance', ['total_km' => 0, 'days' => []]);
        case 'GET /gps/archive':
            return ['files' => []];

        case 'GET /energy':
            return $state('energy', ['available' => false, 'battery' => null, 'solar' => null, 'dcdc' => null, 'inverter' => null, 'devices' => []]);
        case 'GET /energy/forecast':
            return $state('energy_forecast', ['available' => false, 'reason' => 'no data from the van yet']);
        case 'GET /stops':
            return $state('stops', ['stops' => []]);
        case 'GET /energy/history':
            return ['points' => history('energy_samples', ['created_at', 'battery_voltage', 'battery_current', 'battery_soc', 'solar_power', 'solar_yield_today', 'dcdc_output_current', 'ac_out_power'], query_int('hours', 24, 1, 2160))];

        case 'GET /weather':
            return $state('weather', ['available' => false, 'updated_at' => null, 'error' => 'no data from the van yet']);

        case 'GET /system':
            $system = $state('system') ?? throw new HttpError(404, 'no data from the van yet');
            $system['cloud'] = ['enabled' => true, 'url' => 'this server', 'last_ok_at' => last_seen(), 'last_error' => null, 'last_error_at' => null, 'commands_applied' => 0];
            return $system;

        case 'GET /cloud/connection':
            $seen = last_seen();
            return [
                'url' => base_url(),
                'last_seen' => $seen,
                'online' => van_online(),
                'version' => SMARTIFY_CLOUD_VERSION,
                'van_version' => $state('version'),
            ];
        case 'POST /cloud/connection-code':
            // A new token: the van stays disconnected until it gets this code.
            return ['code' => new_device_token(), 'url' => base_url()];

        case 'GET /updates':
            update_check(); // when due
            return update_view();
        case 'PATCH /updates/settings':
            $mode = json_in()['mode'] ?? null;
            if (!in_array($mode, ['off', 'notify', 'auto'], true)) throw new HttpError(422, 'mode must be off, notify or auto');
            set_meta('update_mode', $mode);
            return update_view();
        case 'POST /updates/check':
            update_check(true);
            return update_view();
        case 'POST /updates/install':
            $version = (string)(json_in()['version'] ?? '');
            if (!preg_match('/^\d+\.\d+\.\d+$/', $version)) throw new HttpError(422, 'version must look like 1.2.3');
            $result = update_install($version);
            // This request still runs the old code: report what is installed now.
            $installed = $result['state'] === 'done' ? $version : SMARTIFY_CLOUD_VERSION;
            return array_merge(update_view(), ['current' => $installed, 'update_available' => version_newer(update_latest(), $installed)]);

        case 'GET /commands':
            $rows = db()->query('SELECT id, type, target, status, result, created_at, done_at FROM commands ORDER BY id DESC LIMIT 50')->fetchAll();
            return ['commands' => $rows];

        case 'POST /relays':
        case 'DELETE /relays/*':
        case 'GET /heaters/*':
        case 'POST /heaters':
        case 'PATCH /heaters/*':
        case 'DELETE /heaters/*':
        case 'POST /scenes':
        case 'PATCH /scenes/*':
        case 'DELETE /scenes/*':
        case 'POST /water/calibrate':
        case 'GET /logs':
        case 'GET /wifi':
        case 'GET /wifi/networks':
        case 'POST /wifi/connect':
        case 'GET /notifications':
        case 'GET /notifications/settings':
        case 'PATCH /notifications/settings':
        case 'POST /notifications/test':
        case 'POST /notifications/ntfy/new-topic':
        case 'POST /notifications/telegram/detect-chat':
        case 'POST /notifications/departure/pause':
        case 'GET /victron/devices':
        case 'GET /victron/nearby':
        case 'POST /victron/devices':
        case 'DELETE /victron/devices/*':
        case 'POST /auth/password':
        case 'POST /setup':
        case 'GET /cloud':
        case 'POST /cloud':
        case 'DELETE /cloud':
            throw new HttpError(501, NOT_HERE);
    }
    throw new HttpError(404, 'Not Found');
}

// --- dispatch -------------------------------------------------------------------------------

try {
    $uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
    $pos = strpos($uri, '/api/');
    $path = $pos === false ? '/' : substr($uri, $pos + 4);
    if (is_file(CONFIG_FILE)) {
        ensure_schema();
    }
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $result = route($method, $path);
    json_out($result);
    if ($method === 'POST' && rtrim($path, '/') === '/device/sync') {
        try {
            update_after_sync();
        } catch (Throwable $e) {
            error_log('smartify cloud update check: ' . $e->getMessage());
        }
    }
} catch (HttpError $e) {
    json_out(['detail' => $e->getMessage()], $e->status);
} catch (Throwable $e) {
    error_log('smartify cloud: ' . $e);
    json_out(['detail' => 'server error, see the hosting error log'], 500);
}
