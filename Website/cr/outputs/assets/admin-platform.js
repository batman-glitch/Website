const uploadBlob = async (...args) => { const { upload } = await import('@vercel/blob/client'); return upload(...args); };

const $ = (id) => document.getElementById(id);
const state = { csrf: '', email: '', mfaEnabled: false, projects: [], services: [], settings: {}, inquiriesPage: 1, inquiryPages: 1, noticeTimer: 0 };
const adminApi = async (url, options = {}) => {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) headers.set('X-CSRF-Token', csrfToken());
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin', cache: 'no-store' });
  const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
  if (!response.ok) {
    if (response.status === 401) showLogin('Your secure session ended. Sign in again.');
    throw new Error(data.error || `Could not complete that request (${response.status}).`);
  }
  return data;
};
function csrfToken() {
  const found = document.cookie.split(';').map((part) => part.trim()).find((part) => part.startsWith('__Host-blessson-csrf=') || part.startsWith('blessson_csrf='));
  return found ? decodeURIComponent(found.slice(found.indexOf('=') + 1)) : '';
}
function setStatus(text, connected = true) {
  const el = $('secure-status');
  el.classList.toggle('error', !connected);
  el.querySelector('span').textContent = text;
}
function showLogin(message = '') {
  $('auth-view').hidden = false;
  $('password-view').hidden = true;
  $('workspace').hidden = true;
  $('account-menu').hidden = true;
  $('login-message').textContent = message;
  $('login-message').classList.toggle('success', false);
  $('admin-password').value = '';
  $('mfa-code').value = '';
  setStatus('Private access', true);
}
function showPassword(force, message = '') {
  $('auth-view').hidden = true;
  $('workspace').hidden = true;
  $('password-view').hidden = false;
  $('current-password-wrap').hidden = force;
  $('password-description').textContent = force ? 'Your account needs a new passphrase before the studio can open.' : 'Choose a fresh passphrase. Existing signed-in devices will be signed out.';
  $('password-message').textContent = message;
}
function showWorkspace(session) {
  state.email = session.email || '';
  state.mfaEnabled = Boolean(session.mfaEnabled);
  $('auth-view').hidden = true;
  $('password-view').hidden = true;
  $('workspace').hidden = false;
  $('account-menu').hidden = false;
  $('account-menu').textContent = (state.email[0] || 'B').toUpperCase();
  setStatus('Secure studio connected', true);
  renderMfaState();
  loadWorkspaceData().catch((error) => notice(error.message, true));
}
function notice(message, error = false) {
  const box = $('global-notice');
  box.textContent = message;
  box.classList.toggle('error', error);
  window.clearTimeout(state.noticeTimer);
  state.noticeTimer = window.setTimeout(() => { box.textContent = ''; box.classList.remove('error'); }, 5600);
}
function setMessage(element, message, success = false) {
  element.textContent = message;
  element.classList.toggle('success', success);
}
function renderMfaState() {
  const badge = $('mfa-state');
  badge.textContent = state.mfaEnabled ? 'Enabled' : 'Recommended';
  badge.classList.toggle('enabled', state.mfaEnabled);
  $('mfa-alert').hidden = state.mfaEnabled;
  $('metric-mfa').textContent = state.mfaEnabled ? 'Enabled' : 'Set up MFA';
  $('enable-mfa').hidden = state.mfaEnabled;
}
async function boot() {
  try {
    const health = await adminApi('/api/admin?action=health');
    if (!health.configured) { showLogin('Administrator account setup is not complete.'); setStatus('Setup needed', false); return; }
    const session = await adminApi('/api/admin?action=session');
    if (!session.authenticated) { showLogin(); return; }
    if (session.mustChangePassword) { showPassword(true); return; }
    showWorkspace(session);
  } catch (error) {
    showLogin(error.message || 'Secure service is not available right now.');
    setStatus('Connection needs attention', false);
  }
}
$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('login-button');
  button.disabled = true;
  $('login-message').classList.remove('success');
  setMessage($('login-message'), 'Checking your private sign-in…');
  try {
    const result = await adminApi('/api/admin?action=login', { method: 'POST', body: JSON.stringify({ email: $('admin-email').value.trim(), password: $('admin-password').value, mfaCode: $('mfa-code').value.trim() }) });
    if (result.mustChangePassword) showPassword(true, 'For your security, set a new password before continuing.');
    else showWorkspace(result);
  } catch (error) { setMessage($('login-message'), error.message); }
  finally { button.disabled = false; }
});
$('password-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const newPassword = $('new-password').value;
  if (newPassword !== $('confirm-password').value) return setMessage($('password-message'), 'The new passphrases do not match.');
  try {
    await adminApi('/api/admin?action=password', { method: 'POST', body: JSON.stringify({ currentPassword: $('current-password').value, newPassword }) });
    $('new-password').value = ''; $('confirm-password').value = ''; $('current-password').value = '';
    setMessage($('password-message'), 'Password saved. Reconnecting to your studio…', true);
    const session = await adminApi('/api/admin?action=session');
    if (session.authenticated) showWorkspace(session); else showLogin('Password updated. Sign in with your new passphrase.');
  } catch (error) { setMessage($('password-message'), error.message); }
});
$('signout-button').addEventListener('click', async () => {
  try { await adminApi('/api/admin?action=logout', { method: 'POST', body: '{}' }); } catch { /* A session may already have expired. */ }
  showLogin('You have signed out.');
});
$('account-menu').addEventListener('click', () => switchView('security'));

