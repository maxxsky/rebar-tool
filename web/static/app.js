/* Rebar BBS web — vanilla JS. NOL logika perhitungan: semua dari backend. */

const $ = (id) => document.getElementById(id);
let templates = {};
let lastResult = null;
let lastElemen = [];
let lastOverride = {};
let proyekAktif = localStorage.getItem('rebar_proyek') || '';

const fmtM = (mm) => (mm / 1000).toFixed(3);
const fmtKg = (v) => v.toFixed(2);

// ── proyek & gambar (08 berlapis) ─────────────────────────
let gambarAktif = '';
let proyekBerlapis = false;
let proyekRaw = null;       // config & templates efektif proyek/gambar aktif
let proyekDefault = null;   // config default proyek (berlapis, 08)
let drawingAsal = null;     // asal tiap nilai: {selimut_beton_mm: {balok: {nilai, asal}}}
let wideOverride = null;    // nilai cobaan 'Hitung dengan nilai ini' (PATCH-02/04)

async function loadProjek() {
  const d = await (await fetch('/api/projects')).json();
  const sel = $('projSelect');
  sel.innerHTML = '<option value="">— pilih proyek —</option>' +
    (d.projects || []).map(p =>
      `<option value="${p.kode}" data-berlapis="${p.berlapis ? 1 : 0}">` +
      `${p.kode} — ${p.nama}</option>`).join('');
  if (proyekAktif) {
    const ok = (d.projects || []).some(p => p.kode === proyekAktif);
    if (ok) sel.value = proyekAktif;
    else { proyekAktif = ''; localStorage.removeItem('rebar_proyek'); }
  }
  if (sel.value) pilihProyek(sel.value);
  return d.projects || [];
}

async function pilihProyek(kode) {
  if (!kode) {
    templates = {}; proyekRaw = null; proyekBerlapis = false;
    $('projLabel').textContent = '';
    $('gbrSelect').style.display = 'none';
    $('btnNewGbr').style.display = 'none';
    return;
  }
  proyekAktif = kode;
  localStorage.setItem('rebar_proyek', kode);
  const opt = $('projSelect').selectedOptions[0];
  proyekBerlapis = opt && opt.dataset.berlapis === '1';

  if (!proyekBerlapis) {
    // flat legacy (F3.6) — tanpa gambar
    const d = await (await fetch(`/api/projects/${kode}`)).json();
    if (!d.ok) return;
    templates = d.templates;
    proyekRaw = { config: d.config, templates: d.templates };
    gambarAktif = '';
    $('projLabel').textContent =
      `${d.config.proyek.nama} (${d.config.proyek.kode}) — ` +
      `${d.config.sumber.dokumen} ${d.config.sumber.revisi}`;
    $('gbrSelect').style.display = 'none';
    $('btnNewGbr').style.display = 'none';
    renderParamFromConfig(d.config, []);
    renderSetupProgress();
    return;
  }

  // berlapis — fetch drawings + default proyek
  const dflt = await (await fetch(`/api/projects/${kode}`)).json();
  if (dflt.ok) proyekDefault = dflt.config;
  const dl = await (await fetch(`/api/projects/${kode}/drawings`)).json();
  const gsel = $('gbrSelect');
  gsel.innerHTML = '<option value="">— pilih gambar —</option>' +
    (dl.drawings || []).map(g =>
      `<option value="${g.kode}">${g.kode} ${g.revisi} — ${g.nama}</option>`).join('');
  gsel.style.display = '';
  $('btnNewGbr').style.display = '';
  if (dl.drawings && dl.drawings.length) {
    gambarAktif = dl.drawings[0].kode;
    gsel.value = gambarAktif;
    await pilihGambar(gambarAktif);
  } else {
    $('projLabel').textContent = `${kode} — belum ada gambar`;
  }
}

async function pilihGambar(gkode) {
  if (!gkode) { gambarAktif = ''; return; }
  gambarAktif = gkode;
  const d = await (await fetch(`/api/projects/${proyekAktif}/drawings/${gkode}`)).json();
  if (!d.ok) { alert(d.error || 'Gagal load gambar'); return; }
  templates = d.templates;
  drawingAsal = d.asal || null;
  proyekRaw = { config: d.config_efektif, templates: d.templates,
                override: d.override || {} };
  const info = d.drawing || {};
  $('projLabel').textContent =
    `${proyekAktif} · ${gkode} ${info.revisi || ''} — ${info.nama || ''}`;
  renderPanelView(d.config_efektif);
  renderSetupProgress();
}

