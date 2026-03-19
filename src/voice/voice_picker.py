"""
Voice Picker — 从 Fish Audio 平台随机选择声音。

根据语言、性别、风格等标签筛选，随机挑一个声音，
下载参考音频并注册到本地 Fish S2 Pro。

用法：
    from src.voice_picker import pick_voice

    # 随机挑一个中文年轻男声
    ref_id = pick_voice(tags=["male", "young"], language="zh")

    # 用选中的声音说话
    from src.voice.tts import speak
    speak("你好", reference_id=ref_id)

标签参考（Fish Audio 常用标签）：
    性别: male, female
    年龄: young, middle-aged
    风格: conversational, narration, educational, social-media, entertainment
    语气: calm, energetic, confident, friendly, relaxed, warm, gentle
    速度: fast, slow, smooth
"""
import json
import logging
import os
import random
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger(__name__)

FISH_API = "https://api.fish.audio"
TTS_HOST = os.environ.get("TTS_HOST", "http://localhost:23715")
CACHE_DIR = Path(os.environ.get("VOICE_CACHE_DIR", "D:/Agent/tmp/soul-tts/voice-cache"))
HISTORY_FILE = CACHE_DIR / "voice_history.json"

# 黑名单：不想用的声音（按模型 title 关键词过滤）
BLACKLIST = [
    "丁真", "孙笑川", "蔡徐坤", "卢本伟",  # 太有辨识度的名人
    "郭德纲", "周杰伦", "樊登", "懒羊羊", "赛马娘",  # 辨识度高或角色IP
]


def search_voices(tags: list[str] | None = None, language: str = "zh",
                   limit: int = 30, min_uses: int = 5000) -> list[dict]:
    """从 Fish Audio 平台搜索符合条件的声音模型。"""
    # 清代理
    opener = _get_opener()

    params = f"title_language={language}&sort_by=task_count&page_size={limit}"
    if tags:
        params += "".join(f"&tag={t}" for t in tags)

    url = f"{FISH_API}/model?{params}"
    try:
        resp = opener.open(urllib.request.Request(url), timeout=15)
        data = json.loads(resp.read())
        models = [m for m in data.get("items", [])
                  if m.get("task_count", 0) >= min_uses
                  and m.get("samples")
                  and not any(b in m.get("title", "") for b in BLACKLIST)]
        log.info(f"voice_picker: found {len(models)} voices for tags={tags}")
        return models
    except Exception as e:
        log.warning(f"voice_picker: search failed: {e}")
        return []


def pick_voice(tags: list[str] | None = None, language: str = "zh",
               exclude: list[str] | None = None) -> str | None:
    """随机选一个声音，下载参考音频，注册到 Fish S2 Pro。返回 reference_id。"""
    if tags is None:
        tags = ["male", "young"]

    models = search_voices(tags=tags, language=language)
    if not models:
        log.warning("voice_picker: no voices found")
        return None

    # 排除已用过的
    if exclude:
        models = [m for m in models if m["_id"] not in exclude]

    if not models:
        log.warning("voice_picker: all voices excluded")
        return None

    # 随机选一个
    chosen = random.choice(models)
    model_id = chosen["_id"]
    title = chosen.get("title", "unknown")
    tags_str = ", ".join(chosen.get("tags", [])[:5])

    log.info(f"voice_picker: chose '{title}' ({model_id[:12]}...) [{tags_str}]")

    # 下载参考音频
    ref_id = _download_and_register(chosen)
    if ref_id:
        log.info(f"voice_picker: registered as '{ref_id}'")
    return ref_id


