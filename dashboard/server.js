const express = require('express');
const { WebSocketServer } = require('ws');
const path = require('path');
const http = require('http');
const fs = require('fs');
const { spawn } = require('child_process');
const initSqlJs = require('sql.js');

const PORT = process.env.PORT || 23714;
const DB_PATH = path.join(__dirname, '..', 'data', 'events.db');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

// Swagger UI at /docs
app.get('/api-reference', (req, res) => {
  res.send(`<!DOCTYPE html><html><head><title>Orchestrator API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({ url: '/openapi.json', dom_id: '#swagger-ui', deepLinking: true });</script>
</body></html>`);
});

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

// ── 健康检查 & 跨项目摘要 ──

app.get('/api/health', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ status: 'down', reason: 'db unavailable' });
  db.close();
  res.json({ status: 'ok', uptime: process.uptime() | 0 });
});

app.get('/api/brief', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ status: 'down' });
  try {
    const openDebts = dbAll(db, "SELECT COUNT(*) as cnt FROM attention_debts WHERE status = 'open'");
    const highDebts = dbAll(db, "SELECT id, project, summary, severity FROM attention_debts WHERE status = 'open' AND severity = 'high' ORDER BY created_at DESC LIMIT 5");
    const pendingTasks = dbAll(db, "SELECT COUNT(*) as cnt FROM tasks WHERE status IN ('pending', 'awaiting_approval')");
    const runningTasks = dbAll(db, "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'running'");
    const lastCollector = dbAll(db, "SELECT created_at FROM logs WHERE source = 'collector' ORDER BY id DESC LIMIT 1");
    const lastAnalysis = dbAll(db, "SELECT generated_at FROM insights ORDER BY generated_at DESC LIMIT 1");
    res.json({
      status: 'ok',
      debts: {
        open: openDebts[0]?.cnt || 0,
        high_priority: highDebts,
      },
      tasks: {
        pending: pendingTasks[0]?.cnt || 0,
        running: runningTasks[0]?.cnt || 0,
      },
      last_collector_run: lastCollector[0]?.created_at || null,
      last_analysis: lastAnalysis[0]?.generated_at || null,
    });
  } catch (e) { res.json({ status: 'error', error: e.message }); }
  finally { db.close(); }
});

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
    const { status, department } = req.query;
    let sql = 'SELECT * FROM tasks WHERE 1=1';
    const params = [];
    if (status) { sql += ' AND status = ?'; params.push(status); }
    sql += ' ORDER BY created_at DESC LIMIT 50';
    let rows = dbAll(db, sql, params);
    rows = rows.map(r => ({ ...r, spec: JSON.parse(r.spec || '{}') }));
    if (department) rows = rows.filter(r => r.spec.department === department);
    res.json(rows);
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
db = EventsDB('/orchestrator/data/events.db')
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

  const proc = spawn('python3', ['/orchestrator/src/governance/governor_cli.py', 'approve', String(taskId)]);
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

app.get('/api/scenarios', (req, res) => {
  res.json({
    full_audit: { description: "Full system audit: security + quality + protocol in parallel", departments: ["security", "quality", "protocol"] },
    code_and_review: { description: "Engineering fix + quality review on different projects", departments: ["engineering", "quality"] },
    system_health: { description: "Operations health check + personnel performance report", departments: ["operations", "personnel"] },
    deep_scan: { description: "Protocol debt scan + security audit + personnel metrics", departments: ["protocol", "security", "personnel"] },
    full_pipeline: { description: "All read-only departments scan simultaneously", departments: ["protocol", "security", "quality", "personnel"] },
  });
});