$('gbrSelect').onchange = (e) => pilihGambar(e.target.value);
$('btnNewGbr').onclick = async () => {
  const kode = prompt('Kode gambar (mis. GS-03):');
  if (!kode) return;
  const nama = prompt('Nama gambar (mis. Struktur Atas):');
  const revisi = prompt('Revisi:');
  const tanggal = prompt('Tanggal revisi gambar (YYYY-MM-DD):');
  if (!nama || !revisi || !tanggal) { alert('nama, revisi, tanggal wajib.'); return; }
  alert('Gambar dibuat. Isi HANYA nilai yang berbeda dari parameter proyek — yang dibiarkan kosong akan mengikuti nilai proyek.');
  const res = await fetch(`/api/projects/${proyekAktif}/drawings`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kode, nama, revisi, tanggal })
  });
  const d = await res.json();
  if (!d.ok) { alert(d.error || 'Gagal'); return; }
  await pilihProyek(proyekAktif);
  $('gbrSelect').value = kode;
  await pilihGambar(kode);
};

function updateProjLabel() { /* diganti pilihProyek/pilihGambar */ }

$('projSelect').onchange = (e) => pilihProyek(e.target.value);
$('btnNewProj').onclick = () => bukaWizard('baru');
$('btnEditProj').onclick = async () => {
  if (!proyekAktif) { alert('Pilih proyek dulu.'); return; }
  const d = await (await fetch(`/api/projects/${proyekAktif}`)).json();
  if (d.ok) bukaWizard('edit', d);
};

// ── layar proyek baru (PATCH-04 §7) — daftar status 5 langkah ──
let wiz = null;      // { mode, kode, config, templates }

function bukaWizard(mode, data = null) {
  wiz = {
    mode,
    kode: mode === 'edit' ? data.kode : '',
    config: mode === 'edit' ? data.config : {
      proyek: { nama: '', kode: '' },
      sumber: { dokumen: '', revisi: '', tanggal: '', catatan: '' },
    },
  };
  $('wizTitle').textContent = mode === 'edit' ? `Edit ${data.kode}` : 'Proyek baru';
  $('wizard').style.display = 'flex';
  renderWizard();
}

function wizClose() { $('wizard').style.display = 'none'; wiz = null; }
$('wizClose').onclick = wizClose;

function renderWizard() {
  const c = wiz.config;
  const wajib = (v) => (v && String(v).trim()) ? ' ✅' : '';
  const isEdit = wiz.mode === 'edit';
  $('wizBody').innerHTML = `
    <div class="wiz-hint" style="margin-bottom:10px">Alur setup proyek — 5 langkah. Boleh lompat; yang penting tahu mana yang belum.</div>
    <div class="steps" style="margin-bottom:12px">
      <span class="step active">1 Buat proyek</span>
      <span class="step">2 Parameter proyek</span>
      <span class="step">3 Gambar</span>
      <span class="step">4 Template elemen</span>
      <span class="step">5 Hitung</span>
    </div>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Nama proyek *${wajib(c.proyek.nama)}</label>
        <input id="n1nama" value="${esc(c.proyek.nama)}"></div>
      <div class="wiz-field"><label>Kode *${wajib(c.proyek.kode)}</label>
        <input id="n1kode" value="${esc(c.proyek.kode)}" placeholder="PRJ-001">
        <div class="wiz-hint">Hanya A-Z, a-z, 0-9, _ atau -.</div></div>
      <div class="wiz-field"><label>Dokumen sumber *${wajib(c.sumber.dokumen)}</label>
        <input id="n1dok" value="${esc(c.sumber.dokumen)}" placeholder="Gambar Struktur GS-01"></div>
      <div class="wiz-field"><label>Revisi *${wajib(c.sumber.revisi)}</label>
        <input id="n1rev" value="${esc(c.sumber.revisi)}" placeholder="Rev.3"></div>
      <div class="wiz-field"><label>Tanggal revisi gambar *${wajib(c.sumber.tanggal)}</label>
        <input id="n1tgl" type="date" value="${esc(c.sumber.tanggal)}"></div>
    </div>
    <div class="wiz-field"><label>Catatan sumber</label>
      <input id="n1cat" value="${esc(c.sumber.catatan)}" placeholder="tabel notes GS-01 sheet 2"></div>
    ${isEdit ? '' : `<div class="wiz-hint" style="margin-top:8px">
      Setelah proyek dibuat: isi parameter proyek & tambah gambar lewat panel kiri.</div>`}`;
  $('wizSave').style.display = '';
}

