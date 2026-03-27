Read the WeChat bot's recent chat history from the database.

Run this Python snippet to fetch the last 20 messages:

```python
import sqlite3
conn = sqlite3.connect('data/events.db')
rows = conn.execute("SELECT id, role, content, media_paths, created_at FROM chat_messages WHERE chat_client = 'wechat' ORDER BY id DESC LIMIT 20").fetchall()
memory = conn.execute("SELECT summary, updated_at FROM chat_memory WHERE chat_id LIKE '%@im.wechat' LIMIT 1").fetchone()
conn.close()
```

Display:
1. Chat memory summary (if any)
2. Last 20 messages in chronological order: `[HH:MM:SS] role: content`
   If `media_paths` is non-null, append: `📎 MEDIA: <paths>`

If the user provides an argument like "5", only show the last N messages.

## Viewing media

When a message has `media_paths` (JSON array of container paths like `["/orchestrator/tmp/media/inbound/xxxx.bin"]`):

1. Container path `/orchestrator/tmp/media/inbound/` maps to local `tmp/media/inbound/` (relative to project root)
2. Run `file tmp/media/inbound/<filename>` to identify file type
3. Images: copy to `D:/Agent/tmp/wx-media/<filename>.webp`, then use Read tool to view
4. Audio: copy to `D:/Agent/tmp/wx-media/<filename>.webm`, note path for potential transcription

Example:
```bash
file tmp/media/inbound/eaf630dd.bin
# → JPEG image data, ...
cp tmp/media/inbound/eaf630dd.bin D:/Agent/tmp/wx-media/eaf630dd.webp
# Then use Read tool to view the image
```

When user asks to view an image or references a photo sent to the bot, automatically retrieve and display it.
