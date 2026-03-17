const express = require('express');
const { WebSocketServer } = require('ws');
const path = require('path');
const http = require('http');
const fs = require('fs');
const { spawn } = require('child_process');
const initSqlJs = require('sql.js');

const PORT = process.env.PORT || 23714;
const DB_PATH = path.join(__dirname, '..', 'events.db');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

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

app.get('/api/tasks', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const rows = dbAll(db, 'SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50');
    res.json(rows.map(r => ({ ...r, spec: JSON.parse(r.spec || '{}') })));
  } catch {
    res.json([]);
  } finally {
    db.close();
  }
});

app.get('/api/tasks/:id', (req, res) => {
  const db = getDb();
  if (!db) return res.status(404).json({ error: 'db not available' });
  try {
    const rows = dbAll(db, 'SELECT * FROM tasks WHERE id = ?', [req.params.id]);
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    const r = rows[0];
    res.json({ ...r, spec: JSON.parse(r.spec || '{}') });
  } catch {
    res.status(404).json({ error: 'not found' });
  } finally {
    db.close();
  }
});

app.post('/api/tasks', (req, res) => {
  const { action, reason, priority, spec } = req.body || {};
  if (!action) return res.status(400).json({ error: 'action is required' });

  const payload = JSON.stringify({ action, reason: reason || '', priority: priority || 'medium', spec: spec || {} });
  const proc = spawn('python3', ['-c', `
import sys, json
sys.path.insert(0, '/orchestrator')
from src.storage.events_db import EventsDB
db = EventsDB('/orchestrator/events.db')
data = json.loads(sys.stdin.read())
tid = db.create_task(
    action=data['action'],
    reason=data.get('reason', ''),
    priority=data.get('priority', 'medium'),
    spec=data.get('spec', {}),
    source='manual'
)
print(json.dumps({'id': tid}))
  `]);

  proc.stdin.write(payload);
  proc.stdin.end();

  let out = '';
  let err = '';
  proc.stdout.on('data', d => { out += d; });
  proc.stderr.on('data', d => { err += d; });
  proc.on('close', code => {
    try {
      res.json(JSON.parse(out));
    } catch {
      res.status(500).json({ error: err || out || 'unknown error' });
    }
  });
});

app.post('/api/tasks/:id/approve', (req, res) => {
  const taskId = parseInt(req.params.id);
  if (isNaN(taskId)) return res.status(400).json({ error: 'invalid task id' });

  const proc = spawn('python3', ['/orchestrator/src/governor_cli.py', 'approve', String(taskId)]);
  let out = '';
  let err = '';
  proc.stdout.on('data', d => { out += d; });
  proc.stderr.on('data', d => { err += d; });
  proc.on('close', () => {
    try {
      const result = JSON.parse(out);
      if (result.error) return res.status(400).json(result);
      broadcast({ type: 'task_update', task: result });
      res.json(result);
    } catch {
      res.status(500).json({ error: err || out || 'unknown error' });
    }
  });
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

app.get('/api/schedule-status', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ next_collectors: null, next_analysis: null, running_task: false });
  try {
    const statusRows = dbAll(db, "SELECT key, value FROM scheduler_status");
    const status = Object.fromEntries(statusRows.map(r => [r.key, r.value]));
    const running = dbAll(db, "SELECT id FROM tasks WHERE status = 'running' LIMIT 1");
    res.json({
      next_collectors: status.next_collectors || null,
      next_analysis: status.next_analysis || null,
      running_task: running.length > 0
    });
  } catch {
    res.json({ next_collectors: null, next_analysis: null, running_task: false });
  } finally {
    db.close();
  }
});

app.get('/api/profile-analysis', (req, res) => {
  const db = getDb();
  if (!db) return res.json({});
  try {
    const row = dbAll(db, "SELECT data_json FROM profile_analysis ORDER BY id DESC LIMIT 1");
    res.json(row[0] ? JSON.parse(row[0].data_json) : {});
  } catch { res.json({}); }
  finally { db.close(); }
});

