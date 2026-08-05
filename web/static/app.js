/* Rebar BBS web — vanilla JS. NOL logika perhitungan: semua dari backend. */

const $ = (id) => document.getElementById(id);
let templates = {};
let lastResult = null;
let lastElemen = [];
let lastOverride = {};

const fmtM = (mm) => (mm / 1000).toFixed(3);
const fmtKg = (v) => v.toFixed(2);

// ── load config awal ───────────────────────────────────────
fetch('/api/config').then(r => r.json()).then(d => {
  templates = d.templates;
  renderRows(1);
  renderParam(d.config, []);
  if (d.config.warnings.length) {
    $('warnBanner').textContent = d.config.warnings.join(' | ');
    $('warnBanner').classList.add('show');
  }
});

// ── baris elemen ───────────────────────────────────────────
function renderRows(n) {
  const box = $('rows');
  box.innerHTML = '';
  for (let i = 0; i < n; i++) box.appendChild(newRow());
}
function newRow() {
  const div = document.createElement('div');
  div.className = 'elem-row';
  const opts = Object.keys(templates).map(t =>
    `<option value="${t}">${t}</option>`).join('');
  div.innerHTML = `
    <input list="tipeList" placeholder="B1" class="t-tipe">
    <input type="number" step="any" min="1" placeholder="6000" class="t-bentang">
    <input type="number" step="1" min="1" placeholder="1" class="t-jumlah">
    <button class="del" title="hapus">✕</button>`;
  div.querySelector('.del').onclick = () => {
    if (document.querySelectorAll('.elem-row').length > 1) div.remove();
  };
  return div;
}
$('btnAdd').onclick = () => $('rows').appendChild(newRow());
$('rows').addEventListener('input', (e) => {
  // autocomplete tipe via datalist global
  const dl = document.createElement('datalist');
  dl.id = 'tipeList';
  Object.keys(templates).forEach(t => {
    const o = document.createElement('option');
    o.value = t; dl.appendChild(o);
  });
  if (!$('tipeList')) document.body.appendChild(dl);
});

// ── baca input ─────────────────────────────────────────────
function bacaElemen() {
  const out = [];
  document.querySelectorAll('.elem-row').forEach(row => {
    const tipe = row.querySelector('.t-tipe').value.trim();
    const bentang = row.querySelector('.t-bentang').value;
    const jumlah = row.querySelector('.t-jumlah').value;
    if (!tipe && !bentang && !jumlah) return; // baris kosong dilewati
    out.push({ tipe, bentang_bersih_mm: Number(bentang),
               jumlah: Number(jumlah), lokasi: '' });
  });
  return out;
}
function bacaOverride() {
  const o = {};
  const m = $('ovrMetode').value;
  const z = $('ovrZona').value;
  const k = $('ovrKerf').value;
  const s = $('ovrSisaMin').value;
  if (m) o.metode_hitung = m;
  if (z !== '') o.zona_tumpuan_faktor = Number(z);
  if (k !== '') o.kerf_mm = Number(k);
  if (s !== '') o.sisa_min_simpan_mm = Number(s);
  return o;
}

// ── hitung ─────────────────────────────────────────────────
async function hitung() {
  const elemen = bacaElemen();
  if (!elemen.length) { alert('Isi minimal satu baris elemen.'); return; }
  const override = bacaOverride();
  lastElemen = elemen; lastOverride = override;

  const res = await fetch('/api/hitung', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ elemen, override })
  });
  const d = await res.json();
  if (!d.ok) { renderError(d); return; }

  lastResult = d;
  renderStat(d.total);
  renderParam(d.config, d.override_aktif || []);
  renderBBS(d.bbs, d);
  renderPola(d.optimizer);
}