app.post('/api/scenarios/:name/run', (req, res) => {
  const name = req.params.name;
  const { project, cwd } = req.body || {};
  const proc = spawn('python3', ['-c', `
import sys, json; sys.path.insert(0, '/orchestrator')
from src.governance.governor import Governor
from src.storage.events_db import EventsDB
db = EventsDB('/orchestrator/data/events.db')
g = Governor(db=db)
results = g.run_parallel_scenario('${name}', project='${project || 'orchestrator'}', cwd='${cwd || ''}')
print(json.dumps([{'id': t.get('id'), 'action': t.get('action'), 'status': t.get('status')} for t in results]))
  `]);
  let out = '', err = '';
  proc.stdout.on('data', d => { out += d; });
  proc.stderr.on('data', d => { err += d; });
  proc.on('close', () => {
    try { res.json({ dispatched: JSON.parse(out) }); }
    catch { res.status(500).json({ error: err || out || 'unknown error' }); }
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

  const proc = spawn('python3', ['/orchestrator/src/analysis/profile_analyst_cli.py', 'periodic']);

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
    const { status, project, severity } = req.query;
    let sql = 'SELECT * FROM attention_debts WHERE 1=1';
    const params = [];
    if (status) { sql += ' AND status = ?'; params.push(status); }
    if (project) { sql += ' AND project LIKE ?'; params.push(`%${project}%`); }
    if (severity) { sql += ' AND severity = ?'; params.push(severity); }
    sql += ` ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, created_at DESC LIMIT 50`;
    const rows = dbAll(db, sql, params);
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});

app.get('/api/experiences', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const { type } = req.query;
    const limit = Math.min(parseInt(req.query.limit) || 20, 100);
    let sql = 'SELECT date, type, summary, detail, instance FROM experiences';
    const params = [];
    if (type) { sql += ' WHERE type = ?'; params.push(type); }
    sql += ' ORDER BY date DESC, id DESC LIMIT ?';
    params.push(limit);
    const rows = dbAll(db, sql, params);
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});

// ── Agent Events: real-time observability ──

app.get('/api/agent-events/:taskId', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const limit = Math.min(parseInt(req.query.limit) || 100, 500);
    const rows = dbAll(db,
      'SELECT id, task_id, event_type, data, created_at FROM agent_events WHERE task_id = ? ORDER BY id ASC LIMIT ?',
      [parseInt(req.params.taskId), limit]
    );
    res.json(rows.map(r => ({ ...r, data: JSON.parse(r.data || '{}') })));
  } catch { res.json([]); }
  finally { db.close(); }
});

