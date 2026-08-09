/* Rebar BBS web — 09-SPEC redesign (Kerja/Setup). NOL logika perhitungan:
   semua angka dari backend. Web hanya render + setup config. */

const $ = (id) => document.getElementById(id);
let templates = {};
let lastResult = null;
let lastElemen = [];
let lastOverride = {};
let proyekAktif = localStorage.getItem('rebar_proyek') || '';

const fmtM = (mm) => (mm / 1000).toFixed(3);
const fmtKg = (v) => Number(v || 0).toFixed(2);

// ── proyek & gambar (08 berlapis) ─────────────────────────
let gambarAktif = '';
let proyekBerlapis = false;
let proyekRaw = null;       // config & templates efektif proyek/gambar aktif
let proyekDefault = null;   // config default proyek (berlapis, 08)
let drawingAsal = null;     // asal tiap nilai: {selimut_beton_mm: {balok: {nilai, asal}}}
let wideOverride = null;    // nilai cobaan 'Hitung dengan nilai ini' (PATCH-02/04)
let areaAktif = 'kerja';    // 09-SPEC: 'kerja' | 'setup'
let setupPageAktif = 'proyek';

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
    updateSetupNav();
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
    renderTeknisRingkas(proyekRaw.config);
    updateSetupNav();
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
  refreshTipeOptions();
  if (dl.drawings && dl.drawings.length) {
    gambarAktif = dl.drawings[0].kode;
    gsel.value = gambarAktif;
    await pilihGambar(gambarAktif);
  } else {
    $('projLabel').textContent = `${kode} — belum ada gambar`;
    updateSetupNav();
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
  refreshTipeOptions();
  const info = d.drawing || {};
  $('projLabel').textContent =
    `${proyekAktif} · ${gkode} ${info.revisi || ''} — ${info.nama || ''}`;
  renderTeknisRingkas(d.config_efektif);
  updateSetupNav();
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
  if (areaAktif === 'setup') renderSetupPage(setupPageAktif);
};

$('projSelect').onchange = (e) => pilihProyek(e.target.value);
$('btnNewProj').onclick = () => bukaWizard('baru');

// ── area Kerja / Setup (09-SPEC §2) ────────────────────────
function switchArea(area) {
  areaAktif = area;
  document.querySelectorAll('.area-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.area === area));
  $('areaKerja').style.display = area === 'kerja' ? '' : 'none';
  $('areaSetup').style.display = area === 'setup' ? '' : 'none';
  if (area === 'setup') renderSetupPage(setupPageAktif);
}
$('navKerja').onclick = () => switchArea('kerja');
$('navSetup').onclick = () => switchArea('setup');
$('linkLihatSemua').onclick = (e) => { e.preventDefault(); switchArea('setup'); };

// satu baris nilai teknis ringkas (09-SPEC §3.1)
function renderTeknisRingkas(cfg) {
  const box = $('teknisRingkas');
  if (!cfg) { box.textContent = ''; return; }
  const cover = Object.entries(cfg.cover || {})
    .map(([k, v]) => `cover ${k}=${v}`).join(' ');
  const ld = Object.entries(cfg.ld || {})
    .map(([k, v]) => `Ld D${k}=${v}`).join(' ');
  const metode = cfg.metode_hitung || '';
  box.textContent = `${cover} · ${ld} · ${metode}`;
}

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
  const wajib = (v) => v ? '' : ' <span style="color:var(--karat)">* wajib</span>';
  const c = wiz.config;
  const isEdit = wiz.mode === 'edit';
  $('wizBody').innerHTML = `
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
      Setelah proyek dibuat: isi parameter proyek & tambah gambar lewat Setup.</div>`}`;
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
  switchArea('setup');
  renderSetupPage('proyek');
};

// ── baris elemen (09-SPEC §3.2: select tipe, mm suffix, lokasi) ──
function renderRows(n) {
  const box = $('rows');
  box.innerHTML = '';
  for (let i = 0; i < n; i++) box.appendChild(newRow());
}
function tipeOptions(selected) {
  const tpls = (templates && (templates.balok || templates)) || {};
  const names = Object.keys(tpls);
  if (!names.length) return '<option value="">— belum ada tipe —</option>';
  return '<option value="">— pilih —</option>' + names.map(t =>
    `<option value="${esc(t)}" ${t === selected ? 'selected' : ''}>${esc(t)}</option>`).join('');
}
function newRow(tipe = '', bentang = '', jumlah = '', lokasi = '') {
  const div = document.createElement('div');
  div.className = 'elem-row';
  div.innerHTML = `
    <select class="t-tipe" title="tipe elemen (dari template)">${tipeOptions(tipe)}</select>
    <div class="unit-mm"><input type="number" step="any" min="1" placeholder="6000" class="t-bentang" value="${esc(bentang)}"><span>mm</span></div>
    <div class="unit-mm"><input type="number" step="any" min="1" placeholder="—" class="t-bentang2" value="" style="display:none"><span style="display:none">mm</span></div>
    <input type="number" step="1" min="1" placeholder="1" class="t-jumlah" value="${esc(jumlah)}">
    <input type="text" placeholder="Lt.2 as A-B" class="t-lokasi" value="${esc(lokasi)}">
    <button class="del" title="hapus">✕</button>`;
  div.querySelector('.del').onclick = () => {
    if (document.querySelectorAll('.elem-row').length > 1) div.remove();
  };
  // 12-SPEC §8: placeholder & bantuan per baris mengikuti tipe yang dipilih
  const bentangInput = div.querySelector('.t-bentang');
  const bentang2Wrap = div.querySelector('.t-bentang2').parentElement;
  const bentang2Input = div.querySelector('.t-bentang2');
  const selTipe = div.querySelector('.t-tipe');
  const updateBantuan = () => {
    const tpl = templates && templates[selTipe.value] || null;
    const t = tpl || {};
    bentangInput.placeholder = t.label_L || 'dimensi utama';
    // 13-SPEC §8: kolom Dimensi 2 muncul hanya utk plat
    const isPlat = t.tipe === 'plat';
    bentang2Input.style.display = isPlat ? '' : 'none';
    bentang2Input.parentElement.querySelector('span').style.display = isPlat ? '' : 'none';
    bentang2Input.placeholder = t.label_L2 || 'dimensi 2';
    const hint = t.bantuan_L || '';
    let el = div.querySelector('.t-hintL');
    if (hint) {
      if (!el) {
        el = document.createElement('div');
        el.className = 't-hintL wiz-hint';
        el.style.gridColumn = '2 / 6';
        div.appendChild(el);
      }
      el.textContent = hint;
    } else if (el) { el.remove(); }
  };
  selTipe.addEventListener('change', updateBantuan);
  updateBantuan();
  // Enter di baris terakhir → baris baru; Ctrl+Enter → Hitung (global juga)
  div.querySelector('.t-jumlah').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.ctrlKey) {
      e.preventDefault();
      const rowsAll = document.querySelectorAll('.elem-row');
      if (div === rowsAll[rowsAll.length - 1]) $('rows').appendChild(newRow());
    }
  });
  return div;
}
$('btnAdd').onclick = () => $('rows').appendChild(newRow());

// ── baca input ─────────────────────────────────────────────
function refreshTipeOptions() {
  // setelah proyek/gambar berubah, isi ulang <select> tipe di semua baris
  document.querySelectorAll('.elem-row .t-tipe').forEach(sel => {
    const cur = sel.value;
    sel.innerHTML = tipeOptions(cur);
    sel.dispatchEvent(new Event('change'));   // update placeholder/bantuan per tipe
  });
}
function bacaElemen() {
  const out = [];
  document.querySelectorAll('.elem-row').forEach(row => {
    const tipe = row.querySelector('.t-tipe').value.trim();
    const bentang = row.querySelector('.t-bentang').value;
    const b2 = row.querySelector('.t-bentang2').value;
    const jumlah = row.querySelector('.t-jumlah').value;
    const lokasi = row.querySelector('.t-lokasi').value.trim();
    if (!tipe && !bentang && !jumlah) return;
    out.push({ tipe, bentang_bersih_mm: Number(bentang),
               L2_mm: b2 !== '' ? Number(b2) : 0,
               jumlah: Number(jumlah), lokasi });
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
  // counter override aktif di title Coba nilai lain (PATCH-04 §3, 09 §3.1)
  const nOvr = Object.keys(override).length;
  const s = $('cobaPanel').querySelector('summary');
  if (s) s.textContent = nOvr
    ? `▸ Coba nilai lain (${nOvr} aktif) — tidak disimpan`
    : '▸ Coba nilai lain';
  renderStat(d.total);
  renderTeknisRingkas(d.config);
  renderBBS(d.bbs, d);
  renderPola(d.optimizer);
}

// ── error ──────────────────────────────────────────────────
function renderError(d) {
  const box = $('tab-bbs');
  const flag = d.bug_internal
    ? '<div style="color:var(--karat);font-weight:800;margin-bottom:6px">⚠ BUG INTERNAL — laporkan ke developer</div>'
    : '';
  box.innerHTML = `<div style="background:#FBEAE5;border:1px solid #E8C4B6;padding:12px;
       border-radius:6px;color:#7C3320;font-family:ui-monospace,monospace;font-size:12px;
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
  // total_m & berat_kg dikirim backend (PATCH-06 §4) — JS TIDAK menghitung ulang
  let totalBerat = 0, totalPanjang = 0;
  rows.forEach(r => { totalBerat += r.berat_kg || 0; totalPanjang += r.total_m || 0; });
  const adaSambungan = rows.some(r => r.bagian);
  // 12-SPEC §8: kelompokkan per tipe elemen kalau >1 tipe
  const byTipe = {};
  rows.forEach(r => { (byTipe[r.tipe] = byTipe[r.tipe] || []).push(r); });
  const tipeKeys = Object.keys(byTipe);
  let html = '';
  tipeKeys.forEach(tipe => {
    const trows = byTipe[tipe];
    if (tipeKeys.length > 1) html += `<h4 style="margin:12px 0 4px;font-size:13px">${esc(tipe)}</h4>`;
    html += `<table><thead><tr>
      <th>Bar Mark</th><th>Lokasi</th><th>Posisi</th><th>Shape</th><th>Ø</th>
      <th class="num">Panjang (m)</th><th class="num">Jumlah</th>
      <th class="num">Total (m)</th><th class="num">Berat (kg)</th>`;
    if (adaSambungan) html += '<th>Bagian</th>';
    html += '</tr></thead><tbody>';
    trows.forEach(r => {
      const bagianTxt = r.bagian ? `${r.bagian[0]}/${r.bagian[1]}` : '';
      html += `<tr>
        <td>${escapeHtml(r.bar_mark || '')}</td><td>${escapeHtml(r.lokasi || '')}</td><td>${escapeHtml(r.posisi)}</td>
        <td>${escapeHtml(r.shape)}</td><td>${r.dia}</td>
        <td class="num">${fmtM(r.panjang_mm)}</td><td class="num">${r.jumlah}</td>
        <td class="num">${fmtKg(r.total_m)}</td><td class="num">${fmtKg(r.berat_kg)}</td>
        ${r.bagian ? `<td>${bagianTxt}</td>` : ''}
      </tr>`;
    });
    const colspan = adaSambungan ? 8 : 7;
    html += `<tr class="total"><td colspan="${colspan}">TOTAL ${esc(tipe)}</td>
      <td class="num">${fmtKg(trows.reduce((a, r) => a + (r.total_m || 0), 0))}</td>
      <td class="num">${fmtKg(trows.reduce((a, r) => a + (r.berat_kg || 0), 0))}</td></tr></tbody></table>`;
  });
  // 11-SPEC §10: baris ringkas tambahan baja
  const lr = d.lap_report || {};
  const dias = Object.keys(lr);
  if (dias.length) {
    const totTamb = dias.reduce((a, k) => a + (lr[k].tambahan_m || 0), 0);
    const totBat = dias.reduce((a, k) => a + (lr[k].batang_tersambung || 0), 0);
    const pct = dias.reduce((a, k) => a + (lr[k].pct || 0), 0) / dias.length;
    html += `<div class="lap-note" style="margin-top:8px;font-size:12px;color:var(--tinta2)">
      <b>${totBat} batang tersambung</b> · tambahan baja ${fmtKg(totTamb)} m
      (rata-rata ${pct.toFixed(1)}%) — lihat rincian per diameter di bawah</div>`;
  }
  box.innerHTML = html;
}

