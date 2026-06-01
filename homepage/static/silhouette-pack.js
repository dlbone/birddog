(function (global) {
  'use strict';

  const DEFAULT_GRID_STRIDE = 4;

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

  function buildTiles(nodes, items, width, height) {
    const T = tuning(nodes.length);
    const budget = width * height * T.packingBudgetFrac;
    const minArea = width * height * T.minTileAreaFrac;
    const tiles = nodes.map((node, idx) => {
      const bird = items[idx] || {};
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

  function maskPack(sourceTiles, width, height, ellipseBias, gridStride) {
    const tiles = sourceTiles.slice().sort((a, b) => (b.fullW * b.fullH) - (a.fullW * a.fullH));
    const gridW = Math.max(1, Math.ceil(width / gridStride));
    const gridH = Math.max(1, Math.ceil(height / gridStride));
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
      let x0 = ((tx + cell[0] * sx) / gridStride) | 0;
      let y0 = ((ty + cell[1] * sy) / gridStride) | 0;
      let x1 = ((tx + (cell[0] + 1) * sx) / gridStride) | 0;
      let y1 = ((ty + (cell[1] + 1) * sy) / gridStride) | 0;
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
      const step = Math.max(gridStride, Math.min(tile.fullW, tile.fullH) * 0.05);
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

  function layoutNodes(opts) {
    const nodes = opts.nodes || [];
    const items = opts.items || [];
    const width = opts.width || 0;
    const height = opts.height || 0;
    const gridStride = opts.gridStride || DEFAULT_GRID_STRIDE;
    const built = buildTiles(nodes, items, width, height);
    let tiles = built.tiles;
    let placed = maskPack(tiles, width, height, built.tuning.ellipseAspectBias, gridStride);
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
      placed = maskPack(tiles, width, height, built.tuning.ellipseAspectBias, gridStride);
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

    return placed;
  }

  function applyLayout(placed) {
    placed.forEach(tile => {
      const hidden = tile.x < -1000;
      tile.node.style.width = `${tile.fullW}px`;
      tile.node.style.height = `${tile.fullH}px`;
      tile.node.style.left = `${hidden ? -99999 : tile.x}px`;
      tile.node.style.top = `${hidden ? -99999 : tile.y}px`;
      tile.node.style.zIndex = String(100 + tile.idx);
      tile.node.style.setProperty('--bird-rotate', `${tile.rotate}deg`);
      const img = tile.node.querySelector('img');
      if (img) {
        img.style.width = '100%';
        img.style.height = '100%';
      }
    });
  }

  function hitTest(container, placed, clientX, clientY) {
    const box = container.getBoundingClientRect();
    const px = clientX - box.left;
    const py = clientY - box.top;
    for (let i = placed.length - 1; i >= 0; i--) {
      const tile = placed[i];
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

  global.SilhouettePack = {
    layoutNodes,
    applyLayout,
    hitTest,
    decodeMask,
    fallbackMask,
    tuning
  };
})(window);