document.querySelectorAll('.side-link').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
document.querySelectorAll('[data-nav]').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.nav)));
document.querySelectorAll('[data-action="new-project"]').forEach((button) => button.addEventListener('click', () => { switchView('projects'); clearProjectForm(); $('project-title').focus(); }));
function switchView(name) {
  document.querySelectorAll('.side-link').forEach((button) => button.classList.toggle('active', button.dataset.view === name));
  document.querySelectorAll('.view-panel').forEach((panel) => panel.classList.toggle('active', panel.dataset.panel === name));
  if (name === 'projects') loadProjects();
  if (name === 'services') loadServices();
  if (name === 'inquiries') loadInquiries(1);
  if (name === 'website') loadSettings();
  if (name === 'security') refreshSecurity();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
async function loadWorkspaceData() {
  const settled = await Promise.allSettled([loadProjects(), loadServices(), loadSettings(), loadInquiries(1)]);
  const error = settled.find((result) => result.status === 'rejected');
  if (error) notice(error.reason?.message || 'One section could not refresh.', true);
}

async function loadProjects() {
  const result = await adminApi('/api/admin/projects');
  state.projects = result.projects || [];
  renderProjects();
}
function renderProjects() {
  const list = $('project-list'); list.replaceChildren();
  $('project-count').textContent = String(state.projects.length);
  $('project-nav-count').textContent = String(state.projects.filter((project) => project.is_published).length);
  $('metric-projects').textContent = String(state.projects.filter((project) => project.is_published).length);
  $('project-filter').onchange = renderProjects;
  const filter = $('project-filter').value;
  const projects = state.projects.filter((project) => filter === 'all' || (filter === 'published' ? project.is_published : !project.is_published));
  if (!projects.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    const title = document.createElement('strong'); title.textContent = state.projects.length ? 'No projects in this view yet.' : 'Your first project starts here.';
    const copy = document.createElement('span'); copy.textContent = state.projects.length ? 'Try another filter.' : 'Add a title, cover, and audio preview when you are ready.';
    empty.append(title, copy); list.append(empty);
  }
  projects.forEach((project) => {
    const item = document.createElement('button'); item.type = 'button'; item.className = 'project-item'; item.dataset.id = project.id;
    if (String($('project-id').value) === String(project.id)) item.classList.add('selected');
    const image = project.cover_url ? document.createElement('img') : document.createElement('span');
    if (project.cover_url) { image.src = project.cover_url; image.alt = ''; } else image.className = 'project-thumb-empty';
    const content = document.createElement('span'); content.className = 'project-item-content';
    const title = document.createElement('strong'); title.textContent = project.title;
    const meta = document.createElement('small'); meta.textContent = [project.artist, project.service, project.release_year].filter(Boolean).join(' · ');
    content.append(title, meta);
    const status = document.createElement('span'); status.className = `status-pill ${project.is_published ? 'live' : 'draft'}`; status.textContent = project.is_published ? 'Live' : 'Draft';
    item.append(image, content, status); item.addEventListener('click', () => editProject(project.id)); list.append(item);
  });
  const recent = $('overview-projects'); recent.replaceChildren();
  const recentItems = state.projects.slice(0, 4);
  if (!recentItems.length) { const empty = document.createElement('div'); empty.className = 'empty-state'; empty.textContent = 'Your saved work will appear here.'; recent.append(empty); }
  recentItems.forEach((project) => {
    const row = document.createElement('div'); row.className = 'compact-row';
    const image = project.cover_url ? document.createElement('img') : document.createElement('span');
    if (project.cover_url) { image.src = project.cover_url; image.alt = ''; } else image.className = 'compact-thumb';
    image.classList.add('compact-thumb');
    const copy = document.createElement('div'); const title = document.createElement('h3'); title.textContent = project.title; const detail = document.createElement('p'); detail.textContent = project.service; copy.append(title, detail);
    const badge = document.createElement('span'); badge.className = `status-pill ${project.is_published ? 'live' : 'draft'}`; badge.textContent = project.is_published ? 'Live' : 'Draft'; row.append(image, copy, badge); row.addEventListener('click', () => { switchView('projects'); editProject(project.id); }); recent.append(row);
  });
}
function clearProjectForm() {
  $('project-form').reset(); $('project-id').value = ''; $('project-order').value = '0'; $('cover-url').value = ''; $('audio-url').value = '';
  $('cover-file').value = ''; $('audio-file').value = ''; $('cover-preview').hidden = true; $('audio-preview').hidden = true;
  $('editor-kicker').textContent = 'NEW PORTFOLIO ITEM'; $('editor-title').textContent = 'Add a project'; $('project-published').checked = false; $('project-featured').checked = false;
  $('save-project').querySelector('span').textContent = 'Publish project'; setMessage($('project-message'), '');
}
function editProject(id) {
  const project = state.projects.find((item) => String(item.id) === String(id)); if (!project) return;
  $('project-id').value = project.id; $('project-title').value = project.title; $('project-artist').value = project.artist || ''; $('project-service').value = project.service; $('project-genre').value = project.genre || ''; $('project-year').value = project.release_year || ''; $('project-order').value = project.display_order ?? 0; $('project-description').value = project.description || ''; $('audio-label').value = project.audio_label || ''; $('cover-url').value = project.cover_url || ''; $('audio-url').value = project.audio_url || ''; $('project-published').checked = project.is_published; $('project-featured').checked = project.is_featured;
  $('editor-kicker').textContent = project.is_published ? 'PUBLISHED PROJECT' : 'SAVED DRAFT'; $('editor-title').textContent = project.title; $('save-project').querySelector('span').textContent = project.is_published ? 'Save changes' : 'Publish project';
  showPreview('cover', project.cover_url, 'Current cover'); showPreview('audio', project.audio_url, project.audio_label || 'Current audio preview'); renderProjects(); $('project-editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
$('clear-project').addEventListener('click', clearProjectForm);
$('project-filter').addEventListener('change', renderProjects);
$('project-published').addEventListener('change', () => { $('save-project').querySelector('span').textContent = $('project-published').checked ? 'Publish project' : 'Save changes'; });
$('project-form').addEventListener('submit', (event) => { event.preventDefault(); saveProject($('project-published').checked); });
$('save-draft').addEventListener('click', () => saveProject(false));
async function saveProject(published) {
  const button = $('save-project'); button.disabled = true; setMessage($('project-message'), 'Saving your project…');
  const payload = { id: $('project-id').value || undefined, title: $('project-title').value.trim(), artist: $('project-artist').value.trim(), service: $('project-service').value, genre: $('project-genre').value.trim(), release_year: $('project-year').value || null, description: $('project-description').value.trim(), cover_url: $('cover-url').value, audio_url: $('audio-url').value, audio_label: $('audio-label').value.trim(), is_published: Boolean(published), is_featured: $('project-featured').checked, display_order: Number($('project-order').value || 0) };
  try {
    const result = await adminApi('/api/admin/projects', { method: 'POST', body: JSON.stringify(payload) });
    $('project-id').value = result.id; $('project-published').checked = result.published; await loadProjects();
    setMessage($('project-message'), published ? 'Published — your portfolio is updating now.' : 'Draft saved. Publish it whenever it is ready.', true);
    notice(published ? 'Project published. Your live portfolio will refresh right away.' : 'Draft saved to your studio.');
    broadcastPortfolioUpdate();
    if (published) $('editor-kicker').textContent = 'PUBLISHED PROJECT';
  } catch (error) { setMessage($('project-message'), error.message); }
  finally { button.disabled = false; }
}
async function deleteProject(id) {
  const project = state.projects.find((item) => String(item.id) === String(id));
  if (!project || !window.confirm(`Delete “${project.title}” from your studio? This removes its portfolio listing.`)) return;
  try { await adminApi(`/api/admin/projects/${id}`, { method: 'DELETE' }); clearProjectForm(); await loadProjects(); broadcastPortfolioUpdate(); notice('Project removed from the portfolio.'); }
  catch (error) { notice(error.message, true); }
}
async function uploadAsset(file, kind) {
  if (['localhost', '127.0.0.1', '::1'].includes(location.hostname)) throw new Error('Local studio uploads are not connected. Use the hosted admin at website-ivory-six-35.vercel.app/admin to upload public media.');
  const limit = kind === 'cover' ? 12_000_000 : 250_000_000;
  const ext = `.${file.name.split('.').pop().toLowerCase()}`;
  const allowed = kind === 'cover' ? ['.jpg', '.jpeg', '.png', '.webp'] : ['.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg'];
  if (!allowed.includes(ext)) throw new Error(kind === 'cover' ? 'Use a JPEG, PNG or WebP image.' : 'Use MP3, M4A, AAC, WAV, FLAC or OGG audio.');
  if (file.size > limit) throw new Error(kind === 'cover' ? 'This image is over 12 MB.' : 'This audio file is over 250 MB.');
  const csrf = csrfToken(); if (!csrf) throw new Error('Refresh the admin page and sign in again before uploading.');
  const safeName = file.name.normalize('NFKD').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').slice(-90) || `${kind}${ext}`;
  const name = `projects/${kind}/${crypto.randomUUID()}-${safeName}`;
  const progress = $(`${kind}-progress`); progress.hidden = false; progress.querySelector('span').textContent = 'Preparing secure upload…';
  try {
    const blob = await uploadBlob(name, file, {
      access: 'public',
      handleUploadUrl: '/api/media-upload',
      clientPayload: JSON.stringify({ kind }),
      headers: { 'X-CSRF-Token': csrf },
      multipart: true,
      onUploadProgress(event) { progress.querySelector('span').textContent = `Uploading ${Math.round(event.percentage)}%`; },
    });
    $(`${kind}-url`).value = blob.url;
    showPreview(kind, blob.url, file.name);
    return blob.url;
  } finally { progress.hidden = true; }
}
function showPreview(kind, url, filename) {
  const box = $(`${kind}-preview`); box.replaceChildren();
  if (!url) { box.hidden = true; return; }
  box.hidden = false;
  if (kind === 'cover') { const image = document.createElement('img'); image.src = url; image.alt = 'Selected project cover preview'; box.append(image); }
  else { const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none'; audio.src = url; const file = document.createElement('div'); file.className = 'preview-file'; const name = document.createElement('span'); name.textContent = filename || 'Audio preview'; const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove'; remove.addEventListener('click', () => { $('audio-url').value = ''; box.hidden = true; $('audio-file').value = ''; }); file.append(name, remove); box.append(file, audio); }
}
for (const kind of ['cover', 'audio']) {
  const input = $(`${kind}-file`); const drop = $(`${kind}-dropzone`);
  input.addEventListener('change', async () => { const file = input.files?.[0]; if (!file) return; setMessage($('project-message'), ''); try { await uploadAsset(file, kind); setMessage($('project-message'), `${kind === 'cover' ? 'Cover' : 'Audio'} uploaded. Save the project to attach it.`, true); } catch (error) { setMessage($('project-message'), error.message); input.value = ''; } });
  drop.addEventListener('dragover', (event) => { event.preventDefault(); drop.classList.add('dragover'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', (event) => { event.preventDefault(); drop.classList.remove('dragover'); const file = event.dataTransfer.files?.[0]; if (!file) return; const transfer = new DataTransfer(); transfer.items.add(file); input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true })); });
}

async function loadServices() {
  const result = await adminApi('/api/admin/services'); state.services = result.services || []; renderServices();
  $('metric-services').textContent = String(state.services.filter((service) => service.active).length);
}
function renderServices() {
  const holder = $('service-manager'); holder.replaceChildren();
  if (!state.services.length) { const empty = document.createElement('div'); empty.className = 'empty-state'; empty.textContent = 'No services have been added.'; holder.append(empty); }
  state.services.forEach((service, index) => {
    const card = document.createElement('article'); card.className = 'service-item';
    const num = document.createElement('span'); num.className = 'service-number'; num.textContent = String(index + 1).padStart(2, '0');
    const copy = document.createElement('div'); copy.className = 'service-item-copy'; const title = document.createElement('strong'); title.textContent = service.title; const description = document.createElement('p'); description.textContent = service.description; copy.append(title, description);
    const status = document.createElement('span'); status.className = `status-pill ${service.active ? 'live' : 'draft'}`; status.textContent = service.active ? 'Visible' : 'Hidden';
    const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'icon-button'; edit.setAttribute('aria-label', `Edit ${service.name}`); edit.textContent = '↗'; edit.addEventListener('click', () => editService(service.id)); card.append(num, copy, status, edit); holder.append(card);
  });
  if (!state.services.some((service) => String(service.id) === $('service-id').value)) {
    const service = state.services[0]; if (service) editService(service.id, false);
  }
}
function editService(id, scroll = true) {
  const service = state.services.find((item) => String(item.id) === String(id)); if (!service) return;
  $('service-id').value = service.id; $('service-name').value = service.name; $('service-title').value = service.title; $('service-description').value = service.description; $('service-active').checked = service.active; $('service-order').value = service.display_order;
  $('service-editor-title').textContent = service.name; setMessage($('service-message'), '');
  if (scroll) $('service-editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
$('service-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const btn = event.submitter; if (btn) btn.disabled = true;
  try {
    await adminApi('/api/admin/services', { method: 'POST', body: JSON.stringify({ id: $('service-id').value || undefined, name: $('service-name').value, title: $('service-title').value.trim(), description: $('service-description').value.trim(), active: $('service-active').checked, display_order: Number($('service-order').value || 0) }) });
    await loadServices(); setMessage($('service-message'), 'Service saved and updated on your portfolio.', true); broadcastPortfolioUpdate(); notice('Service updated on your live portfolio.');
  } catch (error) { setMessage($('service-message'), error.message); }
  finally { if (btn) btn.disabled = false; }
});

async function loadSettings() {
  const result = await adminApi('/api/admin/settings'); state.settings = result.settings || {};
  $('setting-title').value = state.settings.heroTitle || ''; $('setting-accent').value = state.settings.heroAccent || ''; $('setting-description').value = state.settings.heroDescription || ''; $('setting-availability').value = state.settings.availability || ''; $('setting-about').value = state.settings.aboutText || ''; $('setting-email').value = state.settings.contactEmail || '';
}
$('settings-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const button = event.submitter; if (button) button.disabled = true;
  try {
    await adminApi('/api/admin/settings', { method: 'PUT', body: JSON.stringify({ heroTitle: $('setting-title').value.trim(), heroAccent: $('setting-accent').value.trim(), heroDescription: $('setting-description').value.trim(), availability: $('setting-availability').value.trim(), aboutText: $('setting-about').value.trim(), contactEmail: $('setting-email').value.trim() }) });
    setMessage($('settings-message'), 'Saved — your portfolio reflects the new copy now.', true); notice('Website content saved and published.'); broadcastPortfolioUpdate();
  } catch (error) { setMessage($('settings-message'), error.message); }
  finally { if (button) button.disabled = false; }
});

let inquiryTimer = 0;
for (const id of ['inquiry-search', 'inquiry-status-filter', 'inquiry-service-filter']) $(id).addEventListener('input', () => { window.clearTimeout(inquiryTimer); inquiryTimer = window.setTimeout(() => loadInquiries(1), 250); });
$('refresh-inquiries').addEventListener('click', () => loadInquiries(state.inquiriesPage));
async function loadInquiries(page = 1) {
  state.inquiriesPage = page;
  const params = new URLSearchParams({ action: 'inquiries', page: String(page), page_size: '24', q: $('inquiry-search').value.trim(), status: $('inquiry-status-filter').value, service: $('inquiry-service-filter').value, sort: 'newest' });
  const data = await adminApi(`/api/admin?${params}`);
  const list = $('inquiry-list'); list.replaceChildren();
  const items = data.inquiries || []; state.inquiryPages = data.pagination?.pages || 1; state.inquiriesPage = data.pagination?.page || 1;
  $('inquiry-nav-count').textContent = String(data.stats?.new || 0); $('metric-new-inquiries').textContent = String(data.stats?.new || 0);
  if (!items.length) { const empty = document.createElement('div'); empty.className = 'empty-state'; const title = document.createElement('strong'); title.textContent = 'No enquiries in this view.'; const copy = document.createElement('span'); copy.textContent = 'When artists reach out, their message will be ready here.'; empty.append(title, copy); list.append(empty); }
  items.forEach((item) => list.append(renderInquiry(item)));
  const pager = $('inquiry-pagination'); pager.replaceChildren();
  const summary = document.createElement('span'); summary.textContent = `${data.pagination?.total || 0} total · Page ${state.inquiriesPage} of ${state.inquiryPages}`;
  const controls = document.createElement('span'); const prev = document.createElement('button'); prev.type = 'button'; prev.textContent = '← Previous'; prev.disabled = state.inquiriesPage <= 1; prev.addEventListener('click', () => loadInquiries(state.inquiriesPage - 1)); const next = document.createElement('button'); next.type = 'button'; next.textContent = 'Next →'; next.disabled = state.inquiriesPage >= state.inquiryPages; next.addEventListener('click', () => loadInquiries(state.inquiriesPage + 1)); controls.append(prev, document.createTextNode(' '), next); pager.append(summary, controls);
}
function renderInquiry(item) {
  const card = document.createElement('article'); card.className = 'inquiry-card';
  const head = document.createElement('div'); head.className = 'inquiry-card-head'; const identity = document.createElement('div'); const title = document.createElement('h3'); title.textContent = item.project || `${item.service} enquiry`; const name = document.createElement('div'); name.className = 'inquiry-name'; name.textContent = `${item.name} · ${formatDate(item.created_at)}`; identity.append(title, name);
  const badge = document.createElement('span'); badge.className = `status-pill ${item.status === 'new' ? 'draft' : item.status === 'completed' ? 'live' : ''}`; badge.textContent = item.status.replace('_', ' '); head.append(identity, badge);
  const meta = document.createElement('div'); meta.className = 'inquiry-meta'; [item.email, item.service, item.timeline, item.genre].filter(Boolean).forEach((text) => { const span = document.createElement('span'); span.textContent = text; meta.append(span); });
  const message = document.createElement('p'); message.className = 'inquiry-message'; message.textContent = item.message;
  const foot = document.createElement('div'); foot.className = 'inquiry-card-foot'; const reply = document.createElement('a'); reply.href = `mailto:${encodeURIComponent(item.email)}?subject=${encodeURIComponent(`Re: Audio project enquiry — ${item.project || item.name}`)}`; reply.textContent = 'Reply by email ↗';
  const status = document.createElement('select'); status.setAttribute('aria-label', `Update status for ${item.name}`); [['new', 'New'], ['in_progress', 'In progress'], ['completed', 'Completed']].forEach(([value, label]) => { const option = document.createElement('option'); option.value = value; option.textContent = label; status.append(option); }); status.value = item.status; status.addEventListener('change', async () => { try { await adminApi('/api/admin?action=status', { method: 'POST', body: JSON.stringify({ id: item.id, status: status.value }) }); badge.textContent = status.value.replace('_', ' '); badge.className = `status-pill ${status.value === 'new' ? 'draft' : status.value === 'completed' ? 'live' : ''}`; notice('Enquiry status updated.'); } catch (error) { notice(error.message, true); } });
  foot.append(reply, status); card.append(head, meta, message, foot); return card;
}
function formatDate(value) { try { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value)); } catch { return 'Recently'; } }
$('export-inquiries').addEventListener('click', async () => {
  const params = new URLSearchParams({ action: 'export', q: $('inquiry-search').value.trim(), status: $('inquiry-status-filter').value, service: $('inquiry-service-filter').value, sort: 'newest' });
  try { const response = await fetch(`/api/admin?${params}`, { credentials: 'same-origin', cache: 'no-store' }); if (!response.ok) throw new Error('Could not export enquiries.'); const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url; link.download = `blessson-enquiries-${new Date().toISOString().slice(0, 10)}.csv`; link.click(); URL.revokeObjectURL(url); }
  catch (error) { notice(error.message, true); }
});

$('enable-mfa').addEventListener('click', async () => {
  $('enable-mfa').disabled = true;
  try { const result = await adminApi('/api/admin?action=mfa-setup', { method: 'POST', body: '{}' }); $('mfa-secret').textContent = result.secret; $('mfa-setup').hidden = false; $('recovery-panel').hidden = true; $('mfa-confirm-code').focus(); }
  catch (error) { notice(error.message, true); }
  finally { $('enable-mfa').disabled = false; }
});
$('copy-mfa-secret').addEventListener('click', async () => { try { await navigator.clipboard.writeText($('mfa-secret').textContent); notice('Authenticator key copied.'); } catch { notice('Select and copy the authenticator key.', true); } });
$('mfa-confirm-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { const result = await adminApi('/api/admin?action=mfa-confirm', { method: 'POST', body: JSON.stringify({ code: $('mfa-confirm-code').value.trim() }) }); state.mfaEnabled = true; $('mfa-confirm-code').value = ''; $('mfa-setup').hidden = true; $('recovery-codes').replaceChildren(); result.recoveryCodes.forEach((code) => { const item = document.createElement('code'); item.textContent = code; $('recovery-codes').append(item); }); $('recovery-panel').hidden = false; renderMfaState(); setMessage($('mfa-message'), 'Two-step sign-in is now enabled.', true); notice('Authenticator sign-in enabled. Save your recovery codes somewhere private.'); }
  catch (error) { setMessage($('mfa-message'), error.message); }
});
$('download-recovery').addEventListener('click', () => { const text = Array.from($('recovery-codes').querySelectorAll('code')).map((node) => node.textContent).join('\n'); const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([`Blessson Studio recovery codes\n\n${text}\n\nEach code can be used once. Keep this file somewhere private.\n`], { type: 'text/plain' })); link.download = 'blessson-recovery-codes.txt'; link.click(); URL.revokeObjectURL(link.href); });
$('security-password-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const fresh = $('security-new-password').value;
  if (fresh !== $('security-confirm-password').value) return setMessage($('security-password-message'), 'The new passphrases do not match.');
  try { await adminApi('/api/admin?action=password', { method: 'POST', body: JSON.stringify({ currentPassword: $('security-current-password').value, newPassword: fresh }) }); ['security-current-password', 'security-new-password', 'security-confirm-password'].forEach((id) => $(id).value = ''); setMessage($('security-password-message'), 'Passphrase updated. Other devices have been signed out.', true); await refreshSecurity(); }
  catch (error) { setMessage($('security-password-message'), error.message); }
});
$('revoke-sessions').addEventListener('click', async () => {
  if (!window.confirm('Sign out all devices, including this browser? You will need your password to sign in again.')) return;
  try { await adminApi('/api/admin?action=revoke-sessions', { method: 'POST', body: '{}' }); showLogin('All active sessions have been signed out.'); }
  catch (error) { notice(error.message, true); }
});
async function refreshSecurity() {
  try { const session = await adminApi('/api/admin?action=session'); state.mfaEnabled = Boolean(session.mfaEnabled); renderMfaState(); }
  catch (error) { notice(error.message, true); }
}
function broadcastPortfolioUpdate() {
  try { const channel = new BroadcastChannel('blessson-portfolio'); channel.postMessage({ type: 'refresh', at: Date.now() }); channel.close(); } catch { /* Browsers without BroadcastChannel use storage events below. */ }
  try { localStorage.setItem('blessson-portfolio-updated', String(Date.now())); } catch { /* Storage may be disabled. */ }
}
function noticeProjectCounts() {
  $('metric-services').textContent = String(state.services.filter((service) => service.active).length);
}
$('mfa-code').addEventListener('input', () => { $('mfa-code').value = $('mfa-code').value.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 32); });
boot();
