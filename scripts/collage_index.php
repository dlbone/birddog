<?php
session_start();
require_once 'common.php';

header('Content-Type: application/json');
header('Cache-Control: no-store');

$home = get_home();
$builder_user = get_user();
if (session_status() === PHP_SESSION_ACTIVE) {
  session_write_close();
}
$hours = isset($_GET['hours']) ? intval($_GET['hours']) : -1;
$new_mode = isset($_GET['new']) && strval($_GET['new']) === '1';
$catalog_mode = isset($_GET['catalog']) && strval($_GET['catalog']) === '1';
$range_files = [
  1 => 'index-1h.json',
  12 => 'index-12h.json',
  -1 => 'index-today.json',
  24 => 'index-24h.json',
  168 => 'index-168h.json',
  1000000 => 'index-all.json',
];

if (!array_key_exists($hours, $range_files)) {
  $hours = -1;
}
if ($new_mode) {
  $hours = 24;
}
if ($catalog_mode) {
  $hours = 1000000;
  $new_mode = false;
}

$index_file = $catalog_mode ? 'index-catalog.json' : $range_files[$hours];
$index_path = $home . '/BirdSongs/Extracted/collage/' . $index_file;
$script_path = $home . '/BirdNET-Pi/scripts/bird_collage.py';
$db_path = $home . '/BirdNET-Pi/scripts/birds.db';
$lock_path = $home . '/BirdSongs/Extracted/collage/build-' . ($catalog_mode ? 'catalog' : $hours) . '.lock';
$all_lock_path = $home . '/BirdSongs/Extracted/collage/build-all.lock';
$index_ttl = 300;
$all_index_ttl = 900;
$db_refresh_grace = 45;
$collage_index_schema = 4;

if (!file_exists(dirname($index_path))) {
  mkdir(dirname($index_path), 0775, true);
}

function collage_index_is_stale($index_path, $db_path, $script_path, $ttl, $db_grace) {
  if (!file_exists($index_path)) return true;
  $index_mtime = filemtime($index_path);
  if (file_exists($script_path) && filemtime($script_path) > $index_mtime) return true;
  $db_mtime = collage_db_mtime($db_path);
  if ($db_mtime > 0) {
    return $db_mtime > $index_mtime && time() - $db_mtime > $db_grace;
  }
  return time() - $index_mtime > $ttl;
}

function collage_db_mtime($db_path) {
  $mtime = 0;
  foreach ([$db_path, $db_path . '-wal', $db_path . '-shm'] as $path) {
    clearstatcache(true, $path);
    if (file_exists($path)) {
      $mtime = max($mtime, filemtime($path));
    }
  }
  return $mtime;
}

function collage_any_range_old($range_files, $home, $db_path, $script_path, $ttl, $db_grace) {
  $base = $home . '/BirdSongs/Extracted/collage/';
  $db_mtime = collage_db_mtime($db_path);
  $has_db = $db_mtime > 0;
  $script_mtime = file_exists($script_path) ? filemtime($script_path) : 0;
  $oldest = PHP_INT_MAX;
  foreach ($range_files as $file) {
    $path = $base . $file;
    if (!file_exists($path)) return true;
    $mtime = filemtime($path);
    if ($script_mtime > $mtime) return true;
    if ($db_mtime > $mtime && time() - $db_mtime > $db_grace) return true;
    if ($mtime < $oldest) $oldest = $mtime;
  }
  if ($has_db) return false;
  return $oldest !== PHP_INT_MAX && time() - $oldest > $ttl;
}

function collage_builder_locked($lock_path) {
  clearstatcache(true, $lock_path);
  return file_exists($lock_path) && time() - filemtime($lock_path) < 180;
}

$stale = collage_index_is_stale($index_path, $db_path, $script_path, $index_ttl, $db_refresh_grace);
$locked = collage_builder_locked($lock_path);
$payload = null;
$raw_payload = null;

