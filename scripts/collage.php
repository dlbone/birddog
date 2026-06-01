<?php
$home = get_home();
$script_path = $home . '/BirdNET-Pi/scripts/bird_collage.py';
$range_options = [
  ['label' => '1h', 'hours' => 1, 'file' => 'index-1h.json'],
  ['label' => '12h', 'hours' => 12, 'file' => 'index-12h.json'],
  ['label' => 'TODAY', 'hours' => -1, 'file' => 'index-today.json'],
  ['label' => '24h', 'hours' => 24, 'file' => 'index-24h.json'],
  ['label' => '7d', 'hours' => 168, 'file' => 'index-168h.json'],
  ['label' => 'all', 'hours' => 1000000, 'file' => 'index-all.json'],
];
$requested_hours = isset($_GET['hours']) ? intval($_GET['hours']) : 24;
$allowed_hours = array_map(function($opt) { return $opt['hours']; }, $range_options);
if (!in_array($requested_hours, $allowed_hours, true)) {
  $requested_hours = 24;
}
$active_range = $range_options[3];
foreach ($range_options as $option) {
  if ($option['hours'] === $requested_hours) {
    $active_range = $option;
    break;
  }
}
$index_rel = 'collage/' . $active_range['file'];
$index_path = $home . '/BirdSongs/Extracted/' . $index_rel;

function collage_has_cached_missing_images($payload, $home) {
  if (empty($payload['species']) || !is_array($payload['species'])) return false;
  $base = $home . '/BirdSongs/Extracted/';
  foreach ($payload['species'] as $bird) {
    if (empty($bird['has_image']) && !empty($bird['image']) && file_exists($base . $bird['image'])) return true;
    if (empty($bird['has_detail_image']) && !empty($bird['detail_image']) && file_exists($base . $bird['detail_image'])) return true;
  }
  return false;
}

