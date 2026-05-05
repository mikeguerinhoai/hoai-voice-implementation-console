export default async function handler(req, res) {
  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'GITHUB_TOKEN not configured' });

  const r = await fetch(
    'https://api.github.com/repos/mikeguerinhoai/hoai-voice-implementation-console/commits?path=docs/data.json&per_page=40',
    { headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' } },
  );
  if (!r.ok) return res.status(502).json({ error: `GitHub ${r.status}` });
  res.json(await r.json());
}
