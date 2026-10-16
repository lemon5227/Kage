// Proactive notices on the avatar window (W3-4 front end).
//
// The backend delivers heartbeat notifications as {type: "proactive", event: "heartbeat",
// notification: {id, type, content: "title\nbody", action?}}. One card is shown at a time;
// the user's click is sent back as {type: "proactive_feedback", id, action} — accept runs the
// follow-up the backend registered (teach, adopt a skill, record a yes), snooze/mute feed the
// proactive policy. Nothing here acts on its own.

export type ProactiveNotification = {
  id: string;
  type?: string;
  source?: string;
  content?: string;
  action?: { type?: string } | null;
};

type Send = (payload: Record<string, unknown>) => void;

const LABELS: Record<string, { accept: string; tag: string }> = {
  help_request: { accept: '好，教我', tag: '想请你教我' },
  adoption_confirm: { accept: '启用', tag: '启用新技能？' },
  learning_report: { accept: '知道了', tag: '学习汇报' },
};

const queue: ProactiveNotification[] = [];
let card: HTMLDivElement | null = null;
let send: Send = () => undefined;

function ensureStyles(): void {
  if (document.getElementById('kage-notice-style')) return;
  const style = document.createElement('style');
  style.id = 'kage-notice-style';
  style.textContent = `
    .kage-notice { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%);
      width: min(340px, calc(100vw - 24px)); box-sizing: border-box; padding: 12px 14px;
      border-radius: 14px; background: rgba(255,255,255,0.94); color: #1f2329;
      font: 13px/1.5 -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25); z-index: 9000; }
    .kage-notice .tag { font-size: 11px; color: #6b7280; margin-bottom: 2px; }
    .kage-notice .title { font-weight: 650; margin-bottom: 4px; }
    .kage-notice .body { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 9em; overflow-y: auto; }
    .kage-notice .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 10px; }
    .kage-notice button { border: 0; border-radius: 8px; padding: 6px 10px; font: inherit; cursor: pointer;
      background: #eef0f3; color: #1f2329; }
    .kage-notice button.primary { background: #2563eb; color: white; }
    .kage-toast { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); padding: 8px 12px;
      border-radius: 10px; background: rgba(31,35,41,0.9); color: white; font: 12px -apple-system, sans-serif;
      z-index: 9001; }
    @media (prefers-color-scheme: dark) {
      .kage-notice { background: rgba(32,34,38,0.95); color: #eceef1; }
      .kage-notice .tag { color: #9aa1ab; }
      .kage-notice button { background: #3a3d43; color: #eceef1; }
    }`;
  document.head.appendChild(style);
}

function button(label: string, primary: boolean, onClick: () => void): HTMLButtonElement {
  const b = document.createElement('button');
  b.type = 'button';
  b.textContent = label;
  if (primary) b.className = 'primary';
  b.addEventListener('click', onClick);
  return b;
}

function respond(n: ProactiveNotification, action: 'accept' | 'snooze' | 'mute'): void {
  send({ type: 'proactive_feedback', id: n.id, action });
  card?.remove();
  card = null;
  showNext();
}

function render(n: ProactiveNotification): void {
  ensureStyles();
  const [title, ...rest] = String(n.content || '').split('\n');
  const label = LABELS[String(n.type || '')];
  card = document.createElement('div');
  card.className = 'kage-notice';
  card.setAttribute('role', 'alertdialog');
  card.setAttribute('aria-label', title || 'Kage');
  const tag = document.createElement('div');
  tag.className = 'tag';
  tag.textContent = label ? label.tag : 'Kage';
  const t = document.createElement('div');
  t.className = 'title';
  t.textContent = title;
  const body = document.createElement('div');
  body.className = 'body';
  body.textContent = rest.join('\n');
  const actions = document.createElement('div');
  actions.className = 'actions';
  actions.append(button('不再提醒', false, () => respond(n, 'mute')));
  actions.append(button('稍后', false, () => respond(n, 'snooze')));
  actions.append(button(label?.accept || (n.action ? '好' : '知道了'), true, () => respond(n, 'accept')));
  card.append(tag, t, body, actions);
  document.body.appendChild(card);
}

function showNext(): void {
  if (card || !queue.length) return;
  render(queue.shift()!);
}

export function initNotices(sender: Send): void {
  send = sender;
}

export function showNotice(n: ProactiveNotification): void {
  if (!n || !n.id || queue.some(q => q.id === n.id)) return;
  queue.push(n);
  showNext();
}

export function toast(text: string, ms = 4000): void {
  ensureStyles();
  const el = document.createElement('div');
  el.className = 'kage-toast';
  el.setAttribute('role', 'status');
  el.textContent = text;
  document.body.appendChild(el);
  window.setTimeout(() => el.remove(), ms);
}

export function handleProactive(data: { event?: string; notification?: ProactiveNotification; tools?: string[];
                                        error?: string }): void {
  if (data.event === 'heartbeat' && data.notification) showNotice(data.notification);
  else if (data.event === 'teaching_started') toast('已打开示范录制，请开始演示');
  else if (data.event === 'skill_adopted') toast(`已启用：${(data.tools || []).join('、')}`);
  else if (data.event === 'skill_adoption_failed') toast(`启用失败：${data.error || ''}`, 6000);
  else if (data.event === 'teacher_started') toast('正在请老师示范…', 6000);
  else if (data.event === 'teacher_failed') toast('这次没能请到老师', 4000);
}

// One-click verdict after a task turn (A2): the label stored with the turn's trajectory.
let reviewEl: HTMLDivElement | null = null;

export function showTurnReview(turnId: string, ms = 30000): void {
  if (!turnId) return;
  ensureStyles();
  reviewEl?.remove();
  const el = document.createElement('div');
  el.className = 'kage-toast';
  el.style.bottom = card ? '180px' : '18px';
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', '这次做得对吗');
  const label = document.createElement('span');
  label.textContent = '这次做对了吗？ ';
  el.append(label);
  for (const [text, value, aria] of [['👍', 'up', '做对了'], ['👎', 'down', '没做对']] as const) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    b.setAttribute('aria-label', aria);
    b.style.cssText = 'margin-left:6px;border:0;border-radius:6px;padding:2px 8px;cursor:pointer;font-size:14px;';
    b.addEventListener('click', () => {
      send({ type: 'turn_feedback', turn_id: turnId, value });
      el.remove();
      reviewEl = null;
      toast(value === 'up' ? '记下了，谢谢' : '记下了，我会想办法学会', 2500);
    });
    el.append(b);
  }
  document.body.appendChild(el);
  reviewEl = el;
  window.setTimeout(() => { if (reviewEl === el) { el.remove(); reviewEl = null; } }, ms);
}