function collage_load_payload($index_path, &$raw_payload) {
  $raw_payload = file_get_contents($index_path);
  return json_decode($raw_payload, true);
}

function run_collage_builder($hours, $generate, $background, $lock_path, $home, $script_path, $builder_user, $skip_enrich = true, $if_stale = false, $catalog = false) {
  if (collage_builder_locked($lock_path)) return false;
  $args = ' --hours ' . intval($hours) . ' --limit ' . ($catalog ? '0' : '28');
  if ($catalog) {
    $args .= ' --catalog';
  }
  if ($if_stale) {
    $args .= ' --if-stale';
  }
  if ($generate) {
    $args .= ' --generate --variant both --max-new 2';
  }
  if ($skip_enrich) {
    $args .= ' --skip-enrich';
  }
  $base = escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3')
    . ' ' . escapeshellarg($script_path)
    . $args
    . ' > /dev/null 2>&1';

  if ($background) {
    touch($lock_path);
    $child = 'flock -n ' . escapeshellarg($lock_path)
      . ' sh -c ' . escapeshellarg(
        'touch ' . escapeshellarg($lock_path) . '; '
        . $base . '; rm -f ' . escapeshellarg($lock_path)
    );
    $cmd = 'sudo -u ' . escapeshellarg($builder_user)
      . ' sh -c ' . escapeshellarg($child)
      . ' > /dev/null 2>&1 &';
    shell_exec($cmd);
    return true;
  } else {
    $lock_handle = fopen($lock_path, 'c');
    if (!$lock_handle || !flock($lock_handle, LOCK_EX | LOCK_NB)) {
      if ($lock_handle) fclose($lock_handle);
      return false;
    }
    touch($lock_path);
    $cmd = 'sudo -u ' . escapeshellarg($builder_user)
      . ' sh -c ' . escapeshellarg($base);
    shell_exec($cmd);
    flock($lock_handle, LOCK_UN);
    fclose($lock_handle);
    @unlink($lock_path);
    return true;
  }
}

function run_all_collage_indexes($lock_path, $home, $script_path, $builder_user) {
  if (collage_builder_locked($lock_path)) return false;
  touch($lock_path);
  $base = escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3')
    . ' ' . escapeshellarg($script_path)
    . ' --all-ranges --if-stale --limit 28 --skip-enrich > /dev/null 2>&1';
  $child = 'flock -n ' . escapeshellarg($lock_path)
    . ' sh -c ' . escapeshellarg(
      'touch ' . escapeshellarg($lock_path) . '; '
      . $base . '; rm -f ' . escapeshellarg($lock_path)
    );
  $cmd = 'sudo -u ' . escapeshellarg($builder_user)
    . ' sh -c ' . escapeshellarg($child)
    . ' > /dev/null 2>&1 &';
  shell_exec($cmd);
  return true;
}

function collage_has_cached_missing_images($payload, $home) {
  if (empty($payload['species']) || !is_array($payload['species'])) return false;
  $base = $home . '/BirdSongs/Extracted/';
  foreach ($payload['species'] as $bird) {
    if (empty($bird['has_image']) && !empty($bird['image']) && file_exists($base . $bird['image'])) return true;
    if (empty($bird['has_detail_image']) && !empty($bird['detail_image']) && file_exists($base . $bird['detail_image'])) return true;
  }
  return false;
}

function collage_payload_schema_old($payload, $schema) {
  return !is_array($payload) || intval($payload['index_schema'] ?? 0) !== intval($schema);
}

function collage_payload_signature($species) {
  $json = json_encode(array_values($species), JSON_UNESCAPED_SLASHES);
  return sha1($json === false ? '' : $json);
}

function collage_filter_new_payload($payload) {
  if (!is_array($payload)) return $payload;
  $species = array_values(array_filter($payload['species'] ?? [], function($bird) {
    return !empty($bird['is_new_bird']);
  }));
  $payload['species'] = $species;
  $payload['species_count'] = count($species);
  $payload['payload_sig'] = collage_payload_signature($species);
  $payload['hours'] = 24;
  $payload['view'] = 'new';
  return $payload;
}

