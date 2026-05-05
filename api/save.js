const REPO = 'mikeguerinhoai/hoai-voice-implementation-console';
const FILE = 'docs/data.json';

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  const { data, authorName, authorEmail } = req.body;
  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN not configured' });

  const getR = await ghFetch(`/repos/${REPO}/contents/${FILE}`, token);
  if (!getR.ok) return res.status(502).json({ error: `GitHub ${getR.status}` });
  const { sha } = await getR.json();

  const ts   = new Date().toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const name  = (authorName  || 'HOAi Team').trim();
  const email = (authorEmail || 'team@hoai.com').trim();

  const putR = await ghFetch(`/repos/${REPO}/contents/${FILE}`, token, {
    method: 'PUT',
    body: JSON.stringify({
      message:   `Save: ${ts} (${name})`,
      content:   Buffer.from(JSON.stringify(data, null, 2)).toString('base64'),
      sha,
      committer: { name, email },
    }),
  });

  if (!putR.ok) {
    const e = await putR.json().catch(() => ({}));
    return res.status(502).json({ error: e.message || `GitHub ${putR.status}` });
  }
  res.json({ ok: true });
}

async function ghFetch(path, token, opts = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
}
