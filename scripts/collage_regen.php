<?php
session_start();
require_once 'common.php';

header('Content-Type: application/json');

$sci = isset($_POST['sci']) ? trim($_POST['sci']) : '';
$variant = isset($_POST['variant']) ? trim($_POST['variant']) : 'collage';
$hours = isset($_POST['hours']) ? intval($_POST['hours']) : 24;
$catalog_mode = isset($_POST['catalog']) && strval($_POST['catalog']) === '1';
$allowed_variants = ['collage', 'detail', 'both'];
$allowed_hours = [1, 12, -1, 24, 168, 1000000];

if ($catalog_mode) {
  $hours = 1000000;
}

if ($sci === '' || !in_array($variant, $allowed_variants, true) || !in_array($hours, $allowed_hours, true)) {
  http_response_code(400);
  echo json_encode(['ok' => false, 'error' => 'invalid request']);
  exit;
}

$home = get_home();
$cmd = 'sudo -u ' . escapeshellarg(get_user())
  . ' ' . escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3')
  . ' ' . escapeshellarg($home . '/BirdNET-Pi/scripts/bird_collage.py')
  . ' --hours ' . intval($hours)
  . ' --limit ' . ($catalog_mode ? '0' : '28')
  . ($catalog_mode ? ' --catalog' : '')
  . ' --generate --force --max-new ' . ($variant === 'both' ? '2' : '1')
  . ' --variant ' . escapeshellarg($variant)
  . ' --sci ' . escapeshellarg($sci)
  . ' 2>&1';

$output = [];
$rc = 0;
exec($cmd, $output, $rc);

if ($rc !== 0) {
  http_response_code(500);
  echo json_encode(['ok' => false, 'error' => implode("\n", $output)]);
  exit;
}

echo json_encode(['ok' => true, 'output' => implode("\n", $output)]);
