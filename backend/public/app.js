'use strict';

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (v, cur) => (v === null || v === undefined || v === '' ? '—' : `${Number(v).toFixed(2)} ${esc(cur || '')}`);
let TOKEN = localStorage.getItem('tp_token') || '';
let CONFIG = { botUsername: '' };

const STATUS = {
  1: ['Faol', 'ok'], 2: ['Bloklangan', 'bad'], 3: ["To'lov qarzi", 'bad'], 7: ['Risk tekshiruvida', 'warn'],
  8: ["To'lov kutilmoqda", 'warn'], 9: ['Grace period', 'warn'], 100: ['Yopilmoqda', 'gray'], 101: ['Yopilgan', 'gray'],
};
const RESULT_TYPES = { messaging: 'Yozishma (Telegram/Instagram)', lead_form: 'Lid (forma)', lead_site: 'Lid (sayt)', purchase: 'Xarid' };
const RULES = {
  account_status: ['Account bloklandi yoki holati o‘zgardi', null],
  ad_issues: ['Reklama rad etildi / muammo', null],
  spend_limit: ['Spend limitga yaqinlashdi', '% limit'],
  cpr_spike: ['Natija narxi oshdi', '% o‘rtachadan'],
  spend_no_result: ['Sarf bor, natija yo‘q', 'sarf (valyuta)'],
  token_error: ['Token ishlamay qoldi', null],
};

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.add('hidden'), 3500);
}

async function api(method, path, body) {
  const res = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + TOKEN },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && path !== '/auth/login') {
    logout();
    throw new Error('Qayta kiring');
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error((data && (Array.isArray(data.message) ? data.message.join(', ') : data.message)) || 'Xatolik');
  return data;
}

async function withBtn(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; }
}

// ---------------- Auth ----------------
function logout() {
  TOKEN = '';
  localStorage.removeItem('tp_token');
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
}

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('#login-error').textContent = '';
  try {
    const r = await api('POST', '/auth/login', { password: $('#password').value });
    TOKEN = r.token;
    localStorage.setItem('tp_token', TOKEN);
    start();
  } catch (err) {
    $('#login-error').textContent = err.message;
  }
});
$('#logout').addEventListener('click', logout);

// ---------------- Router ----------------
const pages = { ulanishlar: pageConnections, accountlar: pageAccounts, mijozlar: pageClients, tahlil: pageAnalysis, alertlar: pageAlerts, tarix: pageLog, sozlamalar: pageSettings };