// ── error ──────────────────────────────────────────────────
function renderError(d) {
  const box = $('tab-bbs');
  const flag = d.bug_internal
    ? '<div style="color:#b4232c;font-weight:800;margin-bottom:6px">⚠ BUG INTERNAL — laporkan ke developer</div>'
    : '';
  box.innerHTML = `<div style="background:#fef2f2;border:1px solid #fecaca;padding:12px;
       border-radius:6px;color:#7f1d1d;font-family:ui-monospace,monospace;font-size:12px;
       white-space:pre-wrap">${flag}${escapeHtml(d.error)}</div>`;
  $('tab-pola').innerHTML = '';
  $('stats').innerHTML = '';
}

// ── render ─────────────────────────────────────────────────
function renderStat(t) {
  $('stats').innerHTML = `
    <div class="stat"><b>${fmtKg(t.berat_kg)}</b><span>berat total (kg)</span></div>
    <div class="stat"><b>${t.batang}</b><span>batang</span></div>
    <div class="stat"><b>${(t.sisa_mm / 1000).toFixed(3)}</b><span>sisa (m)</span></div>
    <div class="stat"><b>${t.baris_bbs}</b><span>baris BBS</span></div>`;
}

function renderBBS(rows, d) {
  const box = $('tab-bbs');
  if (!rows.length) { box.innerHTML = '<div style="color:#5b6572">Tidak ada output.</div>'; return; }
  const uw = d.config.unit_weight;
  let totalBerat = 0, totalPanjang = 0;
  let html = `<table><thead><tr>
    <th>Bar Mark</th><th>Posisi</th><th>Shape</th><th>Ø</th>
    <th class="num">Panjang (m)</th><th class="num">Jumlah</th>
    <th class="num">Total (m)</th><th class="num">Berat (kg)</th></tr></thead><tbody>`;
  rows.forEach(r => {
    const pM = fmtM(r.panjang_mm);
    const totM = r.panjang_mm / 1000 * r.jumlah;
    const berat = totM * (uw[r.dia] || 0);
    totalPanjang += totM;
    totalBerat += berat;
    html += `<tr>
      <td>${escapeHtml(r.bar_mark || '')}</td><td>${escapeHtml(r.posisi)}</td>
      <td>${escapeHtml(r.shape)}</td><td>${r.dia}</td>
      <td class="num">${pM}</td><td class="num">${r.jumlah}</td>
      <td class="num">${fmtKg(totM)}</td><td class="num">${fmtKg(berat)}</td>
    </tr>`;
  });
  html += `<tr class="total"><td colspan="6">TOTAL</td>
    <td class="num">${fmtKg(totalPanjang)}</td>
    <td class="num">${fmtKg(totalBerat)}</td></tr></tbody></table>`;
  box.innerHTML = html;
}

function renderPola(opt) {
  const box = $('tab-pola');
  const dias = Object.keys(opt).map(Number).sort((a, b) => a - b);
  if (!dias.length) { box.innerHTML = '<div style="color:#5b6572">—</div>'; return; }
  const cfg = lastResult.config;
  const uw = cfg.unit_weight;
  const stok = cfg.stok_mm, kerf = cfg.kerf_mm;
  let html = '';
  dias.forEach(dia => {
    const r = opt[dia];
    let flag = '';
    // invariant: kelayakan & frekuensi (harusnya tak pernah muncul setelah PATCH-01)
    const bad = r.patterns.some(p => {
      const n = p.potongan.length;
      return (p.potongan.reduce((a, b) => a + b, 0) + Math.max(n - 1, 0) * kerf) > stok;
    }) || r.patterns.reduce((a, p) => a + p.frekuensi, 0) !== r.total_batang;
    if (bad) flag = ' <span class="warn-flag">⚠ INVARIANT MELANGGAR</span>';
    html += `<div class="dia-block">
      <div class="dia-head">D${dia}${flag}</div>
      <div class="dia-meta">${r.patterns.length} pola · ${r.total_batang} batang · ` +
      `berat ${fmtKg(r.total_panjang_terpakai_mm / 1000 * (uw[dia] || 0))} kg · ` +
      `waste bersih ${r.waste_pct.toFixed(2)}% · kotor ${r.waste_kotor_pct.toFixed(2)}% · ` +
      `sisa simpan ${(r.sisa_reusable_mm / 1000).toFixed(2)} m</div>`;
    r.patterns.forEach((p, i) => {
      const label = `Pola ${String.fromCharCode(65 + i)} × ${p.frekuensi} batang`;
      html += `<div class="pola"><div class="pola-label">${label}</div>${barHtml(p, stok, kerf)}</div>`;
    });
    html += '</div>';
  });
  box.innerHTML = html;
}