app.post('/api/profile-analysis/refresh', (req, res) => {
  res.status(202).json({ status: 'accepted' });

  const proc = spawn('python3', ['/orchestrator/src/profile_analyst_cli.py', 'periodic']);

  const timer = setTimeout(() => {
    proc.kill();
    broadcast({ type: 'profile_analysis_error', error: 'timeout' });
  }, 60000);

  let out = '';
  proc.stdout.on('data', d => { out += d; });
  proc.stderr.on('data', () => {}); // drain stderr to prevent buffer stall
  proc.on('close', () => {
    clearTimeout(timer);
    try {
      const result = JSON.parse(out);
      if (result.error) {
        broadcast({ type: 'profile_analysis_error', error: result.error });
      } else {
        broadcast({ type: 'profile_analysis_done' });
      }
    } catch {
      broadcast({ type: 'profile_analysis_error', error: 'parse error' });
    }
  });
});

app.get('/api/events/heatmap', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const days = parseInt(req.query.days) || 60;
  const since = new Date(Date.now() - days * 86400000).toISOString();
  try {
    const rows = dbAll(db,
      "SELECT DATE(occurred_at) as day, COUNT(*) as count FROM events WHERE occurred_at >= ? GROUP BY DATE(occurred_at) ORDER BY day ASC",
      [since]
    );
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});

app.get('/api/summaries', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const rows = dbAll(db,
      "SELECT date, summary FROM daily_summaries ORDER BY date DESC LIMIT 7"
    );
    res.json(rows.map(r => {
      try { return { date: r.date, ...JSON.parse(r.summary) }; }
      catch { return { date: r.date, summary: r.summary }; }
    }));
  } catch { res.json([]); }
  finally { db.close(); }
});

app.get('/api/debts', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const rows = dbAll(db,
      `SELECT * FROM attention_debts
       ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
       created_at DESC LIMIT 50`
    );
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});

app.get('/api/stats/categories', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const days = parseInt(req.query.days) || 7;
  const since = new Date(Date.now() - days * 86400000).toISOString();
  try {
    const rows = dbAll(db,
      "SELECT category, SUM(duration_minutes) as total_min, COUNT(*) as count FROM events WHERE occurred_at >= ? GROUP BY category ORDER BY total_min DESC",
      [since]
    );
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});

// SSE log stream: polls DB every 1s, pushes new log rows since last_id
app.get('/api/logs', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  let lastId = 0;

  // Send initial backlog (last 50 logs)
  const initDb = getDb();
  if (initDb) {
    try {
      const rows = dbAll(initDb, 'SELECT * FROM logs ORDER BY id DESC LIMIT 50').reverse();
      if (rows.length) {
        lastId = rows[rows.length - 1].id;
        res.write(`data: ${JSON.stringify({ type: 'backlog', logs: rows })}\n\n`);
      }
    } catch { /* logs table may not exist yet */ }
    finally { initDb.close(); }
  }

  const interval = setInterval(() => {
    const db = getDb();
    if (!db) return;
    try {
      const rows = dbAll(db, 'SELECT * FROM logs WHERE id > ? ORDER BY id ASC LIMIT 50', [lastId]);
      if (rows.length) {
        lastId = rows[rows.length - 1].id;
        res.write(`data: ${JSON.stringify({ type: 'append', logs: rows })}\n\n`);
      }
    } catch { /* ignore */ }
    finally { db.close(); }
  }, 1000);

  req.on('close', () => clearInterval(interval));
});

// ── TTS: SOUL 的声音 ──
const TTS_HOST = process.env.TTS_HOST || 'http://host.docker.internal:23715';
let _ttsWarmed = false;
let _todayVoice = null;
let _todayVoiceDate = null;

