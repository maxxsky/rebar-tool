/* Rebar BBS web — vanilla JS. NOL logika perhitungan: semua dari backend. */

const $ = (id) => document.getElementById(id);
let templates = {};
let lastResult = null;
let lastElemen = [];
let lastOverride = {};
let proyekAktif = localStorage.getItem('rebar_proyek') || '';

const fmtM = (mm) => (mm / 1000).toFixed(3);
const fmtKg = (v) => v.toFixed(2);

// ── proyek ─────────────────────────────────────────────────
async function loadProjek() {
  const d = await (await fetch('/api/projects')).json();
  const sel = $('projSelect');
  sel.innerHTML = '<option value="">— pilih proyek —</option>' +
    (d.projects || []).map(p =>
      `<option value="${p.kode}">${p.kode} — ${p.nama}</option>`).join('');
  if (proyekAktif) {
    const ok = (d.projects || []).some(p => p.kode === proyekAktif);
    if (ok) sel.value = proyekAktif;
    else { proyekAktif = ''; localStorage.removeItem('rebar_proyek'); }
  }
  updateProjLabel();
  return d.projects || [];
}

function updateProjLabel() {
  const sel = $('projSelect');
  const opt = sel.options[sel.selectedIndex];
  $('projLabel').textContent = opt && opt.value ? '' : '';
  // label diisi setelah config di-load (nama + sumber)
}

async function pilihProyek(kode) {
  if (!kode) { templates = {}; $('projLabel').textContent = ''; return; }
  proyekAktif = kode;
  localStorage.setItem('rebar_proyek', kode);
  const d = await (await fetch(`/api/projects/${kode}`)).json();
  if (!d.ok) return;
  templates = d.templates;
  const cfg = d.config;
  $('projLabel').textContent =
    `${cfg.proyek.nama} (${cfg.proyek.kode}) — ` +
    `${cfg.sumber.dokumen} ${cfg.sumber.revisi}`;
  renderParamFromConfig(cfg, []);
  if (cfg.sumber && cfg.sumber.warnings_placeholder) { /* noop */ }
}

$('projSelect').onchange = (e) => pilihProyek(e.target.value);
$('btnNewProj').onclick = () => bukaWizard('baru');
$('btnEditProj').onclick = async () => {
  if (!proyekAktif) { alert('Pilih proyek dulu.'); return; }
  const d = await (await fetch(`/api/projects/${proyekAktif}`)).json();
  if (d.ok) bukaWizard('edit', d);
};

// ── wizard ─────────────────────────────────────────────────
let wiz = null;      // { mode, kode, config, templates }
let wizStep = 1;

const UWTABEL = { 10: 0.617, 13: 1.042, 16: 1.578, 19: 2.226, 22: 2.984, 25: 3.853 };

function bukaWizard(mode, data = null) {
  wiz = {
    mode,
    kode: mode === 'edit' ? data.kode : '',
    config: data ? data.config : {
      proyek: { nama: '', kode: '' },
      sumber: { dokumen: '', revisi: '', tanggal: '', catatan: '' },
      stok: { panjang_batang_mm: 12000, kerf_mm: 3, sisa_min_simpan_mm: 1000 },
      selimut_beton_mm: { balok: '', kolom: '', plat: '' },
      panjang_penyaluran_mm: {},
      lap_splice_mm: {},
      unit_weight_kg_per_m: { ...UWTABEL },
      hook: { tail_135_mm: {}, tail_90_mm: {}, diameter_bengkok_faktor: 4,
              koreksi_bengkokan_aktif: false },
      sengkang: { zona_tumpuan_faktor: 0.25, jarak_sengkang_pertama_mm: 50,
                  metode_hitung: 'kontinyu' },
      optimizer: { max_pola: 8, batasi_pola: false },
    },
    templates: data ? data.templates : {},
  };
  wizStep = 1;
  $('wizTitle').textContent = mode === 'edit' ? `Edit ${data.kode}` : 'Proyek baru';
  $('wizard').style.display = 'flex';
  renderWizard();
}

