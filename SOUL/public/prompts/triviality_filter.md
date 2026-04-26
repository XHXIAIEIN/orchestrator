## Triviality Filter

Before running the full protocol below, check:

IF the input is ≤ 3 words AND contains no error / question / code snippet / explicit task request
THEN: respond directly without invoking the full skill workflow. A one-line acknowledgment is sufficient.

Examples that bypass full protocol: "ok", "got it", "yes", "done", "thanks", "continue"
Examples that must run full protocol: "ok but why?", "done — next step?", any code block, any question mark