// SSE stream: real-time agent events across all running tasks
app.get('/api/agent-events-stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  let lastId = parseInt(req.query.since_id) || 0;

  // Send initial: get last 20 events
  const initDb = getDb();
  if (initDb) {
    try {
      const rows = dbAll(initDb, 'SELECT id, task_id, event_type, data, created_at FROM agent_events ORDER BY id DESC LIMIT 20');
      if (rows.length) {
        lastId = rows[0].id;
        const parsed = rows.reverse().map(r => ({ ...r, data: JSON.parse(r.data || '{}') }));
        res.write(`data: ${JSON.stringify({ type: 'backlog', events: parsed })}\n\n`);
      }
    } catch {}
    finally { initDb.close(); }
  }

  const interval = setInterval(() => {
    const db = getDb();
    if (!db) return;
    try {
      const rows = dbAll(db, 'SELECT id, task_id, event_type, data, created_at FROM agent_events WHERE id > ? ORDER BY id ASC LIMIT 20', [lastId]);
      if (rows.length) {
        lastId = rows[rows.length - 1].id;
        const parsed = rows.map(r => ({ ...r, data: JSON.parse(r.data || '{}') }));
        for (const evt of parsed) {
          res.write(`data: ${JSON.stringify({ type: 'agent_event', event: evt })}\n\n`);
        }
      }
    } catch {}
    finally { db.close(); }
  }, 1000);

  req.on('close', () => clearInterval(interval));
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
const VOICE_LOG_PATH = path.join(__dirname, '..', 'SOUL', 'private', 'voice_log.json');

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

// ── Pipeline API endpoints ──

const DEPARTMENTS_DIR = path.join(__dirname, '..', 'departments');
const DEPT_KEYS = ['engineering', 'quality', 'operations', 'protocol', 'security', 'personnel'];

app.get('/api/pipeline/status', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ collectors: {}, analysis: {}, governance: {}, departments: {}, scheduler: {} });
  try {
    // ── Collectors: parse last collector log message for per-source counts ──
    const collectors = {};
    const collectorNames = ['claude', 'browser', 'git', 'steam', 'youtube_music', 'orchestrator_codebase'];
    const collectorLogs = dbAll(db,
      "SELECT message, created_at FROM logs WHERE source = 'collector' AND message LIKE '%采集完成%' ORDER BY id DESC LIMIT 1"
    );
    const lastCollectorRun = collectorLogs[0] ? collectorLogs[0].created_at : null;
    const msg = collectorLogs[0] ? collectorLogs[0].message : '';
    // Parse counts from message like "采集完成：claude, browser, git 各 [4, 500, 14] 条"
    const namesMatch = msg.match(/采集完成：([^各]+)各/);
    const countsMatch = msg.match(/各\s*\[([^\]]+)\]/);
    const okNames = namesMatch ? namesMatch[1].split(',').map(s => s.trim()) : [];
    const okCounts = countsMatch ? countsMatch[1].split(',').map(s => parseInt(s.trim())) : [];
    // Parse failed sources
    const failMatch = msg.match(/失败：(.+)$/);
    const failNames = failMatch ? failMatch[1].split(',').map(s => s.trim()) : [];

    for (const name of collectorNames) {
      const idx = okNames.indexOf(name);
      if (idx >= 0 && idx < okCounts.length) {
        collectors[name] = { status: 'ok', last_count: okCounts[idx], last_run: lastCollectorRun };
      } else if (failNames.includes(name)) {
        collectors[name] = { status: 'error', last_count: -1, last_run: lastCollectorRun };
      } else {
        collectors[name] = { status: 'unknown', last_count: 0, last_run: lastCollectorRun };
      }
    }

    // ── Analysis: last insight ──
    let analysis = { last_run: null, status: 'idle', insights_count: 0 };
    try {
      const insightRow = dbAll(db, "SELECT generated_at FROM insights ORDER BY generated_at DESC LIMIT 1");
      const insightCount = dbAll(db, "SELECT COUNT(*) as cnt FROM insights");
      analysis = {
        last_run: insightRow[0] ? insightRow[0].generated_at : null,
        status: 'idle',
        insights_count: insightCount[0] ? insightCount[0].cnt : 0,
      };
    } catch { /* insights table may not exist */ }

    // ── Governance: task stats ──
    let governance = { tasks_running: 0, tasks_pending: 0, tasks_done_today: 0, last_task: null };
    try {
      const running = dbAll(db, "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'running'");
      const pending = dbAll(db, "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending'");
      const todayStr = new Date().toISOString().slice(0, 10);
      const doneToday = dbAll(db, "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'done' AND finished_at >= ?", [todayStr]);
      const lastTask = dbAll(db, "SELECT * FROM tasks ORDER BY id DESC LIMIT 1");
      let lastTaskObj = null;
      if (lastTask[0]) {
        const t = lastTask[0];
        let spec = {};
        try { spec = JSON.parse(t.spec || '{}'); } catch {}
        lastTaskObj = {
          id: t.id, action: t.action, status: t.status,
          department: spec.department || null,
          cognitive_mode: spec.cognitive_mode || null,
        };
      }
      governance = {
        tasks_running: running[0] ? running[0].cnt : 0,
        tasks_pending: pending[0] ? pending[0].cnt : 0,
        tasks_done_today: doneToday[0] ? doneToday[0].cnt : 0,
        last_task: lastTaskObj,
      };
    } catch { /* tasks table may not exist */ }

    // ── Departments: stats from tasks table by spec.department ──
    const departments = {};
    try {
      const allTasks = dbAll(db, "SELECT spec, status, finished_at FROM tasks");
      const deptStats = {};
      for (const t of allTasks) {
        let spec = {};
        try { spec = JSON.parse(t.spec || '{}'); } catch {}
        const dept = spec.department;
        if (!dept) continue;
        if (!deptStats[dept]) deptStats[dept] = { tasks_done: 0, tasks_failed: 0, last_active: null };
        if (t.status === 'done') deptStats[dept].tasks_done++;
        if (t.status === 'failed') deptStats[dept].tasks_failed++;
        if (t.finished_at && (!deptStats[dept].last_active || t.finished_at > deptStats[dept].last_active)) {
          deptStats[dept].last_active = t.finished_at;
        }
      }
      Object.assign(departments, deptStats);
    } catch { /* ignore */ }

    // ── Scheduler: from scheduler_status table ──
    let scheduler = {};
    try {
      const statusRows = dbAll(db, "SELECT key, value FROM scheduler_status");
      for (const r of statusRows) {
        scheduler[r.key] = r.value;
      }
    } catch { /* table may not exist */ }

    res.json({ collectors, analysis, governance, departments, scheduler });
  } catch (e) {
    res.json({ collectors: {}, analysis: {}, governance: {}, departments: {}, scheduler: {}, error: e.message });
  } finally {
    db.close();
  }
});