function wizClose() { $('wizard').style.display = 'none'; wiz = null; }
$('wizClose').onclick = wizClose;

function wizSetStep(n) {
  wizStep = n;
  document.querySelectorAll('.step').forEach(s =>
    s.classList.toggle('active', Number(s.dataset.s) === n));
  renderWizard();
}

function renderWizard() {
  const body = $('wizBody');
  switch (wizStep) {
    case 1: body.innerHTML = renderW1(); break;
    case 2: body.innerHTML = renderW2(); break;
    case 3: body.innerHTML = renderW3(); break;
    case 4: body.innerHTML = renderW4(); break;
    case 5: body.innerHTML = renderW5(); break;
    case 6: body.innerHTML = renderW6(); break;
  }
  $('wizPrev').style.display = wizStep > 1 ? '' : 'none';
  $('wizNext').style.display = wizStep < 6 ? '' : 'none';
  $('wizSave').style.display = wizStep === 6 ? '' : 'none';
  if (wizStep === 6) wizSaveReview();
}

function renderW1() {
  const c = wiz.config;
  const wajib = (v) => (v && String(v).trim()) ? '✅' : '';
  return `<div class="wiz-field"><label>Nama proyek * ${wajib(c.proyek.nama)}</label>
    <input id="w1nama" value="${esc(c.proyek.nama)}" placeholder="Gedung Kantor Sumbawa"></div>
  <div class="wiz-field"><label>Kode * ${wajib(c.proyek.kode)}</label>
    <input id="w1kode" value="${esc(c.proyek.kode)}" placeholder="PRJ-001">
    <div class="wiz-hint">Jadi nama file. Hanya A-Z, a-z, 0-9, _ atau -.</div></div>
  <div class="wiz-grid">
    <div class="wiz-field"><label>Dokumen sumber * ${wajib(c.sumber.dokumen)}</label>
      <input id="w1dok" value="${esc(c.sumber.dokumen)}" placeholder="Gambar Struktur GS-01"></div>
    <div class="wiz-field"><label>Revisi * ${wajib(c.sumber.revisi)}</label>
      <input id="w1rev" value="${esc(c.sumber.revisi)}" placeholder="Rev.3"></div>
  </div>
  <div class="wiz-grid">
    <div class="wiz-field"><label>Tanggal revisi gambar * ${wajib(c.sumber.tanggal)}</label>
      <input id="w1tgl" type="date" value="${esc(c.sumber.tanggal)}"></div>
  </div>
  <div class="wiz-field"><label>Catatan sumber</label>
    <input id="w1cat" value="${esc(c.sumber.catatan)}" placeholder="tabel notes GS-01 sheet 2">
    <div class="wiz-hint">Sebutkan lokasi tabel di gambar, mis. 'tabel notes GS-01 sheet 2'.
      Enam bulan lagi kamu yang akan berterima kasih.</div></div>`;
}

function renderW2() {
  const c = wiz.config;
  return `<div class="wiz-grid">
    <div class="wiz-field"><label>Panjang batang stok (mm)</label>
      <input id="w2panjang" type="number" value="${c.stok.panjang_batang_mm}"></div>
    <div class="wiz-field"><label>Kerf (mm)</label>
      <input id="w2kerf" type="number" value="${c.stok.kerf_mm}"></div>
    <div class="wiz-field"><label>Sisa min simpan (mm)</label>
      <input id="w2sisa" type="number" value="${c.stok.sisa_min_simpan_mm}"></div>
  </div>
  <div class="wiz-field"><label>Selimut beton (mm) — dari gambar, tanpa default</label></div>
  <div class="wiz-grid">
    <div class="wiz-field"><label>Balok</label><input id="w2balok" type="number" value="${c.selimut_beton_mm.balok || ''}"></div>
    <div class="wiz-field"><label>Kolom</label><input id="w2kolom" type="number" value="${c.selimut_beton_mm.kolom || ''}"></div>
    <div class="wiz-field"><label>Plat</label><input id="w2plat" type="number" value="${c.selimut_beton_mm.plat || ''}"></div>
  </div>`;
}

