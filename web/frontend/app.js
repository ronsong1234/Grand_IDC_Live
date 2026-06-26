const state = {
  collections: [],
  currentCollection: null,
  slides: [],
  selected: new Map(),
  offset: 0,
  limit: 25,
  activeBatch: null,
  results: new Map(),
};

const $ = (id) => document.getElementById(id);
let slideLoadToken = 0;

async function api(path, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`${response.status} ${detail}`);
    }
    return response.json();
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out. Try a smaller search, uncheck Diagnostic only, or pick a TCGA collection.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function loadCollections() {
  const data = await api('/api/collections');
  $('idcVersion').textContent = `IDC ${data.idc_version}`;
  state.collections = data.collections;
  renderCollections();
}

function renderCollections() {
  const query = $('collectionSearch').value.toLowerCase();
  const select = $('collectionSelect');
  const previous = state.currentCollection || select.value;
  select.innerHTML = '';
  state.collections
    .filter(c => c.collection_id.toLowerCase().includes(query) || c.display_name.toLowerCase().includes(query))
    .forEach(c => {
      const option = document.createElement('option');
      option.value = c.collection_id;
      option.textContent = `${c.collection_id} (${c.slide_count} SM, ${c.license_short_name || 'license n/a'})`;
      if (c.collection_id === previous) option.selected = true;
      select.appendChild(option);
    });
  if (!select.value) {
    state.currentCollection = null;
    $('slidePageInfo').textContent = 'No matching collection selected.';
  }
}

async function loadSlides(reset = true) {
  const collection = $('collectionSelect').value;
  if (!collection) return;
  const token = ++slideLoadToken;
  if (collection !== state.currentCollection) {
    state.slides = [];
    state.selected.clear();
    renderSlides();
    updateSelectedCount();
  }
  state.currentCollection = collection;
  if (reset) state.offset = 0;
  $('slidePageInfo').textContent = `Loading ${collection} slides...`;
  const params = new URLSearchParams({
    limit: state.limit,
    offset: state.offset,
    search: $('slideSearch').value,
    diagnostic_only: $('diagnosticOnly').checked ? 'true' : 'false',
  });
  try {
    const data = await api(`/api/collections/${collection}/slides?${params}`);
    if (token !== slideLoadToken) return;
    state.slides = data.slides;
    if (data.total === 0) {
      const kind = data.diagnostic_only ? 'diagnostic slide microscopy series' : 'slide microscopy series';
      $('slidePageInfo').textContent = `${collection}: 0 ${kind} found. Try unchecking Diagnostic only or pick another collection.`;
    } else {
      $('slidePageInfo').textContent = `${collection}: ${data.total} slides, showing ${data.offset + 1}-${Math.min(data.offset + data.limit, data.total)}`;
    }
    renderSlides();
  } catch (err) {
    if (token !== slideLoadToken) return;
    state.slides = [];
    renderSlides();
    $('slidePageInfo').textContent = `Could not load ${collection}: ${err.message}`;
  }
}