function renderPola(opt) {
  const box = $('tab-pola');
  const dias = Object.keys(opt).map(Number).sort((a, b) => a - b);
  if (!dias.length) { box.innerHTML = '<div style="color:var(--tinta2)">—</div>'; return; }
  const cfg = lastResult.config;
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
      `berat ${fmtKg(r.berat_kg)} kg · ` +
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

// ── parameter panel (Setup › Nilai teknis) ────────────────
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
    `koreksi bengkokan: ${cfg.koreksi_bend_aktif ? 'AKTIF' : 'nonaktif'}` +
    (cfg.koreksi_bend_aktif
      ? ' ⚠ Pastikan `hook tail` dan `bend deduction` memakai konvensi yang ' +
        'sama (A: hook total termasuk lengkung vs B: ekor lurus saja). ' +
        'Verifikasi ke BBS asli sebelum memakai hasil (F4).'
      : '');
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

function renderPanelView(cfg, overrideAktif) {
  const gname = gambarAktif || (proyekAktif || '');
  const title = $('paramTitle');
  if (title) title.textContent = `▸ NILAI TEKNIS — ${gname}`;
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
    `koreksi bengkokan: ${cfg.koreksi_bend_aktif ? 'AKTIF' : 'nonaktif'}` +
    (cfg.koreksi_bend_aktif
      ? ' ⚠ Pastikan `hook tail` dan `bend deduction` memakai konvensi yang ' +
        'sama (A: hook total termasuk lengkung vs B: ekor lurus saja). ' +
        'Verifikasi ke BBS asli sebelum memakai hasil (F4).'
      : '') + '\n' +
    `<span style="color:var(--karat);font-size:10.5px">[dari gambar ini] = nilai khusus gambar; sisanya ikut proyek</span>`;
}

// ── edit panel (PATCH-02 §1) ───────────────────────────────
const UWTABEL = { 10: 0.617, 13: 1.042, 16: 1.578, 19: 2.226, 22: 2.984, 25: 3.853 };

function yamlDariEfektif() {
  /* Dict format YAML asli (proyekDefault + override gambar) — dipakai form
     edit supaya diffOverride/panelSimpanConfig dapat format yang benar.
     proyekRaw.config dari GET drawing berformat config_efektif (hook_tail,
     stok_mm) — bukan YAML asli. */
  if (!proyekDefault) return JSON.parse(JSON.stringify(proyekRaw.config || {}));
  const y = JSON.parse(JSON.stringify(proyekDefault));
  const ovr = (proyekRaw && proyekRaw.override) || {};
  for (const k of Object.keys(ovr)) {
    const v = ovr[k];
    if (v && typeof v === 'object' && !Array.isArray(v) &&
        y[k] && typeof y[k] === 'object' && !Array.isArray(y[k])) {
      y[k] = { ...y[k], ...v };
    } else {
      y[k] = v;
    }
  }
  return y;
}

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
  const c = yamlDariEfektif();
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
  const c = yamlDariEfektif();
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
  switchArea('kerja');
  hitung();
}

function showOverrideBanner() {
  const b = $('warnBanner');
  const n = Object.keys(bacaOverride()).length + (wideOverride ? 1 : 0);
  b.textContent = '⚠ Hasil ini memakai NILAI COBAAN — tidak sesuai config. Jangan dipakai untuk pemesanan. Simpan permanen lewat Setup › Nilai teknis kalau cocok.';
  b.className = 'show';
  b.style.background = '#FBEAE5';
  b.style.borderBottomColor = 'var(--karat)';
  const s = $('cobaPanel').querySelector('summary');
  if (s) s.textContent = `▸ Coba nilai lain (${n} aktif) — tidak disimpan`;
}

function renderSetupProgress() {
  // 09-SPEC: diganti oleh updateSetupNav() — dipanggil dari tempat lama.
  updateSetupNav();
}