async function route() {
  const [name, arg] = (location.hash.slice(1) || 'ulanishlar').split('/');
  const fn = pages[name] || pageConnections;
  document.querySelectorAll('.side a').forEach((a) => a.classList.toggle('active', a.dataset.page === name));
  const main = $('#page');
  main.innerHTML = '<p class="muted">Yuklanmoqda…</p>';
  try { await fn(main, arg); } catch (e) { main.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

async function start() {
  $('#login').classList.add('hidden');
  $('#app').classList.remove('hidden');
  try { CONFIG = await api('GET', '/config'); } catch { /* ignore */ }
  route();
  refreshWorker();
}

async function refreshWorker() {
  try {
    const s = await api('GET', '/stats');
    const hb = s.worker_heartbeat ? new Date(s.worker_heartbeat) : null;
    const fresh = hb && Date.now() - hb.getTime() < 30 * 60 * 1000;
    $('#worker-status').innerHTML = fresh
      ? '<span class="pill ok">Worker ishlayapti</span>'
      : '<span class="pill bad">Worker javob bermayapti</span>';
  } catch { /* ignore */ }
}
setInterval(() => TOKEN && refreshWorker(), 60000);
window.addEventListener('hashchange', route);

// ---------------- 1. Ulanishlar ----------------
async function pageConnections(main) {
  const [conns, stats] = await Promise.all([api('GET', '/connections'), api('GET', '/stats')]);
  const card = (c) => {
    const st = c.status === 'ok' ? ['Ulangan', 'ok'] : c.status === 'pending_api' ? ['API kutilmoqda', 'warn'] : ['Xato', 'bad'];
    return `<div class="source">
      <div class="row"><span class="tag ${c.platform === 'meta' ? 'meta' : 'tg'}">${c.platform === 'meta' ? 'Meta' : 'TG Ads'}</span>
        <div><b>${esc(c.name)}</b><div class="mono">•••• ${esc(c.token_last4)} · ${c.accounts} ta account</div>
        ${c.last_error ? `<div class="error">${esc(c.last_error)}</div>` : ''}</div></div>
      <div class="row"><span class="pill ${st[1]}">${st[0]}</span>
        ${c.platform === 'meta' ? `<button class="btn" data-sync="${c.id}">Yangilash</button>` : ''}
        <button class="btn danger" data-del="${c.id}">O'chirish</button></div></div>`;
  };
  const addLink = CONFIG.botUsername ? `https://t.me/${encodeURIComponent(CONFIG.botUsername)}?startgroup=true&admin=post_messages` : '';
  main.innerHTML = `
    <div><h1>Ulanishlar</h1><p class="sub">Reklama kabinetlarini bir marta ulang — accountlar avtomatik yuklanadi.</p></div>
    <section class="card"><h2>Ulangan kabinetlar</h2>
      ${conns.length ? conns.map(card).join('') : '<p class="empty">Hali ulanish yo‘q</p>'}</section>
    <div class="grid2">
      <form id="f-meta" class="card"><h2>Meta Ads qo'shish</h2>
        <div class="field"><label for="m-name">Nomi</label><input id="m-name" type="text" value="Asosiy Business" required></div>
        <div class="field"><label for="m-token">System User tokeni</label><textarea id="m-token" rows="3" placeholder="EAAG…" required></textarea></div>
        <p class="muted small">Business Settings → System users → Generate token (ads_read, read_insights, business_management; muddati: Never).</p>
        <button class="btn primary" type="submit">Tekshirish va ulash</button></form>
      <form id="f-tg" class="card"><h2>Telegram Ads qo'shish</h2>
        <div class="field"><label for="t-name">Kabinet nomi</label><input id="t-name" type="text" placeholder="Masalan: Asosiy EUR kabinet" required></div>
        <div class="field"><label for="t-token">API kaliti / token</label><input id="t-token" type="password" required></div>
        <p class="muted small">Kalit shifrlangan holda saqlanadi. TG Ads API ulagichi kabinetdagi API hujjatiga qarab qo'shiladi.</p>
        <button class="btn primary" type="submit">Saqlash</button></form>
    </div>
    <section class="card"><div class="row between"><div><h2>Telegram bot</h2>
      ${CONFIG.botUsername
        ? `<p class="muted">Botni mijoz guruhiga admin qilib qo'shing — guruh "Mijozlar" sahifasida avtomatik paydo bo'ladi.</p><div>Bot: <b class="mono">@${esc(CONFIG.botUsername)}</b></div>`
        : `<p class="muted">Bot hali ulanmagan. <a href="#sozlamalar">Sozlamalar</a> sahifasida bot tokenini kiriting.</p>`}</div>
      <div class="row">${stats.free_groups ? `<span class="pill warn">${stats.free_groups} ta guruh biriktirilmagan</span>` : ''}
        ${addLink ? `<a class="btn primary" style="display:flex;align-items:center;text-decoration:none" href="${addLink}" target="_blank" rel="noopener">Guruhga qo'shish</a>` : ''}</div></div></section>`;

  $('#f-meta').addEventListener('submit', (e) => {
    e.preventDefault();
    withBtn(e.submitter, async () => {
      await api('POST', '/connections', { platform: 'meta', name: $('#m-name').value, token: $('#m-token').value });
      toast('Ulandi. Accountlar 1 daqiqada yuklanadi.');
      route();
    });
  });
  $('#f-tg').addEventListener('submit', (e) => {
    e.preventDefault();
    withBtn(e.submitter, async () => {
      await api('POST', '/connections', { platform: 'tg_ads', name: $('#t-name').value, token: $('#t-token').value });
      toast('Saqlandi');
      route();
    });
  });
  main.querySelectorAll('[data-sync]').forEach((b) => b.addEventListener('click', () => withBtn(b, async () => {
    await api('POST', `/connections/${b.dataset.sync}/sync`);
    toast('Yangilash navbatga qo‘yildi');
  })));
  main.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => {
    if (!confirm("Ulanish va uning accountlari o'chiriladi. Davom etasizmi?")) return;
    withBtn(b, async () => { await api('DELETE', `/connections/${b.dataset.del}`); route(); });
  }));
}