app.get('/api/pipeline/logs', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const limit = Math.min(parseInt(req.query.limit) || 20, 200);
    const rows = dbAll(db, 'SELECT id, level, source, message, created_at FROM logs ORDER BY id DESC LIMIT ?', [limit]);
    res.json(rows);
  } catch {
    res.json([]);
  } finally {
    db.close();
  }
});

app.get('/api/pipeline/tasks', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const limit = Math.min(parseInt(req.query.limit) || 30, 100);
    const rows = dbAll(db, 'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?', [limit]);
    res.json(rows.map(r => {
      let spec = {};
      try { spec = JSON.parse(r.spec || '{}'); } catch {}
      return {
        id: r.id,
        action: r.action,
        status: r.status,
        department: spec.department || null,
        cognitive_mode: spec.cognitive_mode || null,
        blast_radius: spec.blast_radius || null,
        created_at: r.created_at,
        started_at: r.started_at || null,
        finished_at: r.finished_at || null,
        output: r.output || null,
        scrutiny_note: r.scrutiny_note || null,
      };
    }));
  } catch {
    res.json([]);
  } finally {
    db.close();
  }
});

app.get('/api/pipeline/departments', (req, res) => {
  const result = {};
  for (const dept of DEPT_KEYS) {
    const deptDir = path.join(DEPARTMENTS_DIR, dept);
    const runLogPath = path.join(deptDir, 'run-log.jsonl');
    const suggestionsPath = path.join(deptDir, 'skill-suggestions.md');

    let runs = [];
    try {
      const content = fs.readFileSync(runLogPath, 'utf8').trim();
      if (content) {
        runs = content.split('\n').filter(l => l.trim()).map(l => {
          try { return JSON.parse(l); } catch { return null; }
        }).filter(Boolean);
      }
    } catch { /* file doesn't exist */ }

    const totalRuns = runs.length;
    const recentRuns = runs.slice(-10).reverse().map(r => ({
      ts: r.ts || null,
      task_id: r.task_id || null,
      mode: r.mode || null,
      summary: r.summary || '',
      status: r.status || 'unknown',
    }));

    const doneRuns = runs.filter(r => r.status === 'done').length;
    const successRate = totalRuns > 0 ? Math.round((doneRuns / totalRuns) * 100) / 100 : 0;

    let hasSuggestions = false;
    try { hasSuggestions = fs.existsSync(suggestionsPath); } catch {}

    result[dept] = {
      total_runs: totalRuns,
      recent_runs: recentRuns,
      success_rate: successRate,
      has_suggestions: hasSuggestions,
    };
  }
  res.json(result);
});

// ── Agent Live Status: aggregated real-time view for external consumers ──