function updateSetupNav() {
  // counter navigasi Setup (09-SPEC §4) + tombol Hitung nonaktif kalau kosong
  const tplCount = proyekRaw && proyekRaw.templates && (proyekRaw.templates.balok || proyekRaw.templates)
    ? Object.keys(proyekRaw.templates.balok || proyekRaw.templates).length : 0;
  const gCount = $('gbrSelect') ? $('gbrSelect').options.length - 1 : 0;
  const cg = $('cntGambar'), ce = $('cntElemen');
  if (cg) { cg.textContent = gCount > 0 ? gCount : '⚠'; cg.className = 'cnt' + (gCount ? '' : ' warn'); }
  if (ce) { ce.textContent = tplCount > 0 ? tplCount : '⚠'; ce.className = 'cnt' + (tplCount ? '' : ' warn'); }
  // counter Bentuk diisi saat halaman dibuka (renderSetupBentuk) — inisialisasi
  if (proyekAktif && proyekBerlapis && $('cntBentuk')) {
    (async () => {
      try {
        const d = await (await fetch(`/api/projects/${proyekAktif}/shapes`)).json();
        const n = d.ok ? Object.keys(d.shapes || {}).length : 0;
        const cb = $('cntBentuk');
        if (cb) { cb.textContent = n > 0 ? n : '⚠'; cb.className = 'cnt' + (n ? '' : ' warn'); }
      } catch (_e) { /* biarkan kosong */ }
    })();
  }
  const btn = $('btnHitung');
  if (btn) {
    if (!proyekAktif) {
      btn.disabled = true;
      btn.title = 'Pilih proyek & gambar dulu.';
    } else if (!tplCount) {
      btn.disabled = true;
      btn.title = 'Setup belum lengkap — tambahkan tipe elemen lewat Setup › Elemen.';
    } else {
      btn.disabled = false;
      btn.title = '';
    }
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
    renderSetupPage('teknis');
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
  renderSetupPage('teknis');
}

function unduhYaml() {
  const a = document.createElement('a');
  a.href = `/api/projects/${proyekAktif}/yaml`;
  a.download = `${proyekAktif}.yaml`;
  a.click();
}

// ── Setup pages (09-SPEC §4) ───────────────────────────────
function renderSetupPage(page) {
  setupPageAktif = page;
  document.querySelectorAll('.setup-item').forEach(b =>
    b.classList.toggle('active', b.dataset.page === page));
  const body = $('setupPage');
  if (page === 'proyek') return renderSetupProyek(body);
  if (page === 'gambar') return renderSetupGambar(body);
  if (page === 'teknis') return renderSetupTeknis(body);
  if (page === 'elemen') return renderSetupElemen(body);
  if (page === 'bentuk') return renderSetupBentuk(body);
}

function renderSetupProyek(body) {
  if (!proyekAktif) {
    body.innerHTML = `<h2>Proyek</h2><div class="kosong">
      Pilih proyek di kanan atas, atau buat proyek baru.<br>
      <button class="btn primary" onclick="bukaWizard('baru')">+ Proyek baru</button>
    </div>`;
    return;
  }
  const c = proyekDefault || (proyekRaw && proyekRaw.config) || {};
  const uw = Object.entries(c.unit_weight_kg_per_m || {})
    .map(([d, v]) => `D${d}=${v}`).join(' ');
  const lds = Object.entries(c.panjang_penyaluran_mm || {})
    .map(([d, v]) => `D${d}=${v}`).join(' ');
  const laps = Object.entries(c.lap_splice_mm || {})
    .map(([d, v]) => `D${d}=${v}`).join(' ');
  const lapMetode = (c.lap_splice && c.lap_splice.metode) || 'sisa_di_ujung';
  const lapDesc = {
    'sisa_di_ujung': 'paling hemat — n−1 potongan stok penuh + satu sisa',
    'bagi_rata': 'semua potongan sama panjang — lebih mudah dikerjakan',
    'berselang': 'sambungan digeser bergantian (butuh offset dari gambar)',
  };
  body.innerHTML = `
    <h2>Proyek — ${esc(c.proyek ? c.proyek.nama : proyekAktif)}</h2>
    <div class="sub">Nilai di halaman ini berlaku untuk semua gambar yang tidak punya nilai sendiri.</div>
    <div class="daftar-item"><div class="info">
      <b>${esc(proyekAktif)}</b> · stok ${c.stok ? c.stok.panjang_batang_mm : '—'} mm ·
      kerf ${c.stok ? c.stok.kerf_mm : '—'} mm · sisa min ${c.stok ? c.stok.sisa_min_simpan_mm : '—'} mm<br>
      <small>unit weight: ${uw || '—'}</small><br>
      <small>Ld default: ${lds || '—'}</small><br>
      <small>lap splice: ${laps || '—'} · metode <b>${lapMetode}</b> — ${lapDesc[lapMetode] || ''}</small>
    </div>
    <div class="aksi">
      <button class="btn kecil" onclick="bukaEditorParam()">Edit parameter proyek</button>
      <button class="btn kecil" onclick="unduhYaml()">Unduh YAML</button>
    </div></div>`;
}

function renderSetupGambar(body) {
  if (!proyekAktif || !proyekBerlapis) {
    body.innerHTML = `<h2>Gambar</h2><div class="kosong">
      Pilih proyek berlapis dulu di kanan atas.</div>`;
    return;
  }
  (async () => {
    const d = await (await fetch(`/api/projects/${proyekAktif}/drawings`)).json();
    const list = (d.drawings || []).map(g => `
      <div class="daftar-item"><div class="info">
        <b>${esc(g.kode)}</b> ${esc(g.revisi)} — ${esc(g.nama)}<br>
        <small>${g.tanggal || ''} · ${g.n_override} nilai di-override</small>
      </div>
      <div class="aksi">
        <button class="btn kecil" onclick="pilihGambarDariSetup('${esc(g.kode)}')">Buka</button>
        <button class="btn kecil" onclick="duplikatGambar('${esc(g.kode)}')">Duplikat</button>
      </div></div>`).join('');
    body.innerHTML = `
      <h2>Gambar</h2>
      <div class="sub">Nilai teknis di halaman ini hanya berlaku untuk gambar yang dipilih.</div>
      ${list || '<div class="kosong">Belum ada gambar.</div>'}
      <div style="margin-top:10px"><button class="btn" onclick="tambahGambar()">+ Gambar</button></div>`;
  })();
}

function pilihGambarDariSetup(kode) {
  $('gbrSelect').value = kode;
  pilihGambar(kode);
  renderSetupPage('teknis');
}
function tambahGambar() { $('btnNewGbr').click(); }
async function duplikatGambar(kode) {
  const baru = prompt(`Kode gambar baru (duplikat dari ${kode}):`, `${kode}-DUP`);
  if (!baru) return;
  const d = await (await fetch(`/api/projects/${proyekAktif}/drawings/${kode}`)).json();
  if (!d.ok) { alert(d.error || 'Gagal baca gambar'); return; }
  const nama = prompt('Nama gambar baru:', (d.drawing && d.drawing.nama) || baru);
  const revisi = prompt('Revisi:', (d.drawing && d.drawing.revisi) || 'Rev.1');
  const tanggal = prompt('Tanggal (YYYY-MM-DD):', (d.drawing && d.drawing.tanggal) || '');
  if (!nama || !revisi || !tanggal) { alert('nama, revisi, tanggal wajib.'); return; }
  const res = await fetch(`/api/projects/${proyekAktif}/drawings`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kode: baru, nama, revisi, tanggal,
                           override: d.override || {} })
  });
  const r = await res.json();
  if (!r.ok) { alert(r.error || 'Gagal duplikat'); return; }
  await pilihProyek(proyekAktif);
  $('gbrSelect').value = baru;
  await pilihGambar(baru);
  renderSetupPage('gambar');
}

function renderSetupTeknis(body) {
  if (!proyekAktif) {
    body.innerHTML = `<h2>Nilai teknis</h2><div class="kosong">Pilih proyek dulu.</div>`;
    return;
  }
  const gname = gambarAktif || '(belum ada gambar)';
  body.innerHTML = `
    <h2>Nilai teknis — ${esc(gname)}</h2>
    <div class="sub">Nilai di halaman ini hanya berlaku untuk ${esc(gambarAktif || 'gambar aktif')}. Gambar lain tidak terpengaruh.</div>
    <details class="panel" id="paramPanel" open>
      <summary class="panel-title" id="paramTitle">▸ NILAI TEKNIS — ${esc(gname)}</summary>
      <div id="paramBody" class="param-body">…</div>
      <div id="paramActions" class="param-actions" style="display:none">
        <button id="btnParamEdit" class="btn">✎ Edit</button>
        <button id="btnParamProyek" class="btn" title="Edit nilai proyek — berlaku untuk semua gambar yang tidak punya nilai sendiri">Edit parameter proyek</button>
        <button id="btnParamYaml" class="btn">Unduh YAML</button>
      </div>
      <div id="paramForm" style="display:none"></div>
    </details>`;
  $('btnParamEdit').onclick = () => renderPanelEdit();
  $('btnParamProyek').onclick = () => bukaEditorParam();
  $('btnParamYaml').onclick = () => unduhYaml();
  if (proyekRaw) renderPanelView(proyekRaw.config, []);
  else renderParamFromConfig(proyekDefault || {}, []);
}

