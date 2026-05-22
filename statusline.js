#!/usr/bin/env node

const path = require('path');
const { execFileSync } = require('child_process');

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
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const lines = buildStatusLines(data);
    console.log(lines.join('\n'));
  } catch (e) {
    // フォールバック: パース失敗時もstatuslineは出す
    const fallbackTime = jstNow();
    console.log(`${C.gray}🤖 Claude | 🕐 ${fallbackTime}${C.reset}`);
  }
});

function buildStatusLines(data) {
  const line1 = buildEnvLine(data);
  const line2 = buildUsageLine(data);
  return [line1, line2];
}

// ───── Line 1: 環境・コンテキスト情報 ─────
function buildEnvLine(data) {
  const model = data.model?.display_name || 'Claude';
  const currentDir = path.basename(data.workspace?.current_dir || data.cwd || '.');
  const projectDir = data.workspace?.project_dir;
  const outputStyle = data.output_style?.name;
  const effort = data.effort?.level;
  const thinking = data.thinking?.enabled;
  const agent = data.agent?.name;
  const sessionName = data.session_name;
  const worktree = data.worktree?.name || data.workspace?.git_worktree;

  const parts = [];

  // モデル + effort + thinking
  let modelPart = `${C.cyan}🤖 ${model}${C.reset}`;
  const modelSuffix = [];
  if (effort) modelSuffix.push(formatEffort(effort));
  if (thinking) modelSuffix.push(`${C.magenta}🧠${C.reset}`);
  if (modelSuffix.length > 0) modelPart += `${C.dim}[${C.reset}${modelSuffix.join(' ')}${C.dim}]${C.reset}`;
  parts.push(modelPart);

  // セッション名 (カスタム名が付いているときのみ)
  if (sessionName) parts.push(`${C.dim}📌 ${sessionName}${C.reset}`);

  // エージェント実行中
  if (agent) parts.push(`${C.magenta}🤝 ${agent}${C.reset}`);

  // ディレクトリ
  parts.push(`${C.blue}📁 ${currentDir}${C.reset}`);

  // git ブランチ + worktree
  const gitInfo = getGitInfo(projectDir);
  if (gitInfo) parts.push(gitInfo);
  if (worktree) parts.push(`${C.dim}🌲 ${worktree}${C.reset}`);

  return parts.join(' ');
}

// ───── Line 2: 使用量・コスト・進捗 ─────
function buildUsageLine(data) {
  const ctx = data.context_window || {};
  const cost = data.cost || {};
  const rl = data.rate_limits;
  const exceeds200k = data.exceeds_200k_tokens;
  const outputStyle = data.output_style?.name;

  const parts = [];

  // コンテキスト使用率 + プログレスバー
  const usedPct = ctx.used_percentage;
  if (typeof usedPct === 'number') {
    parts.push(formatProgressBar(usedPct, exceeds200k));
  } else {
    parts.push(`${C.dim}[░░░░░░░░░░] --%${C.reset}`);
  }

  // トークン数 (input / output)
  const totalIn = ctx.total_input_tokens;
  const totalOut = ctx.total_output_tokens;
  if (typeof totalIn === 'number' && totalIn > 0) {
    parts.push(`${C.gray}🪙 ${formatTokens(totalIn)}↓/${formatTokens(totalOut || 0)}↑${C.reset}`);
  }

  // コスト
  const usd = cost.total_cost_usd;
  if (typeof usd === 'number') {
    parts.push(formatCost(usd));
  }

  // コード変更行数 (1行以上変更があれば表示)
  const added = cost.total_lines_added || 0;
  const removed = cost.total_lines_removed || 0;
  if (added > 0 || removed > 0) {
    parts.push(`${C.green}+${added}${C.reset}${C.gray}/${C.reset}${C.red}-${removed}${C.reset}`);
  }

  // セッション経過時間
  if (typeof cost.total_duration_ms === 'number' && cost.total_duration_ms > 0) {
    parts.push(`${C.dim}⏱ ${formatDuration(cost.total_duration_ms)}${C.reset}`);
  }

  // レート制限 (Pro/Max契約時のみ存在)
  if (rl?.five_hour?.used_percentage != null) {
    parts.push(formatRateLimit('5h', rl.five_hour));
  }
  if (rl?.seven_day?.used_percentage != null) {
    parts.push(formatRateLimit('7d', rl.seven_day));
  }

  // output style (default 以外)
  if (outputStyle && outputStyle !== 'default') {
    parts.push(`${C.dim}🎨 ${outputStyle}${C.reset}`);
  }

  // JST 現在時刻
  parts.push(`${C.dim}🕐 ${jstNow()}${C.reset}`);

  return parts.join(' ');
}

// ───── ヘルパー ─────
function getGitInfo(projectDir) {
  if (!projectDir) return null;
  try {
    // execFileSync は shell を経由しないため引数のシェル展開が起きない
    const branch = execFileSync('git', ['branch', '--show-current'], {
      cwd: projectDir,
      encoding: 'utf8',
      timeout: 500,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    if (!branch) return null;

    const status = execFileSync('git', ['status', '--porcelain'], {
      cwd: projectDir,
      encoding: 'utf8',
      timeout: 500,
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();

    const dirty = status ? ` ${C.yellow}●${C.reset}` : ` ${C.green}✓${C.reset}`;
    return `${C.magenta}⎇ ${branch}${C.reset}${dirty}`;
  } catch {
    return null;
  }
}

function formatProgressBar(pct, exceeds200k) {
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
  const warn = exceeds200k ? ` ${C.red}${C.bold}⚠200k${C.reset}` : '';
  return `[${bar}] ${pctStr}${warn}`;
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
