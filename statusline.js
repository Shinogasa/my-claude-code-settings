#!/usr/bin/env node

const path = require('path');
const fs = require('fs');
const os = require('os');
const { execFileSync } = require('child_process');

const LITELLM_CACHE_PATH = path.join(os.homedir(), '.claude', 'cache', 'litellm-budget.json');
const LITELLM_CACHE_TTL_MS = 60_000;
// statusline は頻繁に描画されるので git は短く打ち切る。テストでは負荷で落ちないよう延ばす
const GIT_TIMEOUT_MS = Number(process.env.STATUSLINE_GIT_TIMEOUT_MS) || 500;

// ANSI カラー
const C = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

let input = '';
process.stdin.on('data', chunk => (input += chunk));
process.stdin.on('end', async () => {
  try {
    const data = JSON.parse(input);
    const lines = await buildStatusLines(data);
    console.log(lines.join('\n'));
  } catch (e) {
    // フォールバック: パース失敗時もstatuslineは出す
    const fallbackTime = jstNow();
    console.log(`${C.gray}🤖 Claude | 🕐 ${fallbackTime}${C.reset}`);
  }
});

async function buildStatusLines(data) {
  const columns = parseColumns(process.env.COLUMNS);
  return [
    // 1段目: 名前を中央で省略する。リポジトリ名は省略しない
    fitRow(buildRepoRow(data), columns, { shrink: ['session', 'branch', 'worktree'] }),
    // 2段目: 縮めず、幅を超えたら端末の折り返しに任せる（目的の中心なので欠けるより全部見せる）
    renderRow(await buildBudgetRow(data)),
    // 3段目: 価値の低い順に落とす。コストと output style は落とさない
    fitRow(buildMetricsRow(data), columns, { drop: ['time', 'duration', 'lines', 'tokens'] }),
  ];
}

// Claude Code は実行前に COLUMNS を端末の幅に設定する。正の整数でなければ縮めない
function parseColumns(value) {
  if (!/^\d+$/.test(value || '')) return null;
  const n = Number.parseInt(value, 10);
  return n > 0 ? n : null;
}

const ANSI_RE = /\x1b\[[0-9;]*m/g;
const WIDE_RE = /[\p{Emoji_Presentation}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\u3000-\u303f\uff01-\uff60\uffe0-\uffe6]/u;
const ZERO_RE = /[\u200d\ufe0e\ufe0f\p{Mn}]/u;

// 端末上の表示幅。色コードを除き、絵文字表示の文字と全角文字を2桁で数える
function displayWidth(s) {
  const chars = [...s.replace(ANSI_RE, '')];
  let width = 0;
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (ZERO_RE.test(ch)) continue;
    // 文字表示の記号でも、FE0F が続けば絵文字として2桁で描かれる
    width += WIDE_RE.test(ch) || chars[i + 1] === '\ufe0f' ? 2 : 1;
  }
  return width;
}

const MIN_KEEP_EACH_SIDE = 4; // 前後4文字ずつ、計8文字は残す

// 前後を残し、中央を … にして maxWidth に収める。文字の途中では切らない
function truncateMiddle(name, maxWidth) {
  const chars = [...name];
  if (displayWidth(name) <= maxWidth || chars.length <= MIN_KEEP_EACH_SIDE * 2) return name;
  const budget = Math.max(maxWidth - 1, 0);
  const take = (list, limit) => {
    const out = [];
    let w = 0;
    for (const ch of list) {
      const cw = displayWidth(ch);
      if (out.length >= MIN_KEEP_EACH_SIDE && w + cw > limit) break;
      out.push(ch);
      w += cw;
    }
    return out;
  };
  const front = take(chars, Math.ceil(budget / 2));
  const back = take([...chars].reverse(), Math.floor(budget / 2)).reverse();
  if (front.length + back.length >= chars.length) return name;
  return `${front.join('')}…${back.join('')}`;
}

// 幅を超えている間、drop の順にセグメントを落とし、次に shrink の順に名前を縮める
function fitRow(segments, columns, { drop = [], shrink = [] } = {}) {
  let segs = segments.map(seg => ({ ...seg }));
  if (!columns) return renderRow(segs);
  const overflow = () => displayWidth(renderRow(segs)) - columns;

  for (const id of drop) {
    if (overflow() <= 0) break;
    segs = segs.filter(seg => seg.id !== id);
  }
  for (const id of shrink) {
    const over = overflow();
    if (over <= 0) break;
    const seg = segs.find(s => s.id === id && s.render);
    if (seg) seg.name = truncateMiddle(seg.name, Math.max(displayWidth(seg.name) - over, 0));
  }
  return renderRow(segs);
}