// ---------------- 2. Accountlar ----------------
async function pageAccounts(main, filter) {
  const platform = filter === 'meta' || filter === 'tg_ads' ? filter : '';
  const [rows, s] = await Promise.all([api('GET', '/accounts' + (platform ? `?platform=${platform}` : '')), api('GET', '/stats')]);
  const status = (a) => {
    if (a.platform === 'tg_ads') return '<span class="pill gray">—</span>';
    const [t, c] = STATUS[a.account_status] || [String(a.account_status ?? '?'), 'gray'];
    return `<span class="pill ${c}">${t}</span>`;
  };
  const tab = (key, label) => `<a class="btn ${platform === key ? 'primary' : ''}" style="display:flex;align-items:center;text-decoration:none" href="#accountlar/${key}">${label}</a>`;
  main.innerHTML = `
    <div><h1>Accountlar</h1><p class="sub">Ulangan tokenlardan avtomatik yuklanadi (har 15 daqiqada).</p></div>
    <div class="tiles">
      <div class="tile"><span class="muted">Jami</span><b>${s.total}</b></div>
      <div class="tile"><span class="muted">Faol</span><b style="color:#067647">${s.active}</b></div>
      <div class="tile"><span class="muted">Muammoli</span><b style="color:#B42318">${s.problem}</b></div>
      <div class="tile"><span class="muted">Biriktirilmagan</span><b style="color:#B54708">${s.unassigned}</b></div>
    </div>
    <div class="row">${tab('', 'Hammasi')}${tab('meta', 'Meta')}${tab('tg_ads', 'Telegram Ads')}</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Account</th><th>Platforma</th><th>Holat</th><th class="num">Limit / sarflangan</th><th class="num">Kechagi sarf</th><th>Mijoz</th></tr></thead>
      <tbody>${rows.length ? rows.map((a) => `<tr>
        <td><b>${esc(a.name)}</b><div class="mono">${a.platform === 'meta' ? 'act_' : ''}${esc(a.external_id)}</div></td>
        <td><span class="tag ${a.platform === 'meta' ? 'meta' : 'tg'}">${a.platform === 'meta' ? 'Meta' : 'TG Ads'}</span></td>
        <td>${status(a)}</td>
        <td class="num">${a.spend_cap ? money(a.spend_cap, a.currency) : 'limit yo‘q'} / ${money(a.amount_spent, a.currency)}</td>
        <td class="num">${money(a.yesterday_spend, a.currency)}</td>
        <td>${a.clients ? esc(a.clients) : '<a href="#mijozlar">Biriktirish</a>'}</td></tr>`).join('')
        : '<tr><td colspan="6" class="empty">Account yo‘q. Avval "Ulanishlar"da token qo‘shing.</td></tr>'}</tbody></table></div>`;
}

// ---------------- 3. Mijozlar ----------------
async function pageClients(main, idArg) {
  const clients = await api('GET', '/clients');
  const id = Number(idArg) || (clients[0] && clients[0].id);
  main.innerHTML = `
    <div class="row between"><div><h1>Mijozlar</h1><p class="sub">Har bir mijozga account(lar) va Telegram guruhini biriktiring.</p></div>
      <button id="new-client" class="btn primary">+ Yangi mijoz</button></div>
    <div class="split">
      <section class="list" aria-label="Mijozlar ro'yxati">${clients.length ? clients.map((c) => `
        <a href="#mijozlar/${c.id}" class="${c.id === id ? 'active' : ''}"><b>${esc(c.name)}</b>
        <div class="small ${c.group_id ? 'muted' : ''}" style="${c.group_id ? '' : 'color:#B54708'}">${c.meta_sources} Meta · ${c.tg_sources} TG${c.group_id ? '' : ' · guruh yo‘q'}</div></a>`).join('')
        : '<p class="empty">Mijoz yo‘q</p>'}</section>
      <div id="client-detail" class="detail"></div>
    </div>`;
  $('#new-client').addEventListener('click', async () => {
    const name = prompt('Mijoz nomi:');
    if (!name) return;
    try { const r = await api('POST', '/clients', { name }); location.hash = `#mijozlar/${r.id}`; } catch (e) { toast(e.message); }
  });
  if (id) await renderClient($('#client-detail'), id);
}