function renderSetupElemen(body) {
  if (!proyekAktif || !proyekBerlapis) {
    body.innerHTML = `<h2>Elemen</h2><div class="kosong">
      Pilih proyek berlapis dulu di kanan atas.</div>`;
    return;
  }
  const tpls = (proyekRaw && proyekRaw.templates && (proyekRaw.templates.balok || proyekRaw.templates)) || {};
  const names = Object.keys(tpls);
  body.innerHTML = `
    <h2>Elemen</h2>
    <div class="sub">Template elemen milik proyek — dipakai di semua gambar.</div>
    ${names.length
      ? names.map(n => `
        <div class="daftar-item"><div class="info">
          <b>${esc(n)}</b> · ${esc(tplRingkasanSatu(n, tpls[n]))}
        </div></div>`).join('')
      : '<div class="kosong">Proyek ini belum punya tipe elemen. Tambahkan di bawah.</div>'}
    <div style="margin-top:10px"><button class="btn" onclick="bukaEditorElemen()">Kelola elemen</button></div>`;
}

// ── panel elemen — ringkasan template (PATCH-05 §3-4) ──────
function tplRingkasanSatu(nama, t) {
  const tul = (t.tulangan || []).map(x =>
    `${x.jumlah}D${x.dia} ${x.posisi}`).join(', ');
  const sk = t.sengkang || {};
  return `${nama} · ${t.b_mm}×${t.h_mm} · ${tul || '—'} · ` +
         `sengkang D${sk.dia || '?'}-${sk.jarak_tumpuan_mm || '?'}/${sk.jarak_lapangan_mm || '?'}`;
}

function renderElemSummary() {
  const box = $('elemSummary');
  if (!box) return;   // hanya ada di layout lama; 09-SPEC pakai Setup › Elemen
  const raw = proyekRaw && proyekRaw.templates;
  const tpls = (raw && (raw.balok || raw)) || {};
  const names = Object.keys(tpls);
  if (!proyekAktif) { box.innerHTML = ''; return; }
  if (!names.length) {
    box.innerHTML = `<div class="wiz-warn" style="margin:0 0 8px">
      ⚠ Belum ada tipe elemen di proyek ini. Tambahkan minimal satu sebelum bisa menghitung.</div>`;
    return;
  }
  const shown = names.slice(0, 3);
  const extra = names.length - shown.length;
  box.innerHTML = `<div class="wiz-hint" style="margin-bottom:4px">Tipe tersedia di ${proyekAktif}:</div>` +
    shown.map(n => `<div class="tpl-summary">${tplRingkasanSatu(n, tpls[n])}</div>`).join('') +
    (extra > 0 ? `<div class="wiz-hint">dan ${extra} lainnya</div>` : '');
}

// ── Setup › Bentuk (10-SPEC §7) — daftar & editor shape ──
let shapeDraft = null;      // {kode, nama, deskripsi, segmen[], bengkokan[], hook[]}
let shapePreviewTpl = '';   // template elemen dipilih untuk pratinjau

function renderSetupBentuk(body) {
  if (!proyekAktif || !proyekBerlapis) {
    body.innerHTML = `<h2>Bentuk</h2><div class="kosong">
      Pilih proyek berlapis dulu di kanan atas.</div>`;
    return;
  }
  (async () => {
    const d = await (await fetch(`/api/projects/${proyekAktif}/shapes`)).json();
    if (!d.ok) { body.innerHTML = `<h2>Bentuk</h2><div class="kosong">${escapeHtml(d.error || 'Gagal load')}</div>`; return; }
    const sh = d.shapes || {};
    const keys = Object.keys(sh).sort();
    const cg = $('cntBentuk');
    if (cg) { cg.textContent = keys.length; cg.className = 'cnt'; }
    body.innerHTML = `
      <h2>Bentuk tulangan</h2>
      <div class="sub">Definisi bentuk — menambah bentuk baru = mengisi form, bukan menulis kode.</div>
      ${keys.map(k => {
        const s = sh[k];
        const nSeg = (s.segmen || []).length;
        const nBeng = (s.bengkokan || []).reduce((a, b) => a + (b.jumlah || 0), 0);
        return `<div class="daftar-item"><div class="info">
          <b>${esc(k)}</b> · ${esc(s.nama || '')}<br>
          <small>${nSeg} segmen · ${nBeng} bengkokan</small>
        </div>
        <div class="aksi">
          <button class="btn kecil" onclick="bukaEditorBentuk('${esc(k)}')">edit</button>
        </div></div>`;
      }).join('')}
      <div style="margin-top:10px;display:flex;gap:8px">
        <button class="btn" onclick="bukaEditorBentuk('')">+ Bentuk baru</button>
        <button class="btn" onclick="bukaEditorBentuk('', true)">+ Salin dari bentuk ada</button>
      </div>`;
  })();
}

async function bukaEditorBentuk(kode, salin = false) {
  if (kode && !salin) {
    const d = await (await fetch(`/api/projects/${proyekAktif}/shapes`)).json();
    const s = (d.shapes || {})[kode];
    if (!s) { alert('Shape tidak ada.'); return; }
    shapeDraft = { kode, nama: s.nama || '', deskripsi: s.deskripsi || '',
                   segmen: (s.segmen || []).map(x => ({...x})),
                   bengkokan: (s.bengkokan || []).map(x => ({...x})),
                   hook: (s.hook || []).map(x => ({...x})) };
  } else if (salin) {
    const d = await (await fetch(`/api/projects/${proyekAktif}/shapes`)).json();
    const keys = Object.keys(d.shapes || {}).sort();
    const pilih = prompt(`Salin dari shape yang mana? (${keys.join(', ')})`, keys[0] || '');
    if (!pilih || !d.shapes[pilih]) { alert('Shape sumber tidak ada.'); return; }
    const s = d.shapes[pilih];
    const baru = prompt('Kode shape baru:', `${pilih}-x`);
    if (!baru) return;
    shapeDraft = { kode: baru, nama: s.nama || '', deskripsi: s.deskripsi || '',
                   segmen: (s.segmen || []).map(x => ({...x})),
                   bengkokan: (s.bengkokan || []).map(x => ({...x})),
                   hook: (s.hook || []).map(x => ({...x})) };
  } else {
    shapeDraft = { kode: '', nama: '', deskripsi: '', segmen: [],
                   bengkokan: [], hook: [] };
  }
  // pilih template pratinjau pertama yang ada
  const tpls = (proyekRaw && proyekRaw.templates && (proyekRaw.templates.balok || proyekRaw.templates)) || {};
  shapePreviewTpl = Object.keys(tpls)[0] || '';
  renderShapeEditor();
}

