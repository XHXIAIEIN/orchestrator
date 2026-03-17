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

app.get('/api/profile-analysis/history', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const rows = dbAll(db, "SELECT generated_at, data_json FROM profile_analysis ORDER BY id DESC LIMIT 30");
    const voiceLog = _loadVoiceLog();
    const items = rows.map(r => {
      try {
        const d = JSON.parse(r.data_json);
        const dateKey = (r.generated_at || '').slice(0, 10);
        return { date: r.generated_at, commentary: d.commentary || '', daily_note: d.daily_note || '', voice: voiceLog[dateKey] || null };
      } catch { return null; }
    }).filter(r => r && (r.commentary || r.daily_note));
    res.json(items);
  } catch { res.json([]); }
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
const VOICE_LOG_PATH = path.join(__dirname, '..', 'voice_log.json');

function _loadVoiceLog() {
  try { return JSON.parse(fs.readFileSync(VOICE_LOG_PATH, 'utf8')); } catch { return {}; }
}
function _saveVoiceLog(log) {
  try { fs.writeFileSync(VOICE_LOG_PATH, JSON.stringify(log, null, 2)); } catch {}
}
function getVoiceForDate(date) { return _loadVoiceLog()[date] || null; }

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
          const seed = today.split('-').reduce((a, b) => a + parseInt(b), 0);
          _todayVoice = ids[seed % ids.length];
          _todayVoiceDate = today;
          // Persist to voice log
          const log = _loadVoiceLog();
          if (!log[today]) { log[today] = _todayVoice; _saveVoiceLog(log); }
          console.log(`Daily voice: ${_todayVoice} (from ${ids.length} available)`);
        }
      } catch {}
      callback(_todayVoice);
    });
  });
  req.on('error', () => callback(null));
}

const TTS_SILENCE_MS = parseInt(process.env.TTS_SILENCE_MS || '350');

function ttsPostProcess(buf, callback) {
  if (TTS_SILENCE_MS <= 0) return callback(buf);
  // No speed change — sentence splitting already provides natural rhythm
  callback(buf);
}

function ttsSingleRequest(text, reference_id, onDone, onError) {
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
    ttsRes.on('end', () => onDone(Buffer.concat(chunks)));
  });

  ttsReq.on('error', onError);
  ttsReq.write(payload);
  ttsReq.end();
}

function ttsGenerate(text, reference_id, onDone, onError) {
  // Split by sentence-ending punctuation, filter empties
  const sentences = text.split(/(?<=[。！？.!?])\s*/).filter(s => s.trim());
  if (sentences.length <= 1) {
    return ttsSingleRequest(text, reference_id, onDone, onError);
  }

  // Generate each sentence, concat with silence gaps via ffmpeg
  const tmpDir = require('os').tmpdir();
  const ts = Date.now();
  let completed = 0;
  let failed = false;
  const sentFiles = [];

  sentences.forEach((sent, i) => {
    const outFile = path.join(tmpDir, `tts_sent_${ts}_${i}.mp3`);
    sentFiles.push(outFile);
    ttsSingleRequest(sent, reference_id, (buf) => {
      fs.writeFileSync(outFile, buf);
      completed++;
      if (completed === sentences.length && !failed) concatAll();
    }, (e) => {
      if (!failed) { failed = true; onError(e); }
    });
  });

  function concatAll() {
    // Build ffmpeg concat filter with silence between sentences
    const silenceFile = path.join(tmpDir, `tts_silence_${ts}.mp3`);
    const { execFile } = require('child_process');

    // Generate silence gap
    execFile('ffmpeg', ['-y', '-f', 'lavfi', '-i', `anullsrc=r=44100:cl=mono`, '-t', (TTS_SILENCE_MS / 1000).toFixed(3), '-f', 'mp3', silenceFile],
      { timeout: 5000 }, (err) => {
        // Build concat list: sent0 | silence | sent1 | silence | sent2 ...
        const concatParts = [];
        sentFiles.forEach((f, i) => {
          concatParts.push(f);
          if (i < sentFiles.length - 1) concatParts.push(silenceFile);
        });
        const concatStr = concatParts.join('|');
        const outFile = path.join(tmpDir, `tts_final_${ts}.mp3`);

        execFile('ffmpeg', ['-y', '-i', `concat:${concatStr}`, '-acodec', 'libmp3lame', '-q:a', '2', outFile],
          { timeout: 10000 }, (err2) => {
            // Cleanup temp files
            const cleanup = () => {
              sentFiles.forEach(f => { try { fs.unlinkSync(f); } catch {} });
              try { fs.unlinkSync(silenceFile); } catch {};
              try { fs.unlinkSync(outFile); } catch {};
            };

            if (err2) {
              // Fallback: just concat without silence
              const raw = Buffer.concat(sentFiles.map(f => fs.readFileSync(f)));
              cleanup();
              return onDone(raw);
            }

            const result = fs.readFileSync(outFile);
            cleanup();
            onDone(result);
          });
      });
  }
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

// Audio cache: avoid re-generating the same text+voice
const _ttsCache = new Map(); // key: text+voice -> base64
const TTS_CACHE_MAX = 30;

app.post('/api/tts', async (req, res) => {
  const { text, reference_id } = req.body || {};
  if (!text) return res.status(400).json({ error: 'text is required' });

  const useVoice = (voice) => {
    const cacheKey = text.slice(0, 100) + '|' + (voice || '');
    const cached = _ttsCache.get(cacheKey);
    if (cached) {
      res.json({ ok: true, status: 'cached' });
      broadcast({ type: 'soul_voice', audio: cached, mime: 'audio/mpeg' });
      return;
    }

    res.json({ ok: true, status: 'generating' });
    broadcast({ type: 'tts_status', status: _ttsWarmed ? 'generating' : 'compiling' });

    ttsGenerate(text, voice,
      (buf) => {
        _ttsWarmed = true;
        const b64 = buf.toString('base64');
        // Cache it
        if (_ttsCache.size >= TTS_CACHE_MAX) { const first = _ttsCache.keys().next().value; _ttsCache.delete(first); }
        _ttsCache.set(cacheKey, b64);
        broadcast({ type: 'soul_voice', audio: b64, mime: 'audio/mpeg' });
      },
      (e) => {
        broadcast({ type: 'tts_status', status: 'error', error: e.message });
      }
    );
  };

  try {
    if (reference_id) {
      useVoice(reference_id);
    } else {
      getDailyVoice(useVoice);
    }
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
