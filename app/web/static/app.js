const $ = (id) => document.getElementById(id);
let currentJob = null;
let polling = null;
const fmt = (n, digits = 1) => Number(n).toLocaleString(undefined, {maximumFractionDigits: digits});
const duration = (seconds) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
const fileUrl = (path) => `/api/jobs/${currentJob.id}/files/${path.split('/').map(encodeURIComponent).join('/')}`;
function showError(message) { $('error').textContent = message; $('error').hidden = false; }
function details(id, pairs) {
  const list = $(id); list.replaceChildren();
  pairs.forEach(([name, value]) => {
    const dt = document.createElement('dt'); dt.textContent = name;
    const dd = document.createElement('dd'); dd.textContent = value;
    list.append(dt, dd);
  });
}
$('video').addEventListener('change', () => {
  const file = $('video').files[0];
  $('filename').textContent = file ? `${file.name} · ${fmt(file.size / 1024 ** 2)} MB` : 'Select an MP4 or MOV video';
});
$('upload-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const file = $('video').files[0]; if (!file) return;
  $('error').hidden = true; $('upload-button').disabled = true;
  $('upload-progress').hidden = false;
  const xhr = new XMLHttpRequest();
  xhr.open('POST', `/api/jobs?filename=${encodeURIComponent(file.name)}`);
  xhr.setRequestHeader('Content-Type', 'application/octet-stream');
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const value = Math.round(100 * e.loaded / e.total);
      $('upload-bar').value = value; $('upload-percent').textContent = `${value}%`;
    }
  };
  xhr.onload = () => {
    $('upload-button').disabled = false;
    let response; try { response = JSON.parse(xhr.responseText); } catch { showError('The server returned an unexpected response.'); return; }
    if (xhr.status !== 202) { showError(response.detail || 'Upload failed.'); return; }
    window.location.assign(response.url);
  };
  xhr.onerror = () => { showError('Upload connection failed. Check that the local server is running.'); $('upload-button').disabled = false; };
  xhr.send(file);
});
function renderResult(job) {
  $('processing-page').hidden = true; $('result-page').hidden = false;
  $('result-filename').textContent = job.filename;
  const v = job.video, q = job.quality;
  const threshold = fmt(q.thresholds.confidence, 3);
  $('overlay-legend').textContent = `Green: confidence ≥ ${threshold} · Amber: lower confidence · Overlay videos are silent. The original upload is preserved.`;
  $('lost-note').textContent = `Missing detection or confidence below ${threshold}, excluding ambiguous multi-person frames.`;
  details('video-details', [['Duration', duration(v.decoded_duration_s || v.duration_s)],
    ['Resolution', `${v.width} × ${v.height}`], ['FPS', fmt(v.fps, 3)],
    ['Orientation', v.orientation], ['Codec', v.codec], ['Frames processed', fmt(job.frames_processed, 0)]]);
  details('tracking-details', [['Person detected', `${fmt(q.person_detected_percent)}% of frames`],
    ['Mean visibility', fmt(q.mean_landmark_visibility, 3)], ['Mean presence', fmt(q.mean_landmark_presence, 3)],
    ['Mean body confidence', fmt(q.mean_body_confidence, 3)], ['Tracking interruptions', q.tracking_interruptions],
    ['Multiple-person frames', q.multiple_person_frames], ['Jump flags', q.jump_frames],
    ['Depth instability flags', q.depth_unstable_frames], ['Processing time', duration(job.processing_seconds)]]);
  $('quality-label').textContent = q.quality.toUpperCase(); $('quality-label').className = `quality ${q.quality}`;
  $('limitations').replaceChildren();
  [...q.limitations, ...v.warnings].forEach(text => { const li = document.createElement('li'); li.textContent = text; $('limitations').append(li); });
  $('overlay-mode').value = 'smoothed'; updateVideo();
  $('gallery').replaceChildren();
  job.gallery.forEach(item => {
    const article = document.createElement('article'); article.className = 'gallery-item';
    const meta = document.createElement('div'); meta.className = 'gallery-meta';
    const title = document.createElement('strong'); title.textContent = `${duration(item.timestamp_s)} · Frame ${item.frame_number} · Confidence ${fmt(item.confidence, 2)}`;
    const reasons = document.createElement('span'); reasons.textContent = item.reasons.join(' · '); meta.append(title, reasons); article.append(meta);
    const images = document.createElement('div'); images.className = 'gallery-images';
    [['original', 'Original'], ['raw', 'Raw pose overlay'], ['smoothed', 'Smoothed pose overlay']].forEach(([key, label]) => {
      const figure = document.createElement('figure'); const caption = document.createElement('figcaption'); caption.textContent = label;
      const link = document.createElement('a'); link.href = fileUrl(item[key]); link.target = '_blank'; link.rel = 'noopener';
      const img = document.createElement('img'); img.src = link.href; img.alt = `${label}, frame ${item.frame_number}`; img.loading = 'lazy';
      link.append(img); figure.append(caption, link); images.append(figure);
    }); article.append(images); $('gallery').append(article);
  });
  $('files').replaceChildren();
  [[job.original_path, 'Original uploaded video'], ['output/pose-overlay.mp4', 'Smoothed overlay MP4'],
    ['output/pose-overlay-raw.mp4', 'Raw overlay MP4'], ['tracking/raw.jsonl.gz', 'Raw tracking data · JSONL.gz'],
    ['tracking/smoothed.jsonl.gz', 'Smoothed tracking data · JSONL.gz'], ['tracking/quality.json', 'Tracking-quality report · JSON'],
    ['tracking/schema.json', 'Data schema & model configuration'], ['tracking/events.jsonl.gz', 'All anomaly events · JSONL.gz'],
    ['tracking/metrics.sqlite3', 'Per-frame quality metrics · SQLite']].forEach(([path, label]) => {
      const link = document.createElement('a'); link.href = fileUrl(path); link.download = path.split('/').pop(); link.textContent = label; $('files').append(link);
    });
  $('lost-landmarks').replaceChildren();
  [...q.landmark_loss].sort((a,b) => b.lost_percent - a.lost_percent).slice(0, 8).forEach(item => {
    const row = document.createElement('tr'); [item.name.replaceAll('_', ' '), item.lost_frames, `${fmt(item.lost_percent)}%`].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    }); $('lost-landmarks').append(row);
  });
  $('job-id').textContent = `Job ${job.id} · Heavy model · VIDEO tracking · Data stored locally`;
}
function updateVideo() {
  if (!currentJob) return;
  const mode = $('overlay-mode').value;
  const source = mode === 'original' ? currentJob.original_path : mode === 'raw' ? 'output/pose-overlay-raw.mp4' : 'output/pose-overlay.mp4';
  const video = $('overlay-video'); const at = video.currentTime || 0; const playing = !video.paused;
  video.src = fileUrl(source); video.onloadedmetadata = () => { video.currentTime = Math.min(at, video.duration || at); if (playing) video.play().catch(() => {}); };
}
$('overlay-mode').addEventListener('change', updateVideo);
async function poll(id) {
  try {
    const response = await fetch(`/api/jobs/${id}`);
    const job = await response.json();
    if (!response.ok) { showError(job.detail || 'Job not found.'); return; }
    currentJob = job; $('error').hidden = true;
    $('job-filename').textContent = job.filename; $('stage').textContent = job.stage;
    $('process-bar').value = job.progress;
    $('process-detail').textContent = `${Math.round(job.progress * 100)}% · ${fmt(job.frames_processed, 0)} frames tracked · Last update ${Math.max(0, Math.round(Date.now()/1000-job.updated_at))}s ago`;
    if (job.state === 'complete') { renderResult(job); return; }
    if (job.state === 'failed') { showError(`${job.error}\nChoose a new video from the Linko link above to retry.`); return; }
  } catch { showError('Waiting for the local server to reconnect… This job URL can be reopened.'); }
  polling = setTimeout(() => poll(id), 1500);
}
const match = window.location.pathname.match(/^\/jobs\/([a-f0-9-]+)$/);
if (match) { $('upload-page').hidden = true; $('processing-page').hidden = false; poll(match[1]); }
window.addEventListener('pagehide', () => clearTimeout(polling));