function renderShapeEditor() {
  const body = $('setupPage');
  const d = shapeDraft;
  const tpls = (proyekRaw && proyekRaw.templates && (proyekRaw.templates.balok || proyekRaw.templates)) || {};
  body.innerHTML = `
    <h2>Editor bentuk — ${esc(d.kode || '(baru)')}</h2>
    <div class="sub">Rumus universal: Σ segmen + Σ hook − Σ bend deduction.</div>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Kode *</label>
        <input id="shKode" value="${esc(d.kode)}" placeholder="21"></div>
      <div class="wiz-field"><label>Nama</label>
        <input id="shNama" value="${esc(d.nama)}" placeholder="Batang bengkok satu ujung"></div>
    </div>
    <div class="wiz-field"><label>Deskripsi</label>
      <input id="shDesk" value="${esc(d.deskripsi)}"></div>

    <h3 style="font-size:13px;margin:14px 0 6px">SEGMEN <span class="wiz-hint">(variabel: L b h c Ld d tekuk · operator + − * /)</span></h3>
    <div id="shSegmen">${d.segmen.map((s, i) => shapeSegmenRow(s, i)).join('')}</div>
    <button class="btn" onclick="shapeAddSegmen()">+ segmen</button>

    <h3 style="font-size:13px;margin:14px 0 6px">BENGKOKAN</h3>
    <div id="shBengkokan">${d.bengkokan.map((b, i) => shapeBengkokanRow(b, i)).join('')}</div>
    <button class="btn" onclick="shapeAddBengkokan()">+ bengkokan</button>

    <h3 style="font-size:13px;margin:14px 0 6px">HOOK</h3>
    <div id="shHook">${d.hook.map((h, i) => shapeHookRow(h, i)).join('')}</div>
    <button class="btn" onclick="shapeAddHook()">+ hook</button>

    <div style="margin-top:14px">
      <label class="wiz-hint">Pratinjau dengan template:</label>
      <select id="shPreviewTpl" style="margin-left:8px;padding:5px" onchange="shapePreviewTpl=this.value;shapePreview()">
        ${Object.keys(tpls).map(t => `<option value="${esc(t)}" ${t === shapePreviewTpl ? 'selected' : ''}>${esc(t)}</option>`).join('')}
      </select>
    </div>
    <div id="shPreview" style="margin-top:8px"></div>

    <div class="ovr-actions" style="margin-top:16px">
      <button class="btn primary" onclick="shapeSave()">Simpan bentuk</button>
      <button class="btn" onclick="renderSetupPage('bentuk')">Batal</button>
    </div>`;
  // isi kode lama saat baru dibuat — autogenerate
  if (!d.kode) { /* biarkan kosong, user isi */ }
  shapePreview();
}

function shapeSegmenRow(s, i) {
  return `<div class="shape-row" style="display:flex;gap:6px;margin-bottom:5px;align-items:center">
    <input class="sh-sid" value="${esc(s.id || '')}" style="width:40px;padding:5px" placeholder="A">
    <input class="sh-spanjang" value="${esc(s.panjang || '')}" style="flex:1;padding:5px" placeholder="b - 2*c" oninput="shapePreview()">
    <span class="sh-sval mono" style="width:80px;text-align:right;color:var(--tinta2)"></span>
    <button class="del" onclick="this.closest('.shape-row').remove();shapePreview()">✕</button>
  </div>`;
}
function shapeBengkokanRow(b, i) {
  return `<div class="shape-row" style="display:flex;gap:6px;margin-bottom:5px;align-items:center">
    <select class="sh-bsudut" style="padding:5px" onchange="shapePreview()">
      <option value="90" ${String(b.sudut) === '90' ? 'selected' : ''}>90°</option>
      <option value="135" ${String(b.sudut) === '135' ? 'selected' : ''}>135°</option>
      <option value="hook" ${String(b.sudut) === 'hook' ? 'selected' : ''}>hook (ikut template)</option>
    </select>
    <label class="wiz-hint">×</label>
    <input class="sh-bjumlah" type="number" min="1" value="${b.jumlah || 1}" style="width:60px;padding:5px" oninput="shapePreview()">
    <button class="del" onclick="this.closest('.shape-row').remove();shapePreview()">✕</button>
  </div>`;
}
function shapeHookRow(h, i) {
  return `<div class="shape-row" style="display:flex;gap:6px;margin-bottom:5px;align-items:center">
    <select class="sh-hsudut" style="padding:5px" onchange="shapePreview()">
      <option value="90" ${String(h.sudut) === '90' ? 'selected' : ''}>90°</option>
      <option value="135" ${String(h.sudut) === '135' ? 'selected' : ''}>135°</option>
      <option value="hook" ${String(h.sudut) === 'hook' ? 'selected' : ''}>hook (ikut template)</option>
    </select>
    <label class="wiz-hint">×</label>
    <input class="sh-hjumlah" type="number" min="1" value="${h.jumlah || 1}" style="width:60px;padding:5px" oninput="shapePreview()">
    <button class="del" onclick="this.closest('.shape-row').remove();shapePreview()">✕</button>
  </div>`;
}
function shapeAddSegmen() {
  const box = $('shSegmen');
  const div = document.createElement('div');
  div.innerHTML = shapeSegmenRow({id: String.fromCharCode(65 + box.children.length), panjang: ''}, box.children.length);
  box.appendChild(div.firstChild);
  shapePreview();
}
function shapeAddBengkokan() {
  const box = $('shBengkokan');
  const div = document.createElement('div');
  div.innerHTML = shapeBengkokanRow({sudut: '90', jumlah: 1}, box.children.length);
  box.appendChild(div.firstChild);
  shapePreview();
}
function shapeAddHook() {
  const box = $('shHook');
  const div = document.createElement('div');
  div.innerHTML = shapeHookRow({sudut: 'hook', jumlah: 2}, box.children.length);
  box.appendChild(div.firstChild);
  shapePreview();
}

// pratinjau live — evaluasi tiap segmen + rincian tiga baris (10-SPEC §7)
function shapePreview() {
  const out = $('shPreview');
  if (!out) return;
  const tpl = (proyekRaw && proyekRaw.templates &&
               (proyekRaw.templates.balok || proyekRaw.templates) || {})[shapePreviewTpl];
  if (!tpl) { out.innerHTML = '<div class="wiz-hint">Pilih template elemen dulu.</div>'; return; }
  const cfg = lastResult && lastResult.config ? lastResult.config : null;
  const c = cfg ? cfg.cover.balok : 40;
  const ld = cfg ? (cfg.ld['10'] || cfg.ld[10]) : 400;
  const hook135 = cfg ? (cfg.hook_tail['135'] && cfg.hook_tail['135']['10']) : 80;
  const hook90 = cfg ? (cfg.hook_tail['90'] && cfg.hook_tail['90']['10']) : 120;
  const b = tpl.b_mm, h = tpl.h_mm, d = 10;
  const vars = { L: 6000, b, h, c, Ld: ld, d, tekuk: 200 };
  let rows = '';
  let ok = true;
  document.querySelectorAll('#shSegmen .shape-row').forEach(r => {
    const expr = r.querySelector('.sh-spanjang').value.trim();
    const valSpan = r.querySelector('.sh-sval');
    if (!expr) { valSpan.textContent = ''; return; }
    try {
      const val = evalEkspresiAman(expr, vars);
      valSpan.textContent = `= ${Math.round(val)} mm`;
      valSpan.style.color = 'var(--tinta2)';
      rows += `<div>${esc(expr)} = ${Math.round(val)} mm</div>`;
    } catch (e) {
      ok = false;
      valSpan.textContent = '⚠';
      valSpan.style.color = 'var(--karat)';
      rows += `<div style="color:var(--karat)">${esc(expr)} — ${escapeHtml(e.message)}</div>`;
    }
  });
  // hook & bengkokan summary
  const nHook = [...document.querySelectorAll('#shHook .sh-hjumlah')]
    .reduce((a, x) => a + (parseInt(x.value) || 0), 0);
  const nBeng = [...document.querySelectorAll('#shBengkokan .sh-bjumlah')]
    .reduce((a, x) => a + (parseInt(x.value) || 0), 0);
  out.innerHTML = `
    <div class="wiz-warn" style="margin-top:0">PRATINJAU dengan ${esc(shapePreviewTpl)} (${b}×${h}), D10, cover ${c}, hook 135°</div>
    <div class="mono" style="font-size:12px;line-height:1.7">
      ${rows || '<div class="wiz-hint">— isi segmen —</div>'}
      <div>hook: ${nHook} × ${hook135} (135°) = ${nHook * hook135} mm</div>
      <div>bend deduction: ${ok ? '0 mm (koreksi nonaktif)' : '—'}</div>
      <hr style="border:none;border-top:1px solid var(--garis)">
      <div><b>panjang potong ≈ ${ok && rows ? (6000 + nHook * hook135) : '—'} mm</b></div>
    </div>`;
}

// evaluasi ekspresi aman di frontend (whitelist — mirror parser backend)
function evalEkspresiAman(expr, vars) {
  const ALLOWED = ['L', 'b', 'h', 'c', 'Ld', 'd', 'tekuk'];
  // ganti nama variabel jadi angka dulu, lalu parse manual sederhana
  let s = expr;
  ALLOWED.forEach(v => { s = s.split(v).join(`(${JSON.stringify(vars[v] ?? 0)})`); });
  // setelah substitusi, hanya angka + operator + kurung — aman untuk eval
  if (/[^0-9+\-*/().\s]/.test(s)) throw new Error('variabel tidak dikenal');
  const val = Function(`"use strict";return (${s});`)();
  if (typeof val !== 'number' || !isFinite(val)) throw new Error('hasil tidak valid');
  return val;
}

