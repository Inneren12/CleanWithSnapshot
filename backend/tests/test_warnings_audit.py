import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "warnings_audit.py"
spec = importlib.util.spec_from_file_location("warnings_audit", SCRIPT_PATH)
warnings_audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(warnings_audit)


def test_unclosed_event_loop_origin_marked_actionable():
    log_content = """
=============================== warnings summary ===============================
tests/test_example.py::test_leaky_loop
/usr/lib/python3.11/asyncio/base_events.py:693: ResourceWarning: unclosed event loop <_UnixSelectorEventLoop running=False closed=False debug=False>
  warnings.warn("unclosed event loop")
=========================== short test summary info ============================
"""
    warnings = warnings_audit.parse_warnings_from_log(log_content)
    assert warnings
    warning = warnings[0]
    assert warning.origin == "our"


def test_unclosed_event_loop_not_filtered_by_noise_allowlist():
    signature = warnings_audit.WarningSignature(
        signature_id="abc123",
        category="ResourceWarning",
        message="unclosed event loop",
        message_full="unclosed event loop",
        source_file="/usr/lib/python3.11/asyncio/base_events.py",
        source_line=693,
        source_module="asyncio.base_events",
        origin="third_party",
        count=1,
    )
    filtered, filtered_count = warnings_audit.apply_noise_filter(
        {"abc123": signature},
        [{"pattern": "event loop", "rationale": "test", "review_date": "2099-01-01"}],
    )
    assert "abc123" in filtered
    assert filtered_count == 0
