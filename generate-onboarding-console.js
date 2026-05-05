#!/usr/bin/env node
/**
 * Onboarding Console — Dashboard Generator
 *
 * Reads data/implementation-data.json and copies template + data.json to OneDrive.
 * The HTML is a clean template (no embedded data) — it loads data.json via fetch().
 */

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const HOME = process.env.USERPROFILE || process.env.HOME;
const DATA_PATH = path.join(ROOT, 'data', 'implementation-data.json');
const TEMPLATE_PATH = path.join(ROOT, 'onboarding-template.html');
const OUTPUT_DIR = path.join(HOME, 'OneDrive - Vantaca, LLC', 'HOAi - Documents', 'Voice', 'Implementation Console');
const SNAPSHOT_DIR = path.join(OUTPUT_DIR, 'snapshots');

function main() {
  console.log('[onboarding-console] Starting...');

  if (!fs.existsSync(DATA_PATH)) {
    console.error(`ERROR: ${DATA_PATH} not found.`);
    console.error('  Run: npm run onboarding-console:notion  (to fetch from Notion)');
    console.error('  Or manually place data in implementation-console/data/implementation-data.json');
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(DATA_PATH, 'utf8'));
  const html = fs.readFileSync(TEMPLATE_PATH, 'utf8');
  const dataJson = JSON.stringify(data, null, 0);

  fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });
  const datestamp = data.date || new Date().toISOString().slice(0, 10);

  // Write latest
  const latestHtml = path.join(OUTPUT_DIR, 'latest.html');
  const latestData = path.join(OUTPUT_DIR, 'data.json');
  fs.writeFileSync(latestHtml, html, 'utf8');
  fs.writeFileSync(latestData, dataJson, 'utf8');

  // Write snapshot
  const snapHtml = path.join(SNAPSHOT_DIR, `onboarding-console-${datestamp}.html`);
  const snapData = path.join(SNAPSHOT_DIR, `data-${datestamp}.json`);
  fs.writeFileSync(snapHtml, html, 'utf8');
  fs.writeFileSync(snapData, dataJson, 'utf8');

  const htmlSize = (Buffer.byteLength(html) / 1024).toFixed(0);
  const dataSize = (Buffer.byteLength(dataJson) / 1024).toFixed(0);
  console.log(`  -> ${latestHtml} (${htmlSize} KB)`);
  console.log(`  -> ${latestData} (${dataSize} KB)`);
  console.log(`  -> ${snapHtml}`);
  console.log(`  ${data.customer_count} customers`);
  console.log('[onboarding-console] Done.');
}

main();