async function shapeSave() {
  const kode = $('shKode').value.trim();
  const nama = $('shNama').value.trim();
  const deskripsi = $('shDesk').value.trim();
  if (!kode) { alert('Kode shape wajib.'); return; }
  const segmen = [...document.querySelectorAll('#shSegmen .shape-row')].map(r => ({
    id: r.querySelector('.sh-sid').value.trim() || 'A',
    panjang: r.querySelector('.sh-spanjang').value.trim() }));
  const bengkokan = [...document.querySelectorAll('#shBengkokan .shape-row')].map(r => ({
    sudut: r.querySelector('.sh-bsudut').value, jumlah: parseInt(r.querySelector('.sh-bjumlah').value) || 1 }));
  const hook = [...document.querySelectorAll('#shHook .shape-row')].map(r => ({
    sudut: r.querySelector('.sh-hsudut').value, jumlah: parseInt(r.querySelector('.sh-hjumlah').value) || 1 }));
  if (!segmen.length) { alert('Minimal satu segmen.'); return; }
  const shapes = {};
  const d = await (await fetch(`/api/projects/${proyekAktif}/shapes`)).json();
  if (d.ok) Object.assign(shapes, d.shapes);
  shapes[kode] = { nama, deskripsi, segmen, bengkokan, hook };
  const res = await fetch(`/api/projects/${proyekAktif}/shapes`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ shapes }) });
  const r = await res.json();
  if (!r.ok) { alert(r.error || 'Gagal simpan'); return; }
  alert('Bentuk tersimpan. File lama diarsipkan.');
  renderSetupPage('bentuk');
}

// ── editor elemen (PATCH-05 §5) — form template elemen ─────
let elemenDraft = null;

async function bukaEditorElemen() {
  if (!proyekAktif) { alert('Pilih proyek dulu.'); return; }
  if (!proyekBerlapis) { alert('Proyek ini belum berlapis — pakai panel Nilai teknis.'); return; }
  // fetch fresh — proyekRaw.templates bisa stale setelah save (13-SPEC)
  let tplData = proyekRaw.templates || {};
  try {
    const fresh = await (await fetch(`/api/projects/${proyekAktif}`)).json();
    if (fresh.ok && fresh.templates) {
      // gabung semua tipe jadi flat utk editor: {B1, K1, S1, ...}
      tplData = {};
      Object.entries(fresh.templates).forEach(([tipe, items]) => {
        Object.entries(items || {}).forEach(([nama, t]) => {
          tplData[nama] = { tipe, ...t };
        });
      });
    }
  } catch (_e) { /* pakai cache */ }
  elemenDraft = JSON.parse(JSON.stringify(tplData));
  muatShapeOptions().then(() => {
    $('elemModal').style.display = 'flex';
    renderElemEditor();
  });
}
function elemModalClose() { $('elemModal').style.display = 'none'; elemenDraft = null; }

function renderElemEditor() {
  const body = $('elemModalBody');
  const names = Object.keys(elemenDraft || {});
  body.innerHTML = `
    <div class="wiz-hint" style="margin-bottom:8px">Template elemen milik proyek — dipakai di semua gambar. Sengkang D{dia}-{jarak_tumpuan}/{jarak_lapangan}.</div>
    ${names.map(n => tplBlockHtml(n, elemenDraft[n], true)).join('')}
    <button class="btn" onclick="elemAddTpl()">+ tipe elemen</button>`;
}

function elemAddTpl() {
  const next = 'B' + (Object.keys(elemenDraft).length + 1);
  elemenDraft[next] = {
    deskripsi: '', b_mm: '', h_mm: '',
    tulangan: [{ posisi: 'atas', dia: '', jumlah: '', tumpuan_kedua_ujung: true }],
    sengkang: { dia: '', jarak_tumpuan_mm: '', jarak_lapangan_mm: '', kaki: 2, hook_sudut: 135 } };
  renderElemEditor();
}

function tplBlockHtml(nama, t, editable = true) {
  const tul = (t.tulangan || []).map((x, i) => `
    <div class="tul-row">
      <select class="t-pos"><option value="atas" ${x.posisi === 'atas' ? 'selected' : ''}>atas</option>
        <option value="bawah" ${x.posisi === 'bawah' ? 'selected' : ''}>bawah</option>
        <option value="pinggang" ${x.posisi === 'pinggang' ? 'selected' : ''}>pinggang</option>
        <option value="utama" ${x.posisi === 'utama' ? 'selected' : ''}>utama</option></select>
      <input class="t-dia" type="number" value="${x.dia}" placeholder="Ø">
      <input class="t-jum" type="number" value="${x.jumlah || ''}" placeholder="jml">
      <input class="t-jarak" type="number" value="${x.jarak_mm || ''}" placeholder="jarak" title="plat: spasi antar batang (ganti jumlah)">
      <select class="t-arah" title="arah (plat)">
        <option value="" ${!x.arah ? 'selected' : ''}>—</option>
        <option value="X" ${x.arah === 'X' ? 'selected' : ''}>X</option>
        <option value="Y" ${x.arah === 'Y' ? 'selected' : ''}>Y</option>
      </select>
      <select class="t-shape" title="shape tulangan">${shapeOptions(x.shape || '01')}</select>
      <label class="wiz-hint"><input class="t-dua" type="checkbox" ${x.tumpuan_kedua_ujung ? 'checked' : ''}> 2 ujung</label>
      <button class="del" onclick="this.closest('.tul-row').remove()">✕</button>
    </div>`).join('');
  // 12-SPEC §2: sengkang daftar kelompok
  const sks = (t.sengkang && Array.isArray(t.sengkang)) ? t.sengkang : [t.sengkang || {}];
  const skHtml = sks.map((sk, si) => `
    <div class="sk-block" style="border:1px dashed var(--garis);border-radius:6px;padding:8px;margin-bottom:8px">
      <button class="del" onclick="this.closest('.sk-block').remove()">✕ hapus kelompok</button>
      <div class="wiz-grid">
        <div class="wiz-field"><label>Nama</label><input class="t-sknama" value="${esc(sk.nama || '')}" placeholder="sengkang luar"></div>
        <div class="wiz-field"><label>Sengkang Ø</label><input class="t-skdia" type="number" value="${sk.dia || ''}"></div>
        <div class="wiz-field"><label>Shape</label><select class="t-skshape">${shapeOptions(sk.shape || '51')}</select></div>
        <div class="wiz-field"><label>Jumlah per set</label><input class="t-skjps" type="number" min="1" value="${sk.jumlah_per_set || 1}"></div>
        <div class="wiz-field"><label>Jarak tumpuan (mm)</label><input class="t-skt" type="number" value="${sk.jarak_tumpuan_mm || ''}"></div>
        <div class="wiz-field"><label>Jarak lapangan (mm)</label><input class="t-skl" type="number" value="${sk.jarak_lapangan_mm || ''}"></div>
        <div class="wiz-field"><label>Kaki</label><input class="t-skkaki" type="number" value="${sk.kaki || 2}"></div>
        <div class="wiz-field"><label>Hook sudut</label><select class="t-skhook">
          <option value="135" ${sk.hook_sudut === 135 ? 'selected' : ''}>135°</option>
          <option value="90" ${sk.hook_sudut === 90 ? 'selected' : ''}>90°</option></select></div>
      </div>
    </div>`).join('');
  return `<div class="tpl-block">
    <button class="del" onclick="this.closest('.tpl-block').remove()">✕ hapus tipe</button>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Nama tipe</label><input class="t-nama" value="${esc(nama)}"></div>
      <div class="wiz-field"><label>Tipe elemen</label><select class="t-tipeelem">
        <option value="balok" ${t.tipe === 'balok' ? 'selected' : ''}>balok</option>
        <option value="kolom" ${t.tipe === 'kolom' ? 'selected' : ''}>kolom</option>
        <option value="plat" ${t.tipe === 'plat' ? 'selected' : ''}>plat</option>
      </select></div>
      <div class="wiz-field"><label>Deskripsi</label><input class="t-desk" value="${esc(t.deskripsi || '')}"></div>
      <div class="wiz-field"><label>b (mm)</label><input class="t-b" type="number" value="${t.b_mm}"></div>
      <div class="wiz-field"><label>h (mm)</label><input class="t-h" type="number" value="${t.h_mm}"></div>
      <div class="wiz-field"><label>Label dimensi utama</label><input class="t-labelL" value="${esc(t.label_L || '')}" placeholder="Bentang bersih"></div>
      <div class="wiz-field"><label>Bantuan dimensi utama</label><input class="t-bantuanL" value="${esc(t.bantuan_L || '')}" placeholder="Muka ke muka tumpuan..."></div>
    </div>
    <div class="wiz-hint">Tulangan</div>
    <div class="tul-list">${tul}</div>
    <button class="btn" onclick="elemAddTul(this)">+ tulangan</button>
    <div class="wiz-hint" style="margin-top:8px">Sengkang (daftar kelompok)</div>
    <div class="sk-list">${skHtml}</div>
    <button class="btn" onclick="elemAddSk(this)">+ kelompok sengkang</button>
    ${t.tipe === 'plat'
      ? '<div class="wiz-warn" style="margin-top:8px">Plat berbentuk L atau trapesium belum didukung. Pecah jadi beberapa panel persegi panjang.</div>'
      : ''}
  </div>`;
}