function renderW3() {
  const c = wiz.config;
  const dias = new Set([...Object.keys(c.panjang_penyaluran_mm || {}),
                        ...Object.keys(c.hook.tail_135_mm || {}),
                        ...Object.keys(c.hook.tail_90_mm || {}),
                        ...Object.keys(c.unit_weight_kg_per_m || {}),
                        ...Object.keys(c.lap_splice_mm || {})].map(Number));
  [...Object.keys(UWTABEL)].map(Number).forEach(d => dias.add(d));
  const rows = [...dias].sort((a, b) => a - b).map(d => `
    <tr data-dia="${d}">
      <td><b>D${d}</b></td>
      <td><input class="d-ld" type="number" value="${c.panjang_penyaluran_mm[d] || ''}"></td>
      <td><input class="d-lap" type="number" value="${c.lap_splice_mm[d] || ''}" placeholder="opsional (F6)"></td>
      <td><input class="d-uw" type="number" step="0.001" value="${c.unit_weight_kg_per_m[d] ?? UWTABEL[d] ?? ''}"></td>
      <td><input class="d-h135" type="number" value="${c.hook.tail_135_mm[d] || ''}"></td>
      <td><input class="d-h90" type="number" value="${c.hook.tail_90_mm[d] || ''}"></td>
    </tr>`).join('');
  return `<div class="wiz-warn">⚠ Nilai Ld, lap splice, dan hook tail harus diambil dari gambar dan
    spesifikasi proyek ini — bukan dari standar generik atau proyek lain.</div>
  <table class="dia-table"><thead><tr>
    <th>Ø</th><th>Ld (mm)</th><th>Lap splice (mm)</th><th>Unit weight (kg/m)</th>
    <th>Hook 135 tail</th><th>Hook 90 tail</th></tr></thead>
  <tbody id="diaBody">${rows}</tbody></table>
  <button class="btn" onclick="addDiaRow()">+ diameter</button>`;
}