function barHtml(p, stok, kerf) {
  let html = '<div class="bar">';
  let used = 0;
  p.potongan.forEach((len, i) => {
    const w = (len / stok * 100).toFixed(2);
    html += `<div class="seg" style="width:${w}%" title="${len} mm">${len > 300 ? len : ''}</div>`;
    used += len;
    if (i < p.potongan.length - 1) {
      html += `<div class="seg kerf" style="width:${(kerf / stok * 100).toFixed(2)}%"></div>`;
      used += kerf;
    }
  });
  const sisaW = ((stok - used) / stok * 100).toFixed(2);
  const cls = p.reusable ? 'sisa' : 'sisa buang';
  html += `<div class="seg ${cls}" style="width:${sisaW}%" title="sisa ${p.sisa_mm} mm">` +
          `sisa ${p.sisa_mm} ${p.reusable ? '(simpan)' : '(buang)'}</div>`;
  html += '</div>';
  return html;
}

// ── parameter panel ────────────────────────────────────────
function renderParam(cfg, overrideAktif) {
  const oset = new Set(overrideAktif);
  const flag = (k) => oset.has(k) ? ' <span class="ovr-flag">[override]</span>' : '';
  const ld = Object.entries(cfg.ld).map(([k, v]) => `D${k}=${v}`).join(' ');
  const hook = Object.entries(cfg.hook_tail).map(([s, m]) =>
    `${s}°:` + Object.entries(m).map(([d, v]) => `D${d}=${v}`).join(' ')).join(' | ');
  $('paramBody').innerHTML =
    `stok ${cfg.stok_mm} mm | kerf ${cfg.kerf_mm}${flag('kerf_mm')} | ` +
    `sisa min ${cfg.sisa_min_simpan_mm}${flag('sisa_min_simpan_mm')}\n` +
    `cover: ${Object.entries(cfg.cover).map(([k, v]) => `${k}=${v}`).join(' ')}\n` +
    `Ld: ${ld}\n` +
    `hook tail: ${hook}\n` +
    `zona tumpuan ${cfg.zona_tumpuan_faktor}${flag('zona_tumpuan_faktor')} | ` +
    `sengkang pertama ${cfg.jarak_sengkang_pertama_mm} mm | ` +
    `metode ${cfg.metode_hitung}${flag('metode_hitung')}\n` +
    `koreksi bengkokan: ${cfg.koreksi_bend_aktif ? 'AKTIF' : 'nonaktif'}`;
}

// ── tab ────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $('tab-bbs').style.display = b.dataset.tab === 'bbs' ? '' : 'none';
  $('tab-pola').style.display = b.dataset.tab === 'pola' ? '' : 'none';
});

// ── tombol ─────────────────────────────────────────────────
$('btnHitung').onclick = hitung;
$('btnExcel').onclick = async () => {
  const elemen = lastElemen.length ? lastElemen : bacaElemen();
  if (!elemen.length) { alert('Isi minimal satu baris elemen.'); return; }
  const override = lastOverride;
  const res = await fetch('/api/export', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ elemen, override })
  });
  if (!res.ok) {
    const d = await res.json();
    alert(d.error || 'Gagal export');
    return;
  }
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?(.+?)"?$/);
  a.download = m ? m[1] : 'BBS.xlsx';
  a.click();
};

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