function elemAddSk(btn) {
  const list = btn.closest('.tpl-block').querySelector('.sk-list');
  const div = document.createElement('div');
  div.className = 'sk-block';
  div.style.cssText = 'border:1px dashed var(--garis);border-radius:6px;padding:8px;margin-bottom:8px';
  div.innerHTML = `<button class="del" onclick="this.closest('.sk-block').remove()">✕ hapus kelompok</button>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Nama</label><input class="t-sknama" placeholder="sengkang ikat"></div>
      <div class="wiz-field"><label>Sengkang Ø</label><input class="t-skdia" type="number"></div>
      <div class="wiz-field"><label>Shape</label><select class="t-skshape">${shapeOptions('51')}</select></div>
      <div class="wiz-field"><label>Jumlah per set</label><input class="t-skjps" type="number" min="1" value="1"></div>
      <div class="wiz-field"><label>Jarak tumpuan (mm)</label><input class="t-skt" type="number"></div>
      <div class="wiz-field"><label>Jarak lapangan (mm)</label><input class="t-skl" type="number"></div>
      <div class="wiz-field"><label>Kaki</label><input class="t-skkaki" type="number" value="2"></div>
      <div class="wiz-field"><label>Hook sudut</label><select class="t-skhook">
        <option value="135" selected>135°</option><option value="90">90°</option></select></div>
    </div>`;
  list.appendChild(div);
}

function shapeOptions(selected) {
  // opsi shape dari proyek — dibaca dari API saat editor dibuka
  const opts = shapeOptionsCache || [];
  if (!opts.length) return `<option value="${esc(selected)}">${esc(selected)}</option>`;
  return opts.map(s => `<option value="${esc(s.kode)}" ${s.kode === selected ? 'selected' : ''}>${esc(s.kode)} ${esc(s.nama || '')}</option>`).join('');
}
let shapeOptionsCache = null;
async function muatShapeOptions() {
  try {
    const d = await (await fetch(`/api/projects/${proyekAktif}/shapes`)).json();
    shapeOptionsCache = d.ok ? Object.entries(d.shapes || {}).map(([k, v]) => ({ kode: k, nama: v.nama })) : null;
  } catch (_e) { shapeOptionsCache = null; }
}

function elemAddTul(btn) {
  const list = btn.closest('.tpl-block').querySelector('.tul-list');
  const div = document.createElement('div');
  div.className = 'tul-row';
  div.innerHTML = `<select class="t-pos"><option>atas</option><option>bawah</option><option>pinggang</option></select>
    <input class="t-dia" type="number" placeholder="Ø"><input class="t-jum" type="number" placeholder="jml">
    <select class="t-shape">${shapeOptions('01')}</select>
    <label class="wiz-hint"><input class="t-dua" type="checkbox" checked> 2 ujung</label>
    <button class="del" onclick="this.closest('.tul-row').remove()">✕</button>`;
  list.appendChild(div);
}

