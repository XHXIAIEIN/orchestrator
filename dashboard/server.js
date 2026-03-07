const express = require('express');
const { WebSocketServer } = require('ws');
const path = require('path');
const http = require('http');
const fs = require('fs');
const initSqlJs = require('sql.js');

const PORT = process.env.PORT || 23714;
const DB_PATH = path.join(__dirname, '..', 'events.db');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.static(path.join(__dirname, 'public')));

let SQL = null;
initSqlJs().then(s => { SQL = s; });

function getDb() {
  if (!SQL || !fs.existsSync(DB_PATH)) return null;
  try {
    const buf = fs.readFileSync(DB_PATH);
    return new SQL.Database(buf);
  } catch { return null; }
}

function dbAll(db, sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

app.get('/api/summary', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ summaries: [], profile: {} });
  const summaries = dbAll(db, "SELECT * FROM daily_summaries ORDER BY date DESC LIMIT 7");
  const profileRow = dbAll(db, "SELECT profile_json FROM user_profile ORDER BY updated_at DESC LIMIT 1");
  db.close();
  res.json({
    summaries,
    profile: profileRow[0] ? JSON.parse(profileRow[0].profile_json) : {}
  });
});

app.get('/api/events', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const days = parseInt(req.query.days) || 7;
  const since = new Date(Date.now() - days * 86400000).toISOString();
  const events = dbAll(db,
    "SELECT source, category, title, duration_minutes, score, tags, occurred_at FROM events WHERE occurred_at >= ? ORDER BY occurred_at DESC LIMIT 200",
    [since]
  );
  db.close();
  res.json(events.map(e => ({ ...e, tags: JSON.parse(e.tags || '[]') })));
});

app.get('/api/insights', (req, res) => {
  const db = getDb();
  if (!db) return res.json({});
  const row = dbAll(db, "SELECT data_json FROM insights ORDER BY generated_at DESC LIMIT 1");
  db.close();
  res.json(row[0] ? JSON.parse(row[0].data_json) : {});
});

app.get('/api/stats', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ bySource: [], total: 0 });
  const bySource = dbAll(db,
    "SELECT source, COUNT(*) as count, SUM(duration_minutes) as total_min FROM events GROUP BY source"
  );
  const totalRow = dbAll(db, "SELECT COUNT(*) as count FROM events");
  db.close();
  res.json({ bySource, total: totalRow[0]?.count || 0 });
});

wss.on('connection', (ws) => {
  ws.send(JSON.stringify({ type: 'connected', message: 'Orchestrator Dashboard' }));
});

function broadcast(data) {
  wss.clients.forEach(client => {
    if (client.readyState === 1) client.send(JSON.stringify(data));
  });
}

server.listen(PORT, () => {
  console.log(`Dashboard running at http://localhost:${PORT}`);
});

module.exports = { broadcast };
