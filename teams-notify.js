/**
 * teams-notify.js -- Teams Adaptive Card sender for implementation console.
 *
 * Sends color-coded Adaptive Cards (v1.4) to a Microsoft Teams Incoming Webhook.
 * Supports FDE @mentions, OneDrive report links, and inline metric summaries.
 * Rate-limited to 1 request/second.
 *
 * Usage:
 *   const { sendWelcomeDraft, sendStalledAlert, sendMorningBriefing } = require('./teams-notify');
 */

require('dotenv').config();
const https = require('https');
const path = require('path');
const fs = require('fs');

const WEBHOOK_URL = process.env.TEAMS_IMPLEMENTATION_WEBHOOK_URL;

// Load FDE email mapping from config
const CONFIG_PATH = path.join(__dirname, 'implementation-config.json');
const CONFIG = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
const FDE_EMAILS = CONFIG.fde_emails || {};

// -- Rate limiter -------------------------------------------------------------
let lastSendTime = 0;
const MIN_INTERVAL_MS = 1000;

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// -- Colors -------------------------------------------------------------------
const COLORS = {
  green:  'good',      // ready / complete
  blue:   'accent',    // in-progress
  amber:  'warning',   // reminder
  red:    'attention', // stalled / alert
};

// -- Low-level sender ---------------------------------------------------------

async function sendCard(card) {
  if (!WEBHOOK_URL) {
    throw new Error(
      'TEAMS_IMPLEMENTATION_WEBHOOK_URL is not set. Add it to .env.'
    );
  }

  const now = Date.now();
  const elapsed = now - lastSendTime;
  if (elapsed < MIN_INTERVAL_MS) {
    await sleep(MIN_INTERVAL_MS - elapsed);
  }
  lastSendTime = Date.now();

  const payload = JSON.stringify({
    type: 'message',
    attachments: [
      {
        contentType: 'application/vnd.microsoft.card.adaptive',
        contentUrl: null,
        content: {
          $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
          type: 'AdaptiveCard',
          version: '1.4',
          ...card,
        },
      },
    ],
  });

  return new Promise((resolve, reject) => {
    const parsed = new URL(WEBHOOK_URL);
    const options = {
      hostname: parsed.hostname,
      port: 443,
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
    };

    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => {
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, body });
      });
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

// -- Helpers ------------------------------------------------------------------

function headerContainer(text, style) {
  return {
    type: 'Container',
    style,
    bleed: true,
    items: [
      {
        type: 'TextBlock',
        text,
        weight: 'bolder',
        size: 'medium',
        color: style === 'attention' ? 'attention' : 'default',
        wrap: true,
      },
    ],
    padding: 'default',
  };
}

function factSet(facts) {
  return {
    type: 'FactSet',
    facts: facts.filter(f => f.value != null).map(f => ({
      title: f.title,
      value: String(f.value),
    })),
  };
}

function actionOpenUrl(title, urlStr) {
  if (!urlStr) return null;
  return { type: 'Action.OpenUrl', title, url: urlStr };
}

function divider() {
  return { type: 'TextBlock', text: ' ', separator: true, spacing: 'small' };
}

/**
 * Build an @mention TextBlock for the assigned FDE.
 * Falls back to plain text if no email is available.
 */
function mentionBlock(fdeName, fdeEmail, contextText) {
  const name = fdeName || 'Unassigned';
  if (!fdeEmail) {
    const text = contextText
      ? `**Assigned FDE:** ${name} -- ${contextText}`
      : `**Assigned FDE:** ${name}`;
    return { type: 'TextBlock', text, wrap: true, size: 'small' };
  }
  const mentionTag = `<at>${name}</at>`;
  const text = contextText
    ? `**Assigned FDE:** ${mentionTag} -- ${contextText}`
    : `**Assigned FDE:** ${mentionTag}`;
  return {
    type: 'TextBlock',
    text,
    wrap: true,
    size: 'small',
    msteams: {
      entities: [{
        type: 'mention',
        text: mentionTag,
        mentioned: { id: fdeEmail, name },
      }],
    },
  };
}

/**
 * Resolve FDE name to email using the config lookup table.
 */
function resolveFdeEmail(fdeName) {
  return FDE_EMAILS[fdeName] || null;
}

/**
 * Convert a local relative path to a clickable OneDrive web URL.
 * Reuses the SharePoint URL pattern from find_wow_calls.py.
 */