if (!file_exists($index_path) || time() - filemtime($index_path) > 300) {
  shell_exec('sudo -u ' . escapeshellarg(get_user()) . ' ' . escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3') . ' ' . escapeshellarg($script_path) . ' --hours ' . intval($requested_hours) . ' --limit 28 --generate --variant both --max-new 2 > /dev/null 2>&1 &');
}

$payload = null;
if (file_exists($index_path)) {
  $payload = json_decode(file_get_contents($index_path), true);
  if (collage_has_cached_missing_images($payload, $home)) {
    shell_exec('sudo -u ' . escapeshellarg(get_user()) . ' ' . escapeshellarg($home . '/BirdNET-Pi/birdnet/bin/python3') . ' ' . escapeshellarg($script_path) . ' --hours ' . intval($requested_hours) . ' --limit 28 > /dev/null 2>&1');
    $payload = json_decode(file_get_contents($index_path), true);
  }
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
?>
<div class="collage-page">
  <div class="collage-toolbar">
    <div class="collage-range">
      <?php foreach ($range_options as $option) {
        $href = 'views.php?view=Collage&hours=' . intval($option['hours']);
        $active = $option['hours'] === $requested_hours ? ' class="active"' : '';
        echo '<a' . $active . ' href="' . htmlspecialchars($href) . '">' . htmlspecialchars($option['label']) . '</a>';
      } ?>
    </div>
    <a class="collage-menu" href="views.php?view=Overview">menu</a>
  </div>
  <header class="collage-header">
    <p class="collage-kicker"><?php echo htmlspecialchars(get_sitename()); ?> birds</p>
    <h2>Heard Recently</h2>
  </header>
  <div class="collage-empty" <?php if (count($birds) > 0) echo 'hidden'; ?>>No detections yet. The collage will fill in as BirdNET hears species.</div>
  <div class="bird-collage <?php echo collage_count_class(count($birds)); ?>" aria-label="Recently heard birds collage" <?php if (count($birds) === 0) echo 'hidden'; ?>>
    <?php foreach ($birds as $idx => $bird) {
        $name = htmlspecialchars($bird['com_name']);
        $sci = htmlspecialchars($bird['sci_name']);
        $count = intval($bird['recent_count']);
        if (!empty($bird['has_image'])) {
          $src = htmlspecialchars($bird['image']);
          echo "<figure class=\"collage-bird\" data-bird-idx=\"$idx\" tabindex=\"0\"><img src=\"$src\" alt=\"$name\"><figcaption><b>$name</b><span>$count heard</span></figcaption></figure>";
        } else {
          $initials = htmlspecialchars(bird_initials($bird['com_name']));
          echo "<figure class=\"collage-bird collage-placeholder\" data-bird-idx=\"$idx\" tabindex=\"0\"><div>$initials</div><figcaption><b>$name</b><span>image queued</span><i>$sci</i></figcaption></figure>";
        }
      } ?>
  </div>
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
<script>
(function() {
  const initialIndex = <?php echo json_encode($payload ?: ['generated_at' => null, 'species' => []]); ?>;
  const indexUrl = <?php echo json_encode($index_rel); ?>;
  const dataUrl = <?php echo json_encode('scripts/collage_index.php?hours=' . intval($requested_hours)); ?>;
  const collage = document.querySelector('.bird-collage');
  const empty = document.querySelector('.collage-empty');
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
  let lastGeneratedAt = initialIndex.generated_at || '';
  let currentBirds = initialIndex.species || [];
  let lastPayloadSig = payloadSignature(initialIndex);
  let pollDelay = 5000;
  let activeModalSci = '';
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

  function assetUrl(path) {
    if (!path) return '';
    const sep = String(path).includes('?') ? '&' : '?';
    return `${path}${sep}v=${encodeURIComponent(lastGeneratedAt || Date.now())}`;
  }

  function payloadSignature(payload) {
    const birds = (payload && payload.species) || [];
    return JSON.stringify(birds.map(bird => [
      bird.sci_name || '',
      bird.com_name || '',
      Number(bird.recent_count || 0),
      Number(bird.today_count || 0),
      Number(bird.total_count || 0),
      bird.last_heard || '',
      bird.first_heard || '',
      bird.image || '',
      bird.detail_image || '',
      bird.has_image ? 1 : 0,
      bird.has_detail_image ? 1 : 0
    ]));
  }

  function birdMarkup(bird, idx) {
    const name = escapeHtml(bird.com_name);
    const sci = escapeHtml(bird.sci_name);
    const heard = Number(bird.recent_count || 0);
    if (bird.has_image) {
      const src = escapeHtml(assetUrl(bird.image));
      return `<figure class="collage-bird" data-bird-idx="${idx}" tabindex="0"><img src="${src}" alt="${name}"><figcaption><b>${name}</b><span>${heard} heard</span></figcaption></figure>`;
    }
    return `<figure class="collage-bird collage-placeholder" data-bird-idx="${idx}" tabindex="0"><div>${escapeHtml(initials(bird.com_name))}</div><figcaption><b>${name}</b><span>image queued</span><i>${sci}</i></figcaption></figure>`;
  }

  function relativeDate(value) {
    if (!value || value === 'manual seed') return value || 'unknown';
    const parsed = new Date(value.replace(' ', 'T'));
    if (Number.isNaN(parsed.getTime())) return value;
    const days = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 86400000));
    if (days === 0) return 'today';
    if (days === 1) return '1d ago';
    return `${days}d ago`;
  }

  function recordingMarkup(recording) {
    const confidence = Math.round(Number(recording.confidence || 0) * 100);
    return `<div class="bird-modal-recording">
      <a class="bird-modal-play" href="/views.php?view=Recordings&filename=${encodeURIComponent(recording.file_name || '')}" target="_top">&#9654;</a>
      <div><b>${escapeHtml(relativeDate(`${recording.date} ${recording.time}`))}</b><span>${escapeHtml(recording.date)} &middot; ${escapeHtml(recording.time)}</span></div>
      <strong>${confidence}%</strong>
    </div>`;
  }

  function openModal(idx) {
    const bird = currentBirds[idx];
    if (!bird) return;
    activeModalSci = bird.sci_name || '';
    const name = escapeHtml(bird.com_name);
    const sci = escapeHtml(bird.sci_name);
    const modalImage = bird.has_detail_image ? bird.detail_image : bird.image;
    const modalRegen = `<button class="regen-image-btn modal-regen" type="button" data-bird-idx="${idx}" data-variant="both" aria-label="Regenerate bird images">${refreshIcon}</button>`;
    modalArt.innerHTML = (bird.has_detail_image || bird.has_image)
      ? `<img src="${escapeHtml(assetUrl(modalImage))}" alt="${name}">${modalRegen}`
      : `<div class="bird-modal-placeholder">${escapeHtml(initials(bird.com_name))}</div>${modalRegen}`;
    modalTitle.textContent = bird.com_name || 'Unknown bird';
    modalSci.textContent = bird.sci_name || '';
    modalStats.innerHTML = `
      <div><b>${Number(bird.total_count || bird.recent_count || 0)}</b><span>all time</span></div>
      <div><b>${Number(bird.today_count || 0)}</b><span>today</span></div>
      <div><b>${escapeHtml(relativeDate(bird.first_heard || bird.last_heard))}</b><span>first heard</span></div>`;
    modalDescription.textContent = bird.description || `${bird.com_name} was heard by BirdNET-Pi at ${<?php echo json_encode(get_sitename()); ?>}. Generated artwork is used for the collage when no local bird image exists.`;
    modalMeta.innerHTML = `<dt>Genus</dt><dd>${escapeHtml(bird.genus || '')}</dd><dt>Rarity</dt><dd>${escapeHtml(bird.rarity || 'new')}</dd><dt>Last heard</dt><dd>${escapeHtml(relativeDate(bird.last_heard))}</dd>`;
    const recordings = bird.recordings || [];
    modalRecordingCount.textContent = `${recordings.length || Number(bird.total_count || 0)} captured`;
    modalList.innerHTML = recordings.length
      ? recordings.map(recordingMarkup).join('')
      : '<div class="bird-modal-empty">No recordings are indexed for this manual entry yet.</div>';
    modal.hidden = false;
    document.body.classList.add('modal-open');
    closeButton.focus();
  }

  function closeModal() {
    modal.hidden = true;
    activeModalSci = '';
    document.body.classList.remove('modal-open');
  }

  function render(payload) {
    const birds = payload.species || [];
    lastGeneratedAt = payload.generated_at || lastGeneratedAt;
    lastPayloadSig = payloadSignature(payload);
    currentBirds = birds;
    collage.className = `bird-collage ${countClass(birds.length)}`;
    collage.innerHTML = birds.map(birdMarkup).join('');
    collage.querySelectorAll('img').forEach(img => {
      if (!img.complete) img.addEventListener('load', packBirds, {once: true});
    });
    collage.hidden = birds.length === 0;
    empty.hidden = birds.length > 0;
    requestAnimationFrame(packBirds);
    if (!modal.hidden && activeModalSci) {
      const modalIdx = currentBirds.findIndex(bird => bird.sci_name === activeModalSci);
      if (modalIdx >= 0) openModal(modalIdx);
    }
  }

  const GRID_STRIDE = 4;
  let collagePlaced = [];
  let collageHovered = null;

  function decodeMask(raw) {
    if (!raw || !raw.w || !raw.h || !raw.bits) return null;
    if (raw.cells) return raw;
    const bin = atob(raw.bits);
    const cells = [];
    const total = raw.w * raw.h;
    for (let i = 0; i < total; i++) {
      const byte = bin.charCodeAt(i >> 3);
      if (byte & (1 << (7 - (i & 7)))) cells.push([i % raw.w, Math.floor(i / raw.w)]);
    }
    raw.cells = cells;
    return raw;
  }

  function fallbackMask() {
    const w = 32;
    const h = 32;
    const cells = [];
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) cells.push([x, y]);
    }
    return {w, h, cells};
  }

  function tuning(n) {
    if (n <= 2) return {packingBudgetFrac: 0.42, minTileAreaFrac: 0.075, countExp: 0.56, ellipseAspectBias: 1.15};
    if (n <= 8) return {packingBudgetFrac: 0.50, minTileAreaFrac: 0.028, countExp: 0.60, ellipseAspectBias: 1.22};
    if (n <= 18) return {packingBudgetFrac: 0.56, minTileAreaFrac: 0.013, countExp: 0.64, ellipseAspectBias: 1.30};
    return {packingBudgetFrac: 0.60, minTileAreaFrac: 0.0075, countExp: 0.66, ellipseAspectBias: 1.38};
  }

  function buildTiles(nodes, width, height) {
    const T = tuning(nodes.length);
    const budget = width * height * T.packingBudgetFrac;
    const minArea = width * height * T.minTileAreaFrac;
    const tiles = nodes.map((node, idx) => {
      const bird = currentBirds[idx] || {};
      const rawMask = decodeMask(bird.mask) || fallbackMask();
      const imageW = Number(bird.image_width || rawMask.w || 1);
      const imageH = Number(bird.image_height || rawMask.h || 1);
      const count = Math.max(1, Number(bird.recent_count || bird.total_count || 1));
      return {
        node,
        idx,
        data: bird,
        mask: rawMask,
        ar: imageW / Math.max(1, imageH),
        score: Math.pow(count, T.countExp),
        rotate: 0
      };
    });
    const sumScore = tiles.reduce((sum, tile) => sum + tile.score, 0) || 1;
    tiles.forEach(tile => {
      tile.area = Math.max(minArea, budget * tile.score / sumScore);
    });
    if (tiles.length > 2) {
      const ranked = tiles.slice().sort((a, b) => b.score - a.score);
      ranked[0].area *= 2.65;
      ranked[0].featuredScale = 'major';
      ranked[1].area *= 1.45;
      ranked[1].featuredScale = 'minor';
    }
    const sumArea = tiles.reduce((sum, tile) => sum + tile.area, 0);
    if (sumArea > budget) {
      const fixed = tiles.filter(tile => tile.area <= minArea + 1e-9).reduce((sum, tile) => sum + tile.area, 0);
      const flex = sumArea - fixed;
      const flexBudget = Math.max(0, budget - fixed);
      const shrink = flex > 0 ? Math.min(1, flexBudget / flex) : 1;
      tiles.forEach(tile => {
        if (tile.area > minArea + 1e-9) tile.area *= shrink;
      });
    }
    tiles.forEach(tile => {
      tile.fullW = Math.sqrt(tile.area * tile.ar);
      tile.fullH = tile.fullW / tile.ar;
    });
    return {tiles, tuning: T};
  }

  function maskPack(sourceTiles, width, height, ellipseBias) {
    const tiles = sourceTiles.slice().sort((a, b) => (b.fullW * b.fullH) - (a.fullW * a.fullH));
    const gridW = Math.max(1, Math.ceil(width / GRID_STRIDE));
    const gridH = Math.max(1, Math.ceil(height / GRID_STRIDE));
    const grid = new Uint8Array(gridW * gridH);
    const centerX = width / 2;
    const centerY = height / 2;
    let seed = 0x9E3779B9;
    function rand() {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    }
    function cellRange(tile, tx, ty, cell) {
      const sx = tile.fullW / tile.mask.w;
      const sy = tile.fullH / tile.mask.h;
      let x0 = ((tx + cell[0] * sx) / GRID_STRIDE) | 0;
      let y0 = ((ty + cell[1] * sy) / GRID_STRIDE) | 0;
      let x1 = ((tx + (cell[0] + 1) * sx) / GRID_STRIDE) | 0;
      let y1 = ((ty + (cell[1] + 1) * sy) / GRID_STRIDE) | 0;
      if (x0 < 0) x0 = 0;
      if (y0 < 0) y0 = 0;
      if (x1 >= gridW) x1 = gridW - 1;
      if (y1 >= gridH) y1 = gridH - 1;
      return [x0, y0, x1, y1];
    }
    function offGrid(tile, tx, ty) {
      return tx < 0 || ty < 0 || tx + tile.fullW > width || ty + tile.fullH > height;
    }
    function collides(tile, tx, ty) {
      for (const cell of tile.mask.cells) {
        const range = cellRange(tile, tx, ty, cell);
        for (let gy = range[1]; gy <= range[3]; gy++) {
          const off = gy * gridW;
          for (let gx = range[0]; gx <= range[2]; gx++) {
            if (grid[off + gx]) return true;
          }
        }
      }
      return false;
    }
    function stamp(tile, tx, ty) {
      for (const cell of tile.mask.cells) {
        const range = cellRange(tile, tx, ty, cell);
        for (let gy = range[1]; gy <= range[3]; gy++) {
          const off = gy * gridW;
          for (let gx = range[0]; gx <= range[2]; gx++) grid[off + gx] = 1;
        }
      }
    }
    const placed = [];
    for (let i = 0; i < tiles.length; i++) {
      const tile = tiles[i];
      if (i === 0) {
        tile.x = centerX - tile.fullW / 2;
        tile.y = centerY - tile.fullH / 2;
        stamp(tile, tile.x, tile.y);
        placed.push(tile);
        continue;
      }
      let comX = 0;
      let comY = 0;
      let comW = 0;
      placed.forEach(prev => {
        if (prev.x < -1000) return;
        const area = prev.fullW * prev.fullH;
        comX += (prev.x + prev.fullW / 2) * area;
        comY += (prev.y + prev.fullH / 2) * area;
        comW += area;
      });
      comX = comW ? comX / comW : centerX;
      comY = comW ? comY / comW : centerY;
      let best = null;
      let bestCost = Infinity;
      let foundRing = -1;
      const step = Math.max(GRID_STRIDE, Math.min(tile.fullW, tile.fullH) * 0.05);
      const maxR = Math.max(width, height);
      const phase = rand() * Math.PI * 2;
      for (let r = 0; r <= maxR; r += step) {
        if (foundRing >= 0 && r > foundRing + step * 2) break;
        const samples = Math.max(36, Math.floor(r / 1.6));
        for (let k = 0; k < samples; k++) {
          const theta = phase + (k / samples) * Math.PI * 2;
          const x = centerX + r * ellipseBias * Math.cos(theta) - tile.fullW / 2;
          const y = centerY + r * Math.sin(theta) - tile.fullH / 2;
          if (offGrid(tile, x, y) || collides(tile, x, y)) continue;
          const dx = x + tile.fullW / 2 - comX;
          const dy = y + tile.fullH / 2 - comY;
          const cost = Math.hypot(dx / ellipseBias, dy) + rand() * step * 0.5;
          if (cost < bestCost) {
            bestCost = cost;
            best = {x, y};
          }
        }
        if (best && foundRing < 0) foundRing = r;
      }
      if (best) {
        tile.x = best.x;
        tile.y = best.y;
        stamp(tile, tile.x, tile.y);
      } else {
        tile.x = -99999;
        tile.y = -99999;
      }
      placed.push(tile);
    }
    return sourceTiles;
  }

  function clusterBounds(tiles) {
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    tiles.forEach(tile => {
      if (tile.x < -1000) return;
      left = Math.min(left, tile.x);
      right = Math.max(right, tile.x + tile.fullW);
      top = Math.min(top, tile.y);
      bottom = Math.max(bottom, tile.y + tile.fullH);
    });
    if (left === Infinity) return {left: 0, right: 0, top: 0, bottom: 0};
    return {left, right, top, bottom};
  }

  function applyImageCrop(tile) {
    const img = tile.node.querySelector('img');
    if (!img) return;
    img.style.width = '100%';
    img.style.height = '100%';
  }

  function packBirds() {
    if (collage.hidden || currentBirds.length === 0) return;
    const nodes = Array.from(collage.querySelectorAll('.collage-bird'));
    if (nodes.length === 0) return;

    const rect = collage.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    if (width < 100 || height < 100) return;

    const built = buildTiles(nodes, width, height);
    let tiles = built.tiles;
    let placed = maskPack(tiles, width, height, built.tuning.ellipseAspectBias);
    let bounds = clusterBounds(placed);

    for (let iter = 0; iter < 10; iter++) {
      const missing = placed.some(tile => tile.x < -1000);
      const overflow = bounds.left < 0 || bounds.top < 0 || bounds.right > width || bounds.bottom > height;
      if (!missing && !overflow) break;
      let scale = 0.93;
      if (overflow) {
        const clusterW = bounds.right - bounds.left;
        const clusterH = bounds.bottom - bounds.top;
        const sx = (width * 0.96) / Math.max(clusterW, width * 0.96);
        const sy = (height * 0.94) / Math.max(clusterH, height * 0.94);
        scale = Math.min(scale, sx, sy);
      }
      tiles.forEach(tile => {
        tile.fullW *= scale;
        tile.fullH *= scale;
      });
      placed = maskPack(tiles, width, height, built.tuning.ellipseAspectBias);
      bounds = clusterBounds(placed);
    }

    bounds = clusterBounds(placed);
    const dx = width / 2 - (bounds.left + bounds.right) / 2;
    const dy = height / 2 - (bounds.top + bounds.bottom) / 2;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      placed.forEach(tile => {
        if (tile.x > -1000) {
          tile.x += dx;
          tile.y += dy;
        }
      });
    }

    placed.forEach(tile => {
      const hidden = tile.x < -1000;
      tile.node.style.width = `${tile.fullW}px`;
      tile.node.style.height = `${tile.fullH}px`;
      tile.node.style.left = `${hidden ? -99999 : tile.x}px`;
      tile.node.style.top = `${hidden ? -99999 : tile.y}px`;
      tile.node.style.zIndex = String(100 + tile.idx);
      tile.node.style.setProperty('--bird-rotate', `${tile.rotate}deg`);
      applyImageCrop(tile);
    });
    collagePlaced = placed.filter(tile => tile.x > -1000);
  }

  function maskHitTest(clientX, clientY) {
    const box = collage.getBoundingClientRect();
    const px = clientX - box.left;
    const py = clientY - box.top;
    for (let i = collagePlaced.length - 1; i >= 0; i--) {
      const tile = collagePlaced[i];
      if (px < tile.x || py < tile.y || px > tile.x + tile.fullW || py > tile.y + tile.fullH) continue;
      const mx = ((px - tile.x) / tile.fullW * tile.mask.w) | 0;
      const my = ((py - tile.y) / tile.fullH * tile.mask.h) | 0;
      if (!tile.mask._set) {
        const set = Object.create(null);
        tile.mask.cells.forEach(cell => { set[`${cell[0]}|${cell[1]}`] = 1; });
        tile.mask._set = set;
      }
      if (tile.mask._set[`${mx}|${my}`]) return tile;
    }
    return null;
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
      const response = await fetch('scripts/collage_regen.php', {
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

  collage.addEventListener('mousemove', function(event) {
    const hit = maskHitTest(event.clientX, event.clientY);
    if (hit === collageHovered) return;
    if (collageHovered && collageHovered.node) collageHovered.node.classList.remove('is-hover');
    collageHovered = hit;
    if (hit && hit.node) hit.node.classList.add('is-hover');
    collage.style.cursor = hit ? 'pointer' : 'default';
  });

  collage.addEventListener('mouseleave', function() {
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
    window.clearTimeout(window.__collagePackTimer);
    window.__collagePackTimer = window.setTimeout(packBirds, 100);
  });
  window.addEventListener('load', packBirds);
  requestAnimationFrame(packBirds);

  async function poll() {
    try {
      const response = await fetch(`${dataUrl}&ts=${Date.now()}`, {cache: 'no-store'});
      if (response.ok) {
        const payload = await response.json();
        const nextSig = payloadSignature(payload);
        if (nextSig !== lastPayloadSig) {
          render(payload);
        } else {
          lastGeneratedAt = payload.generated_at || lastGeneratedAt;
        }
        pollDelay = 5000;
      }
    } catch (error) {
      pollDelay = Math.min(pollDelay + 5000, 30000);
    } finally {
      window.setTimeout(poll, pollDelay);
    }
  }

  window.setTimeout(poll, pollDelay);
})();
</script>
