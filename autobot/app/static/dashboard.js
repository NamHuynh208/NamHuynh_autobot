'use strict';
const $ = (id) => document.getElementById(id);
const screens = ['reports', 'messages', 'settings'];
const kinds = {manual: 'Quét thủ công', interval: 'Báo cáo định kỳ', morning: 'Tổng hợp buổi sáng'};
const groups = {urgent: 'Khẩn cấp / Cần trả lời ngay', important: 'Công việc / Học tập / Quan trọng', casual: 'Thông thường / Tán gẫu'};
const names = {discord: 'Discord', messenger: 'Messenger'};
const states = {
  ready: ['Đang hoạt động', 'good'], running: ['Đang tổng hợp', 'good'], connecting: ['Đang kết nối', 'warn'],
  disabled: ['Chưa cấu hình', ''], error: ['Có lỗi', 'bad'], unknown: ['Chưa có tín hiệu', ''],
  CONNECTED: ['Đã kết nối Meta', 'good'], CONNECTING: ['Đang kết nối', 'warn'], BACKFILLING: ['Đang đồng bộ', 'warn'],
  STARTING: ['Đang khởi động', 'warn'], UNCONFIGURED: ['Chưa đăng nhập', ''], BAD_CREDENTIALS: ['Cần đăng nhập lại', 'bad'],
  LOGGED_OUT: ['Đã đăng xuất', 'bad'], TRANSIENT_DISCONNECT: ['Mất kết nối', 'warn'],
  UNKNOWN_ERROR: ['Có lỗi', 'bad'], BRIDGE_UNREACHABLE: ['Không liên lạc được', 'bad'],
};
let zone = 'Asia/Ho_Chi_Minh';
let screen;
let latestKey;
let settingsLoaded = false;
let automaticSaving = false;
let overviewLoading = false;

function text(tag, value, className) {
  const item = document.createElement(tag);
  item.textContent = value;
  if (className) item.className = className;
  return item;
}
function note(message, error = false) {
  $('feedback').textContent = message;
  $('feedback').classList.toggle('error', error);
}
function format(seconds) {
  return new Intl.DateTimeFormat('vi-VN', {dateStyle: 'short', timeStyle: 'short', timeZone: zone}).format(seconds * 1000);
}
function badge(node, label, tone = '') {
  node.textContent = label;
  node.className = `badge ${tone}`;
}
async function api(path, method = 'GET', body) {
  const options = {method};
  if (method !== 'GET') {
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(body ?? {});
  }
  const response = await fetch(`/api/${path}`, options);
  if (response.status === 401) location.replace('/');
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))).detail;
    throw new Error(Array.isArray(detail) ? detail.join(' · ') : detail || `Không tải được dữ liệu (HTTP ${response.status}).`);
  }
  return response.json();
}
function digest(row) {
  const wrapper = document.createElement('div');
  wrapper.append(text('p', `${format(row.created)} · Discord ${row.discord_count} · Messenger ${row.messenger_count}`, 'digest-meta'));
  const sections = document.createElement('div');
  sections.className = 'digest';
  // Reports before the per-source format keep the three legacy groups.
  const parts = row.body.sources
    ? [['⭐ Quan trọng', row.body.important], ...row.body.sources.map(item => [item.name, item.summary])]
    : Object.entries(groups).map(([key, label]) => [label, row.body[key]]);
  for (const [label, body] of parts) {
    const section = document.createElement('section');
    section.append(text('h3', label), text('p', (body || '').trim() || 'Không có mục nổi bật.'));
    sections.append(section);
  }
  wrapper.append(sections);
  return wrapper;
}
async function overview() {
  if (overviewLoading) return;
  overviewLoading = true;
  try {
    const data = await api('overview');
    zone = $('zone').textContent = data.timezone;
    for (const [key, state] of Object.entries(data.services)) badge($(`${key}-status`), ...(states[state] || states.unknown));
    if (!automaticSaving) {
      $('automatic').disabled = false;
      $('automatic').checked = data.automatic;
    }
    $('stats').textContent = `${data.stats.pending} tin chưa tóm tắt · ${data.stats.total} tin đã lưu`;
    const state = {done: 'Hoàn thành', queued: 'Đang chờ / xử lý', retry: 'Chờ thử lại'};
    $('job').textContent = data.job ? `Lượt #${data.job.id} · ${state[data.job.state]}` : 'Chưa có lượt tổng hợp.';
    $('checked').textContent = `Cập nhật ${format(data.checked)} (${zone})`;
    const row = data.latest;
    const key = row ? `${row.id}:${row.delivery}` : 'empty';
    if (key !== latestKey) {
      const initial = latestKey === undefined;
      latestKey = key;
      $('latest-state').hidden = !row;
      if (row) badge($('latest-state'), ...({sent: ['Đã gửi Messenger', 'good'], failed: ['Gửi Messenger lỗi', 'bad']}[row.delivery] ?? ['Đã lưu']));
      $('latest').replaceChildren(row ? digest(row) : text('p', 'Chưa có báo cáo. Thêm nguồn tin trong Cấu hình, đợi tin nhắn mới rồi chạy tóm tắt.', 'muted'));
      if (!initial && screen === 'reports' && !reports.loading && !reports.paged) await reports.load(false, true);
    }
  } catch (error) {
    $('checked').textContent = 'Mất kết nối dashboard; trạng thái bên trên có thể đã cũ.';
    if (latestKey === undefined) $('latest').replaceChildren(text('p', error.message, 'muted'));
  } finally { overviewLoading = false; }
}
function reportItem(row) {
  const details = document.createElement('details');
  details.dataset.report = row.id;
  details.append(text('summary', `#${row.id} · ${kinds[row.kind]} · ${format(row.created)}`), digest(row));
  return details;
}
function messageItem(row) {
  const tr = document.createElement('tr');
  const source = text('td', names[row.platform]);
  source.append(text('span', `${row.author} · ${row.room}`, 'room'));
  const status = document.createElement('td');
  status.append(text('span', row.is_summarized ? 'Đã tóm tắt' : 'Chưa tóm tắt', row.is_summarized ? 'badge good' : 'badge'));
  tr.append(text('td', format(row.ts)), source, text('td', row.content), status);
  return tr;
}
function listing(endpoint, filterId, listId, moreId, limit, render) {
  const filter = $(filterId), list = $(listId), more = $(moreId);
  let before, filters, version = 0;
  const control = {loading: false, paged: false, async load(append = false, refresh = false) {
    const request = ++version;
    if (!append && !refresh) filters = new URLSearchParams(new FormData(filter));
    const params = new URLSearchParams(filters);
    params.set('limit', limit);
    if (append) params.set('before', before);
    control.loading = true;
    more.disabled = true;
    try {
      const items = await api(`${endpoint}?${params}`);
      if (request !== version) return;
      const nodes = items.map(render);
      if (append) list.append(...nodes);
      else {
        const empty = nodes.length === 0 && endpoint === 'summaries' ? [text('p', 'Không có báo cáo phù hợp.', 'muted')] : [];
        if (refresh && endpoint === 'summaries') {
          const open = new Set([...list.querySelectorAll('details[open]')].map((item) => item.dataset.report));
          for (const row of nodes) row.open = open.has(row.dataset.report);
        }
        list.replaceChildren(...nodes, ...empty);
      }
      if (endpoint === 'messages') $('message-note').textContent = items.length || append ? `Cập nhật ${format(Date.now() / 1000)}` : 'Không có tin nhắn phù hợp.';
      before = items.at(-1)?.id;
      more.hidden = items.length < limit;
      control.paged = append;
    } catch (error) { if (request === version) note(error.message, true); }
    finally { if (request === version) { control.loading = false; more.disabled = false; } }
  }};
  filter.addEventListener('submit', (event) => { event.preventDefault(); note(''); control.load(); });
  more.addEventListener('click', () => control.load(true));
  return control;
}
const reports = listing('summaries', 'report-filter', 'report-list', 'more-reports', 15, reportItem);
const messages = listing('messages', 'message-filter', 'message-list', 'more-messages', 25, messageItem);