function buildOnedriveUrl(localPath) {
  if (!localPath) return null;
  const normalized = localPath.replace(/\\/g, '/');
  const serverRel = `/personal/mike_guerin_hoai_com/Documents/${normalized}`;
  const base = 'https://vantaca-my.sharepoint.com/personal/mike_guerin_hoai_com';
  return `${base}/_layouts/15/onedrive.aspx?id=${encodeURIComponent(serverRel)}`;
}

// -- Card builders ------------------------------------------------------------

/**
 * Welcome draft email notification -- shows full email body in card.
 */
async function sendWelcomeDraft(customer, fdeName, fdeEmail, goLiveDate, emailBody, notionUrl) {
  const card = {
    body: [
      headerContainer(`Welcome Package Ready -- ${customer}`, COLORS.green),
      factSet([
        { title: 'Customer', value: customer },
        { title: 'Target Go-Live', value: goLiveDate },
      ]),
      mentionBlock(fdeName, fdeEmail),
      divider(),
      {
        type: 'TextBlock',
        text: 'Draft Email',
        weight: 'bolder',
        size: 'small',
      },
      {
        type: 'TextBlock',
        text: emailBody,
        wrap: true,
        size: 'small',
        fontType: 'monospace',
      },
    ],
    actions: [
      actionOpenUrl('Open in Notion', notionUrl),
    ].filter(Boolean),
  };
  return sendCard(card);
}

/**
 * AOP reminder -- prompts FDE to generate AOP before alignment call.
 */
async function sendAopReminder(customer, fdeName, fdeEmail, daysToAlignment, notionUrl) {
  const urgency = daysToAlignment <= 3 ? COLORS.red : COLORS.amber;
  const card = {
    body: [
      headerContainer(`AOP Reminder -- ${customer}`, urgency),
      factSet([
        { title: 'Customer', value: customer },
        { title: 'Days to Alignment Call', value: daysToAlignment },
      ]),
      mentionBlock(fdeName, fdeEmail, 'AOP needed before alignment call'),
      divider(),
      {
        type: 'TextBlock',
        text: 'Run `/generate-aop` to create the Agent Operating Procedure before the alignment call.',
        wrap: true,
        size: 'small',
      },
      {
        type: 'TextBlock',
        text: '```\n/generate-aop ' + customer + '\n```',
        wrap: true,
        fontType: 'monospace',
        size: 'small',
      },
    ],
    actions: [
      actionOpenUrl('Open in Notion', notionUrl),
    ].filter(Boolean),
  };
  return sendCard(card);
}

/**
 * Alignment deck generated notification with OneDrive link.
 */
async function sendDeckReady(customer, fdeName, fdeEmail, alignmentDate, daysAway, deckPath, notionUrl) {
  const deckUrl = buildOnedriveUrl(deckPath);
  const card = {
    body: [
      headerContainer(`Alignment Deck Ready -- ${customer}`, COLORS.green),
      factSet([
        { title: 'Customer', value: customer },
        { title: 'Alignment Date', value: alignmentDate },
        { title: 'Days Away', value: daysAway },
      ]),
      mentionBlock(fdeName, fdeEmail),
    ],
    actions: [
      actionOpenUrl('View Alignment Deck', deckUrl),
      actionOpenUrl('Open in Notion', notionUrl),
    ].filter(Boolean),
  };
  return sendCard(card);
}

/**
 * Analysis results notification with inline metrics and report link.
 */
async function sendAnalysisReady(customer, fdeName, fdeEmail, analysisType, metrics, reportPath, notionUrl) {
  const reportUrl = buildOnedriveUrl(reportPath);
  const metricFacts = Object.entries(metrics || {}).map(([title, value]) => ({
    title,
    value,
  }));

  const bodyItems = [
    headerContainer(`${analysisType} Analysis Complete -- ${customer}`, COLORS.blue),
    factSet([
      { title: 'Customer', value: customer },
      { title: 'Analysis Type', value: analysisType },
    ]),
  ];

  if (fdeEmail || fdeName) {
    bodyItems.push(mentionBlock(fdeName, fdeEmail));
  }

  if (metricFacts.length > 0) {
    bodyItems.push(divider());
    bodyItems.push({
      type: 'TextBlock',
      text: 'Metric Highlights',
      weight: 'bolder',
      size: 'small',
    });
    bodyItems.push(factSet(metricFacts));
  }

  const card = {
    body: bodyItems,
    actions: [
      actionOpenUrl('View Report', reportUrl),
      actionOpenUrl('Open in Notion', notionUrl),
    ].filter(Boolean),
  };
  return sendCard(card);
}

/**
 * Stalled customer alert -- red card with FDE @mention.
 */
