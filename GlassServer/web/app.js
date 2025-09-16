// Platform hint, download fallback, and changelog loader
(function(){
  // Year
  const y = document.getElementById('year');
  if (y) y.textContent = new Date().getFullYear();

  // Windows-only hint
  const isWindows = navigator.userAgent.includes('Windows');
  const btn = document.getElementById('download-btn');
  const hint = document.getElementById('win-only');
  if (btn && hint && !isWindows) {
    hint.textContent = 'Windows only — download on a Windows PC';
    btn.classList.add('ghost');
  }

  // Try /static/Glass.exe then /static/GlassSetup.exe
  async function resolveDownload(){
    if (!btn) return;
    const tryUrls = ['static/Glass.exe', 'static/GlassSetup.exe'];
    for (const url of tryUrls){
      try{
        const r = await fetch(url, { method: 'HEAD' });
        if (r.ok) { btn.href = '/' + url; return; }
      }catch(e){}
    }
  }
  resolveDownload();

  // Changelog (expects web/changelog.json in this folder)
  async function loadChangelog(){
    const list = document.getElementById('changelog-list');
    const ver = document.getElementById('latest-version');
    if (!list) return;
    try{
      const r = await fetch('changelog.json', { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      if (Array.isArray(data.releases)){
        if (data.releases[0] && ver) ver.textContent = data.releases[0].version || '';
        for (const rel of data.releases){
          const div = document.createElement('div');
          div.className = 'entry';
          const notes = (rel.notes || []).map(n => `<li>${n}</li>`).join('');
          div.innerHTML = `<strong>${rel.version || ''}</strong> <span class="muted">${rel.date || ''}</span><ul>${notes}</ul>`;
          list.appendChild(div);
        }
      }
    }catch(e){}
  }
  loadChangelog();
})();