app.get('/api/agents/live', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ agents: [], idle: true });
  try {
    // Running tasks = active agents
    const running = dbAll(db, "SELECT * FROM tasks WHERE status = 'running' ORDER BY started_at ASC");
    const agents = running.map(t => {
      let spec = {};
      try { spec = JSON.parse(t.spec || '{}'); } catch {}

      // Get latest agent events for this task
      let events = [];
      try {
        events = dbAll(db,
          "SELECT event_type, data, created_at FROM agent_events WHERE task_id = ? ORDER BY id DESC LIMIT 5",
          [t.id]
        ).reverse();
      } catch {}

      // Parse latest turn info
      const lastTurn = events.filter(e => e.event_type === 'agent_turn').pop();
      let currentActivity = null;
      if (lastTurn) {
        try {
          const d = JSON.parse(lastTurn.data || '{}');
          const tools = d.tools || [];
          const thinking = d.thinking || [];
          currentActivity = {
            turn: d.turn,
            tools: tools.map(t => t.tool),
            thinking_preview: thinking[0] ? thinking[0].slice(0, 100) : null,
            text_preview: (d.text || [])[0]?.slice(0, 100) || null,
          };
        } catch {}
      }

      // Elapsed time
      let elapsed_s = 0;
      if (t.started_at) {
        elapsed_s = Math.floor((Date.now() - new Date(t.started_at).getTime()) / 1000);
      }

      return {
        task_id: t.id,
        department: spec.department || null,
        project: spec.project || null,
        cwd: spec.cwd || null,
        action: t.action,
        cognitive_mode: spec.cognitive_mode || null,
        started_at: t.started_at,
        elapsed_s,
        current_activity: currentActivity,
        recent_events: events.map(e => ({
          type: e.event_type,
          data: JSON.parse(e.data || '{}'),
          at: e.created_at,
        })),
      };
    });

    // Pending/queued
    const pending = dbAll(db, "SELECT COUNT(*) as cnt FROM tasks WHERE status IN ('pending', 'awaiting_approval')");
    const pendingCount = pending[0]?.cnt || 0;

    res.json({
      agents,
      idle: agents.length === 0,
      running_count: agents.length,
      pending_count: pendingCount,
      max_concurrent: 3,
    });
  } catch (e) { res.json({ agents: [], idle: true, error: e.message }); }
  finally { db.close(); }
});

app.get('/api/agents/:taskId/trace', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ task: null, events: [] });
  try {
    const taskId = parseInt(req.params.taskId);

    // Task info
    const tasks = dbAll(db, 'SELECT * FROM tasks WHERE id = ?', [taskId]);
    if (!tasks.length) return res.status(404).json({ error: 'task not found' });
    const t = tasks[0];
    let spec = {};
    try { spec = JSON.parse(t.spec || '{}'); } catch {}

    // All events
    const events = dbAll(db,
      'SELECT id, event_type, data, created_at FROM agent_events WHERE task_id = ? ORDER BY id ASC',
      [taskId]
    ).map(e => ({ ...e, data: JSON.parse(e.data || '{}') }));

    // Build trace summary
    const turns = events.filter(e => e.event_type === 'agent_turn').length;
    const tools_used = [];
    const errors = [];
    const decisions = [];
    for (const e of events) {
      if (e.event_type === 'agent_turn') {
        for (const tool of (e.data.tools || [])) {
          tools_used.push(tool.tool);
        }
        if (e.data.error) errors.push({ turn: e.data.turn, error: e.data.error });
        if (e.data.thinking) {
          for (const thought of e.data.thinking) {
            decisions.push({ turn: e.data.turn, thought: thought.slice(0, 200) });
          }
        }
      }
      if (e.event_type === 'agent_result' && e.data.is_error) {
        errors.push({ turn: 'final', error: e.data.stop_reason || 'unknown' });
      }
    }

    const result = events.find(e => e.event_type === 'agent_result');

    res.json({
      task: {
        id: t.id,
        action: t.action,
        status: t.status,
        department: spec.department,
        project: spec.project,
        cognitive_mode: spec.cognitive_mode,
        started_at: t.started_at,
        finished_at: t.finished_at,
        output: t.output,
      },
      trace: {
        total_turns: turns,
        tools_used: [...new Set(tools_used)],
        tool_call_count: tools_used.length,
        errors,
        decisions: decisions.slice(-10),
        duration_ms: result?.data?.duration_ms || null,
        cost_usd: result?.data?.cost_usd || null,
      },
      events,
    });
  } catch (e) { res.status(500).json({ error: e.message }); }
  finally { db.close(); }
});