$('wizSave').onclick = async () => {
  const c = wiz.config;
  c.proyek.nama = $('n1nama').value.trim();
  c.proyek.kode = $('n1kode').value.trim();
  c.sumber.dokumen = $('n1dok').value.trim();
  c.sumber.revisi = $('n1rev').value.trim();
  c.sumber.tanggal = $('n1tgl').value;
  c.sumber.catatan = $('n1cat').value.trim();
  if (!c.proyek.nama || !c.proyek.kode || !c.sumber.dokumen || !c.sumber.revisi || !c.sumber.tanggal) {
    alert('Nama, kode, dan tiga field sumber wajib diisi.'); return;
  }
  if (wiz.mode === 'edit') {
    const res = await fetch(`/api/projects/${wiz.kode}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kode: c.proyek.kode, config: {
        proyek: c.proyek, sumber: c.sumber,
        ...(wiz.extraConfig || {}) }, templates: wiz.extraTemplates || {} })
    });
    const d = await res.json();
    if (!d.ok) { alert(d.error || 'Gagal'); return; }
  } else {
    const payload = { kode: c.proyek.kode, config: {
      proyek: c.proyek, sumber: c.sumber,
      stok: { panjang_batang_mm: 12000, kerf_mm: 3, sisa_min_simpan_mm: 1000 },
      selimut_beton_mm: {}, panjang_penyaluran_mm: {}, lap_splice_mm: {},
      unit_weight_kg_per_m: {}, hook: {}, sengkang: {},
      optimizer: { max_pola: 8, batasi_pola: false } },
      templates: { balok: {} } };
    const res = await fetch('/api/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) });
    const d = await res.json();
    if (res.status === 409) { alert(`${d.error} — pakai kode lain.`); return; }
    if (!d.ok) { alert(d.error || 'Gagal'); return; }
  }
  wizClose();
  await loadProjek();
  $('projSelect').value = c.proyek.kode;
  await pilihProyek(c.proyek.kode);
};

// ── baris elemen ───────────────────────────────────────────
function renderRows(n) {
  const box = $('rows');
  box.innerHTML = '';
  for (let i = 0; i < n; i++) box.appendChild(newRow());
}
function newRow() {
  const div = document.createElement('div');
  div.className = 'elem-row';
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
  const dl = document.createElement('datalist');
  dl.id = 'tipeList';
  Object.keys((templates.balok) || {}).forEach(t => {
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
    if (!tipe && !bentang && !jumlah) return;
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
  // override 4-field + override luas 'Pakai sekali' (PATCH-02)
  const override = { ...bacaOverride() };
  if (wideOverride) Object.assign(override, wideOverride);
  lastElemen = elemen; lastOverride = override;

  const res = await fetch('/api/hitung', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ elemen, override, proyek: proyekAktif, gambar: gambarAktif })
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
  if (!rows.length) { box.innerHTML = '<div class="kosong">Tekan Hitung untuk melihat hasil.</div>'; return; }
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
  const flag = (k) => oset.has(k) ? ' <span class="ovr-flag">[nilai cobaan]</span>' : '';
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
  $('paramActions').style.display = proyekAktif ? '' : 'none';
  $('paramForm').style.display = 'none';
  $('paramBody').style.display = '';
  $('btnParamEdit').textContent = '✎ Edit';
}

function renderParamFromConfig(cfg, overrideAktif) {
  const c = {
    stok_mm: cfg.stok.panjang_batang_mm,
    kerf_mm: cfg.stok.kerf_mm,
    sisa_min_simpan_mm: cfg.stok.sisa_min_simpan_mm,
    cover: cfg.selimut_beton_mm,
    ld: Object.fromEntries(Object.entries(cfg.panjang_penyaluran_mm).map(([k, v]) => [k, v])),
    hook_tail: { '135': cfg.hook.tail_135_mm || {}, '90': cfg.hook.tail_90_mm || {} },
    zona_tumpuan_faktor: cfg.sengkang.zona_tumpuan_faktor,
    jarak_sengkang_pertama_mm: cfg.sengkang.jarak_sengkang_pertama_mm,
    metode_hitung: cfg.sengkang.metode_hitung,
    koreksi_bend_aktif: cfg.hook.koreksi_bengkokan_aktif,
  };
  renderParam(c, overrideAktif || []);
}

// ── tampilan panel dengan asal nilai (08 §5 / PATCH-04 §5) ─
function renderPanelView(cfg) {
  $('paramActions').style.display = proyekAktif ? '' : 'none';
  $('paramForm').style.display = 'none';
  $('paramBody').style.display = '';
  $('btnParamEdit').textContent = '✎ Edit';
  // judul panel: sebutkan gambar
  const gname = gambarAktif || (proyekAktif || '');
  $('paramTitle').textContent = `▸ NILAI TEKNIS — ${gname}`;
  if (!drawingAsal) { renderParam(cfg, []); return; }
  const a = drawingAsal;
  const m = (x) => (x && x.asal === 'gambar')
    ? ' <span class="ovr-flag">[dari gambar ini]</span>'
    : ' <span class="wz-proyek">[dari proyek]</span>';
  const coverTxt = Object.entries(a.selimut_beton_mm || {}).map(([k, v]) =>
    `${k}=${v.nilai}${m(v)}`).join(' ');
  const ldTxt = Object.entries(a.panjang_penyaluran_mm || {}).map(([k, v]) =>
    `D${k}=${v.nilai}${m(v)}`).join(' ');
  const hookTxt = Object.entries(a.hook_tail || {}).map(([s, mm]) =>
    `${s.replace('tail_', '').replace('_mm', '')}°:` +
    Object.entries(mm).map(([d, v]) => `D${d}=${v.nilai}${m(v)}`).join(' ')
  ).join(' | ');
  const skTxt = Object.entries(a.sengkang || {}).map(([k, v]) =>
    `${k}=${v.nilai}${m(v)}`).join(' | ');
  $('paramBody').innerHTML =
    `stok ${cfg.stok_mm} mm | kerf ${cfg.kerf_mm} | sisa min ${cfg.sisa_min_simpan_mm} ${m({asal:'proyek'})}\n` +
    `cover: ${coverTxt}\n` +
    `Ld: ${ldTxt}\n` +
    `hook tail: ${hookTxt}\n` +
    `sengkang: ${skTxt}\n` +
    `koreksi bengkokan: ${cfg.koreksi_bend_aktif ? 'AKTIF' : 'nonaktif'}\n` +
    `<span style="color:#b45309;font-size:10.5px">[dari gambar ini] = nilai khusus gambar; sisanya ikut proyek</span>`;
}

// ── edit panel (PATCH-02 §1) ───────────────────────────────
const UWTABEL = { 10: 0.617, 13: 1.042, 16: 1.578, 19: 2.226, 22: 2.984, 25: 3.853 };

function diffOverride(formConfig, defConfig) {
  /* Hanya field yang beda dari default proyek — yang lain diwarisi (08 §5.1). */
  const ovr = {};
  const diffDict = (dk, fk) => {
    const d = defConfig[dk] || {}, f = formConfig[fk] || {};
    const out = {};
    for (const k of new Set([...Object.keys(d), ...Object.keys(f)])) {
      if (f[k] !== undefined && String(f[k]) !== String(d[k] ?? '')) out[k] = f[k];
    }
    return out;
  };
  const c = diffDict('selimut_beton_mm', 'selimut_beton_mm');
  if (Object.keys(c).length) ovr.selimut_beton_mm = c;
  const ld = diffDict('panjang_penyaluran_mm', 'panjang_penyaluran_mm');
  if (Object.keys(ld).length) ovr.panjang_penyaluran_mm = ld;
  const lap = diffDict('lap_splice_mm', 'lap_splice_mm');
  if (Object.keys(lap).length) ovr.lap_splice_mm = lap;
  const uw = diffDict('unit_weight_kg_per_m', 'unit_weight_kg_per_m');
  if (Object.keys(uw).length) ovr.unit_weight_kg_per_m = uw;
  const h135 = diffDict('tail_135_mm', 'tail_135_mm');
  const h90 = diffDict('tail_90_mm', 'tail_90_mm');
  if (Object.keys(h135).length || Object.keys(h90).length) {
    ovr.hook = {};
    if (Object.keys(h135).length) ovr.hook.tail_135_mm = h135;
    if (Object.keys(h90).length) ovr.hook.tail_90_mm = h90;
  }
  const dsk = defConfig.sengkang || {}, fsk = formConfig.sengkang || {};
  const sk = {};
  for (const k of ['zona_tumpuan_faktor', 'jarak_sengkang_pertama_mm', 'metode_hitung']) {
    if (fsk[k] !== undefined && String(fsk[k]) !== String(dsk[k] ?? '')) sk[k] = fsk[k];
  }
  if (Object.keys(sk).length) ovr.sengkang = sk;
  if (formConfig.hook && defConfig.hook &&
      !!formConfig.hook.koreksi_bengkokan_aktif !== !!defConfig.hook.koreksi_bengkokan_aktif) {
    ovr.hook = ovr.hook || {};
    ovr.hook.koreksi_bengkokan_aktif = !!formConfig.hook.koreksi_bengkokan_aktif;
  }
  return ovr;
}

function renderPanelEdit() {
  if (!proyekRaw) return;
  const c = proyekRaw.config;
  const dias = new Set([...Object.keys(c.panjang_penyaluran_mm || {}),
                        ...Object.keys(c.hook.tail_135_mm || {}),
                        ...Object.keys(c.hook.tail_90_mm || {}),
                        ...Object.keys(c.unit_weight_kg_per_m || {}),
                        ...Object.keys(c.lap_splice_mm || {})].map(Number));
  const rows = [...dias].sort((a, b) => a - b).map(d => `
    <tr data-dia="${d}">
      <td><b>D${d}</b></td>
      <td><input class="e-ld" type="number" value="${c.panjang_penyaluran_mm[d] || ''}"></td>
      <td><input class="e-lap" type="number" value="${c.lap_splice_mm[d] || ''}"></td>
      <td><input class="e-uw" type="number" step="0.001" value="${c.unit_weight_kg_per_m[d] ?? UWTABEL[d] ?? ''}"></td>
      <td><input class="e-h135" type="number" value="${c.hook.tail_135_mm[d] || ''}"></td>
      <td><input class="e-h90" type="number" value="${c.hook.tail_90_mm[d] || ''}"></td>
    </tr>`).join('');
  const sk = c.sengkang;
  $('paramForm').innerHTML = `
    <div class="wiz-warn">Nilai Ld, selimut beton, dan hook harus dari gambar proyek ini — bukan dari standar generik atau proyek lain.</div>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Panjang stok (mm)</label>
        <input id="ePanjang" type="number" value="${c.stok.panjang_batang_mm}"></div>
      <div class="wiz-field"><label>Kerf (mm)</label>
        <input id="eKerf" type="number" value="${c.stok.kerf_mm}"></div>
      <div class="wiz-field"><label>Sisa min (mm)</label>
        <input id="eSisa" type="number" value="${c.stok.sisa_min_simpan_mm}"></div>
      <div class="wiz-field"><label>Cover balok</label>
        <input id="eCoverB" type="number" value="${c.selimut_beton_mm.balok || ''}"></div>
      <div class="wiz-field"><label>Cover kolom</label>
        <input id="eCoverK" type="number" value="${c.selimut_beton_mm.kolom || ''}"></div>
      <div class="wiz-field"><label>Cover plat</label>
        <input id="eCoverP" type="number" value="${c.selimut_beton_mm.plat || ''}"></div>
    </div>
    <table class="dia-table"><thead><tr>
      <th>Ø</th><th>Ld</th><th>Lap</th><th>UW</th><th>H135</th><th>H90</th></tr></thead>
      <tbody id="panelDia">${rows}</tbody></table>
    <button class="btn" onclick="panelAddDia()">+ diameter</button>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Zona tumpuan</label>
        <input id="eZona" type="number" step="0.05" value="${sk.zona_tumpuan_faktor}"></div>
      <div class="wiz-field"><label>Sengkang pertama</label>
        <input id="ePertama" type="number" value="${sk.jarak_sengkang_pertama_mm}"></div>
      <div class="wiz-field"><label>Metode</label>
        <select id="eMetode"><option value="kontinyu" ${sk.metode_hitung === 'kontinyu' ? 'selected' : ''}>kontinyu</option>
        <option value="per_zona" ${sk.metode_hitung === 'per_zona' ? 'selected' : ''}>per_zona</option></select></div>
    </div>
    <div class="wiz-field"><label><input id="eKoreksi" type="checkbox" ${c.hook.koreksi_bengkokan_aktif ? 'checked' : ''}>
      Koreksi bengkokan aktif</label></div>
    <div class="ovr-actions">
      <button class="btn primary" onclick="panelPakaiSekali()">Hitung dengan nilai ini</button>
      <button class="btn" onclick="panelSimpanConfig()">Simpan ke gambar ${gambarAktif || proyekAktif}</button>
      <button class="btn" onclick="renderPanelView(proyekRaw.config)">Batal</button>
    </div>`;
  $('paramForm').style.display = '';
  $('paramBody').style.display = 'none';
  $('paramActions').style.display = 'none';
  $('btnParamEdit').textContent = '';
}

function panelAddDia() {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><input class="e-dia" type="number" placeholder="Ø"></td>
    <td><input class="e-ld" type="number"></td><td><input class="e-lap" type="number"></td>
    <td><input class="e-uw" type="number" step="0.001"></td>
    <td><input class="e-h135" type="number"></td><td><input class="e-h90" type="number"></td>`;
  $('panelDia').appendChild(tr);
}

function bacaPanelForm() {
  const c = proyekRaw.config;
  c.stok.panjang_batang_mm = +$('ePanjang').value;
  c.stok.kerf_mm = +$('eKerf').value;
  c.stok.sisa_min_simpan_mm = +$('eSisa').value;
  c.selimut_beton_mm = { balok: +$('eCoverB').value, kolom: +$('eCoverK').value,
                         plat: +$('eCoverP').value };
  const ld = {}, lap = {}, uw = {}, h135 = {}, h90 = {};
  document.querySelectorAll('#panelDia tr').forEach(tr => {
    const diaInput = tr.querySelector('.e-dia');
    const diaRaw = (tr.querySelector('b') || {}).textContent || '';
    const dia = diaInput && diaInput.value !== '' ? +diaInput.value
               : (parseInt(diaRaw.replace('D', '')) || NaN);
    if (!isNaN(dia)) {
      const v = (sel) => { const x = tr.querySelector(sel); return x && x.value !== '' ? +x.value : undefined; };
      const a = v('.e-ld'); if (a) ld[dia] = a;
      const b = v('.e-lap'); if (b) lap[dia] = b;
      const u = v('.e-uw'); if (u) uw[dia] = u;
      const h1 = v('.e-h135'); if (h1) h135[dia] = h1;
      const h2 = v('.e-h90'); if (h2) h90[dia] = h2;
    }
  });
  c.panjang_penyaluran_mm = ld;
  c.lap_splice_mm = lap;
  c.unit_weight_kg_per_m = uw;
  c.hook.tail_135_mm = h135;
  c.hook.tail_90_mm = h90;
  c.sengkang.zona_tumpuan_faktor = +$('eZona').value;
  c.sengkang.jarak_sengkang_pertama_mm = +$('ePertama').value;
  c.sengkang.metode_hitung = $('eMetode').value;
  c.hook.koreksi_bengkokan_aktif = $('eKoreksi').checked;
  return c;
}

function panelPakaiSekali() {
  const c = bacaPanelForm();
  wideOverride = {
    stok: c.stok, cover: c.selimut_beton_mm, ld: c.panjang_penyaluran_mm,
    lap: c.lap_splice_mm, unit_weight: c.unit_weight_kg_per_m,
    hook_tail: { '135': c.hook.tail_135_mm, '90': c.hook.tail_90_mm },
    bend_factor: c.hook.diameter_bengkok_faktor,
    koreksi_bend_aktif: c.hook.koreksi_bengkokan_aktif,
    sengkang: c.sengkang,
  };
  showOverrideBanner();
  renderParamFromConfig(proyekRaw.config, []);
  hitung();
}

function showOverrideBanner() {
  const b = $('warnBanner');
  const n = Object.keys(bacaOverride()).length + (wideOverride ? 1 : 0);
  b.textContent = '⚠ Hasil ini memakai NILAI COBAAN — tidak sesuai config. Jangan dipakai untuk pemesanan. Simpan permanen lewat panel Nilai teknis kalau cocok.';
  b.className = 'show';
  b.style.background = '#fee2e2';
  b.style.borderBottomColor = '#b4232c';
  $('cobaPanel').querySelector('summary').textContent =
    `▸ Coba nilai lain (${n} aktif) — tidak disimpan`;
}

function renderSetupProgress() {
  const box = $('setupProgress');
  if (!proyekAktif) { box.innerHTML = ''; return; }
  const tplCount = proyekRaw && proyekRaw.templates && (proyekRaw.templates.balok || proyekRaw.templates)
    ? Object.keys(proyekRaw.templates.balok || proyekRaw.templates).length : 0;
  const gCount = $('gbrSelect').options.length - 1;
  const p = proyekBerlapis
    ? `<span class="ok">✓ parameter proyek</span> <span class="ok">✓ ${gCount} gambar</span>` +
      (tplCount ? ` <span class="ok">✓ ${tplCount} template elemen</span>`
                : ` <span class="warn">⚠ belum ada template elemen</span>`)
    : `<span class="ok">✓ parameter proyek</span> <span class="warn">⚠ belum ada gambar</span>`;
  box.innerHTML = `${proyekAktif} — ${p}`;
  // tombol Hitung nonaktif kalau template kosong
  const btn = $('btnHitung');
  if (!tplCount) {
    btn.disabled = true;
    btn.title = 'Setup belum lengkap — tambahkan template elemen lewat panel Nilai teknis.';
  } else {
    btn.disabled = false;
    btn.title = '';
  }
}

async function panelSimpanConfig() {
  const c = bacaPanelForm();
  const revisi = prompt('Revisi gambar yang jadi dasar nilai baru (wajib):', proyekRaw.config.sumber?.revisi || '');
  if (revisi === null) return;
  const catatan = prompt('Catatan — dari mana nilainya diambil (wajib):', proyekRaw.config.sumber?.catatan || '');
  if (catatan === null) return;
  const koreksi = confirm('Centang OK kalau ini KOREKSI SALAH KETIK, bukan revisi gambar.');
  c.sumber.revisi = revisi.trim();
  c.sumber.catatan = catatan.trim();

  if (proyekBerlapis && gambarAktif && proyekDefault) {
    // simpan ke GAMBAR — override saja (yang beda dari default proyek)
    const ovr = diffOverride(c, proyekDefault);
    const res = await fetch(`/api/projects/${proyekAktif}/drawings/${gambarAktif}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ override: ovr, revisi: revisi.trim(),
                             catatan: catatan.trim(),
                             koreksi_bukan_revisi: koreksi })
    });
    const d = await res.json();
    if (!d.ok) { alert(d.error || 'Gagal simpan'); return; }
    wideOverride = null;
    $('warnBanner').className = '';
    alert('Tersimpan ke gambar. File lama diarsipkan.');
    await pilihGambar(gambarAktif);
    return;
  }

  // flat legacy — PATCH /api/config
  const res = await fetch('/api/config', {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kode: proyekAktif, config: c, templates: proyekRaw.templates,
                           revisi: revisi.trim(), catatan: catatan.trim(),
                           koreksi_bukan_revisi: koreksi })
  });
  const d = await res.json();
  if (!d.ok) { alert(d.error || 'Gagal simpan'); return; }
  wideOverride = null;
  $('warnBanner').className = '';
  alert('Tersimpan. File lama diarsipkan.');
  await pilihProyek(proyekAktif);
}

$('btnParamEdit').onclick = () => renderPanelEdit();
$('btnParamYaml').onclick = () => {
  const a = document.createElement('a');
  a.href = `/api/projects/${proyekAktif}/yaml`;
  a.download = `${proyekAktif}.yaml`;
  a.click();
};

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
    body: JSON.stringify({ elemen, override, proyek: proyekAktif, gambar: gambarAktif })
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

// ── init ───────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeHtml(s) { return esc(s); }

(async () => {
  const projs = await loadProjek();
  renderRows(1);
  if (proyekAktif) await pilihProyek(proyekAktif);
  // warning dari proyek aktif (banner)
  const d = await (await fetch('/api/config')).json();
  if (d.ok && d.config.warnings && d.config.warnings.length) {
    $('warnBanner').textContent = d.config.warnings.join(' | ');
    $('warnBanner').classList.add('show');
  }
})();
