/**
 * Generate Welcome Package email draft and post to Teams.
 *
 * Usage:
 *   node implementation-console/generate-welcome-package.js <company-name> [--post-teams]
 *   node implementation-console/generate-welcome-package.js --from-json <path> [--post-teams]
 *
 * When called from the trigger engine, uses --from-json with customer data.
 * When called standalone, reads from Notion via implementation-data.json.
 */

require('dotenv').config();
const fs = require('fs');
const path = require('path');

const SCRIPT_DIR = __dirname;
const ROOT_DIR = path.dirname(SCRIPT_DIR);
const CONFIG = JSON.parse(
  fs.readFileSync(path.join(SCRIPT_DIR, 'implementation-config.json'), 'utf8')
);

// ── Date Helpers ────────────────────────────────────────────────────────────
function addBusinessDays(dateStr, days) {
  const d = new Date(dateStr + 'T12:00:00');
  let added = 0;
  while (added < days) {
    d.setDate(d.getDate() + 1);
    const dow = d.getDay();
    if (dow !== 0 && dow !== 6) added++;
  }
  return d.toISOString().split('T')[0];
}

function formatDate(dateStr) {
  if (!dateStr) return 'TBD';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

function getFirstOfNextMonth(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  d.setMonth(d.getMonth() + 1);
  d.setDate(1);
  return d.toISOString().split('T')[0];
}

function getNextBusinessDay(dateStr) {
  return addBusinessDays(dateStr, 1);
}

function getWeekOf(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  // Find Monday of that week
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  const monday = new Date(d);
  monday.setDate(diff);
  return formatDate(monday.toISOString().split('T')[0]);
}

// ── Template Rendering ──────────────────────────────────────────────────────
function renderTemplate(templateStr, vars) {
  return templateStr.replace(/\{\{(\w+)\}\}/g, (match, key) => {
    return vars[key] !== undefined ? vars[key] : match;
  });
}

function generateWelcomeEmail(customer) {
  const wpDate = customer.welcome_package_date;
  if (!wpDate) {
    console.error(`  ERROR: No Welcome Package date for ${customer.company_name}`);
    return null;
  }

  const offsets = CONFIG.timeline_offsets;
  const activationDate = getFirstOfNextMonth(wpDate);

  const vars = {
    customer_contact_name: '[Contact Name]',
    fde_name: customer.fde || '[FDE Name]',
    company_name: customer.company_name,
    activation_date: formatDate(activationDate),
    questionnaire_deadline: formatDate(addBusinessDays(wpDate, offsets.questionnaire_deadline_days)),
    alignment_call_deadline: formatDate(addBusinessDays(wpDate, offsets.alignment_call_days)),
    internal_testing_week: getWeekOf(addBusinessDays(wpDate, offsets.customer_testing_days)),
    activation_day: formatDate(activationDate),
    day_two_date: formatDate(getNextBusinessDay(activationDate)),
    day_three_date: formatDate(addBusinessDays(activationDate, 2)),
    questionnaire_link: CONFIG.questionnaire_link,
  };

  // Read template
  const templatePath = path.join(SCRIPT_DIR, 'templates', 'welcome-email.md');
  const template = fs.readFileSync(templatePath, 'utf8');
  const emailBody = renderTemplate(template, vars);

  return {
    company_name: customer.company_name,
    fde_name: vars.fde_name,
    go_live_date: activationDate,
    go_live_formatted: vars.activation_date,
    email_body: emailBody,
    notion_url: customer.notion_url || '',
    vars,
  };
}

// ── OneDrive Folder Scaffold ────────────────────────────────────────────────
function scaffoldFolder(companyName) {
  const folderPath = path.join(
    ROOT_DIR,
    CONFIG.onedrive_base,
    companyName
  );
  if (!fs.existsSync(folderPath)) {
    fs.mkdirSync(folderPath, { recursive: true });
    console.log(`  ✓ Created OneDrive folder: ${folderPath}`);
  } else {
    console.log(`  ○ OneDrive folder exists: ${folderPath}`);
  }
  return folderPath;
}

// ── Teams Posting ───────────────────────────────────────────────────────────
async function postToTeams(result) {
  let teamsNotify;
  try {
    teamsNotify = require(path.join(SCRIPT_DIR, 'teams-notify.js'));
  } catch (e) {
    console.log('  WARN: teams-notify.js not loaded — skipping Teams post');
    return;
  }

  await teamsNotify.sendWelcomeDraft(
    result.company_name,
    result.fde_name,
    result.go_live_formatted,
    result.email_body,
    result.notion_url
  );
}

// ── Main ────────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2);
  const postTeams = args.includes('--post-teams');
  const fromJsonIdx = args.indexOf('--from-json');

  let customer;

  if (fromJsonIdx !== -1) {
    // Read customer data from JSON file
    const jsonPath = args[fromJsonIdx + 1];
    customer = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  } else {
    // Read from implementation-data.json by company name
    const companyName = args.filter(a => !a.startsWith('--'))[0];
    if (!companyName) {
      console.log('Usage: node generate-welcome-package.js <company-name> [--post-teams]');
      console.log('       node generate-welcome-package.js --from-json <path> [--post-teams]');
      process.exit(1);
    }

    const dataPath = path.join(SCRIPT_DIR, 'data', 'implementation-data.json');
    if (!fs.existsSync(dataPath)) {
      console.error(`  ERROR: ${dataPath} not found. Run fetch-implementation-data.py first.`);
      process.exit(1);
    }

    const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
    customer = data.customers.find(
      c => c.company_name.toLowerCase().includes(companyName.toLowerCase())
    );

    if (!customer) {
      console.error(`  ERROR: Customer "${companyName}" not found in implementation data.`);
      process.exit(1);
    }
  }

  console.log('='.repeat(60));
  console.log('HOAi Implementation Console — Welcome Package Generator');
  console.log(`  Customer: ${customer.company_name}`);
  console.log(`  Welcome Package Date: ${customer.welcome_package_date || 'NOT SET'}`);
  console.log('='.repeat(60));

  // Generate email
  const result = generateWelcomeEmail(customer);
  if (!result) process.exit(1);

  console.log(`\n  FDE: ${result.fde_name}`);
  console.log(`  Go-Live: ${result.go_live_formatted}`);

  // Scaffold OneDrive folder
  scaffoldFolder(customer.company_name);

  // Write email body to file for review
  const outputDir = path.join(SCRIPT_DIR, 'data');
  const outputPath = path.join(outputDir, `welcome_${customer.company_name.replace(/[^a-zA-Z0-9]/g, '_')}.md`);
  fs.writeFileSync(outputPath, result.email_body, 'utf8');
  console.log(`\n  Email draft: ${outputPath}`);

  // Post to Teams
  if (postTeams) {
    console.log('\n  Posting to Teams...');
    await postToTeams(result);
    console.log('  ✓ Posted to Teams');
  } else {
    console.log('\n  Use --post-teams to send to Teams channel');
  }

  // Print preview
  console.log('\n' + '─'.repeat(60));
  console.log('EMAIL PREVIEW:');
  console.log('─'.repeat(60));
  console.log(result.email_body.substring(0, 1000));
  if (result.email_body.length > 1000) {
    console.log(`\n  ... (${result.email_body.length} chars total)`);
  }
  console.log('─'.repeat(60));
}

main().catch(err => {
  console.error('ERROR:', err.message);
  process.exit(1);
});