function collage_encode_payload($payload) {
  $json = json_encode($payload, JSON_UNESCAPED_SLASHES);
  return ($json === false ? '{"generated_at":null,"species_count":0,"species":[]}' : $json) . "\n";
}

function collage_needs_generated_images($payload) {
  if (empty($payload['species']) || !is_array($payload['species'])) return false;
  foreach ($payload['species'] as $bird) {
    if (empty($bird['has_image']) || empty($bird['has_detail_image'])) return true;
  }
  return false;
}

function collage_needs_metadata($payload) {
  if (empty($payload['species']) || !is_array($payload['species'])) return false;
  foreach ($payload['species'] as $bird) {
    if (empty($bird['description'])) return true;
  }
  return false;
}

if (file_exists($index_path)) {
  $payload = collage_load_payload($index_path, $raw_payload);
  if (collage_payload_schema_old($payload, $collage_index_schema) || collage_has_cached_missing_images($payload, $home)) {
    if (run_collage_builder($hours, false, false, $lock_path, $home, $script_path, $builder_user, true, false, $catalog_mode)) {
      clearstatcache(true, $index_path);
      $payload = null;
      $raw_payload = null;
      $stale = false;
    }
  }
}

if ($stale && !$locked) {
  if (!file_exists($index_path)) {
    // First boot (or cache reset): build inline so the page has content.
    if (run_collage_builder($hours, false, false, $lock_path, $home, $script_path, $builder_user, true, false, $catalog_mode)) {
      clearstatcache(true, $index_path);
      $payload = null;
      $raw_payload = null;
      $stale = false;
    }
  } else {
    // Steady state: let a background rebuild refresh stale pages to avoid
    // adding request latency while this lightweight box is already busy.
    run_collage_builder($hours, false, true, $lock_path, $home, $script_path, $builder_user, true, false, $catalog_mode);
  }
}

$all_locked = collage_builder_locked($all_lock_path);
if (!$all_locked && collage_any_range_old($range_files, $home, $db_path, $script_path, $all_index_ttl, $db_refresh_grace)) {
  run_all_collage_indexes($all_lock_path, $home, $script_path, $builder_user);
}

if (!$locked && file_exists($index_path)) {
  if (!isset($payload) || !is_array($payload)) {
    $payload = collage_load_payload($index_path, $raw_payload);
  }
  if (collage_needs_generated_images($payload)) {
    run_collage_builder($hours, true, true, $lock_path, $home, $script_path, $builder_user, false, true, $catalog_mode);
  } else if (collage_needs_metadata($payload)) {
    run_collage_builder($hours, false, true, $lock_path, $home, $script_path, $builder_user, false, true, $catalog_mode);
  }
}

if (file_exists($index_path)) {
  if (!isset($payload) || !is_array($payload)) {
    $payload = collage_load_payload($index_path, $raw_payload);
  } else if ($raw_payload === null) {
    $raw_payload = file_get_contents($index_path);
  }
  if ($new_mode) {
    $payload = collage_filter_new_payload($payload);
    $raw_payload = collage_encode_payload($payload);
  }
  $client_sig = isset($_GET['sig']) ? strval($_GET['sig']) : '';
  $payload_sig = isset($payload['payload_sig']) ? strval($payload['payload_sig']) : '';
  if ($client_sig !== '' && $payload_sig !== '' && hash_equals($payload_sig, $client_sig)) {
    http_response_code(204);
    exit;
  }
  echo $raw_payload;
  exit;
}

echo json_encode([
  'generated_at' => null,
  'hours' => $hours,
  'view' => $catalog_mode ? 'catalog' : ($new_mode ? 'new' : 'recent'),
  'species_count' => 0,
  'species' => [],
]);
