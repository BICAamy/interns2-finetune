/* Theme preference shared with the portal's React workbenches. */
(() => {
  const key = 'ai4s-theme';
  const media = matchMedia('(prefers-color-scheme: dark)');
  let preference = 'light';
  const read = () => {
    try { const value = localStorage.getItem(key); return ['light','dark','system'].includes(value) ? value : 'light'; }
    catch { return 'light'; }
  };
  const apply = () => {
    const dark = preference === 'dark' || (preference === 'system' && media.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.querySelectorAll('[data-agent-theme]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.agentTheme === preference)));
    document.querySelectorAll('[data-theme-icon]').forEach(icon => { icon.innerHTML = dark ? '<path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/>' : '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>'; });
    document.querySelectorAll('meta[name="theme-color"]').forEach(meta => { meta.content = dark ? '#0d1420' : '#ffffff'; meta.removeAttribute('media'); });
  };
  preference = read(); apply();
  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-agent-theme]');
    if (button) {
      preference = button.dataset.agentTheme;
      try { localStorage.setItem(key, preference); } catch { /* Keep this page's selection. */ }
      apply(); const menu = button.closest('details'); if (menu) { menu.open = false; menu.querySelector('summary')?.focus(); }
    } else if (event.target.closest?.('.theme-control summary')) apply();
    else document.querySelectorAll('.agent-masthead .theme-control[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') document.querySelectorAll('.agent-masthead .theme-control[open]').forEach(menu => { menu.open = false; menu.querySelector('summary')?.focus(); }); });
  media.addEventListener('change', apply);
  window.addEventListener('storage', event => { if (event.key === key || event.key === null) { preference = read(); apply(); } });
})();