// ── Department API: per-department detail endpoints ──

app.get('/api/departments', (req, res) => {
  res.json(DEPT_KEYS);
});

app.get('/api/departments/:name', (req, res) => {
  const dept = req.params.name;
  if (!DEPT_KEYS.includes(dept)) return res.status(404).json({ error: 'unknown department' });
  const deptDir = path.join(DEPARTMENTS_DIR, dept);

  // SKILL.md
  let skill = '';
  try { skill = fs.readFileSync(path.join(deptDir, 'SKILL.md'), 'utf8'); } catch {}

  // guidelines
  const guidelines = [];
  const guidelinesDir = path.join(deptDir, 'guidelines');
  try {
    for (const f of fs.readdirSync(guidelinesDir)) {
      if (f.endsWith('.md')) {
        guidelines.push({ name: f.replace('.md', ''), content: fs.readFileSync(path.join(guidelinesDir, f), 'utf8') });
      }
    }
  } catch {}

  // run-log (last 20)
  let runs = [];
  try {
    const lines = fs.readFileSync(path.join(deptDir, 'run-log.jsonl'), 'utf8').trim().split('\n').filter(Boolean);
    runs = lines.slice(-20).reverse().map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  } catch {}

  // learned-skills
  let learnedSkills = '';
  try { learnedSkills = fs.readFileSync(path.join(deptDir, 'learned-skills.md'), 'utf8'); } catch {}

  // skill-suggestions
  let suggestions = '';
  try { suggestions = fs.readFileSync(path.join(deptDir, 'skill-suggestions.md'), 'utf8'); } catch {}

  res.json({ name: dept, skill, guidelines, runs, learnedSkills, suggestions });
});

app.get('/api/departments/:name/skill', (req, res) => {
  const dept = req.params.name;
  if (!DEPT_KEYS.includes(dept)) return res.status(404).json({ error: 'unknown department' });
  try {
    res.type('text/markdown').send(fs.readFileSync(path.join(DEPARTMENTS_DIR, dept, 'SKILL.md'), 'utf8'));
  } catch { res.status(404).json({ error: 'SKILL.md not found' }); }
});

app.get('/api/departments/:name/runs', (req, res) => {
  const dept = req.params.name;
  if (!DEPT_KEYS.includes(dept)) return res.status(404).json({ error: 'unknown department' });
  const limit = Math.min(parseInt(req.query.limit) || 20, 100);
  try {
    const lines = fs.readFileSync(path.join(DEPARTMENTS_DIR, dept, 'run-log.jsonl'), 'utf8').trim().split('\n').filter(Boolean);
    const runs = lines.slice(-limit).reverse().map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    res.json(runs);
  } catch { res.json([]); }
});

app.get('/api/departments/:name/guidelines', (req, res) => {
  const dept = req.params.name;
  if (!DEPT_KEYS.includes(dept)) return res.status(404).json({ error: 'unknown department' });
  const guidelinesDir = path.join(DEPARTMENTS_DIR, dept, 'guidelines');
  const result = [];
  try {
    for (const f of fs.readdirSync(guidelinesDir)) {
      if (f.endsWith('.md')) {
        result.push({ name: f.replace('.md', ''), content: fs.readFileSync(path.join(guidelinesDir, f), 'utf8') });
      }
    }
  } catch {}
  res.json(result);
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
