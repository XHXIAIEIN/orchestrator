# Required — crash if missing
from .immutable_constraints import enforce_tool_constraint, enforce_timeout_constraint

# Optional — isolated so one failure doesn't break the others
try:
    from .doom_loop import check_doom_loop
except ImportError:
    pass

try:
    from .verify_gate import run_gates, save_gate_record
except ImportError:
    pass

try:
    from .agent_semaphore import AgentSemaphore
except ImportError:
    pass

try:
    from .taint import TaintTracker, TaintViolation, TaintLabel
except ImportError:
    pass

try:
    from .injection_scanner import scan_text, scan_context_file, scan_agent_output, has_high_severity
except ImportError:
    pass

try:
    from .ssrf import assert_safe_url, is_safe_url, SSRFError
except ImportError:
    pass