async function renderClient(el, id) {
  const [c, groups, accounts] = await Promise.all([api('GET', `/clients/${id}`), api('GET', '/groups'), api('GET', '/accounts')]);
  const usedIds = new Set(c.sources.map((s) => s.ad_account_id));
  const groupOpts = groups.filter((g) => !g.client || g.id === c.group_id);
  el.innerHTML = `
    <form id="f-client" class="card"><h2>${esc(c.name)}</h2>
      <div class="grid2">
        <div class="field"><label for="c-name">Mijoz nomi</label><input id="c-name" type="text" value="${esc(c.name)}"></div>
        <div class="field"><label for="c-result">Natija nima hisoblanadi</label><select id="c-result">
          ${Object.entries(RESULT_TYPES).map(([k, v]) => `<option value="${k}" ${c.result_type === k ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
        <div class="field"><label for="c-group">Hisobot yuboriladigan guruh</label><select id="c-group">
          <option value="">— tanlanmagan —</option>
          ${groupOpts.map((g) => `<option value="${g.id}" ${g.id === c.group_id ? 'selected' : ''}>${esc(g.title)}${g.bot_is_admin ? '' : ' (bot admin emas)'}</option>`).join('')}</select></div>
        <div class="field"><label for="c-time">Kunlik hisobot vaqti</label><input id="c-time" type="time" value="${esc(c.report_daily_time)}"></div>
      </div>
      <div class="row">
        <label class="row"><input id="c-daily" type="checkbox" ${c.report_daily ? 'checked' : ''}> Kunlik hisobot</label>
        <label class="row"><input id="c-weekly" type="checkbox" ${c.report_weekly ? 'checked' : ''}> Haftalik (dushanba 10:00)</label>
        <label class="row"><input id="c-diag" type="checkbox" ${c.diagnostics ? 'checked' : ''}> Kunlik AI tahlil (sizga)</label>
        <label class="row"><input id="c-aigroup" type="checkbox" ${c.ai_to_group ? 'checked' : ''}> AI tahlilni mijoz guruhiga ham</label>
      </div>
      <div class="row"><button class="btn primary" type="submit">Saqlash</button>
        <button id="c-test" class="btn" type="button">Sinov hisobotini yuborish</button>
        <a class="btn" style="display:flex;align-items:center;text-decoration:none" href="#tahlil/${id}">AI tahlil</a>
        <button id="c-del" class="btn danger" type="button">Mijozni o'chirish</button></div>
    </form>
    <section class="card"><h2>Reklama manbalari</h2>
      ${c.sources.length ? c.sources.map((s) => `<div class="source">
        <div class="row"><span class="tag ${s.platform === 'meta' ? 'meta' : 'tg'}">${s.platform === 'meta' ? 'Meta' : 'TG Ads'}</span>
        <div><b>${esc(s.name)}</b><div class="mono">${s.platform === 'meta' ? 'act_' + esc(s.external_id) + ' · butun account' : 'prefiks: ' + esc(s.tg_prefix || 'hammasi')}</div></div></div>
        <button class="btn danger" data-rm="${s.id}" type="button">Olib tashlash</button></div>`).join('') : '<p class="muted">Manba qo‘shilmagan</p>'}
      <form id="f-source" class="row">
        <select id="s-acc" style="flex:2 1 260px" aria-label="Account tanlash"><option value="">Account tanlang…</option>
          ${accounts.filter((a) => !usedIds.has(a.id)).map((a) => `<option value="${a.id}" data-p="${a.platform}">${a.platform === 'meta' ? 'Meta' : 'TG'} · ${esc(a.name)}${a.clients ? ' (' + esc(a.clients) + ')' : ''}</option>`).join('')}</select>
        <input id="s-prefix" type="text" placeholder="TG uchun prefiks, masalan [KLINIKA_A]" style="flex:1 1 200px" aria-label="TG prefiks">
        <button class="btn" type="submit">+ Qo'shish</button></form>
    </section>`;

  $('#f-client').addEventListener('submit', (e) => {
    e.preventDefault();
    withBtn(e.submitter, async () => {
      await api('PATCH', `/clients/${id}`, {
        name: $('#c-name').value, result_type: $('#c-result').value, group_id: $('#c-group').value || null,
        report_daily_time: $('#c-time').value, report_daily: $('#c-daily').checked,
        report_weekly: $('#c-weekly').checked, diagnostics: $('#c-diag').checked, ai_to_group: $('#c-aigroup').checked,
      });
      toast('Saqlandi');
      route();
    });
  });
  $('#c-test').addEventListener('click', (e) => withBtn(e.target, async () => {
    await api('POST', `/clients/${id}/test-report`);
    toast('Sinov hisobot 30 soniya ichida guruhga yuboriladi');
  }));
  $('#c-del').addEventListener('click', (e) => {
    if (!confirm('Mijoz o‘chirilsinmi?')) return;
    withBtn(e.target, async () => { await api('DELETE', `/clients/${id}`); location.hash = '#mijozlar'; });
  });
  el.querySelectorAll('[data-rm]').forEach((b) => b.addEventListener('click', () => withBtn(b, async () => {
    await api('DELETE', `/clients/${id}/sources/${b.dataset.rm}`);
    route();
  })));
  $('#f-source').addEventListener('submit', (e) => {
    e.preventDefault();
    withBtn(e.submitter, async () => {
      await api('POST', `/clients/${id}/sources`, { ad_account_id: $('#s-acc').value, tg_prefix: $('#s-prefix').value });
      route();
    });
  });
}

// ---------------- 4. Alertlar ----------------
async function pageAlerts(main, clientArg) {
  const clients = await api('GET', '/clients');
  const cid = Number(clientArg) || 0;
  const rules = await api('GET', `/alert-rules?client_id=${cid}`);
  main.innerHTML = `
    <div><h1>Hisobot va alertlar</h1><p class="sub">Standart qoidalar hamma mijozga ishlaydi; mijoz tanlab, unga alohida sozlash mumkin.</p></div>
    <div class="field" style="max-width:360px"><label for="a-client">Qoidalar kimga</label>
      <select id="a-client"><option value="0">Standart (hamma mijozlar)</option>
      ${clients.map((c) => `<option value="${c.id}" ${c.id === cid ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></div>
    <form id="f-rules" class="card"><h2>Alert qoidalari</h2>
      ${rules.map((r) => {
        const [title, unit] = RULES[r.type] || [r.type, null];
        return `<div class="rule" data-type="${r.type}">
          <label class="row what"><input type="checkbox" data-k="enabled" ${r.enabled ? 'checked' : ''}> <span>${title}</span></label>
          ${unit ? `<label class="row">Chegara <input type="number" step="any" data-k="threshold" value="${esc(r.threshold ?? '')}"> <span class="muted small">${unit}</span></label>` : ''}
          <label class="row"><input type="checkbox" data-k="notify_client" ${r.notify_client ? 'checked' : ''}> Mijoz guruhiga ham</label></div>`;
      }).join('')}
      <div><button class="btn primary" type="submit">Saqlash</button></div></form>
    <p class="muted small">Alertlar standart holatda faqat sizga (ADMIN_CHAT_ID) yuboriladi.</p>`;
  $('#a-client').addEventListener('change', (e) => { location.hash = `#alertlar/${e.target.value}`; });
  $('#f-rules').addEventListener('submit', (e) => {
    e.preventDefault();
    const out = [...main.querySelectorAll('.rule')].map((row) => ({
      type: row.dataset.type,
      enabled: $('[data-k=enabled]', row).checked,
      notify_client: $('[data-k=notify_client]', row).checked,
      threshold: $('[data-k=threshold]', row) ? $('[data-k=threshold]', row).value : null,
    }));
    withBtn(e.submitter, async () => { await api('PUT', '/alert-rules', { client_id: cid, rules: out }); toast('Saqlandi'); });
  });
}

// ---------------- 5. Tarix ----------------
async function pageLog(main) {
  const rows = await api('GET', '/alerts-log');
  main.innerHTML = `<div><h1>Tarix</h1><p class="sub">Oxirgi 100 ta alert.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Vaqt</th><th>Turi</th><th>Mijoz</th><th>Xabar</th><th>Kimga</th></tr></thead>
    <tbody>${rows.length ? rows.map((r) => `<tr><td class="mono">${esc(new Date(r.created_at).toLocaleString('uz-UZ'))}</td>
      <td>${esc((RULES[r.type] || [r.type])[0])}</td><td>${esc(r.client || '—')}</td>
      <td style="white-space:pre-line">${esc(r.message)}</td><td class="mono">${esc(r.sent_to || '')}</td></tr>`).join('')
      : '<tr><td colspan="5" class="empty">Hali alert yo‘q</td></tr>'}</tbody></table></div>`;
}

// ---------------- Job kutish ----------------
async function waitJob(id, timeoutMs = 180000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    await new Promise((r) => setTimeout(r, 2500));
    const j = await api('GET', `/jobs/${id}`);
    if (j.status === 'done') return j;
    if (j.status === 'error') throw new Error(j.error || 'Xatolik');
  }
  throw new Error('Kutish vaqti tugadi — worker ishlayaptimi?');
}

// ---------------- 6. AI tahlil ----------------
const STATE = { yaxshi: ['Yaxshi', 'ok'], "o'rtacha": ["O'rtacha", 'warn'], yomon: ['Yomon', 'bad'] };
const LEVEL = { yuqori: ['Yuqori', 'bad'], "o'rta": ["O'rta", 'warn'], past: ['Past', 'gray'] };
const SEV = { high: 'bad', medium: 'warn', low: 'gray' };

function renderAnalysis(a) {
  const when = esc(new Date(a.created_at).toLocaleString('uz-UZ'));
  if (a.kind === 'question') {
    return `<div class="analysis"><div class="row between"><h3>Savol: ${esc(a.question)}</h3><span class="mono">${when}</span></div>
      <div class="answer">${esc(a.ai_text || a.error || '')}</div></div>`;
  }
  const j = a.ai_json;
  let body = '';
  if (j) {
    const st = STATE[j.holat] || [esc(j.holat || '—'), 'gray'];
    body += `<div class="row"><span class="pill ${st[1]}">Holat: ${st[0]}</span></div><p style="margin:0">${esc(j.xulosa || '')}</p>`;
    if ((j.muammolar || []).length) {
      body += '<h3>Muammolar</h3>' + j.muammolar.map((p) => {
        const lv = LEVEL[p.daraja] || ['—', 'gray'];
        return `<div class="prob"><div class="row"><span class="pill ${lv[1]}">${lv[0]}</span><b>${esc(p.joy || '')}</b></div>
          <div>${esc(p.muammo || '')}</div>${p.sabab ? `<div class="muted">Sabab: ${esc(p.sabab)}</div>` : ''}
          ${p.tavsiya ? `<div class="tip">👉 ${esc(p.tavsiya)}</div>` : ''}</div>`;
      }).join('');
    }
    if ((j.imkoniyatlar || []).length) body += '<h3>Imkoniyatlar</h3><ul>' + j.imkoniyatlar.map((x) => `<li>${esc(x)}</li>`).join('') + '</ul>';
    if ((j.qadamlar || []).length) body += '<h3>Bugungi qadamlar</h3><ol>' + j.qadamlar.map((x) => `<li>${esc(x)}</li>`).join('') + '</ol>';
  } else {
    if (a.ai_text) body += `<div class="answer">${esc(a.ai_text)}</div>`;
    if (a.error) body += `<p class="error">AI: ${esc(a.error)}</p>`;
    body += (a.findings || []).length
      ? '<h3>Qoidalar signallari</h3>' + a.findings.map((f) => `<div class="row"><span class="pill ${SEV[f.severity] || 'gray'}">${esc(f.account)}</span> ${esc(f.text)}</div>`).join('')
      : '<p class="muted">Qoidalar jiddiy muammo topmadi.</p>';
  }
  return `<div class="analysis"><div class="row between"><h3>${a.kind === 'daily' ? 'Kunlik tahlil' : "Qo'lda tahlil"}</h3>
    <span class="mono">${when}${a.model ? ' · ' + esc(a.model) : ''}</span></div>${body}</div>`;
}

async function pageAnalysis(main, idArg) {
  const [clients, st] = await Promise.all([api('GET', '/clients'), api('GET', '/settings')]);
  const id = Number(idArg) || (clients[0] && clients[0].id);
  const aiReady = st.ai.enabled && st.ai.key_set;
  main.innerHTML = `
    <div><h1>AI tahlil</h1><p class="sub">AI har bir mijozning kampaniya, reklama, joylashuv va auditoriya ma'lumotlarini ko'rib, muammo va tavsiyalarni beradi.</p></div>
    ${aiReady ? '' : `<p class="pill warn" style="align-self:flex-start">AI ulanmagan — <a href="#sozlamalar">Sozlamalar</a>da Anthropic API kalitini kiriting</p>`}
    ${clients.length ? `<div class="split">
      <section class="list" aria-label="Mijozlar">${clients.map((c) => `<a href="#tahlil/${c.id}" class="${c.id === id ? 'active' : ''}"><b>${esc(c.name)}</b>
        <div class="small muted">${c.meta_sources} Meta account</div></a>`).join('')}</section>
      <div class="detail">
        <section class="card"><div class="row between"><h2>${esc((clients.find((c) => c.id === id) || {}).name || '')}</h2>
          <button id="run-ai" class="btn primary" type="button">Hozir tahlil qilish</button></div>
          <form id="f-ask" class="row"><label for="q" style="position:absolute;width:1px;height:1px;overflow:hidden">Savol</label>
            <input id="q" type="text" placeholder="AI'dan so'rang: nega bu hafta lid qimmatlashdi?" style="flex:1 1 300px" maxlength="1000">
            <button class="btn" type="submit">So'rash</button></form>
          <p id="ai-status" class="muted small" role="status"></p></section>
        <div id="analyses" class="card"><p class="muted">Yuklanmoqda…</p></div>
      </div></div>` : '<p class="empty">Avval mijoz qo‘shing.</p>'}`;
  if (!id) return;
  const load = async () => {
    const rows = await api('GET', `/clients/${id}/analyses`);
    $('#analyses').innerHTML = rows.length ? rows.map(renderAnalysis).join('') : '<p class="empty">Hali tahlil yo‘q. «Hozir tahlil qilish»ni bosing.</p>';
  };
  await load();
  const run = (btn, path, body, msg) => withBtn(btn, async () => {
    $('#ai-status').textContent = msg;
    const j = await api('POST', path, body);
    try { await waitJob(j.id); } finally { $('#ai-status').textContent = ''; }
    await load();
  });
  $('#run-ai').addEventListener('click', (e) => run(e.target, `/clients/${id}/diagnostics`, null, 'Tahlil qilinmoqda (30–90 soniya)…'));
  $('#f-ask').addEventListener('submit', (e) => {
    e.preventDefault();
    const q = $('#q').value.trim();
    if (!q) { toast('Savol yozing'); return; }
    run(e.submitter, `/clients/${id}/ask`, { question: q }, "AI o'ylayapti…").then(() => { $('#q').value = ''; });
  });
}

// ---------------- 7. Sozlamalar ----------------
async function pageSettings(main) {
  const s = await api('GET', '/settings');
  const botOk = s.bot.connected && (!s.bot.status || s.bot.status === 'ok' || s.bot.status === 'restarting');
  main.innerHTML = `
    <div><h1>Sozlamalar</h1><p class="sub">Bot va AI shu yerdan ulanadi — serverga kirish shart emas.</p></div>
    <div class="grid2">
      <form id="f-bot" class="card"><div class="row between"><h2>Telegram bot</h2>
        ${s.bot.connected ? `<span class="pill ${botOk ? 'ok' : 'bad'}">${botOk ? 'Ulangan' : 'Xato'}</span>` : '<span class="pill gray">Ulanmagan</span>'}</div>
        ${s.bot.username ? `<div>Bot: <b class="mono">@${esc(s.bot.username)}</b>${s.bot.token_last4 ? ` · token •••• ${esc(s.bot.token_last4)}` : ''}</div>` : ''}
        ${s.bot.status && s.bot.status.startsWith('error') ? `<p class="error">${esc(s.bot.status)}</p>` : ''}
        <div class="field"><label for="b-token">${s.bot.connected ? 'Yangi token (almashtirish uchun)' : 'Bot tokeni'}</label>
          <input id="b-token" type="password" placeholder="123456789:AA…" autocomplete="off" required></div>
        <p class="muted small">@BotFather → /newbot → tokenni nusxalang. Saqlangach bot 15 soniyada ishga tushadi.</p>
        <button class="btn primary" type="submit">Tekshirish va saqlash</button></form>

      <section class="card"><h2>Admin (alertlar va tahlil kimga)</h2>
        <div>Hozirgi admin: ${s.admin_chat_id ? `<b>${esc(s.admin_chat_name || '')}</b> <span class="mono">${esc(s.admin_chat_id)}</span>` : '<span class="pill warn">belgilanmagan</span>'}</div>
        <p class="muted small">Botga Telegram'da <b>/start</b> yozing — siz shu ro'yxatda paydo bo'lasiz. Keyin «Admin qilib belgilash»ni bosing.</p>
        <div>${(s.starters || []).length ? s.starters.map((u) => `<div class="source"><div><b>${esc(u.name)}</b>
          <div class="mono">${u.username ? '@' + esc(u.username) + ' · ' : ''}${esc(u.id)}</div></div>
          <button class="btn" type="button" data-admin="${esc(u.id)}" data-name="${esc(u.name)}">${String(u.id) === String(s.admin_chat_id) ? 'Admin ✓' : 'Admin qilib belgilash'}</button></div>`).join('')
          : '<p class="muted">Hali hech kim /start yozmagan.</p>'}</div>
        <div class="row"><button id="refresh-starters" class="btn" type="button">Ro'yxatni yangilash</button>
          <button id="test-admin" class="btn" type="button">Sinov xabari</button></div></section>
    </div>
    <form id="f-ai" class="card"><div class="row between"><h2>AI tahlil (Claude)</h2>
      ${s.ai.key_set ? `<span class="pill ${s.ai.enabled ? 'ok' : 'gray'}">${s.ai.enabled ? 'Yoqilgan' : "O'chirilgan"}</span>` : '<span class="pill gray">Kalit yo‘q</span>'}</div>
      <div class="grid2">
        <div class="field"><label for="ai-key">Anthropic API kaliti${s.ai.key_last4 ? ` (hozirgi •••• ${esc(s.ai.key_last4)})` : ''}</label>
          <input id="ai-key" type="password" placeholder="${s.ai.key_set ? "O'zgartirmaslik uchun bo'sh qoldiring" : 'sk-ant-…'}" autocomplete="off"></div>
        <div class="field"><label for="ai-model">Model</label><select id="ai-model">
          ${s.ai.models.map((m) => `<option value="${m}" ${m === s.ai.model ? 'selected' : ''}>${m}${m.includes('sonnet') ? ' (tavsiya)' : m.includes('opus') ? ' (eng kuchli, qimmatroq)' : ' (tez, arzon)'}</option>`).join('')}</select></div>
        <div class="field"><label for="ai-time">Kunlik tahlil vaqti</label><input id="ai-time" type="time" value="${esc(s.diagnostics_time)}"></div>
      </div>
      <label class="row"><input id="ai-on" type="checkbox" ${s.ai.enabled ? 'checked' : ''}> AI tahlil yoqilgan</label>
      <p class="muted small">Kalit: console.anthropic.com → API Keys. Kalit shifrlangan holda saqlanadi.</p>
      <div><button class="btn primary" type="submit">Saqlash</button></div></form>`;

  $('#f-bot').addEventListener('submit', (e) => {
    e.preventDefault();
    withBtn(e.submitter, async () => {
      const r = await api('PUT', '/settings/bot', { token: $('#b-token').value });
      CONFIG.botUsername = r.username;
      toast(`@${r.username} ulandi. Endi botga /start yozing.`);
      route();
    });
  });
  main.querySelectorAll('[data-admin]').forEach((b) => b.addEventListener('click', () => withBtn(b, async () => {
    await api('PUT', '/settings/admin-chat', { chat_id: b.dataset.admin, name: b.dataset.name });
    toast('Admin belgilandi');
    route();
  })));
  $('#refresh-starters').addEventListener('click', route);
  $('#test-admin').addEventListener('click', (e) => withBtn(e.target, async () => {
    const j = await api('POST', '/settings/test-message');
    await waitJob(j.id, 60000);
    toast('Sinov xabari yuborildi');
  }));
  $('#f-ai').addEventListener('submit', (e) => {
    e.preventDefault();
    withBtn(e.submitter, async () => {
      await api('PUT', '/settings/ai', {
        api_key: $('#ai-key').value, model: $('#ai-model').value,
        enabled: $('#ai-on').checked, diagnostics_time: $('#ai-time').value,
      });
      toast('Saqlandi');
      route();
    });
  });
}

if (TOKEN) start(); else logout();