const form = $('settings-form');
const settingsButton = form.querySelector('button');
const ids = ['discord_servers', 'discord_rooms', 'discord_ignore', 'matrix_rooms', 'matrix_ignore'];
async function loadSettings() {
  try {
    const config = await api('settings');
    for (const [key, value] of Object.entries(config)) if (form.elements[key]) form.elements[key].value = Array.isArray(value) ? value.join('\n') : value;
    form.elements.discord_servers.disabled = false;
    settingsLoaded = true;
    settingsButton.disabled = false;
  } catch (error) { note(error.message, true); }
}
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  settingsButton.disabled = true;
  try {
    const config = Object.fromEntries(new FormData(form));
    for (const key of ids) config[key] = config[key].split(/[\s,]+/).filter(Boolean);
    config.interval_minutes = Number(config.interval_minutes);
    config.automatic = (await api('settings')).automatic;
    await api('settings', 'PUT', config);
    note('Đã lưu cấu hình.');
  } catch (error) { note(error.message, true); }
  finally { settingsButton.disabled = false; }
});

async function action(button, callback) {
  button.disabled = true;
  try { await callback(); }
  catch (error) { note(error.message, true); }
  finally { button.disabled = false; }
}
$('trigger').onclick = () => action($('trigger'), async () => {
  const data = await api('summarize', 'POST');
  note(data.queued ? `Đã xếp lượt #${data.id}. Theo dõi trạng thái ở mục Vận hành.` : `Lượt #${data.id} đang chờ hoặc đang xử lý.`);
  await overview();
});
$('automatic').onchange = () => action($('automatic'), async () => {
  automaticSaving = true;
  try {
    const value = $('automatic').checked;
    await api('automatic', 'PUT', {automatic: value});
    note(value ? 'Đã bật lịch tự động.' : 'Đã tắt lịch tự động. Lượt đã xếp vẫn được xử lý.');
  } catch (error) { $('automatic').checked = !$('automatic').checked; throw error; }
  finally { automaticSaving = false; }
});
$('logout').onclick = () => action($('logout'), async () => { await api('logout', 'POST'); location.replace('/'); });

async function route() {
  const next = location.hash.slice(1);
  if (next === 'main') return;
  screen = screens.includes(next) ? next : 'reports';
  for (const id of screens) {
    $(id).hidden = id !== screen;
    const link = document.querySelector(`nav a[href="#${id}"]`);
    if (id === screen) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  note('');
  if (screen === 'reports') await reports.load();
  if (screen === 'messages') await messages.load();
  if (screen === 'settings' && !settingsLoaded) await loadSettings();
}
window.addEventListener('hashchange', route);
route();
overview();
setInterval(() => {
  if (document.hidden) return;
  overview();
  if (screen === 'messages' && !messages.loading && !messages.paged) messages.load(false, true);
}, 6000);
