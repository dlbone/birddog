<?php
$home = get_home();
$collage_user = get_user();
$collage_site_name = get_sitename();
if (session_status() === PHP_SESSION_ACTIVE) {
  session_write_close();
}
$script_path = $home . '/BirdNET-Pi/scripts/bird_collage.py';
$range_options = [
  ['label' => '1h', 'hours' => 1, 'file' => 'index-1h.json'],
  ['label' => '12h', 'hours' => 12, 'file' => 'index-12h.json'],
  ['label' => 'TODAY', 'hours' => -1, 'file' => 'index-today.json'],
  ['label' => '24h', 'hours' => 24, 'file' => 'index-24h.json'],
  ['label' => '7d', 'hours' => 168, 'file' => 'index-168h.json'],
  ['label' => 'all', 'hours' => 1000000, 'file' => 'index-all.json'],
];
$requested_hours = isset($_GET['hours']) ? intval($_GET['hours']) : -1;
$new_mode = isset($_GET['new']) && strval($_GET['new']) === '1';
$allowed_hours = array_map(function($opt) { return $opt['hours']; }, $range_options);
if (!in_array($requested_hours, $allowed_hours, true)) {
  $requested_hours = -1;
}
if ($new_mode) {
  $requested_hours = 24;
}
$active_range = $range_options[2];
foreach ($range_options as $option) {
  if ($option['hours'] === $requested_hours) {
    $active_range = $option;
    break;
  }
}
$index_rel = 'collage/' . $active_range['file'];
$index_path = $home . '/BirdSongs/Extracted/' . $index_rel;
$db_path = $home . '/BirdNET-Pi/scripts/birds.db';
$lock_path = $home . '/BirdSongs/Extracted/collage/build-' . $requested_hours . '.lock';
$collage_index_schema = 4;
$collage_db_refresh_grace = 45;

if (!file_exists(dirname($lock_path))) {
  mkdir(dirname($lock_path), 0775, true);
}