function addDiaRow() {
  const body = $('diaBody');
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><input class="d-dia" type="number" placeholder="Ø"></td>
    <td><input class="d-ld" type="number"></td>
    <td><input class="d-lap" type="number"></td><td><input class="d-uw" type="number" step="0.001"></td>
    <td><input class="d-h135" type="number"></td><td><input class="d-h90" type="number"></td>`;
  body.appendChild(tr);
}

function renderW4() {
  const s = wiz.config.sengkang;
  const k = wiz.config.hook.koreksi_bengkokan_aktif;
  return `<div class="wiz-grid">
    <div class="wiz-field"><label>Zona tumpuan faktor</label>
      <input id="w4zona" type="number" step="0.05" min="0" max="0.5" value="${s.zona_tumpuan_faktor}"></div>
    <div class="wiz-field"><label>Jarak sengkang pertama (mm)</label>
      <input id="w4pertama" type="number" value="${s.jarak_sengkang_pertama_mm}"></div>
    <div class="wiz-field"><label>Metode hitung</label>
      <select id="w4metode"><option value="kontinyu" ${s.metode_hitung === 'kontinyu' ? 'selected' : ''}>kontinyu</option>
      <option value="per_zona" ${s.metode_hitung === 'per_zona' ? 'selected' : ''}>per_zona</option></select></div>
  </div>
  <div class="wiz-field"><label>
    <input id="w4koreksi" type="checkbox" ${k ? 'checked' : ''}> Koreksi bengkokan aktif</label>
    <div class="wiz-hint">Default false. Nilainya baru boleh diaktifkan setelah dikalibrasi
      di verifikasi (05-VERIFICATION.md §3.3).</div></div>`;
}

function renderW5() {
  const tpls = wiz.templates.balok || {};
  const names = Object.keys(tpls);
  let html = '';
  names.forEach(n => { html += tplBlockHtml(n, tpls[n]); });
  html += `<button class="btn" onclick="addTpl()">+ tipe balok</button>`;
  return `<div class="wiz-hint" style="margin-bottom:8px">Minimal satu tipe elemen. Dimensi & tulangan dari gambar.</div>${html}`;
}

function tplBlockHtml(nama, t) {
  const tul = (t.tulangan || []).map((x, i) => `
    <div class="tul-row">
      <select class="t-pos"><option value="atas" ${x.posisi === 'atas' ? 'selected' : ''}>atas</option>
        <option value="bawah" ${x.posisi === 'bawah' ? 'selected' : ''}>bawah</option>
        <option value="pinggang" ${x.posisi === 'pinggang' ? 'selected' : ''}>pinggang</option></select>
      <input class="t-dia" type="number" value="${x.dia}" placeholder="Ø">
      <input class="t-jum" type="number" value="${x.jumlah}" placeholder="jml">
      <label class="wiz-hint"><input class="t-dua" type="checkbox" ${x.tumpuan_kedua_ujung ? 'checked' : ''}> 2 ujung</label>
      <button class="del" onclick="this.closest('.tul-row').remove()">✕</button>
    </div>`).join('');
  const sk = t.sengkang || {};
  return `<div class="tpl-block">
    <button class="del" onclick="this.closest('.tpl-block').remove()">✕ hapus tipe</button>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Nama tipe</label><input class="t-nama" value="${esc(nama)}"></div>
      <div class="wiz-field"><label>Deskripsi</label><input class="t-desk" value="${esc(t.deskripsi || '')}"></div>
      <div class="wiz-field"><label>b (mm)</label><input class="t-b" type="number" value="${t.b_mm}"></div>
      <div class="wiz-field"><label>h (mm)</label><input class="t-h" type="number" value="${t.h_mm}"></div>
    </div>
    <div class="wiz-hint">Tulangan</div>
    <div id="tulList">${tul}</div>
    <button class="btn" onclick="addTul(this)">+ tulangan</button>
    <div class="wiz-grid">
      <div class="wiz-field"><label>Sengkang Ø</label><input class="t-skdia" type="number" value="${sk.dia || ''}"></div>
      <div class="wiz-field"><label>Jarak tumpuan (mm)</label><input class="t-skt" type="number" value="${sk.jarak_tumpuan_mm || ''}"></div>
      <div class="wiz-field"><label>Jarak lapangan (mm)</label><input class="t-skl" type="number" value="${sk.jarak_lapangan_mm || ''}"></div>
      <div class="wiz-field"><label>Kaki</label><input class="t-skkaki" type="number" value="${sk.kaki || 2}"></div>
      <div class="wiz-field"><label>Hook sudut</label><select class="t-skhook">
        <option value="135" ${sk.hook_sudut === 135 ? 'selected' : ''}>135°</option>
        <option value="90" ${sk.hook_sudut === 90 ? 'selected' : ''}>90°</option></select></div>
    </div>
  </div>`;
}

function addTpl() {
  wiz.templates.balok = wiz.templates.balok || {};
  const next = 'B' + (Object.keys(wiz.templates.balok).length + 1);
  wiz.templates.balok[next] = {
    deskripsi: '', b_mm: '', h_mm: '', tulangan: [{ posisi: 'atas', dia: '', jumlah: '', tumpuan_kedua_ujung: true }],
    sengkang: { dia: '', jarak_tumpuan_mm: '', jarak_lapangan_mm: '', kaki: 2, hook_sudut: 135 } };
  renderWizard();
}

function addTul(btn) {
  const list = btn.closest('.tpl-block').querySelector('#tulList');
  const div = document.createElement('div');
  div.className = 'tul-row';
  div.innerHTML = `<select class="t-pos"><option>atas</option><option>bawah</option><option>pinggang</option></select>
    <input class="t-dia" type="number" placeholder="Ø"><input class="t-jum" type="number" placeholder="jml">
    <label class="wiz-hint"><input class="t-dua" type="checkbox" checked> 2 ujung</label>
    <button class="del" onclick="this.closest('.tul-row').remove()">✕</button>`;
  list.appendChild(div);
}

// ── collect wizard → payload ───────────────────────────────
function bacaWizard() {
  if (wizStep === 1) {
    wiz.config.proyek.nama = $('w1nama').value.trim();
    wiz.config.proyek.kode = $('w1kode').value.trim();
    wiz.config.sumber.dokumen = $('w1dok').value.trim();
    wiz.config.sumber.revisi = $('w1rev').value.trim();
    wiz.config.sumber.tanggal = $('w1tgl').value;
    wiz.config.sumber.catatan = $('w1cat').value.trim();
  } else if (wizStep === 2) {
    wiz.config.stok.panjang_batang_mm = +$('w2panjang').value;
    wiz.config.stok.kerf_mm = +$('w2kerf').value;
    wiz.config.stok.sisa_min_simpan_mm = +$('w2sisa').value;
    wiz.config.selimut_beton_mm = { balok: +$('w2balok').value, kolom: +$('w2kolom').value, plat: +$('w2plat').value };
  } else if (wizStep === 3) {
    const ld = {}, lap = {}, uw = {}, h135 = {}, h90 = {};
    document.querySelectorAll('#diaBody tr').forEach(tr => {
      const diaInput = tr.querySelector('.d-dia');
      const diaRaw = (tr.querySelector('b') || {}).textContent || '';
      let dia = diaInput && diaInput.value !== '' ? +diaInput.value
               : (parseInt(diaRaw.replace('D', '')) || NaN);
      if (!isNaN(dia)) {
        const v = (sel) => { const x = tr.querySelector(sel); return x && x.value !== '' ? +x.value : undefined; };
        const a = v('.d-ld'); if (a) ld[dia] = a;
        const b = v('.d-lap'); if (b) lap[dia] = b;
        const c2 = v('.d-uw'); if (c2) uw[dia] = c2;
        const d = v('.d-h135'); if (d) h135[dia] = d;
        const e = v('.d-h90'); if (e) h90[dia] = e;
      }
    });
    wiz.config.panjang_penyaluran_mm = ld;
    wiz.config.lap_splice_mm = lap;
    wiz.config.unit_weight_kg_per_m = uw;
    wiz.config.hook.tail_135_mm = h135;
    wiz.config.hook.tail_90_mm = h90;
  } else if (wizStep === 4) {
    wiz.config.sengkang.zona_tumpuan_faktor = +$('w4zona').value;
    wiz.config.sengkang.jarak_sengkang_pertama_mm = +$('w4pertama').value;
    wiz.config.sengkang.metode_hitung = $('w4metode').value;
    wiz.config.hook.koreksi_bengkokan_aktif = $('w4koreksi').checked;
  } else if (wizStep === 5) {
    const tpls = {};
    document.querySelectorAll('.tpl-block').forEach(block => {
      const nama = block.querySelector('.t-nama').value.trim();
      if (!nama) return;
      const tulangan = [];
      block.querySelectorAll('#tulList .tul-row').forEach(row => {
        const dia = +row.querySelector('.t-dia').value;
        const jum = +row.querySelector('.t-jum').value;
        if (dia && jum) tulangan.push({
          posisi: row.querySelector('.t-pos').value, dia, jumlah: jum,
          tumpuan_kedua_ujung: row.querySelector('.t-dua').checked });
      });
      tpls[nama] = {
        deskripsi: block.querySelector('.t-desk').value,
        b_mm: +block.querySelector('.t-b').value,
        h_mm: +block.querySelector('.t-h').value,
        tulangan,
        sengkang: { dia: +block.querySelector('.t-skdia').value,
                    jarak_tumpuan_mm: +block.querySelector('.t-skt').value,
                    jarak_lapangan_mm: +block.querySelector('.t-skl').value,
                    kaki: +block.querySelector('.t-skkaki').value,
                    hook_sudut: +block.querySelector('.t-skhook').value },
      };
    });
    wiz.templates = { balok: tpls };
  }
}

function renderW6() {
  bacaWizard();
  return `<div class="wiz-hint" style="margin-bottom:8px">Review — validasi dijalankan server saat simpan.</div>
    <div id="wizReview" style="font-family:ui-monospace,monospace;font-size:12px;line-height:1.7"></div>`;
}

async function wizSaveReview() {
  const c = wiz.config;
  $('wizReview').textContent =
    `PROYEK  : ${c.proyek.nama} (${c.proyek.kode})\n` +
    `SUMBER  : ${c.sumber.dokumen} ${c.sumber.revisi} (${c.sumber.tanggal})\n` +
    `stok ${c.stok.panjang_batang_mm} | kerf ${c.stok.kerf_mm} | sisa min ${c.stok.sisa_min_simpan_mm}\n` +
    `cover: balok ${c.selimut_beton_mm.balok} | kolom ${c.selimut_beton_mm.kolom} | plat ${c.selimut_beton_mm.plat}\n` +
    `Ld: ` + Object.entries(c.panjang_penyaluran_mm).map(([k, v]) => `D${k}=${v}`).join(' ') + '\n' +
    `sengkang: zona ${c.sengkang.zona_tumpuan_faktor} | pertama ${c.sengkang.jarak_sengkang_pertama_mm} | metode ${c.sengkang.metode_hitung}\n` +
    `template: ` + Object.keys((wiz.templates.balok) || {}).join(', ');
}

$('wizPrev').onclick = () => { bacaWizard(); wizSetStep(wizStep - 1); };
$('wizNext').onclick = () => {
  bacaWizard();
  if (wizStep === 1) {
    const c = wiz.config;
    if (!c.proyek.nama || !c.proyek.kode || !c.sumber.dokumen || !c.sumber.revisi || !c.sumber.tanggal) {
      alert('Nama, kode, dan tiga field sumber (dokumen/revisi/tanggal) wajib diisi.'); return;
    }
  }
  if (wizStep === 2) {
    const c = wiz.config.selimut_beton_mm;
    if (!c.balok || !c.kolom || !c.plat) { alert('Selimut beton wajib diisi (dari gambar).'); return; }
  }
  wizSetStep(wizStep + 1);
};
$('wizSave').onclick = async () => {
  bacaWizard();
  const payload = { kode: wiz.config.proyek.kode, config: wiz.config, templates: wiz.templates };
  const url = wiz.mode === 'edit' ? `/api/projects/${wiz.kode}` : '/api/projects';
  const res = await fetch(url, {
    method: wiz.mode === 'edit' ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload) });
  const d = await res.json();
  if (res.status === 409) {
    const pilihan = confirm(`${d.error}\n\nPakai kode lain? (OK = edit file, arsip otomatis)`);
    if (pilihan) {
      const res2 = await fetch(`/api/projects/${d.kode}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload) });
      const d2 = await res2.json();
      if (d2.ok) { wizClose(); await loadProjek(); $('projSelect').value = d.kode; await pilihProyek(d.kode); }
      else alert(d2.error || 'Gagal simpan');
    }
    return;
  }
  if (!d.ok) { alert(d.error || 'Gagal simpan'); return; }
  wizClose();
  await loadProjek();
  $('projSelect').value = d.kode;
  await pilihProyek(d.kode);
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
  const override = bacaOverride();
  lastElemen = elemen; lastOverride = override;

  const res = await fetch('/api/hitung', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ elemen, override, kode: proyekAktif })
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
    body: JSON.stringify({ elemen, override, kode: proyekAktif })
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