function renderSlides() {
  const tbody = $('slideTable').querySelector('tbody');
  tbody.innerHTML = '';
  state.slides.forEach(slide => {
    const tr = document.createElement('tr');
    const checked = state.selected.has(slide.SeriesInstanceUID) ? 'checked' : '';
    const dims = slide.width_px && slide.height_px ? `${slide.width_px} x ${slide.height_px}` : '';
    tr.innerHTML = `
      <td><input type="checkbox" data-series="${slide.SeriesInstanceUID}" ${checked}></td>
      <td>${slide.slide_id}</td>
      <td>${slide.PatientID || ''}</td>
      <td>${dims}</td>
      <td>${slide.objective_power || ''}</td>
      <td>${slide.size_MB || ''}</td>
      <td>${slide.license_short_name || ''}</td>
      <td>${slide.already_processed ? '<span class="badge done">processed</span>' : ''}</td>
      <td>${slide.slim_url ? `<a href="${slide.slim_url}" target="_blank">Open</a>` : ''}</td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll('input[type="checkbox"]').forEach(input => {
    input.addEventListener('change', (event) => {
      const series = event.target.dataset.series;
      const slide = state.slides.find(s => s.SeriesInstanceUID === series);
      if (event.target.checked) state.selected.set(series, slide);
      else state.selected.delete(series);
      updateSelectedCount();
    });
  });
}

function updateSelectedCount() {
  $('selectedCount').textContent = `${state.selected.size} selected`;
}

async function runSelected() {
  if (!state.currentCollection || state.selected.size === 0) return;
  const runButton = $('runSelected');
  runButton.disabled = true;
  $('jobs').className = 'jobs muted';
  $('jobs').textContent = `Submitting ${state.selected.size} job(s)...`;
  const body = {
    collection_id: state.currentCollection,
    series: Array.from(state.selected.keys()),
    artifact_mpp: Number($('artifactMpp').value || 1.5),
    force: $('forceRun').checked,
  };
  try {
    const data = await api('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}, 120000);
    state.activeBatch = data.batch_id;
    pollBatch();
  } catch (err) {
    $('jobs').className = 'jobs error';
    $('jobs').textContent = `Could not submit jobs: ${err.message}`;
  } finally {
    runButton.disabled = false;
  }
}

async function pollBatch() {
  if (!state.activeBatch) return;
  const batch = await api(`/api/batches/${state.activeBatch}`);
  renderJobs(batch.jobs);
  batch.jobs.forEach(job => {
    if (job.state === 'done' && job.result) state.results.set(job.job_id, job.result);
  });
  renderResults();
  const unfinished = batch.jobs.some(job => !['done', 'failed'].includes(job.state));
  if (unfinished) setTimeout(pollBatch, 2000);
}

function renderJobs(jobs) {
  const box = $('jobs');
  box.className = 'jobs';
  box.innerHTML = '';
  jobs.forEach(job => {
    const div = document.createElement('div');
    div.className = `job ${job.state}`;
    div.innerHTML = `<strong>${job.slide_id || job.series_instance_uid}</strong><span>${job.state}</span><em>${job.error || job.message || ''}</em>`;
    box.appendChild(div);
  });
}

function renderResults() {
  const gallery = $('results');
  gallery.innerHTML = '';
  Array.from(state.results.values()).forEach(result => {
    const card = document.createElement('article');
    card.className = 'result-card';
    const flag = result.qc_flag_review ? `<span class="badge review">review</span>` : '';
    const tissueFlag = result.tissue_detection_suspect ? `<span class="badge review">tissue check</span>` : '';
    const usable = result.usable ? '<span class="badge done">usable</span>' : '<span class="badge fail">not usable</span>';
    card.innerHTML = `
      <header><h3>${result.slide_id}</h3><div>${usable}${flag}${tissueFlag}</div></header>
      <div class="metrics">
        <span>Tissue ${(result.tissue_percentage * 100).toFixed(2)}%</span>
        <span>Artifact ${(result.artifact_percentage_of_tissue * 100).toFixed(2)}%</span>
        <span>${result.reader_path_used}</span>
      </div>
      ${result.qc_flag_review ? `<p class="review-note">${result.qc_flag_reason}</p>` : ''}
      ${result.tissue_detection_suspect ? `<p class="review-note">${result.tissue_detection_reason}</p>` : ''}
      <div class="images">
        ${imageBlock('Mask', result.artifact_urls.mask)}
        ${imageBlock('Overlay', result.artifact_urls.overlay)}
        ${imageBlock('Map', result.artifact_urls.map)}
        ${imageBlock('Thumbnail', result.artifact_urls.thumbnail)}
      </div>
      <div class="bars">${Object.entries(result.artifact_fractions).map(([key, value]) => `<label>${pretty(key)}<progress max="1" value="${value}"></progress><span>${(value * 100).toFixed(1)}%</span></label>`).join('')}</div>
      <a href="${result.slim_url}" target="_blank">Open in IDC SLIM</a>`;
    gallery.appendChild(card);
  });
}

function imageBlock(label, url) {
  return `<figure><img src="${url}" alt="${label}"><figcaption>${label}</figcaption></figure>`;
}

function pretty(key) {
  return key.replace('_fraction', '').replaceAll('_', ' ');
}

function exportCsv() {
  const rows = Array.from(state.results.values());
  if (!rows.length) return;
  const headers = ['slide_id','collection_id','tissue_percentage','artifact_percentage_of_tissue','usable','qc_flag_review','qc_flag_reason','slim_url'];
  const csv = [headers.join(',')].concat(rows.map(row => headers.map(h => JSON.stringify(row[h] ?? '')).join(','))).join('\n');
  const blob = new Blob([csv], {type: 'text/csv'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'grandqc_live_results.csv';
  a.click();
  URL.revokeObjectURL(url);
}

$('collectionSearch').addEventListener('input', renderCollections);
$('collectionSelect').addEventListener('change', () => loadSlides(true));
$('loadSlides').addEventListener('click', () => loadSlides(true));
$('slideSearch').addEventListener('keydown', e => { if (e.key === 'Enter') loadSlides(true); });
$('diagnosticOnly').addEventListener('change', () => loadSlides(true));
$('prevPage').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); loadSlides(false); });
$('nextPage').addEventListener('click', () => { state.offset += state.limit; loadSlides(false); });
$('selectPage').addEventListener('click', () => { state.slides.forEach(slide => state.selected.set(slide.SeriesInstanceUID, slide)); renderSlides(); updateSelectedCount(); });
$('runSelected').addEventListener('click', runSelected);
$('exportCsv').addEventListener('click', exportCsv);

loadCollections().catch(err => { $('idcVersion').textContent = `Load failed: ${err.message}`; });