function collage_index_needs_data_refresh($index_path, $db_path, $script_path, $db_grace) {
  if (!file_exists($index_path)) return true;
  $index_mtime = filemtime($index_path);
  if (file_exists($script_path) && filemtime($script_path) > $index_mtime) return true;
  $db_mtime = collage_db_mtime($db_path);
  if ($db_mtime > 0) {
    return $db_mtime > $index_mtime && time() - $db_mtime > $db_grace;
  }
  return false;
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

function collage_builder_locked($lock_path) {
  clearstatcache(true, $lock_path);
  return file_exists($lock_path) && time() - filemtime($lock_path) < 180;
}

function run_initial_collage_index($home, $script_path, $hours, $lock_path, $builder_user, $extra_args = '') {
  if (collage_builder_locked($lock_path)) return false;
  $lock_handle = fopen($lock_path, 'c');
  if (!$lock_handle || !flock($lock_handle, LOCK_EX | LOCK_NB)) {
    if ($lock_handle) fclose($lock_handle);
    return false;
  }
  touch($lock_path);
  shell_exec('sudo -u ' . escapeshellarg($builder_user) . ' '
    . escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3') . ' '
    . escapeshellarg($script_path)
    . ' --hours ' . intval($hours)
    . ' --limit 28 --skip-enrich'
    . $extra_args
    . ' > /dev/null 2>&1');
  flock($lock_handle, LOCK_UN);
  fclose($lock_handle);
  @unlink($lock_path);
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

if (collage_index_needs_data_refresh($index_path, $db_path, $script_path, $collage_db_refresh_grace)) {
  run_initial_collage_index($home, $script_path, $requested_hours, $lock_path, $collage_user, ' --if-stale');
}

$payload = null;
if (file_exists($index_path)) {
  $payload = json_decode(file_get_contents($index_path), true);
  if (collage_payload_schema_old($payload, $collage_index_schema) || collage_has_cached_missing_images($payload, $home)) {
    run_initial_collage_index($home, $script_path, $requested_hours, $lock_path, $collage_user);
    $payload = json_decode(file_get_contents($index_path), true);
  }
}
if ($new_mode) {
  $payload = collage_filter_new_payload($payload);
}
$birds = $payload['species'] ?? [];

function bird_initials($name) {
  $parts = array_slice(explode(' ', $name), 0, 2);
  return implode('', array_map(function($part) { return strtoupper(substr($part, 0, 1)); }, $parts));
}

function collage_count_class($count) {
  if ($count <= 2) return 'bird-count-few';
  if ($count <= 8) return 'bird-count-some';
  if ($count <= 18) return 'bird-count-many';
  return 'bird-count-dense';
}

function collage_window_label($hours) {
  if ($hours === -1) return 'since midnight';
  if ($hours === 1) return 'last hour';
  if ($hours === 12) return 'last 12 hours';
  if ($hours === 24) return 'last 24 hours';
  if ($hours === 168) return 'last 7 days';
  return 'all time';
}

function collage_subtitle($hours, $new_mode = false) {
  if ($new_mode) return 'A record of birds first heard in the last 24 hours.';
  if ($hours === -1) return 'A record of birds detected by ear since midnight.';
  if ($hours === 1000000) return 'A record of birds detected by ear across all time.';
  return 'A record of birds detected by ear in the ' . collage_window_label($hours) . '.';
}

function collage_asset_url($path, $version) {
  if (!$path) return '';
  $sep = strpos($path, '?') === false ? '?' : '&';
  return $path . $sep . 'v=' . rawurlencode(strval($version));
}

function collage_daily_note() {
  $notes = [
    ['Tiny beaks at dawn.', 'The yard keeps soft secrets.'],
    ['Feathers sign the sky.', 'Morning answers in chirps.'],
    ['A little wing report.', 'Filed under sunshine.'],
    ['Small songs drift in.', 'The porch becomes a page.'],
    ['Bright calls, quick hops.', 'Breakfast news from branches.'],
    ['Soft wings clock in.', 'The day starts with whistles.'],
    ['A beak taps hello.', 'The garden writes back.'],
  ];
  return $notes[intval(date('z')) % count($notes)];
}
$daily_note = collage_daily_note();
$bird_count = count($birds);
$recent_birds = array_slice($birds, 0, 5);
$rail_heading = $new_mode ? 'New birds' : 'Recently heard';
$empty_message = $new_mode ? 'No new birds in the last 24 hours.' : 'No detections yet. The plate will fill in as BirdNET hears species.';
$page_title = $new_mode ? 'New Visitors' : 'Recent Visitors';
$initial_payload = $payload ?: ['generated_at' => null, 'species' => []];
$json_flags = JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT;
$initial_payload_json = json_encode($initial_payload, $json_flags);
if ($initial_payload_json === false) {
  $initial_payload_json = '{"generated_at":null,"species":[]}';
}
$index_rel_json = json_encode($index_rel, $json_flags);
$data_url = '/scripts/collage_index.php?hours=' . intval($requested_hours) . ($new_mode ? '&new=1' : '');
$data_url_json = json_encode($data_url, $json_flags);
$silhouette_pack_path = $home . '/BirdNET-Pi/homepage/static/silhouette-pack.js';
$silhouette_pack_version = file_exists($silhouette_pack_path) ? filemtime($silhouette_pack_path) : time();
?>
<div class="collage-page">
  <aside class="field-guide-rail" aria-label="Observation controls and summary">
    <div class="field-guide-brand">
      <span><?php echo htmlspecialchars($collage_site_name); ?> birds</span>
    </div>
    <nav class="field-mode-tabs" aria-label="Bird view">
      <a<?php if (!$new_mode) echo ' class="active"'; ?> href="views.php?view=Collage&amp;hours=<?php echo intval($requested_hours); ?>">Recent</a>
      <a<?php if ($new_mode) echo ' class="active"'; ?> href="views.php?view=Collage&amp;hours=24&amp;new=1">New</a>
    </nav>
    <section class="field-recent">
      <div class="field-section-head"><h3><?php echo htmlspecialchars($rail_heading); ?></h3><span><?php echo htmlspecialchars($new_mode ? '24h' : $active_range['label']); ?></span></div>
      <ol class="field-recent-list">
        <?php foreach ($recent_birds as $bird) {
          $name = htmlspecialchars($bird['com_name']);
          $count = intval($bird['recent_count']);
          echo '<li><span>' . $name . '</span><b>' . $count . ' ' . ($count === 1 ? 'call' : 'calls') . '</b></li>';
        } ?>
      </ol>
    </section>
    <section class="field-meta">
      <h3>Metadata</h3>
      <p><span>Date</span><?php echo htmlspecialchars(date('M j, Y')); ?></p>
      <p><span>Window</span><?php echo htmlspecialchars(collage_window_label($requested_hours)); ?></p>
      <p><span>Mode</span><?php echo htmlspecialchars($new_mode ? 'New' : 'Recent'); ?></p>
      <p><span>Source</span>Auto-detected</p>
    </section>
    <p class="field-script-note"><?php echo htmlspecialchars($daily_note[0]); ?><br><?php echo htmlspecialchars($daily_note[1]); ?></p>
  </aside>
  <main class="field-guide-plate">
    <div class="collage-toolbar">
      <p>Passeriformes <span>/</span> Aves</p>
      <div class="collage-toolbar-actions">
        <a class="collage-menu" href="views.php?view=Overview">menu</a>
      </div>
    </div>
    <header class="collage-header">
      <h2><?php echo htmlspecialchars($page_title); ?></h2>
      <p class="field-guide-subtitle"><?php echo htmlspecialchars(collage_subtitle($requested_hours, $new_mode)); ?></p>
    </header>
    <div class="collage-empty" <?php if ($bird_count > 0) echo 'hidden'; ?>><?php echo htmlspecialchars($empty_message); ?></div>
    <div class="bird-collage <?php echo collage_count_class($bird_count); ?>" data-layout="pending" aria-label="Recently heard birds collage" <?php if ($bird_count === 0) echo 'hidden'; ?>>
      <?php foreach ($birds as $idx => $bird) {
          $name = htmlspecialchars($bird['com_name']);
          $sci = htmlspecialchars($bird['sci_name']);
          $count = intval($bird['recent_count']);
          $is_new_bird = !empty($bird['is_new_bird']);
          $bird_classes = 'collage-bird' . ($is_new_bird ? ' is-new-bird' : '');
          $new_badge = (!$new_mode && $is_new_bird) ? '<span class="new-bird-badge">New</span>' : '';
          if (!empty($bird['has_image'])) {
            $version = $bird['image_version'] ?? ($payload['payload_sig'] ?? '');
            $src = htmlspecialchars(collage_asset_url($bird['image'], $version));
            echo "<figure class=\"$bird_classes\" data-bird-idx=\"$idx\" tabindex=\"0\">$new_badge<img src=\"$src\" alt=\"$name\"><figcaption><b>$name</b><i>$sci</i><span>$count heard</span></figcaption></figure>";
          } else {
            $initials = htmlspecialchars(bird_initials($bird['com_name']));
            echo "<figure class=\"$bird_classes collage-placeholder\" data-bird-idx=\"$idx\" tabindex=\"0\">$new_badge<div>$initials</div><figcaption><b>$name</b><i>$sci</i><span>image queued</span></figcaption></figure>";
          }
        } ?>
    </div>
    <nav class="collage-range" aria-label="Observation window">
      <?php foreach ($range_options as $option) {
        $href = 'views.php?view=Collage&hours=' . intval($option['hours']);
        $active = $option['hours'] === $requested_hours ? ' class="active"' : '';
        echo '<a' . $active . ' href="' . htmlspecialchars($href) . '">' . htmlspecialchars($option['label']) . '</a>';
      } ?>
    </nav>
    <footer class="field-guide-footer">
      <div><b>Notes</b><span>Birds are listed in order of recent detections.</span></div>
      <div><b>Reading the plate</b><span>Larger portraits mark the most frequent visitors; smaller studies are passing notes from the microphone.</span></div>
      <div><b>Recorded by</b><span>BirdDog Audio Recorder</span></div>
    </footer>
  </main>
</div>
<div class="bird-modal" hidden>
  <div class="bird-modal-panel" role="dialog" aria-modal="true" aria-labelledby="bird-modal-title">
    <button class="bird-modal-close" type="button" aria-label="Close">x</button>
    <section class="bird-modal-top">
      <div class="bird-modal-art"></div>
      <div class="bird-modal-copy">
        <h2 id="bird-modal-title"></h2>
        <p class="bird-modal-sci"></p>
        <div class="bird-modal-stats"></div>
        <p class="bird-modal-description"></p>
        <dl class="bird-modal-meta"></dl>
      </div>
    </section>
    <section class="bird-modal-recordings">
      <div class="bird-modal-section-title">Recordings <span></span></div>
      <div class="bird-modal-list"></div>
    </section>
  </div>
</div>
<script src="static/silhouette-pack.js?v=<?php echo intval($silhouette_pack_version); ?>"></script>
<script>
(function() {
  const initialIndex = <?php echo $initial_payload_json; ?>;
  const indexUrl = <?php echo $index_rel_json; ?>;
  const dataUrl = <?php echo $data_url_json; ?>;
  const isNewMode = <?php echo $new_mode ? 'true' : 'false'; ?>;
  const collage = document.querySelector('.bird-collage');
  const empty = document.querySelector('.collage-empty');
  const recentList = document.querySelector('.field-recent-list');
  const modal = document.querySelector('.bird-modal');
  const modalArt = modal.querySelector('.bird-modal-art');
  const modalTitle = modal.querySelector('#bird-modal-title');
  const modalSci = modal.querySelector('.bird-modal-sci');
  const modalStats = modal.querySelector('.bird-modal-stats');
  const modalDescription = modal.querySelector('.bird-modal-description');
  const modalMeta = modal.querySelector('.bird-modal-meta');
  const modalList = modal.querySelector('.bird-modal-list');
  const modalRecordingCount = modal.querySelector('.bird-modal-section-title span');
  const closeButton = modal.querySelector('.bird-modal-close');
  const rangeNav = document.querySelector('.collage-range');
  const ACTIVE_POLL_MS = 10000;
  const HIDDEN_POLL_MS = 30000;
  const MAX_POLL_MS = 60000;
  let lastGeneratedAt = initialIndex.generated_at || '';
  let currentBirds = initialIndex.species || [];
  let lastPayloadSig = payloadSignature(initialIndex);
  let pollDelay = ACTIVE_POLL_MS;
  let pollTimer = 0;
  let pollInFlight = false;
  let activeModalSci = '';
  let renderSeq = 0;
  let packFrame = 0;
  let packTimer = 0;
  let layoutGeneration = 0;
  let lastPackKey = '';
  let collageNodes = null;
  const refreshIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5"></path><path d="M4 18v-5h5"></path><path d="M18.5 9A7 7 0 0 0 6.1 6.1L4 8"></path><path d="M5.5 15a7 7 0 0 0 12.4 2.9L20 16"></path></svg>';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, function(char) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[char];
    });
  }

  function initials(name) {
    return String(name || 'Bird')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(part => part.charAt(0).toUpperCase())
      .join('');
  }

  function countClass(length) {
    if (length <= 2) return 'bird-count-few';
    if (length <= 8) return 'bird-count-some';
    if (length <= 18) return 'bird-count-many';
    return 'bird-count-dense';
  }

  function hashString(value) {
    let hash = 2166136261;
    const source = String(value || '');
    for (let i = 0; i < source.length; i++) {
      hash ^= source.charCodeAt(i);
      hash = Math.imul(hash, 16777619) >>> 0;
    }
    return hash >>> 0;
  }

  function randomFrom(seed) {
    let value = seed >>> 0;
    return function() {
      value += 0x6D2B79F5;
      let t = value;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function assetUrl(path, version) {
    if (!path) return '';
    const sep = String(path).includes('?') ? '&' : '?';
    return `${path}${sep}v=${encodeURIComponent(version || lastPayloadSig || lastGeneratedAt || '')}`;
  }

  function payloadSignature(payload) {
    if (payload && payload.payload_sig) return String(payload.payload_sig);
    const birds = (payload && payload.species) || [];
    const source = JSON.stringify(birds.map(bird => [
      bird.sci_name || '',
      bird.com_name || '',
      Number(bird.recent_count || 0),
      Number(bird.today_count || 0),
      Number(bird.total_count || 0),
      bird.last_heard || '',
      bird.first_heard || '',
      bird.is_new_bird ? 1 : 0,
      bird.image || '',
      bird.detail_image || '',
      bird.has_image ? 1 : 0,
      bird.has_detail_image ? 1 : 0,
      bird.image_version || '',
      bird.detail_image_version || ''
    ]));
    return String(hashString(source));
  }

  function birdMarkup(bird, idx) {
    const name = escapeHtml(bird.com_name);
    const sci = escapeHtml(bird.sci_name);
    const heard = Number(bird.recent_count || 0);
    const isNew = bird.is_new_bird ? ' is-new-bird' : '';
    const badge = !isNewMode && bird.is_new_bird ? '<span class="new-bird-badge">New</span>' : '';
    if (bird.has_image) {
      const src = escapeHtml(assetUrl(bird.image, bird.image_version));
      return `<figure class="collage-bird${isNew}" data-bird-idx="${idx}" tabindex="0">${badge}<img src="${src}" alt="${name}"><figcaption><b>${name}</b><i>${sci}</i><span>${heard} heard</span></figcaption></figure>`;
    }
    return `<figure class="collage-bird${isNew} collage-placeholder" data-bird-idx="${idx}" tabindex="0">${badge}<div>${escapeHtml(initials(bird.com_name))}</div><figcaption><b>${name}</b><i>${sci}</i><span>image queued</span></figcaption></figure>`;
  }

  function recentListMarkup(birds) {
    return birds.slice(0, 5).map(bird => {
      const heard = Number(bird.recent_count || 0);
      const noun = heard === 1 ? 'call' : 'calls';
      return `<li><span>${escapeHtml(bird.com_name)}</span><b>${heard} ${noun}</b></li>`;
    }).join('');
  }

  function parseBirdTimestamp(value) {
    if (!value || value === 'manual seed') return null;
    const text = String(value).trim();
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/);
    if (match) {
      return new Date(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        Number(match[4] || 0),
        Number(match[5] || 0),
        Number(match[6] || 0)
      );
    }
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function localDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function relativeDate(value) {
    if (!value || value === 'manual seed') return value || 'unknown';
    const parsed = parseBirdTimestamp(value);
    if (!parsed) return value;
    const days = Math.round((localDay(new Date()).getTime() - localDay(parsed).getTime()) / 86400000);
    if (days <= 0) return 'today';
    if (days === 1) return 'yesterday';
    return `${days}d ago`;
  }

  function absoluteDate(value) {
    const parsed = parseBirdTimestamp(value);
    if (!parsed) return value || '';
    return parsed.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  function relativeDateHtml(value) {
    return `<b class="js-relative-date" data-date-value="${escapeHtml(value || '')}" title="${escapeHtml(absoluteDate(value))}">${escapeHtml(relativeDate(value))}</b>`;
  }

  function earliestTimestamp(values) {
    let bestValue = '';
    let bestTime = Infinity;
    values.forEach(function(value) {
      if (!value || value === 'manual seed') return;
      const parsed = parseBirdTimestamp(value);
      if (!parsed) return;
      const time = parsed.getTime();
      if (time < bestTime) {
        bestTime = time;
        bestValue = value;
      }
    });
    return bestValue;
  }

  function firstHeardValue(bird) {
    const values = [bird && bird.first_heard];
    ((bird && bird.recordings) || []).forEach(function(recording) {
      if (recording.date) values.push(`${recording.date} ${recording.time || '00:00:00'}`);
    });
    return earliestTimestamp(values) || (bird && bird.last_heard) || '';
  }

  function refreshRelativeDates() {
    document.querySelectorAll('.js-relative-date').forEach(function(node) {
      node.textContent = relativeDate(node.dataset.dateValue || '');
      node.title = absoluteDate(node.dataset.dateValue || '');
    });
  }

  function recordingMarkup(recording) {
    const confidence = Math.round(Number(recording.confidence || 0) * 100);
    const folder = String(recording.file_name || '').split('-')[0] || '';
    const comFolder = String(recording.file_name || '').replace(/-\d+-.*$/, '') || folder;
    const audioPath = `/By_Date/${encodeURIComponent(recording.date || '')}/${encodeURIComponent(comFolder)}/${encodeURIComponent(recording.file_name || '')}`;
    return `<div class="bird-modal-recording">
      <button class="bird-modal-play" type="button" data-audio="${escapeHtml(audioPath)}" aria-label="Play recording">&#9654;</button>
      <div class="bird-modal-rec-main">
        <div>${relativeDateHtml(`${recording.date} ${recording.time}`)}<span>${escapeHtml(recording.date)} &middot; ${escapeHtml(recording.time)}</span></div>
        <canvas class="bird-modal-viz" width="320" height="34" data-audio="${escapeHtml(audioPath)}" aria-hidden="true"></canvas>
      </div>
      <strong>${confidence}%</strong>
      <a class="bird-modal-download" href="${escapeHtml(audioPath)}" download>mp3</a>
    </div>`;
  }

  function fallbackDescription(bird) {
    const common = bird.com_name || 'This bird';
    const sci = bird.sci_name ? ` (${bird.sci_name})` : '';
    const genus = bird.genus ? ` It belongs to the genus ${bird.genus}.` : '';
    return `${common}${sci} has been detected by the porch microphone and added to this local BirdNET catalog.${genus} A fuller field-guide description will appear automatically once species metadata is available.`;
  }

  function openModal(idx) {
    stopModalAudio();
    const bird = currentBirds[idx];
    if (!bird) return;
    activeModalSci = bird.sci_name || '';
    const name = escapeHtml(bird.com_name);
    const sci = escapeHtml(bird.sci_name);
    const modalImage = bird.has_detail_image ? bird.detail_image : bird.image;
    const modalImageVersion = bird.has_detail_image ? bird.detail_image_version : bird.image_version;
    const modalRegen = `<button class="regen-image-btn modal-regen" type="button" data-bird-idx="${idx}" data-variant="both" aria-label="Regenerate bird images">${refreshIcon}</button>`;
    modalArt.innerHTML = (bird.has_detail_image || bird.has_image)
      ? `<img src="${escapeHtml(assetUrl(modalImage, modalImageVersion))}" alt="${name}">${modalRegen}`
      : `<div class="bird-modal-placeholder">${escapeHtml(initials(bird.com_name))}</div>${modalRegen}`;
    modalTitle.textContent = bird.com_name || 'Unknown bird';
    modalSci.textContent = bird.sci_name || '';
    modalStats.innerHTML = `
      <div><b>${Number(bird.total_count || bird.recent_count || 0)}</b><span>all time</span></div>
      <div><b>${Number(bird.today_count || 0)}</b><span>today</span></div>
      <div>${relativeDateHtml(firstHeardValue(bird))}<span>first heard</span></div>`;
    modalDescription.textContent = bird.description || fallbackDescription(bird);
    modalMeta.innerHTML = `<dt>Genus</dt><dd>${escapeHtml(bird.genus || '')}</dd><dt>Rarity</dt><dd>${escapeHtml(bird.rarity || 'new')}</dd><dt>Last heard</dt><dd>${relativeDateHtml(bird.last_heard)}</dd>`;
    const recordings = bird.recordings || [];
    modalRecordingCount.textContent = `${recordings.length || Number(bird.total_count || 0)} captured`;
    modalList.innerHTML = recordings.length
      ? recordings.map(recordingMarkup).join('')
      : '<div class="bird-modal-empty">No recordings are indexed for this manual entry yet.</div>';
    modal.hidden = false;
    document.body.classList.add('modal-open');
    initRecordingWaveforms();
    closeButton.focus();
  }

  function closeModal() {
    stopModalAudio();
    modal.hidden = true;
    activeModalSci = '';
    document.body.classList.remove('modal-open');
  }

  let modalAudio = null;
  let modalAudioButton = null;
  let modalAudioCtx = null;
  let modalVizFrame = 0;
  const PLAYHEAD_VISUAL_LAG_SEC = 0.2;
  const waveformCache = new Map();
  const waveformPending = new Map();

  function resetRecordingRow(button) {
    if (!button) return;
    const row = button.closest('.bird-modal-recording');
    button.innerHTML = '&#9654;';
    button.setAttribute('aria-label', 'Play recording');
    button.removeAttribute('data-playing');
    if (row) {
      row.removeAttribute('data-playing');
      const canvas = row.querySelector('.bird-modal-viz');
      if (canvas) drawWaveformCanvas(canvas, 0);
    }
  }

  function stopModalAudio() {
    if (modalVizFrame) {
      cancelAnimationFrame(modalVizFrame);
      modalVizFrame = 0;
    }
    if (modalAudio) {
      try { modalAudio.pause(); } catch (error) {}
      modalAudio.src = '';
      modalAudio = null;
    }
    resetRecordingRow(modalAudioButton);
    modalAudioButton = null;
  }

  function baseViz(canvas, message) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#f5f4f0';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(33,31,27,0.16)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(10, Math.round(h / 2) + 0.5);
    ctx.lineTo(w - 10, Math.round(h / 2) + 0.5);
    ctx.stroke();
    if (message) {
      ctx.fillStyle = 'rgba(33,31,27,0.42)';
      ctx.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(message, w / 2, h / 2);
    }
  }

  function buildEnergyLine(audioBuffer, points) {
    const ch0 = audioBuffer.getChannelData(0);
    const ch1 = audioBuffer.numberOfChannels > 1 ? audioBuffer.getChannelData(1) : null;
    const step = Math.max(1, Math.floor(ch0.length / points));
    const values = new Array(points);
    let max = 0;
    for (let i = 0; i < points; i++) {
      const start = i * step;
      const end = Math.min(ch0.length, start + step);
      let sum = 0;
      let n = 0;
      for (let j = start; j < end; j += 8) {
        const sample = ch1 ? (ch0[j] + ch1[j]) * 0.5 : ch0[j];
        sum += sample * sample;
        n++;
      }
      const rms = Math.sqrt(sum / Math.max(1, n));
      values[i] = rms;
      if (rms > max) max = rms;
    }
    if (max > 0) {
      for (let i = 0; i < values.length; i++) values[i] = Math.min(1, values[i] / max);
    }
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 1; i < values.length - 1; i++) {
        values[i] = (values[i - 1] + values[i] * 2 + values[i + 1]) / 4;
      }
    }
    return values;
  }

  function drawWaveformCanvas(canvas, progress) {
    const values = waveformCache.get(canvas.dataset.audio || '');
    if (!values) {
      baseViz(canvas, 'loading');
      return;
    }
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    const padX = 10;
    const padY = 7;
    const plotW = w - padX * 2;
    const plotH = h - padY * 2;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#f5f4f0';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(127,181,138,0.22)';
    ctx.fillRect(0, 0, Math.round(w * Math.max(0, Math.min(1, progress || 0))), h);
    ctx.strokeStyle = 'rgba(33,31,27,0.14)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padX, h - padY + 0.5);
    ctx.lineTo(w - padX, h - padY + 0.5);
    ctx.stroke();
    ctx.strokeStyle = '#211f1b';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    values.forEach(function(v, i) {
      const x = padX + (i / Math.max(1, values.length - 1)) * plotW;
      const y = h - padY - Math.pow(v, 0.72) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const playX = padX + Math.max(0, Math.min(1, progress || 0)) * plotW;
    ctx.strokeStyle = 'rgba(33,31,27,0.45)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(playX, padY - 1);
    ctx.lineTo(playX, h - padY + 2);
    ctx.stroke();
  }

  function ensureWaveform(canvas) {
    const url = canvas && canvas.dataset.audio;
    if (!url) return Promise.resolve();
    if (waveformCache.has(url)) {
      drawWaveformCanvas(canvas, 0);
      return Promise.resolve();
    }
    if (waveformPending.has(url)) {
      return waveformPending.get(url).then(function() {
        drawWaveformCanvas(canvas, 0);
      });
    }
    baseViz(canvas, 'loading');
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) {
      baseViz(canvas, 'audio preview unavailable');
      return Promise.resolve();
    }
    modalAudioCtx = modalAudioCtx || new Ctx();
    if (modalAudioCtx.state === 'suspended') {
      modalAudioCtx.resume().catch(function() {});
    }
    const pending = fetch(url, {cache: 'force-cache'})
      .then(function(response) {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.arrayBuffer();
      })
      .then(function(buffer) { return modalAudioCtx.decodeAudioData(buffer); })
      .then(function(audioBuffer) {
        waveformCache.set(url, buildEnergyLine(audioBuffer, canvas.width - 20));
        drawWaveformCanvas(canvas, 0);
      })
      .catch(function(error) {
        console.warn('waveform render failed', error);
        baseViz(canvas, 'preview unavailable');
      });
    waveformPending.set(url, pending);
    return pending.finally(function() {
      waveformPending.delete(url);
    });
  }

  function initRecordingWaveforms() {
    modalList.querySelectorAll('.bird-modal-viz').forEach(function(canvas) {
      if (waveformCache.has(canvas.dataset.audio || '')) drawWaveformCanvas(canvas, 0);
      else baseViz(canvas, 'tap play');
    });
  }

  function startPlayhead(canvas) {
    if (modalVizFrame) cancelAnimationFrame(modalVizFrame);
    const tick = function() {
      if (!modalAudio || !canvas) return;
      drawWaveformCanvas(canvas, playheadProgress());
      modalVizFrame = requestAnimationFrame(tick);
    };
    tick();
  }

  function playheadProgress() {
    if (!modalAudio || !modalAudio.duration) return 0;
    return Math.max(0, (modalAudio.currentTime - PLAYHEAD_VISUAL_LAG_SEC) / modalAudio.duration);
  }

  function playModalRecording(button) {
    if (!button) return;
    if (button === modalAudioButton && modalAudio) {
      if (modalAudio.paused) {
        modalAudio.play().catch(function(error) { console.warn('recording play failed', error); });
        button.innerHTML = '&#10074;&#10074;';
        button.setAttribute('data-playing', 'true');
        button.setAttribute('aria-label', 'Pause recording');
        const row = button.closest('.bird-modal-recording');
        if (row) row.setAttribute('data-playing', 'true');
        const canvas = row && row.querySelector('.bird-modal-viz');
        if (canvas) startPlayhead(canvas);
      } else {
        modalAudio.pause();
        if (modalVizFrame) {
          cancelAnimationFrame(modalVizFrame);
          modalVizFrame = 0;
        }
        button.innerHTML = '&#9654;';
        button.removeAttribute('data-playing');
        button.setAttribute('aria-label', 'Play recording');
        const row = button.closest('.bird-modal-recording');
        if (row) row.removeAttribute('data-playing');
      }
      return;
    }

    stopModalAudio();
    const row = button.closest('.bird-modal-recording');
    const canvas = row && row.querySelector('.bird-modal-viz');
    modalAudioButton = button;
    modalAudio = new Audio(button.dataset.audio || '');
    button.innerHTML = '&#10074;&#10074;';
    button.setAttribute('data-playing', 'true');
    button.setAttribute('aria-label', 'Pause recording');
    if (row) row.setAttribute('data-playing', 'true');

    modalAudio.addEventListener('ended', stopModalAudio);
    modalAudio.addEventListener('error', function() {
      resetRecordingRow(button);
      button.innerHTML = '!';
      window.setTimeout(function() { resetRecordingRow(button); }, 1400);
    });

    Promise.resolve(canvas ? ensureWaveform(canvas) : null)
      .then(function() { return modalAudio.play(); })
      .then(function() { if (canvas) startPlayhead(canvas); })
      .catch(function(error) {
        console.warn('recording play failed', error);
        stopModalAudio();
      });
  }

  function applyPayload(payload) {
    const birds = payload.species || [];
    lastGeneratedAt = payload.generated_at || lastGeneratedAt;
    lastPayloadSig = payloadSignature(payload);
    currentBirds = birds;
    collage.className = `bird-collage ${countClass(birds.length)}`;
    collage.dataset.layout = 'pending';
    collage.innerHTML = birds.map(birdMarkup).join('');
    collageNodes = null;
    layoutGeneration++;
    lastPackKey = '';
    if (recentList) recentList.innerHTML = recentListMarkup(birds);
    collage.hidden = birds.length === 0;
    empty.hidden = birds.length > 0;
    schedulePack();
    refreshRelativeDates();
    if (!modal.hidden && activeModalSci) {
      const modalIdx = currentBirds.findIndex(bird => bird.sci_name === activeModalSci);
      if (modalIdx >= 0) openModal(modalIdx);
    }
  }

  function render(payload) {
    const seq = ++renderSeq;
    const fadeDelay = collage.dataset.layout === 'ready' ? 170 : 0;
    collage.dataset.layout = 'pending';
    window.setTimeout(function() {
      if (seq !== renderSeq) return;
      applyPayload(payload);
    }, fadeDelay);
  }

  function basePollDelay() {
    return document.hidden ? HIDDEN_POLL_MS : ACTIVE_POLL_MS;
  }

  function schedulePoll(delay) {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(poll, delay);
  }

  let collagePlaced = [];
  let collageHovered = null;
  let hoverFrame = 0;
  let hoverX = 0;
  let hoverY = 0;

  function schedulePack(delay) {
    if (delay) {
      window.clearTimeout(packTimer);
      packTimer = window.setTimeout(function() {
        packTimer = 0;
        schedulePack();
      }, delay);
      return;
    }
    if (packTimer) {
      window.clearTimeout(packTimer);
      packTimer = 0;
    }
    if (packFrame) return;
    packFrame = requestAnimationFrame(function() {
      packFrame = 0;
      packBirds();
    });
  }

  function packBirds() {
    if (collage.hidden || currentBirds.length === 0 || !window.SilhouettePack) return;
    const nodes = collageNodes || (collageNodes = Array.from(collage.querySelectorAll('.collage-bird')));
    if (nodes.length === 0) return;

    const rect = collage.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    if (width < 100 || height < 100) return;
    const packKey = [
      layoutGeneration,
      lastPayloadSig,
      nodes.length,
      Math.round(width),
      Math.round(height)
    ].join('|');
    if (packKey === lastPackKey) {
      collage.dataset.layout = 'ready';
      return;
    }

    const placed = window.SilhouettePack.layoutNodes({
      nodes,
      items: currentBirds,
      width,
      height
    });
    window.SilhouettePack.applyLayout(placed);
    collagePlaced = placed
      .filter(tile => tile.x > -1000)
      .sort((a, b) => Number(a.node.style.zIndex || 0) - Number(b.node.style.zIndex || 0));
    lastPackKey = packKey;
    requestAnimationFrame(function() {
      collage.dataset.layout = 'ready';
    });
  }

  function maskHitTest(clientX, clientY) {
    if (!window.SilhouettePack) return null;
    return window.SilhouettePack.hitTest(collage, collagePlaced, clientX, clientY);
  }

  async function refreshIndex() {
    const response = await fetch(`${dataUrl}&ts=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`index ${response.status}`);
    const payload = await response.json();
    render(payload);
    return payload;
  }

  async function regenerateImage(idx, variant, button) {
    const bird = currentBirds[idx];
    if (!bird || !variant) return;
    const body = new URLSearchParams();
    body.set('sci', bird.sci_name || '');
    body.set('variant', variant);
    body.set('hours', String(initialIndex.hours || <?php echo intval($requested_hours); ?>));
    if (button) {
      button.disabled = true;
      button.setAttribute('data-loading', 'true');
    }
    try {
      const response = await fetch('/scripts/collage_regen.php', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: body.toString(),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
      await refreshIndex();
    } catch (error) {
      console.warn('image regeneration failed', error);
      if (button) {
        button.setAttribute('data-error', 'true');
        window.setTimeout(() => button.removeAttribute('data-error'), 2200);
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.removeAttribute('data-loading');
      }
    }
  }

  function updateCollageHover(clientX, clientY) {
    const hit = maskHitTest(clientX, clientY);
    if (hit === collageHovered) return;
    if (collageHovered && collageHovered.node) collageHovered.node.classList.remove('is-hover');
    collageHovered = hit;
    if (hit && hit.node) hit.node.classList.add('is-hover');
    collage.style.cursor = hit ? 'pointer' : 'default';
  }

  collage.addEventListener('mousemove', function(event) {
    hoverX = event.clientX;
    hoverY = event.clientY;
    if (hoverFrame) return;
    hoverFrame = requestAnimationFrame(function() {
      hoverFrame = 0;
      updateCollageHover(hoverX, hoverY);
    });
  });

  collage.addEventListener('mouseleave', function() {
    if (hoverFrame) {
      cancelAnimationFrame(hoverFrame);
      hoverFrame = 0;
    }
    if (collageHovered && collageHovered.node) collageHovered.node.classList.remove('is-hover');
    collageHovered = null;
    collage.style.cursor = 'default';
  });

  collage.addEventListener('click', function(event) {
    const regen = event.target.closest && event.target.closest('.regen-image-btn');
    if (regen) {
      event.preventDefault();
      event.stopPropagation();
      regenerateImage(Number(regen.dataset.birdIdx), regen.dataset.variant, regen);
      return;
    }
    const hit = maskHitTest(event.clientX, event.clientY);
    if (hit) openModal(hit.idx);
  });

  collage.addEventListener('keydown', function(event) {
    if (event.key === 'Enter' || event.key === ' ') {
      const bird = event.target.closest('.collage-bird');
      if (bird) {
        event.preventDefault();
        openModal(Number(bird.dataset.birdIdx));
      }
    }
  });

  closeButton.addEventListener('click', closeModal);
  modal.addEventListener('click', function(event) {
    const play = event.target.closest && event.target.closest('.bird-modal-play');
    if (play) {
      event.preventDefault();
      event.stopPropagation();
      playModalRecording(play);
      return;
    }
    const regen = event.target.closest && event.target.closest('.regen-image-btn');
    if (regen) {
      event.preventDefault();
      event.stopPropagation();
      regenerateImage(Number(regen.dataset.birdIdx), regen.dataset.variant, regen);
      return;
    }
    if (event.target === modal) closeModal();
  });
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });
  window.addEventListener('resize', function() {
    schedulePack(100);
  });
  window.addEventListener('load', function() { schedulePack(); });
  schedulePack();

  if (rangeNav) {
    rangeNav.addEventListener('click', function(event) {
      const link = event.target.closest('a');
      if (!link || link.classList.contains('active')) return;
      event.preventDefault();
      collage.dataset.layout = 'pending';
      window.setTimeout(function() {
        window.location.href = link.href;
      }, 120);
    });
  }

  async function poll() {
    if (pollInFlight) {
      schedulePoll(pollDelay);
      return;
    }
    pollInFlight = true;
    try {
      const sig = lastPayloadSig ? `&sig=${encodeURIComponent(lastPayloadSig)}` : '';
      const response = await fetch(`${dataUrl}&ts=${Date.now()}${sig}`, {cache: 'no-store'});
      if (response.status === 204) {
        pollDelay = basePollDelay();
        refreshRelativeDates();
        return;
      }
      if (response.ok) {
        const payload = await response.json();
        const nextSig = payloadSignature(payload);
        if (nextSig !== lastPayloadSig) {
          render(payload);
        } else {
          lastGeneratedAt = payload.generated_at || lastGeneratedAt;
          refreshRelativeDates();
        }
        pollDelay = basePollDelay();
      }
    } catch (error) {
      pollDelay = Math.min(pollDelay + ACTIVE_POLL_MS, MAX_POLL_MS);
    } finally {
      pollInFlight = false;
      schedulePoll(pollDelay);
    }
  }

  document.addEventListener('visibilitychange', function() {
    if (!document.hidden) {
      pollDelay = ACTIVE_POLL_MS;
      refreshRelativeDates();
      schedulePoll(0);
    }
  });

  window.setInterval(refreshRelativeDates, 60000);
  refreshRelativeDates();
  schedulePoll(pollDelay);
})();
</script>
