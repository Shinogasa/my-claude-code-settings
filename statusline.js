#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { execSync } = require('child_process');

// Constants
const COMPACTION_THRESHOLD = 200000 * 0.8

// Read JSON from stdin
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', async () => {
  try {
    const data = JSON.parse(input);

    // Extract values
    const model = data.model?.display_name || 'Claude';
    const currentDir = path.basename(data.workspace?.current_dir || data.cwd || '.');
    const projectDir = data.workspace?.project_dir;
    const sessionId = data.session_id;
    const outputStyle = data.output_style?.name || 'default';

    // Get current time in JST
    const jstTime = new Date().toLocaleString('ja-JP', { 
      timeZone: 'Asia/Tokyo',
      hour: '2-digit',
      minute: '2-digit'
    });

    // Check if we're in a git repository
    let gitBranch = '';
    let gitStatus = '';
    if (projectDir) {
      try {
        const branch = execSync('git branch --show-current', { 
          cwd: projectDir, 
          encoding: 'utf8',
          timeout: 1000
        }).trim();
        gitBranch = branch ? `⎇ ${branch}` : '';
        
        // Check git status
        const statusOut = execSync('git status --porcelain', { 
          cwd: projectDir, 
          encoding: 'utf8',
          timeout: 1000
        }).trim();
        if (statusOut) {
          const modified = statusOut.split('\n').filter(line => line.startsWith(' M')).length;
          const added = statusOut.split('\n').filter(line => line.startsWith('A')).length;
          const untracked = statusOut.split('\n').filter(line => line.startsWith('??')).length;
          
          if (modified || added || untracked) {
            gitStatus = ' 📝';
          }
        }
      } catch (e) {
        // Not a git repo or git command failed
      }
    }

    // Calculate token usage for current session
    let totalTokens = 0;

    if (sessionId) {
      // Find all transcript files
      const projectsDir = path.join(process.env.HOME, '.claude', 'projects');

      if (fs.existsSync(projectsDir)) {
        // Get all project directories
        const projectDirs = fs.readdirSync(projectsDir)
          .map(dir => path.join(projectsDir, dir))
          .filter(dir => fs.statSync(dir).isDirectory());

        // Search for the current session's transcript file
        for (const projectDir of projectDirs) {
          const transcriptFile = path.join(projectDir, `${sessionId}.jsonl`);

          if (fs.existsSync(transcriptFile)) {
            totalTokens = await calculateTokensFromTranscript(transcriptFile);
            break;
          }
        }
      }
    }

    // Calculate percentage
    const percentage = Math.min(100, Math.round((totalTokens / COMPACTION_THRESHOLD) * 100));

    // Format token display
    const tokenDisplay = formatTokenCount(totalTokens);

    // Color coding for percentage
    let percentageColor = '\x1b[32m'; // Green
    if (percentage >= 70) percentageColor = '\x1b[33m'; // Yellow
    if (percentage >= 90) percentageColor = '\x1b[31m'; // Red

    // Build status line with Japanese-friendly format
    const statusParts = [
      `🤖 ${model}`,
      `📁 ${currentDir}`,
      gitBranch + gitStatus,
      `🪙 ${tokenDisplay}`,
      `${percentageColor}${percentage}%\x1b[0m`,
      `🕐 ${jstTime}`,
      outputStyle !== 'default' ? `🎨 ${outputStyle}` : ''
    ].filter(part => part);

    const statusLine = statusParts.join(' | ');

    console.log(statusLine);
  } catch (error) {
    // Fallback status line on error
    const fallbackTime = new Date().toLocaleString('ja-JP', { 
      timeZone: 'Asia/Tokyo',
      hour: '2-digit',
      minute: '2-digit'
    });
    console.log(`🤖 Claude | 📁 . | 🪙 0 | 0% | 🕐 ${fallbackTime}`);
  }
});

async function calculateTokensFromTranscript(filePath) {
  return new Promise((resolve, reject) => {
    let lastUsage = null;

    const fileStream = fs.createReadStream(filePath);
    const rl = readline.createInterface({
      input: fileStream,
      crlfDelay: Infinity
    });

    rl.on('line', (line) => {
      try {
        const entry = JSON.parse(line);

        // Check if this is an assistant message with usage data
        if (entry.type === 'assistant' && entry.message?.usage) {
          lastUsage = entry.message.usage;
        }
      } catch (e) {
        // Skip invalid JSON lines
      }
    });

    rl.on('close', () => {
      if (lastUsage) {
        // The last usage entry contains cumulative tokens
        const totalTokens = (lastUsage.input_tokens || 0) +
          (lastUsage.output_tokens || 0) +
          (lastUsage.cache_creation_input_tokens || 0) +
          (lastUsage.cache_read_input_tokens || 0);
        resolve(totalTokens);
      } else {
        resolve(0);
      }
    });

    rl.on('error', (err) => {
      reject(err);
    });
  });
}

function formatTokenCount(tokens) {
  if (tokens >= 1000000) {
    return `${(tokens / 1000000).toFixed(1)}M`;
  } else if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}K`;
  }
  return tokens.toString();
}
