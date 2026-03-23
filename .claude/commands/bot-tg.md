Read the Telegram bot's recent chat history from the database.

Run this Python snippet to fetch the last 20 messages:

```python
import sqlite3
conn = sqlite3.connect('data/events.db')
rows = conn.execute("SELECT role, content, created_at FROM chat_messages WHERE chat_client = 'telegram' ORDER BY id DESC LIMIT 20").fetchall()
memory = conn.execute("SELECT summary, updated_at FROM chat_memory WHERE chat_id NOT LIKE '%@im.wechat' LIMIT 1").fetchone()
conn.close()
```

Display:
1. The chat memory summary (if any)
2. The last 20 messages in chronological order, formatted as:
   `[HH:MM:SS] role: content`

If the user provides an argument like "5", only show the last N messages.