// セグメントは { id, text } か、名前を省略できる { id, name, render(name) }
function renderSegment(seg) {
  return seg.render ? seg.render(seg.name) : seg.text;
}

function renderRow(segments) {
  return segments.map(renderSegment).join(' ');
}

// ───── 1段目: どこで作業しているか ─────
function buildRepoRow(data) {
  const currentDirPath = data.workspace?.current_dir || data.cwd || '.';
  const projectDir = data.workspace?.project_dir;
  const agent = data.agent?.name;
  const sessionName = data.session_name;
  const worktree = data.worktree?.name || data.workspace?.git_worktree;
  // worktree の中では basename が worktree 名になり 🌲 と重複するので、元リポジトリ名を出す
  const currentDir = (worktree && getMainRepoName(currentDirPath)) || path.basename(currentDirPath);

  const segs = [{ id: 'repo', text: `${C.blue}📁 ${currentDir}${C.reset}` }];

  if (worktree) {
    segs.push({ id: 'worktree', name: worktree, render: n => `${C.dim}🌲 ${n}${C.reset}` });
  }

  const git = getGitInfo(projectDir);
  if (git) {
    const dirty = git.dirty ? `${C.yellow}●${C.reset}` : `${C.green}✓${C.reset}`;
    // EnterWorktree のブランチ名は worktree-<worktree名> なので、🌲 と同じ名前を二度出さない
    if (worktree && git.branch === `worktree-${worktree}`) {
      segs.push({ id: 'branch', text: `${C.magenta}⎇${C.reset} ${dirty}` });
    } else {
      segs.push({ id: 'branch', name: git.branch, render: n => `${C.magenta}⎇ ${n}${C.reset} ${dirty}` });
    }
  }

  const prText = formatPr(data.pr);
  if (prText) segs.push({ id: 'pr', text: prText });

  if (sessionName) {
    segs.push({ id: 'session', name: sessionName, render: n => `${C.dim}📌 ${n}${C.reset}` });
  }
  if (agent) segs.push({ id: 'agent', text: `${C.magenta}🤝 ${agent}${C.reset}` });

  return segs;
}

// ───── 2段目: あとどれだけ効率よく続けられるか ─────
async function buildBudgetRow(data) {
  const model = data.model?.display_name || 'Claude';
  const effort = data.effort?.level;
  const thinking = data.thinking?.enabled;
  const rl = data.rate_limits;
  const usedPct = data.context_window?.used_percentage;

  const segs = [];

  // モデル + effort + thinking
  let modelPart = `${C.cyan}🤖 ${model}${C.reset}`;
  const modelSuffix = [];
  if (effort) modelSuffix.push(formatEffort(effort));
  if (thinking) modelSuffix.push(`${C.magenta}🧠${C.reset}`);
  if (modelSuffix.length > 0) modelPart += `${C.dim}[${C.reset}${modelSuffix.join(' ')}${C.dim}]${C.reset}`;
  segs.push({ id: 'model', text: modelPart });

  // 認証プロファイル (常時表示)
  segs.push({ id: 'profile', text: formatProfile() });

  // バジェット: litellm 利用額 (全ターミナル合算、キャッシュ経由)
  const budget = await getLitellmBudget();
  if (budget) segs.push({ id: 'budget', text: formatBudget(budget.spend, budget.max_budget) });

  // レート制限 (Pro/Max契約時のみ存在)
  if (rl?.five_hour?.used_percentage != null) {
    segs.push({ id: 'rate5h', text: formatRateLimit('5h', rl.five_hour) });
  }
  if (rl?.seven_day?.used_percentage != null) {
    segs.push({ id: 'rate7d', text: formatRateLimit('7d', rl.seven_day) });
  }

  // gateway の spend limit
  const spendText = formatSpendLimit(rl?.spend_limit);
  if (spendText) segs.push({ id: 'spend', text: spendText });

  // コンテキスト使用率 + プログレスバー
  if (typeof usedPct === 'number') {
    segs.push({ id: 'context', text: formatProgressBar(usedPct) });
  } else {
    segs.push({ id: 'context', text: `${C.dim}[░░░░░░░░░░] --%${C.reset}` });
  }

  // プロンプトキャッシュ
  const cacheText = formatCache(data.prompt_cache, Math.floor(Date.now() / 1000));
  if (cacheText) segs.push({ id: 'cache', text: cacheText });

  return segs;
}

