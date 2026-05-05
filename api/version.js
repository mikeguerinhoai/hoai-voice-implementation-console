export default async function handler(req, res) {
  const { sha } = req.query;
  if (!sha) return res.status(400).json({ error: 'sha param required' });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN not configured' });

  const r = await fetch(
    `https://api.github.com/repos/mikeguerinhoai/hoai-voice-implementation-console/contents/docs/data.json?ref=${sha}`,
    { headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' } },
  );
  if (!r.ok) return res.status(502).json({ error: `GitHub ${r.status}` });
  const file = await r.json();
  res.json(JSON.parse(Buffer.from(file.content, 'base64').toString('utf8')));
}
