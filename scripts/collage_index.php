<?php
session_start();
require_once 'common.php';

header('Content-Type: application/json');
header('Cache-Control: no-store');

$home = get_home();
$hours = isset($_GET['hours']) ? intval($_GET['hours']) : -1;
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

$index_path = $home . '/BirdSongs/Extracted/collage/' . $range_files[$hours];
$script_path = $home . '/BirdNET-Pi/scripts/bird_collage.py';
$lock_path = $home . '/BirdSongs/Extracted/collage/build-' . $hours . '.lock';
$all_lock_path = $home . '/BirdSongs/Extracted/collage/build-all.lock';

if (!file_exists(dirname($index_path))) {
  mkdir(dirname($index_path), 0775, true);
}

$stale = !file_exists($index_path) || time() - filemtime($index_path) > 20;
$locked = file_exists($lock_path) && time() - filemtime($lock_path) < 180;

function run_collage_builder($hours, $generate, $background, $lock_path, $home, $script_path, $skip_enrich = true) {
  $args = ' --hours ' . intval($hours) . ' --limit 28';
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
    $cmd = 'sudo -u ' . escapeshellarg(get_user())
      . ' sh -c ' . escapeshellarg($base . '; rm -f ' . escapeshellarg($lock_path))
      . ' > /dev/null 2>&1 &';
  } else {
    $cmd = 'sudo -u ' . escapeshellarg(get_user())
      . ' sh -c ' . escapeshellarg($base);
  }
  shell_exec($cmd);
}

function run_all_collage_indexes($lock_path, $home, $script_path) {
  touch($lock_path);
  $cmd = 'sudo -u ' . escapeshellarg(get_user())
    . ' sh -c ' . escapeshellarg(
      escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3')
      . ' ' . escapeshellarg($script_path)
      . ' --all-ranges --limit 28 --skip-enrich > /dev/null 2>&1; '
      . 'rm -f ' . escapeshellarg($lock_path)
    )
    . ' > /dev/null 2>&1 &';
  shell_exec($cmd);
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
  $payload = json_decode(file_get_contents($index_path), true);
  if (collage_has_cached_missing_images($payload, $home)) {
    run_collage_builder($hours, false, false, $lock_path, $home, $script_path);
    $stale = false;
  }
}

if ($stale && !$locked) {
  // First refresh the cheap JSON index synchronously so empty/changed
  // windows self-correct before the response is returned. Missing image
  // generation can then happen in the background without stale counts.
  run_collage_builder($hours, false, false, $lock_path, $home, $script_path);
  $stale = false;
}

$all_locked = file_exists($all_lock_path) && time() - filemtime($all_lock_path) < 180;
if (!$all_locked) {
  run_all_collage_indexes($all_lock_path, $home, $script_path);
}

if (!$locked && file_exists($index_path)) {
  $payload = json_decode(file_get_contents($index_path), true);
  if (collage_needs_generated_images($payload)) {
    run_collage_builder($hours, true, true, $lock_path, $home, $script_path, false);
  } else if (collage_needs_metadata($payload)) {
    run_collage_builder($hours, false, true, $lock_path, $home, $script_path, false);
  }
}

if (file_exists($index_path)) {
  readfile($index_path);
  exit;
}

echo json_encode([
  'generated_at' => null,
  'hours' => $hours,
  'species_count' => 0,
  'species' => [],
]);
