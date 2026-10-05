(() => {
  const grid = document.querySelector('.work-grid');
  if (!grid) return;
  const defaults = { contactEmail: 'blessonkondeti@gmail.com' };
  let lastSnapshot = '';
  const normalize = (value) => String(value || '').trim();
  const safeMedia = (value) => {
    if (!value) return '';
    try {
      const url = new URL(value, location.origin);
      if (url.origin === location.origin && url.pathname.startsWith('/assets/') && !url.pathname.includes('..')) return url.href;
      if (url.protocol === 'https:' && url.hostname.endsWith('.public.blob.vercel-storage.com')) return url.href;
    } catch {}
    return '';
  };
  const textNode = (tag, className, value) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = value;
    return el;
  };
  const slug = (value) => normalize(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  function updateContactEmail(email) {
    const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalize(email)) ? normalize(email) : defaults.contactEmail;
    window.BlesssonContactEmail = valid;
    document.querySelectorAll('a[href^="mailto:"]').forEach((link) => {
      try {
        const url = new URL(link.href);
        const subject = url.searchParams.get('subject');
        url.pathname = valid;
        if (subject) url.searchParams.set('subject', subject);
        link.href = url.href;
      } catch { link.href = `mailto:${valid}`; }
    });
  }
  function updateSettings(settings = {}) {
    const hero = document.querySelector('.hero h1');
    if (hero && settings.heroTitle && settings.heroAccent) {
      const accent = document.createElement('em');
      accent.textContent = settings.heroAccent;
      hero.replaceChildren(document.createTextNode(`${settings.heroTitle} `), accent);
    }
    const description = document.querySelector('.hero-text');
    if (description && settings.heroDescription) description.textContent = settings.heroDescription;
    const eyebrow = document.querySelector('.hero-eyebrow');
    if (eyebrow && settings.availability) {
      const dot = eyebrow.querySelector('.status-dot');
      eyebrow.replaceChildren(...(dot ? [dot, document.createTextNode(` ${settings.availability}`)] : [document.createTextNode(settings.availability)]));
    }
    const about = document.querySelector('.about-copy > p');
    if (about && settings.aboutText) about.textContent = settings.aboutText;
    if (settings.contactEmail) updateContactEmail(settings.contactEmail);
  }
  function createProject(project, index, total) {
    const article = document.createElement('article');
    article.className = 'work-card live-project-card';
    article.dataset.category = slug(project.service).replaceAll('-', ' ');
    article.dataset.brief = normalize(project.description) || `${project.service} project${project.genre ? ` · ${project.genre}` : ''}.`;
    const cover = document.createElement('div');
    cover.className = 'cover live-project-cover';
    const label = textNode('span', 'cover-label', `${project.is_featured ? 'FEATURED · ' : ''}${normalize(project.genre) || normalize(project.service) || 'AUDIO PROJECT'}`);
    const number = textNode('span', 'cover-index', `${String(index + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}`);
    cover.append(label, number);
    const coverUrl = safeMedia(project.cover_url);
    if (coverUrl) {
      const image = document.createElement('img');
      image.src = coverUrl;
      image.alt = `${normalize(project.title) || 'Project'} cover artwork`;
      image.loading = 'lazy';
      image.decoding = 'async';
      cover.append(image);
    } else {
      cover.classList.add('live-cover-art');
      cover.append(textNode('span', 'live-cover-mark', normalize(project.title).slice(0, 1).toUpperCase() || 'B'));
    }
    const meta = document.createElement('div');
    meta.className = 'work-meta';
    const details = document.createElement('div');
    details.append(textNode('h3', 'work-title', normalize(project.title) || 'Untitled project'));
    const line = [normalize(project.artist), normalize(project.genre), project.release_year].filter(Boolean).join(' · ');
    details.append(textNode('p', 'work-detail', line || normalize(project.description).slice(0, 90)));
    const type = textNode('span', 'work-type', normalize(project.service).toUpperCase());
    meta.append(details, type);
    article.append(cover, meta);
    if (normalize(project.description)) article.append(textNode('p', 'live-project-description', normalize(project.description)));
    const audioUrl = safeMedia(project.audio_url);
    if (audioUrl) {
      const player = document.createElement('audio');
      player.controls = true;
      player.preload = 'none';
      player.controlsList = 'nodownload';
      player.setAttribute('aria-label', `${normalize(project.audio_label) || normalize(project.title)} audio preview`);
      const source = document.createElement('source');
      source.src = audioUrl;
      player.append(source);
      article.append(player, textNode('span', 'live-audio-label', normalize(project.audio_label) || 'Audio preview'));
    }
    return article;
  }
  function updateProjects(projects) {
    if (!Array.isArray(projects) || projects.length === 0) return;
    grid.replaceChildren(...projects.map((project, index) => createProject(project, index, projects.length)));
    grid.classList.add('has-live-projects');
    const count = document.querySelector('.filter-count');
    if (count) count.textContent = `${projects.length} ${projects.length === 1 ? 'project' : 'projects'}`;
    const note = document.querySelector('#work .section-head p');
    if (note) note.textContent = 'Selected work shaped with care — listen to the preview and explore the details.';
    document.querySelectorAll('.work-filters .filter-button').forEach((oldButton) => {
      const button = oldButton.cloneNode(true);
      oldButton.replaceWith(button);
      button.addEventListener('click', () => {
        const filter = button.dataset.filter;
        const cards = [...grid.querySelectorAll('.work-card')];
        document.querySelectorAll('.work-filters .filter-button').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
        let shown = 0;
        cards.forEach((card) => {
          const matches = filter === 'all' || card.dataset.category.split(' ').includes(filter);
          card.hidden = !matches;
          if (matches) shown += 1;
        });
        const countNode = document.querySelector('.filter-count');
        if (countNode) countNode.textContent = `${shown} ${shown === 1 ? 'project' : 'projects'}`;
      });
    });
  }
  function updateServices(services) {
    if (!Array.isArray(services) || !services.length) return;
    const serviceGrid = document.querySelector('.service-grid');
    if (!serviceGrid) return;
    serviceGrid.replaceChildren(...services.map((service, index) => {
      const article = document.createElement('article');
      article.className = 'service';
      article.append(textNode('span', 'service-number', `${String(index + 1).padStart(2, '0')} / ${normalize(service.name).toUpperCase()}`));
      article.append(textNode('h3', '', normalize(service.title) || normalize(service.name)));
      article.append(textNode('p', '', normalize(service.description)));
      const link = textNode('a', 'service-link', `Ask about ${normalize(service.name).toLowerCase()} ↗`);
      link.href = '#contact';
      link.dataset.service = normalize(service.name);
      link.addEventListener('click', () => {
        const select = document.getElementById('service-select');
        if (select) select.value = normalize(service.name);
      });
      article.append(link);
      return article;
    }));
    const select = document.getElementById('service-select');
    if (select) {
      const first = select.options[0];
      select.replaceChildren(first, ...services.map((service) => new Option(normalize(service.name), normalize(service.name))));
      select.add(new Option('Not sure yet', 'Not sure yet'));
    }
    const tags = document.querySelector('.hero-services');
    if (tags) tags.replaceChildren(...services.slice(0, 4).map((service) => textNode('span', '', normalize(service.name).toUpperCase())));
  }
  async function refresh() {
    if (location.protocol === 'file:') return;
    try {
      const response = await fetch('/api/portfolio', { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      const snapshot = JSON.stringify(data);
      if (snapshot === lastSnapshot) return;
      lastSnapshot = snapshot;
      updateSettings(data.settings || {});
      updateServices(data.services || []);
      updateProjects(data.projects || []);
    } catch {}
  }
  updateContactEmail(defaults.contactEmail);
  refresh();
  window.setInterval(refresh, 12000);
  if ('BroadcastChannel' in window) {
    const channel = new BroadcastChannel('blessson-portfolio');
    channel.addEventListener('message', refresh);
  }
  window.addEventListener('storage', (event) => { if (event.key === 'blessson-portfolio-updated') refresh(); });
})();