async function sendStalledAlert(customer, stage, daysInStage, fdeName, fdeEmail, suggestedAction, notionUrl) {
  const card = {
    body: [
      headerContainer(`STALLED -- ${customer}`, COLORS.red),
      factSet([
        { title: 'Customer', value: customer },
        { title: 'Current Stage', value: stage },
        { title: 'Days in Stage', value: daysInStage },
      ]),
      mentionBlock(fdeName, fdeEmail, 'customer stalled'),
      divider(),
      {
        type: 'TextBlock',
        text: `Suggested Action: ${suggestedAction}`,
        wrap: true,
        weight: 'bolder',
        color: 'attention',
        size: 'small',
      },
    ],
    actions: [
      actionOpenUrl('Open in Notion', notionUrl),
    ].filter(Boolean),
  };
  return sendCard(card);
}

/**
 * Morning briefing -- daily pipeline summary card.
 */
async function sendMorningBriefing(date, pipelineCount, generatedToday, analysesDueTonight, dueThisWeek, stalledCustomers) {
  const stalledItems = (stalledCustomers || []).map(
    (c) => `- **${c.name}** -- ${c.stage} (${c.days}d)`
  ).join('\n');

  const card = {
    body: [
      headerContainer(`Morning Briefing -- ${date}`, COLORS.blue),
      factSet([
        { title: 'Pipeline Customers', value: pipelineCount },
        { title: 'Generated Today', value: generatedToday },
        { title: 'Analyses Due Tonight', value: analysesDueTonight },
        { title: 'Due This Week', value: dueThisWeek },
      ]),
    ],
    actions: [],
  };

  if (stalledItems) {
    card.body.push(divider());
    card.body.push({
      type: 'TextBlock',
      text: 'Stalled Customers',
      weight: 'bolder',
      color: 'attention',
      size: 'small',
    });
    card.body.push({
      type: 'TextBlock',
      text: stalledItems,
      wrap: true,
      size: 'small',
    });
  }

  return sendCard(card);
}

// -- Exports ------------------------------------------------------------------

module.exports = {
  sendCard,
  sendWelcomeDraft,
  sendAopReminder,
  sendDeckReady,
  sendAnalysisReady,
  sendStalledAlert,
  sendMorningBriefing,
  resolveFdeEmail,
  buildOnedriveUrl,
};

// -- CLI entry point ----------------------------------------------------------
// Called from check-triggers.py via subprocess:
//   node teams-notify.js --card-type welcome --data '{"customer":"Acme",...}'

if (require.main === module) {
  const args = process.argv.slice(2);
  const cardTypeIdx = args.indexOf('--card-type');
  const dataIdx = args.indexOf('--data');

  if (cardTypeIdx === -1 || dataIdx === -1) {
    console.error('Usage: node teams-notify.js --card-type <type> --data <json>');
    process.exit(1);
  }

  const cardType = args[cardTypeIdx + 1];
  const data = JSON.parse(args[dataIdx + 1]);

  // Resolve FDE email from config lookup (CLI callers pass name only)
  const fdeEmail = data.fde_email || resolveFdeEmail(data.fde);

  const DISPATCH = {
    welcome: (d) => sendWelcomeDraft(d.customer, d.fde, fdeEmail, d.go_live_date, d.email_body || '', d.notion_url || ''),
    aop_reminder: (d) => sendAopReminder(d.customer, d.fde, fdeEmail, d.days_to_alignment, d.notion_url || ''),
    deck_ready: (d) => sendDeckReady(d.customer, d.fde, fdeEmail, d.alignment_date, d.days_away, d.deck_path, d.notion_url || ''),
    analysis_result: (d) => sendAnalysisReady(d.customer, d.fde || '', fdeEmail, d.analysis_type, d.metrics || {}, d.report_path || '', d.notion_url || ''),
    stalled: (d) => sendStalledAlert(d.customer, d.stage, d.days_in_stage, d.fde, fdeEmail, d.suggested_action, d.notion_url || ''),
    morning_briefing: (d) => sendMorningBriefing(d.date, d.pipeline_count, d.generated_today, d.analyses_tonight, d.due_this_week, d.stalled_customers || []),
  };

  const handler = DISPATCH[cardType];
  if (!handler) {
    console.error(`Unknown card type: ${cardType}. Valid: ${Object.keys(DISPATCH).join(', ')}`);
    process.exit(1);
  }

  handler(data)
    .then((res) => {
      if (res.ok) {
        console.log(`OK (${res.status})`);
      } else {
        console.error(`Failed (${res.status}): ${res.body}`);
        process.exit(1);
      }
    })
    .catch((err) => {
      console.error(`Error: ${err.message}`);
      process.exit(1);
    });
}
