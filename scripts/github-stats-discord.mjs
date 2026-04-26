#!/usr/bin/env node
/**
 * ALIVE GitHub Pulse → Discord #github-feed
 *
 * Posts daily stats embed with cumulative totals + daily snapshot.
 * Tracks running totals in stats-history.json (GitHub traffic API only keeps 14 days).
 *
 * Runs: GitHub Actions cron (11pm UTC = 9am AEST) or locally.
 * Requires: DISCORD_BOT_TOKEN + DISCORD_GUILD_ID as env vars or in ~/.env.
 * gh CLI must be authenticated (GH_TOKEN in CI, local auth otherwise).
 * Channel: #github-feed (1495113363561119886)
 */

import { execSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ── Config ──
const REPO = 'alivecontext/alive';
const CHANNEL_ID = '1495113363561119886';
const BRAND_COLOR = 0x621f1f;
const REPO_URL = 'https://github.com/alivecontext/alive';
const HISTORY_FILE = join(__dirname, 'stats-history.json');

// ── Load env (local dev — CI sets env vars directly) ──
if (!process.env.DISCORD_BOT_TOKEN) {
  try {
    const envFile = readFileSync(`${homedir()}/.env`, 'utf8');
    for (const line of envFile.split('\n')) {
      const match = line.match(/^([A-Z_]+)=(.+)$/);
      if (match && !process.env[match[1]]) {
        process.env[match[1]] = match[2].replace(/^["']|["']$/g, '');
      }
    }
  } catch {}
}

const BOT_TOKEN = process.env.DISCORD_BOT_TOKEN;
if (!BOT_TOKEN) {
  console.error('DISCORD_BOT_TOKEN not set');
  process.exit(1);
}

// ── GitHub API ──
function ghRaw(endpoint) {
  const path = endpoint ? `repos/${REPO}/${endpoint}` : `repos/${REPO}`;
  try {
    return JSON.parse(
      execSync(`gh api "${path}"`, { encoding: 'utf8', timeout: 15000 })
    );
  } catch (e) {
    console.error(`gh api ${path} failed:`, e.message?.split('\n')[0]);
    return null;
  }
}

function ghPaginated(endpoint) {
  try {
    return JSON.parse(
      execSync(`gh api "${endpoint}" --paginate`, { encoding: 'utf8', timeout: 30000 })
    );
  } catch {
    return null;
  }
}

// ── History tracking ──
function loadHistory() {
  if (existsSync(HISTORY_FILE)) {
    return JSON.parse(readFileSync(HISTORY_FILE, 'utf8'));
  }
  return { cumulative_views: 0, cumulative_clones: 0, tracked_days: [], first_tracked: null };
}

function saveHistory(history) {
  writeFileSync(HISTORY_FILE, JSON.stringify(history, null, 2));
}

function updateHistory(history, views, clones) {
  const today = new Date().toISOString().slice(0, 10);
  if (!history.first_tracked) history.first_tracked = today;

  // Add any new days from the 14-day windows that we haven't tracked yet
  for (const day of (views?.views || [])) {
    const date = day.timestamp.slice(0, 10);
    if (!history.tracked_days.includes(date)) {
      history.tracked_days.push(date);
      history.cumulative_views += day.uniques;
    }
  }
  for (const day of (clones?.clones || [])) {
    const date = day.timestamp.slice(0, 10);
    const key = `clone_${date}`;
    if (!history.tracked_days.includes(key)) {
      history.tracked_days.push(key);
      history.cumulative_clones += day.uniques;
    }
  }

  // Keep tracked_days from growing unbounded (only need last 30 days for dedup)
  if (history.tracked_days.length > 60) {
    history.tracked_days = history.tracked_days.slice(-60);
  }

  return history;
}

// ── Fetch all data ──
const repo = ghRaw('');
const views = ghRaw('traffic/views');
const clones = ghRaw('traffic/clones');
const referrers = ghRaw('traffic/popular/referrers');
const popularPaths = ghRaw('traffic/popular/paths');

if (!repo) {
  console.error('Failed to fetch repo data');
  process.exit(1);
}

// Get total commits
let totalCommits = '?';
try {
  const header = execSync(
    `gh api "repos/${REPO}/commits?per_page=1" --include 2>&1 | grep -i "^link:"`,
    { encoding: 'utf8', timeout: 10000 }
  ).trim();
  const match = header.match(/page=(\d+)>; rel="last"/);
  if (match) totalCommits = match[1];
} catch {}

// Get total contributors
let totalContributors = '?';
try {
  const contribs = JSON.parse(
    execSync(`gh api "repos/${REPO}/contributors"`, { encoding: 'utf8', timeout: 10000 })
  );
  totalContributors = contribs.length;
} catch {}

// Get PRs merged
let prsMerged = '?';
try {
  const prs = JSON.parse(
    execSync(`gh api "repos/${REPO}/pulls?state=closed&per_page=100"`, { encoding: 'utf8', timeout: 15000 })
  );
  prsMerged = prs.filter((p) => p.merged_at).length;
} catch {}

// Get Discord member count
let discordMembers = null;
try {
  const guildRes = await fetch(`https://discord.com/api/v10/guilds/${process.env.DISCORD_GUILD_ID}?with_counts=true`, {
    headers: { Authorization: `Bot ${BOT_TOKEN}` },
  });
  if (guildRes.ok) {
    const guild = await guildRes.json();
    discordMembers = guild.approximate_member_count;
  }
} catch {}

// Update cumulative tracking
let history = loadHistory();
history = updateHistory(history, views, clones);
saveHistory(history);

// Yesterday's snapshot
const yesterdayViews = views?.views?.slice(-1)[0];
const yesterdayClones = clones?.clones?.slice(-1)[0];
const yesterdayDate = yesterdayViews?.timestamp?.slice(0, 10) || 'recent';

// ── Bar chart for 7-day views ──
function barChart(data, key = 'uniques') {
  if (!data || data.length < 2) return '';
  const days = data.slice(-7);
  const max = Math.max(...days.map((d) => d[key]));
  if (max === 0) return '';
  const bars = ['_', '\u2581', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588'];
  return days
    .map((d) => {
      const level = Math.round((d[key] / max) * (bars.length - 1));
      return bars[level];
    })
    .join('');
}

const viewChart = barChart(views?.views);
const cloneChart = barChart(clones?.clones);

// ── Format referrers ──
const topReferrers =
  (referrers || [])
    .slice(0, 4)
    .map((r) => `\`${r.referrer}\` ${r.uniques}`)
    .join(' · ') || '_none_';

// ── Days since public launch ──
// Repo created Feb 19, but first public star was March 13. That's the real launch.
const PUBLIC_LAUNCH = new Date('2026-03-13T00:00:00Z');
const daysSinceLaunch = Math.floor((Date.now() - PUBLIC_LAUNCH.getTime()) / 86400000);

// ── Build embed ──
const embed = {
  title: 'ALIVE -- GitHub Pulse',
  url: REPO_URL,
  color: BRAND_COLOR,
  description: `**${repo.stargazers_count}** stars · Day **${daysSinceLaunch}** since launch`,
  fields: [
    {
      name: `Yesterday (${yesterdayDate})`,
      value: `**${yesterdayViews?.uniques || 0}** visitors · **${yesterdayClones?.uniques || 0}** cloners`,
      inline: false,
    },
    {
      name: '14-Day Window',
      value: `**${views?.uniques || 0}** visitors · **${clones?.uniques || 0}** cloners`,
      inline: true,
    },
    {
      name: 'All-Time (tracked)',
      value: `**${history.cumulative_views}** visitors · **${history.cumulative_clones}** cloners`,
      inline: true,
    },
    {
      name: '7-Day Trend',
      value: `Visitors \`${viewChart}\`\nCloners  \`${cloneChart}\``,
      inline: false,
    },
    {
      name: 'Top Referrers',
      value: topReferrers,
      inline: true,
    },
    {
      name: 'Exploring',
      value: (popularPaths || [])
        .filter((p) => p.path !== `/${REPO}`)
        .slice(0, 3)
        .map((p) => `\`${p.path.replace(`/${REPO}/`, '')}\` ${p.uniques}`)
        .join(' · ') || '_none_',
      inline: true,
    },
    {
      name: 'Build Activity',
      value: `${prsMerged} PRs merged · ${totalCommits} commits · ${totalContributors} contributors`,
      inline: false,
    },
    ...(discordMembers ? [{
      name: 'Community',
      value: `**${discordMembers}** Discord members`,
      inline: false,
    }] : []),
  ],
  footer: {
    text: 'Context infrastructure for builders. Star if you ship.',
  },
  timestamp: new Date().toISOString(),
};

// ── CTA buttons ──
const components = [
  {
    type: 1,
    components: [
      {
        type: 2,
        style: 5,
        label: 'Star on GitHub',
        url: REPO_URL,
      },
      {
        type: 2,
        style: 5,
        label: 'Install ALIVE',
        url: 'https://alivecontext.com',
      },
    ],
  },
];

// ── Post to Discord ──
async function post() {
  const res = await fetch(`https://discord.com/api/v10/channels/${CHANNEL_ID}/messages`, {
    method: 'POST',
    headers: {
      Authorization: `Bot ${BOT_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ embeds: [embed], components }),
  });

  if (!res.ok) {
    const err = await res.text();
    console.error(`Discord API error ${res.status}: ${err}`);
    process.exit(1);
  }

  const msg = await res.json();
  console.log(`Posted to #github-feed -- ${msg.id}`);
}

post();