// ───── 3段目: 参考の数値 ─────
function buildMetricsRow(data) {
  const ctx = data.context_window || {};
  const cost = data.cost || {};
  const outputStyle = data.output_style?.name;

  const segs = [];

  // トークン数 (input / output)
  const totalIn = ctx.total_input_tokens;
  const totalOut = ctx.total_output_tokens;
  if (typeof totalIn === 'number' && totalIn > 0) {
    segs.push({ id: 'tokens', text: `${C.gray}🪙 ${formatTokens(totalIn)}↓/${formatTokens(totalOut || 0)}↑${C.reset}` });
  }

  // コスト
  const usd = cost.total_cost_usd;
  if (typeof usd === 'number') segs.push({ id: 'cost', text: formatCost(usd) });

  // コード変更行数 (1行以上変更があれば表示)
  const added = cost.total_lines_added || 0;
  const removed = cost.total_lines_removed || 0;
  if (added > 0 || removed > 0) {
    segs.push({ id: 'lines', text: `${C.green}+${added}${C.reset}${C.gray}/${C.reset}${C.red}-${removed}${C.reset}` });
  }

  // セッション経過時間
  if (typeof cost.total_duration_ms === 'number' && cost.total_duration_ms > 0) {
    segs.push({ id: 'duration', text: `${C.dim}⏱ ${formatDuration(cost.total_duration_ms)}${C.reset}` });
  }

  // output style (default 以外)
  if (outputStyle && outputStyle !== 'default') {
    segs.push({ id: 'style', text: `${C.dim}🎨 ${outputStyle}${C.reset}` });
  }

  // JST 現在時刻
  segs.push({ id: 'time', text: `${C.dim}🕐 ${jstNow()}${C.reset}` });

  return segs;
}

