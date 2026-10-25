from refund_agent.config import Settings


def test_settings_defaults(monkeypatch):
    for k in ("REFUND_WINDOW_DAYS", "REVIEW_THRESHOLD_CENTS", "RUNNING_TOTAL_DAYS", "TIMEZONE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert (
        s.refund_window_days,
        s.review_threshold_cents,
        s.running_total_days,
        s.timezone,
    ) == (30, 10000, 30, "UTC")


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("REVIEW_THRESHOLD_CENTS", "5000")
    assert Settings(_env_file=None).review_threshold_cents == 5000