def _download_and_register(model: dict) -> str | None:
    """下载模型的参考音频并注册到本地 Fish S2 Pro。"""
    model_id = model["_id"]
    title = model.get("title", "voice")
    samples = model.get("samples", [])
    if not samples or not samples[0].get("audio"):
        return None

    # 获取带签名的新鲜 URL（列表里的 URL 可能已过期）
    try:
        opener = _get_opener()
        req = urllib.request.Request(f"{FISH_API}/model/{model_id}")
        resp = opener.open(req, timeout=15)
        fresh = json.loads(resp.read())
        audio_url = fresh["samples"][0]["audio"]
        sample_text = fresh["samples"][0].get("text", "参考音频")
    except Exception:
        audio_url = samples[0]["audio"]
        sample_text = samples[0].get("text", "参考音频")

    # 下载到缓存
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{model_id}.mp3"

    if not cache_path.exists():
        try:
            opener = _get_opener()
            resp = opener.open(urllib.request.Request(audio_url), timeout=30)
            cache_path.write_bytes(resp.read())
            log.info(f"voice_picker: downloaded {title} ({cache_path.stat().st_size/1024:.0f} KB)")
        except Exception as e:
            log.warning(f"voice_picker: download failed for {title}: {e}")
            return None

    # 注册到 Fish S2 Pro（multipart form upload）
    ref_id = f"voice_{model_id[:8]}"
    try:
        import mimetypes
        boundary = "----VoicePickerBoundary"
        audio_data = cache_path.read_bytes()
        content_type = mimetypes.guess_type(str(cache_path))[0] or "audio/mpeg"

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="id"\r\n\r\n{ref_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="text"\r\n\r\n{sample_text[:200]}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="{cache_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode() + audio_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{TTS_HOST}/v1/references/add",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()  # consume response
        return ref_id
    except urllib.error.HTTPError as e:
        if e.code == 409:  # already exists
            return ref_id
        log.warning(f"voice_picker: register failed: {e}")
        return None
    except Exception as e:
        log.warning(f"voice_picker: register failed: {e}")
        return None


def _load_history() -> dict:
    """加载声音使用历史。"""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"used": [], "current_pool": [], "last_refresh": None}


def _save_history(history: dict):
    """保存声音使用历史。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_voice_pool(pool_size: int = 12) -> list[str]:
    """清空旧声音，从平台拉一批新的注册到 Fish S2 Pro。每 7 天调用一次。"""
    from datetime import datetime
    history = _load_history()
    used_ids = set(history.get("used", []))

    # 删除现有 references
    opener = _get_opener()
    try:
        req = urllib.request.Request(f"{TTS_HOST}/v1/references/list",
                                     headers={"Accept": "application/json"})
        resp = opener.open(req, timeout=10)
        old_ids = json.loads(resp.read()).get("reference_ids", [])
        for rid in old_ids:
            try:
                body = json.dumps({"reference_id": rid}).encode()
                dreq = urllib.request.Request(
                    f"{TTS_HOST}/v1/references/delete",
                    data=body, headers={"Content-Type": "application/json"},
                    method="DELETE")
                urllib.request.urlopen(dreq, timeout=10).read()
            except Exception:
                pass
        log.info(f"voice_picker: cleared {len(old_ids)} old voices")
    except Exception as e:
        log.warning(f"voice_picker: failed to list/clear old voices: {e}")

    # 搜索多种风格
    tag_groups = [
        ["male", "young", "narration"],
        ["male", "young", "conversational"],
        ["male", "energetic"],
        ["male", "calm"],
        ["female", "young", "conversational"],
        ["female", "young", "narration"],
        ["female", "warm"],
    ]

    candidates = {}
    for tags in tag_groups:
        for m in search_voices(tags=tags, language="zh", limit=15, min_uses=8000):
            candidates[m["_id"]] = m

    # 优先选没用过的，不够再从用过的里选
    fresh = {k: v for k, v in candidates.items() if k not in used_ids}
    if len(fresh) >= pool_size:
        pool = random.sample(list(fresh.values()), pool_size)
    else:
        pool = list(fresh.values())
        remaining = pool_size - len(pool)
        recycled = [v for k, v in candidates.items() if k in used_ids]
        pool += random.sample(recycled, min(remaining, len(recycled)))
        if len(fresh) == 0:
            log.info("voice_picker: all candidates used before, recycling")

    registered = []
    current_pool = []
    for m in pool:
        ref_id = _download_and_register(m)
        if ref_id:
            registered.append(ref_id)
            current_pool.append({
                "model_id": m["_id"],
                "ref_id": ref_id,
                "title": m.get("title", "?"),
                "tags": m.get("tags", [])[:5],
            })
            used_ids.add(m["_id"])
            log.info(f"voice_picker: pool += {m.get('title','?')} -> {ref_id}")

    # 更新历史
    history["used"] = list(used_ids)
    history["current_pool"] = current_pool
    history["last_refresh"] = datetime.now().isoformat()
    _save_history(history)

    log.info(f"voice_picker: refreshed pool with {len(registered)} voices "
             f"({len(used_ids)} total used historically)")
    return registered


def list_cached_voices() -> list[str]:
    """列出已缓存的声音。"""
    if not CACHE_DIR.exists():
        return []
    return [f.stem for f in CACHE_DIR.glob("*.mp3")]


def _get_opener():
    """创建绕过代理的 URL opener。"""
    for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
        os.environ.pop(k, None)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))