// ───── ヘルパー ─────
function getGitInfo(projectDir) {
  if (!projectDir) return null;
  try {
    // execFileSync は shell を経由しないため引数のシェル展開が起きない
    const branch = execFileSync('git', ['branch', '--show-current'], {
      cwd: projectDir,
      encoding: 'utf8',
      timeout: GIT_TIMEOUT_MS,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    if (!branch) return null;

    const status = execFileSync('git', ['status', '--porcelain'], {
      cwd: projectDir,
      encoding: 'utf8',
      timeout: GIT_TIMEOUT_MS,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();

    return { branch, dirty: Boolean(status) };
  } catch {
    return null;
  }
}

// linked worktree でも共通の .git を返す --git-common-dir から、元リポジトリ名を求める
function getMainRepoName(dir) {
  try {
    const commonDir = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      cwd: dir,
      encoding: 'utf8',
      timeout: GIT_TIMEOUT_MS,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    if (!commonDir) return null;
    // 通常は <repo>/.git、bare リポジトリでは <repo>.git が返る
    return path.basename(commonDir) === '.git'
      ? path.basename(path.dirname(commonDir))
      : path.basename(commonDir, '.git');
  } catch {
    return null;
  }
}

async function getLitellmBudget() {
  if (!process.env.ANTHROPIC_BASE_URL || !process.env.ANTHROPIC_AUTH_TOKEN) return null;

  let cached = null;
  try {
    cached = JSON.parse(fs.readFileSync(LITELLM_CACHE_PATH, 'utf8'));
  } catch {
    // キャッシュ未存在または壊れている場合は下の初回取得にフォールバック
  }

  const isFresh = cached && Date.now() - cached.fetched_at < LITELLM_CACHE_TTL_MS;
  if (isFresh) return cached;

  // キャッシュ無し(初回)は表示に間に合わせるため待つ。キャッシュ有り(TTL切れ)は
  // 古い値を先に返し、更新は次回表示に反映されるようバックグラウンドで進める
  if (!cached) return updateLitellmBudgetCache();

  updateLitellmBudgetCache();
  return cached;
}

async function updateLitellmBudgetCache() {
  const base = process.env.ANTHROPIC_BASE_URL;
  const token = process.env.ANTHROPIC_AUTH_TOKEN;
  if (!base || !token) return null;

  try {
    const res = await fetch(`${base}/key/info`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const spend = data?.info?.spend;
    const maxBudget = data?.info?.max_budget;
    if (typeof spend !== 'number' || typeof maxBudget !== 'number') return null;

    const cache = { spend, max_budget: maxBudget, fetched_at: Date.now() };
    fs.mkdirSync(path.dirname(LITELLM_CACHE_PATH), { recursive: true });
    fs.writeFileSync(LITELLM_CACHE_PATH, JSON.stringify(cache));
    return cache;
  } catch {
    // ネットワーク不通・タイムアウト時は静かに諦める(次回のTTL切れで再試行される)
    return null;
  }
}

// プロンプトキャッシュ: 温かければ残り分、冷えていれば cold。expires_at は epoch 秒で null もありうる
function formatCache(pc, nowSec) {
  if (!pc) return null;
  const hit = typeof pc.hit_ratio === 'number' ? ` ${C.dim}(hit ${Math.round(pc.hit_ratio * 100)}%)${C.reset}` : '';
  const remaining = typeof pc.expires_at === 'number' ? pc.expires_at - nowSec : 0;
  if (pc.warm && remaining > 0) {
    return `${C.yellow}🔥cache ${Math.ceil(remaining / 60)}m${C.reset}${hit}`;
  }
  return `${C.blue}🧊cache cold${C.reset}${hit}`;
}

// PR: GitHub は #番号、GitLab の merge request は !番号。review_state は無いこともある
function formatPr(pr) {
  if (!pr || typeof pr.number !== 'number') return null;
  const num = pr.kind === 'mr' ? `!${pr.number}` : `#${pr.number}`;
  const colors = { approved: C.green, changes_requested: C.red, pending: C.yellow, draft: C.gray };
  const state = pr.review_state ? ` ${pr.review_state}` : '';
  return `${colors[pr.review_state] || C.cyan}${num}${state}${C.reset}`;
}

// gateway の spend limit。used_usd / limit_usd は無いこともある
function formatSpendLimit(sl) {
  if (!sl || typeof sl.used_percentage !== 'number') return null;
  const pct = Math.round(sl.used_percentage);
  let color = C.green;
  if (pct >= 90) color = C.red + C.bold;
  else if (pct >= 70) color = C.yellow;
  const usd = typeof sl.used_usd === 'number' && typeof sl.limit_usd === 'number'
    ? ` $${Math.round(sl.used_usd)}/$${Math.round(sl.limit_usd)}`
    : '';
  return `${color}💸 ${pct}%${usd}${C.reset}`;
}

function formatProgressBar(pct) {
  const width = 10;
  const clamped = Math.max(0, Math.min(100, pct));
  const filled = Math.round((clamped * width) / 100);
  const empty = width - filled;

  let color = C.green;
  if (clamped >= 90) color = C.red + C.bold;
  else if (clamped >= 70) color = C.yellow;
  else if (clamped >= 50) color = C.cyan;

  const bar = `${color}${'▓'.repeat(filled)}${C.reset}${C.dim}${'░'.repeat(empty)}${C.reset}`;
  const pctStr = `${color}${Math.round(clamped)}%${C.reset}`;
  return `[${bar}] ${pctStr}`;
}

function formatTokens(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(usd) {
  let color = C.green;
  if (usd >= 5) color = C.red + C.bold;
  else if (usd >= 1) color = C.yellow;
  // 小さい額は4桁、大きい額は2桁
  const formatted = usd < 1 ? usd.toFixed(4) : usd.toFixed(2);
  return `${color}💰 $${formatted}${C.reset}`;
}

function formatBudget(spend, maxBudget) {
  const pct = maxBudget > 0 ? (spend / maxBudget) * 100 : 0;
  let color = C.green;
  if (pct >= 90) color = C.red + C.bold;
  else if (pct >= 70) color = C.yellow;
  return `${color}💳 $${Math.round(spend)}/$${Math.round(maxBudget)}${C.reset}`;
}

function formatDuration(ms) {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m${sec % 60}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h${min % 60}m`;
}

function formatEffort(level) {
  const map = {
    low: `${C.gray}⚡low${C.reset}`,
    medium: `${C.cyan}⚡med${C.reset}`,
    high: `${C.yellow}⚡high${C.reset}`,
    xhigh: `${C.red}⚡xhigh${C.reset}`,
    max: `${C.red}${C.bold}⚡max${C.reset}`,
  };
  return map[level] || `${C.gray}⚡${level}${C.reset}`;
}

// 認証プロファイル: LiteLLM経由(会社) か 個人Anthropicアカウントか。
// getLitellmBudget() と同じ判定条件を使い、💳 残高表示の有無と整合させる。
// 意図しない接続先で作業する事故を防ぐため、どちらの状態でも必ず表示する。
function formatProfile() {
  const isWork = Boolean(process.env.ANTHROPIC_BASE_URL && process.env.ANTHROPIC_AUTH_TOKEN);
  return isWork ? `${C.yellow}🏢WORK${C.reset}` : `${C.green}🏠PERSONAL${C.reset}`;
}

function formatRateLimit(label, win) {
  const pct = Math.round(win.used_percentage);
  let color = C.green;
  if (pct >= 90) color = C.red + C.bold;
  else if (pct >= 70) color = C.yellow;

  let resetStr = '';
  if (win.resets_at) {
    const now = Math.floor(Date.now() / 1000);
    const diff = win.resets_at - now;
    if (diff > 0) resetStr = `${C.dim}(${formatDuration(diff * 1000)})${C.reset}`;
  }
  return `${color}📊${label} ${pct}%${C.reset}${resetStr}`;
}

function jstNow() {
  return new Date().toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
  });
}