async function elemSave() {
  const tpls = {};
  document.querySelectorAll('#elemModalBody .tpl-block').forEach(block => {
    const nama = block.querySelector('.t-nama').value.trim();
    if (!nama) return;
    const tulangan = [];
    block.querySelectorAll('.tul-list .tul-row').forEach(row => {
      const dia = +row.querySelector('.t-dia').value;
      const jum = +row.querySelector('.t-jum').value;
      const jarak = +row.querySelector('.t-jarak').value;
      if (dia && (jum || jarak)) {
        const trow = {
          posisi: row.querySelector('.t-pos').value,
          dia,
          tumpuan_kedua_ujung: row.querySelector('.t-dua').checked,
          shape: row.querySelector('.t-shape').value,
        };
        // 13-SPEC §3: tepat satu dari jumlah / jarak_mm
        if (jarak) { trow.jarak_mm = jarak; trow.arah = row.querySelector('.t-arah').value; }
        else trow.jumlah = jum;
        tulangan.push(trow);
      }
    });
    // 12-SPEC §2: sengkang daftar kelompok
    const sengkang = [];
    block.querySelectorAll('.sk-list .sk-block').forEach(sk => {
      const dia = +sk.querySelector('.t-skdia').value;
      if (!dia) return;
      sengkang.push({
        nama: sk.querySelector('.t-sknama').value.trim(),
        dia,
        jarak_tumpuan_mm: +sk.querySelector('.t-skt').value,
        jarak_lapangan_mm: +sk.querySelector('.t-skl').value,
        kaki: +sk.querySelector('.t-skkaki').value,
        hook_sudut: +sk.querySelector('.t-skhook').value,
        shape: sk.querySelector('.t-skshape').value,
        jumlah_per_set: +sk.querySelector('.t-skjps').value || 1,
      });
    });
    if (!sengkang.length) return;
    const tipeElem = block.querySelector('.t-tipeelem').value;
    tpls[nama] = {
      tipe: tipeElem,
      deskripsi: block.querySelector('.t-desk').value,
      b_mm: +block.querySelector('.t-b').value || 0,
      h_mm: +block.querySelector('.t-h').value || 0,
      label_L: block.querySelector('.t-labelL').value.trim() ||
               (tipeElem === 'kolom' ? 'Tinggi bersih' : 'Bentang bersih'),
      bantuan_L: block.querySelector('.t-bantuanL').value.trim(),
      tulangan,
      sengkang,
    };
  });
  if (!Object.keys(tpls).length) { alert('Minimal satu tipe elemen.'); return; }
  // 13-SPEC: kelompokkan per tipe elemen (balok/kolom/plat)
  const perTipe = {};
  Object.entries(tpls).forEach(([nama, t]) => {
    perTipe[t.tipe] = perTipe[t.tipe] || {};
    perTipe[t.tipe][nama] = t;
  });
  const res = await fetch(`/api/projects/${proyekAktif}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kode: proyekAktif, config: proyekDefault, templates: perTipe })
  });
  const d = await res.json();
  if (!d.ok) { alert(d.error || 'Gagal simpan'); return; }
  elemModalClose();
  // muat ulang templates + counter
  const gd = await (await fetch(`/api/projects/${proyekAktif}/drawings/${gambarAktif}`)).json();
  if (gd.ok) { templates = gd.templates; proyekRaw.templates = gd.templates; }
  updateSetupNav();
  renderSetupPage('elemen');
}

$('elemSave').onclick = elemSave;

// ── editor parameter proyek (PATCH-05 §6) ──────────────────
function bukaEditorParam() {
  if (!proyekBerlapis || !proyekDefault) { alert('Proyek belum berlapis.'); return; }
  $('paramModal').style.display = 'flex';
  const c = proyekDefault;
  const dias = Object.keys(c.panjang_penyaluran_mm || {}).map(Number)
    .concat(Object.keys(c.unit_weight_kg_per_m || {})).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b);
  const rows = dias.map(d => `
    <tr data-dia="${d}">
      <td><b>D${d}</b></td>
      <td><input class="p-ld" type="number" value="${c.panjang_penyaluran_mm[d] || ''}"></td>
      <td><input class="p-lap" type="number" value="${c.lap_splice_mm[d] || ''}"></td>
      <td><input class="p-uw" type="number" step="0.001" value="${c.unit_weight_kg_per_m[d] ?? ''}"></td>
      <td><input class="p-h135" type="number" value="${c.hook.tail_135_mm[d] || ''}"></td>
      <td><input class="p-h90" type="number" value="${c.hook.tail_90_mm[d] || ''}"></td>
    </tr>`).join('');
  $('paramModalBody').innerHTML = `
    <div class="wiz-warn" style="margin-top:0">Mengubah nilai proyek — berlaku untuk semua gambar yang tidak punya nilai sendiri.
      Kalau gambar punya nilai sendiri, yang itu yang dipakai.</div>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Panjang stok (mm)</label>
        <input id="pPanjang" type="number" value="${c.stok.panjang_batang_mm}"></div>
      <div class="wiz-field"><label>Kerf (mm)</label>
        <input id="pKerf" type="number" value="${c.stok.kerf_mm}"></div>
      <div class="wiz-field"><label>Sisa min (mm)</label>
        <input id="pSisa" type="number" value="${c.stok.sisa_min_simpan_mm}"></div>
      <div class="wiz-field"><label>Cover balok</label>
        <input id="pCoverB" type="number" value="${c.selimut_beton_mm.balok || ''}"></div>
      <div class="wiz-field"><label>Cover kolom</label>
        <input id="pCoverK" type="number" value="${c.selimut_beton_mm.kolom || ''}"></div>
      <div class="wiz-field"><label>Cover plat</label>
        <input id="pCoverP" type="number" value="${c.selimut_beton_mm.plat || ''}"></div>
    </div>
    <table class="dia-table"><thead><tr>
      <th>Ø</th><th>Ld</th><th>Lap</th><th>UW</th><th>H135</th><th>H90</th></tr></thead>
      <tbody id="paramDia">${rows}</tbody></table>
    <button class="btn" onclick="paramAddDia()">+ diameter</button>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Zona tumpuan</label>
        <input id="pZona" type="number" step="0.05" value="${c.sengkang.zona_tumpuan_faktor}"></div>
      <div class="wiz-field"><label>Sengkang pertama</label>
        <input id="pPertama" type="number" value="${c.sengkang.jarak_sengkang_pertama_mm}"></div>
      <div class="wiz-field"><label>Metode</label>
        <select id="pMetode"><option value="kontinyu" ${c.sengkang.metode_hitung === 'kontinyu' ? 'selected' : ''}>kontinyu</option>
        <option value="per_zona" ${c.sengkang.metode_hitung === 'per_zona' ? 'selected' : ''}>per_zona</option></select></div>
    </div>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Metode lap splice</label>
        <select id="pLapMetode">
          <option value="sisa_di_ujung" ${(c.lap_splice && c.lap_splice.metode) === 'sisa_di_ujung' ? 'selected' : ''}>sisa_di_ujung — hemat, n−1 stok penuh + sisa</option>
          <option value="bagi_rata" ${(c.lap_splice && c.lap_splice.metode) === 'bagi_rata' ? 'selected' : ''}>bagi_rata — semua sama panjang</option>
          <option value="berselang" ${(c.lap_splice && c.lap_splice.metode) === 'berselang' ? 'selected' : ''}>berselang — sambungan digeser</option>
        </select></div>
      <div class="wiz-field"><label>Offset berselang (mm)</label>
        <input id="pLapOffset" type="number" min="0" value="${(c.lap_splice && c.lap_splice.berselang_offset_mm) || 0}">
        <div class="wiz-hint">Hanya utk metode berselang — isi dari gambar.</div></div>
    </div>`;
}
function paramModalClose() { $('paramModal').style.display = 'none'; }
function paramAddDia() {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><input class="p-dia" type="number" placeholder="Ø"></td>
    <td><input class="p-ld" type="number"></td><td><input class="p-lap" type="number"></td>
    <td><input class="p-uw" type="number" step="0.001"></td>
    <td><input class="p-h135" type="number"></td><td><input class="p-h90" type="number"></td>`;
  $('paramDia').appendChild(tr);
}

async function paramSave() {
  const c = JSON.parse(JSON.stringify(proyekDefault));
  c.stok.panjang_batang_mm = +$('pPanjang').value;
  c.stok.kerf_mm = +$('pKerf').value;
  c.stok.sisa_min_simpan_mm = +$('pSisa').value;
  c.selimut_beton_mm = { balok: +$('pCoverB').value, kolom: +$('pCoverK').value, plat: +$('pCoverP').value };
  const ld = {}, lap = {}, uw = {}, h135 = {}, h90 = {};
  document.querySelectorAll('#paramDia tr').forEach(tr => {
    const diaInput = tr.querySelector('.p-dia');
    const diaRaw = (tr.querySelector('b') || {}).textContent || '';
    const dia = diaInput && diaInput.value !== '' ? +diaInput.value
               : (parseInt(diaRaw.replace('D', '')) || NaN);
    if (!isNaN(dia)) {
      const v = (sel) => { const x = tr.querySelector(sel); return x && x.value !== '' ? +x.value : undefined; };
      const a = v('.p-ld'); if (a) ld[dia] = a;
      const b = v('.p-lap'); if (b) lap[dia] = b;
      const u = v('.p-uw'); if (u) uw[dia] = u;
      const h1 = v('.p-h135'); if (h1) h135[dia] = h1;
      const h2 = v('.p-h90'); if (h2) h90[dia] = h2;
    }
  });
  c.panjang_penyaluran_mm = ld;
  c.lap_splice_mm = lap;
  c.unit_weight_kg_per_m = uw;
  c.hook.tail_135_mm = h135;
  c.hook.tail_90_mm = h90;
  c.sengkang.zona_tumpuan_faktor = +$('pZona').value;
  c.sengkang.jarak_sengkang_pertama_mm = +$('pPertama').value;
  c.sengkang.metode_hitung = $('pMetode').value;
  // 11-SPEC §3: metode lap splice + offset berselang
  c.lap_splice = c.lap_splice || {};
  c.lap_splice.metode = $('pLapMetode').value;
  c.lap_splice.berselang_offset_mm = +$('pLapOffset').value || 0;

  // revisi wajib kalau nilai teknis proyek berubah
  const sig = (x) => JSON.stringify(x);
  const oldProj = proyekDefault;
  const teknisBerubah = sig(c.panjang_penyaluran_mm) !== sig(oldProj.panjang_penyaluran_mm)
    || sig(c.selimut_beton_mm) !== sig(oldProj.selimut_beton_mm)
    || sig(c.hook) !== sig(oldProj.hook)
    || sig(c.sengkang) !== sig(oldProj.sengkang)
    || (c.stok || {}).panjang_batang_mm !== (oldProj.stok || {}).panjang_batang_mm;
  const revisi = prompt(teknisBerubah
    ? 'Nilai teknis proyek berubah — revisi gambar wajib diisi:'
    : 'Revisi gambar (biarkan kosong kalau tidak berubah):', oldProj.sumber.revisi || '');
  if (revisi === null) return;
  if (teknisBerubah && revisi.trim() === oldProj.sumber.revisi) {
    alert('Revisi harus berbeda kalau nilai teknis berubah.'); return;
  }
  c.sumber.revisi = revisi.trim() || oldProj.sumber.revisi;

  // templates proyek fresh — format berlapis {balok: {...}} dari GET proyek,
  // bukan flat dari GET drawing (PATCH-05 §6)
  let tplProyek = proyekRaw.templates;
  try {
    const pf = await (await fetch(`/api/projects/${proyekAktif}`)).json();
    if (pf.ok && pf.templates) tplProyek = pf.templates;
  } catch (_e) { /* pakai fallback */ }
  if (tplProyek && !tplProyek.balok) tplProyek = { balok: tplProyek };

  const res = await fetch(`/api/projects/${proyekAktif}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kode: proyekAktif, config: c, templates: tplProyek })
  });
  const d = await res.json();
  if (!d.ok) { alert(d.error || 'Gagal simpan'); return; }
  paramModalClose();
  await pilihProyek(proyekAktif);
  renderSetupPage('proyek');
}

$('paramSave').onclick = paramSave;

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

// ── keyboard (09-SPEC §6): Ctrl+Enter = Hitung dari mana pun ──
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    hitung();
  }
});

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
  updateSetupNav();
  // warning dari proyek aktif (banner)
  const d = await (await fetch('/api/config')).json();
  if (d.ok && d.config.warnings && d.config.warnings.length) {
    $('warnBanner').textContent = d.config.warnings.join(' | ');
    $('warnBanner').classList.add('show');
  }
  // default area Kerja (09-SPEC §2)
  switchArea('kerja');
})();
