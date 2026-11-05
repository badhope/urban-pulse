const $ = (id) => document.getElementById(id);

function card(k, v, cls) {
  return `<div class="card"><div class="k">${k}</div>
    <div class="v ${cls || ''}">${v}</div></div>`;
}

async function load() {
  const health = await fetch('/health').then(r => r.json()).catch(() => ({}));
  const vm = await fetch('/state').then(r => r.json()).catch(() => ({}));
  const sessions = await fetch('/admin/sessions').then(r => r.json()).catch(() => ({}));

  $('sub').textContent = `v${health.version || '?'} · state ${health.state_note || '?'} · ` +
    `queue ${health.inbox_pending ?? 0}`;

  $('runtime').innerHTML =
    card('Version', health.version || '—') +
    card('State file', health.ok ? 'healthy' : 'missing',
         health.ok ? 'ok' : 'bad') +
    card('Turn', vm.tick ?? '—') +
    card('World', (vm.world && vm.world.name) || '—') +
    card('Queued actions', health.inbox_pending ?? 0) +
    card('Sessions', sessions.count ?? '—');

  const rows = (sessions.sessions || []).map(s =>
    `<tr><td><code>${s.name}</code>${s.current ? ' <span class="pill ok">current</span>' : ''}</td>
     <td>${s.tick ?? '—'}</td><td>${s.world || '—'}</td>
     <td>${s.size_kb} KB</td><td>${s.modified || '—'}</td></tr>`).join('');
  $('saves').innerHTML = rows || '<tr><td colspan="5">no saves yet</td></tr>';

  const checks = [
    ['State readable', vm && !vm.error, vm.error || `${health.state_note || ''}`],
    ['Archive pending', !(health.archive_pending), health.archive_pending ? 'needs manual review' : 'clear'],
    ['Chart sidecar', health.sidecar || 'optional', health.sidecar_note || ''],
    ['Panel assets', health.assets_ok !== false, health.assets_note || 'served from package'],
  ];
  $('diag').innerHTML = checks.map(([name, ok, detail]) =>
    `<tr><td>${name}</td><td><span class="pill ${ok ? 'ok' : 'warn'}">${ok ? 'ok' : 'check'}</span></td>
     <td><code>${detail || '—'}</code></td></tr>`).join('');
}

load();
setInterval(load, 5000);
