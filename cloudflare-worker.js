/**
 * HOAi Voice Implementation Console — Cloudflare Worker
 *
 * Proxies GitHub API calls so the PAT stays server-side.
 * Deploy to Cloudflare Workers and add GITHUB_TOKEN as a secret.
 *
 * Setup:
 *   1. wrangler deploy  (or paste in the CF dashboard)
 *   2. wrangler secret put GITHUB_TOKEN
 *      Paste a fine-grained PAT with Contents: Read & Write on this repo.
 *
 * Endpoints:
 *   POST /save       { data, authorName, authorEmail }  → commit data.json
 *   GET  /history                                       → list commits
 *   GET  /version?sha=<sha>                             → data at that commit
 */

const GITHUB_REPO = 'mikeguerinhoai/hoai-voice-implementation-console';
const GITHUB_FILE = 'docs/data.json';
const ALLOWED_ORIGIN = 'https://mikeguerinhoai.github.io';

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return preflight();

    const origin = request.headers.get('Origin') || '';
    if (origin && origin !== ALLOWED_ORIGIN) {
      return new Response('Forbidden', { status: 403 });
    }

    const url = new URL(request.url);
    try {
      if (url.pathname === '/save'    && request.method === 'POST') return await handleSave(request, env);
      if (url.pathname === '/history' && request.method === 'GET')  return await handleHistory(env);
      if (url.pathname === '/version' && request.method === 'GET')  return await handleVersion(url, env);
      return json({ error: 'Not found' }, 404);
    } catch (e) {
      return json({ error: e.message }, 500);
    }
  },
};

// -- Handlers -----------------------------------------------------------------

async function handleSave(request, env) {
  const { data, authorName, authorEmail } = await request.json();

  const fileInfo = await ghJson(`/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, env);
  const content  = toBase64(JSON.stringify(data, null, 2));
  const ts       = new Date().toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const name     = (authorName  || 'HOAi Team').trim();
  const email    = (authorEmail || 'team@hoai.com').trim();

  const put = await ghFetch(`/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, env, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message:   `Save: ${ts} (${name})`,
      content,
      sha:       fileInfo.sha,
      committer: { name, email },
    }),
  });

  if (!put.ok) {
    const err = await put.json().catch(() => ({}));
    throw new Error(err.message || `GitHub ${put.status}`);
  }
  return json({ ok: true });
}

async function handleHistory(env) {
  const commits = await ghJson(
    `/repos/${GITHUB_REPO}/commits?path=${GITHUB_FILE}&per_page=40`,
    env,
  );
  return json(commits);
}

async function handleVersion(url, env) {
  const sha = url.searchParams.get('sha');
  if (!sha) throw new Error('sha param required');
  const file = await ghJson(`/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}?ref=${sha}`, env);
  const data = JSON.parse(fromBase64(file.content));
  return json(data);
}

// -- Helpers ------------------------------------------------------------------

async function ghFetch(path, env, opts = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...opts,
    headers: {
      'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(opts.headers || {}),
    },
  });
}

async function ghJson(path, env, opts = {}) {
  const r = await ghFetch(path, env, opts);
  if (!r.ok) throw new Error(`GitHub API ${r.status} on ${path}`);
  return r.json();
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    },
  });
}

function preflight() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin':  ALLOWED_ORIGIN,
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}

function toBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  bytes.forEach(b => binary += String.fromCharCode(b));
  return btoa(binary);
}

function fromBase64(b64) {
  const binary = atob(b64.replace(/\n/g, ''));
  const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