function getDailyVoice(callback) {
  const today = new Date().toISOString().slice(0, 10);
  if (_todayVoice && _todayVoiceDate === today) return callback(_todayVoice);

  const httpLib = require('http');
  const { URL } = require('url');
  const url = new URL(`${TTS_HOST}/v1/references/list`);
  const req = httpLib.get({ hostname: url.hostname, port: url.port, path: url.pathname, headers: { 'Accept': 'application/json' } }, (res) => {
    let data = '';
    res.on('data', d => { data += d; });
    res.on('end', () => {
      try {
        const ids = JSON.parse(data).reference_ids || [];
        if (ids.length) {
          // Seed by date for daily consistency
          const seed = today.split('-').reduce((a, b) => a + parseInt(b), 0);
          _todayVoice = ids[seed % ids.length];
          _todayVoiceDate = today;
          console.log(`Daily voice: ${_todayVoice} (from ${ids.length} available)`);
        }
      } catch {}
      callback(_todayVoice);
    });
  });
  req.on('error', () => callback(null));
}

const TTS_SPEED = parseFloat(process.env.TTS_SPEED || '1.3');

function ttsPostProcess(buf, callback) {
  if (TTS_SPEED === 1.0) return callback(buf);
  const { execFile } = require('child_process');
  const tmp = path.join(require('os').tmpdir(), `tts_raw_${Date.now()}.mp3`);
  fs.writeFileSync(tmp, buf);
  execFile('ffmpeg', ['-y', '-i', tmp, '-filter:a', `atempo=${TTS_SPEED}`, '-f', 'mp3', 'pipe:1'], { encoding: 'buffer', maxBuffer: 10 * 1024 * 1024 }, (err, stdout) => {
    try { fs.unlinkSync(tmp); } catch {}
    if (err) return callback(buf); // fallback to raw on error
    callback(stdout);
  });
}

function ttsGenerate(text, reference_id, onDone, onError) {
  const httpLib = require('http');
  const { URL } = require('url');
  const url = new URL(`${TTS_HOST}/v1/tts`);

  const payload = JSON.stringify({
    text,
    reference_id: reference_id || null,
    normalize: false,
    temperature: 0.8,
    format: 'mp3',
  });

  const ttsReq = httpLib.request({
    hostname: url.hostname,
    port: url.port,
    path: url.pathname,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    timeout: 120000,
  }, (ttsRes) => {
    const chunks = [];
    ttsRes.on('data', (chunk) => chunks.push(chunk));
    ttsRes.on('end', () => {
      const raw = Buffer.concat(chunks);
      ttsPostProcess(raw, (processed) => onDone(processed));
    });
  });

  ttsReq.on('error', onError);
  ttsReq.write(payload);
  ttsReq.end();
}

// Warmup: silent TTS on startup to trigger torch.compile before user clicks
setTimeout(() => {
  getDailyVoice((voice) => {
    ttsGenerate('。', voice,
      () => { _ttsWarmed = true; console.log(`TTS warmup complete (voice: ${voice})`); },
      () => { console.log('TTS warmup failed (service may not be ready)'); }
    );
  });
}, 5000);

app.post('/api/tts', async (req, res) => {
  const { text } = req.body || {};
  if (!text) return res.status(400).json({ error: 'text is required' });

  res.json({ ok: true, status: 'generating' });
  broadcast({ type: 'tts_status', status: _ttsWarmed ? 'generating' : 'compiling' });

  try {
    getDailyVoice((voice) => {
      ttsGenerate(text, voice,
        (buf) => {
          _ttsWarmed = true;
          const b64 = buf.toString('base64');
          broadcast({ type: 'soul_voice', audio: b64, mime: 'audio/mpeg' });
        },
        (e) => {
          broadcast({ type: 'tts_status', status: 'error', error: e.message });
        }
      );
    });
  } catch (e) {
    broadcast({ type: 'tts_status', status: 'error', error: e.message });
  }
});

app.get('/api/tts/health', async (req, res) => {
  try {
    const resp = await fetch(`${TTS_HOST}/v1/health`);
    const data = await resp.json();
    res.json(data);
  } catch {
    res.json({ status: 'unavailable' });
  }
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
