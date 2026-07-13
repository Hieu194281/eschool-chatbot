"""Per-PSID rate limit, daily budget, bounded windows."""

from app.channel.rate_limiter import RateLimiter


def test_per_minute_cap():
    rl = RateLimiter(per_min=3, per_day=100, max_concurrent=5)
    assert all(rl.allow("psid") for _ in range(3))
    assert rl.allow("psid") is False       # over cap


def test_per_day_cap():
    rl = RateLimiter(per_min=100, per_day=2, max_concurrent=5)
    assert rl.allow("p") is True
    assert rl.allow("p") is True
    assert rl.allow("p") is False


def test_separate_psids_independent():
    rl = RateLimiter(per_min=1, per_day=10, max_concurrent=5)
    assert rl.allow("a") is True
    assert rl.allow("b") is True           # different PSID unaffected


def test_budget_alert_and_flag():
    seen = []
    rl = RateLimiter(10, 10, 5, daily_budget=100, on_budget_alert=seen.append)
    rl.add_spend(60)
    assert rl.budget_exceeded() is False
    rl.add_spend(60)
    assert rl.budget_exceeded() is True
    assert seen == [120]                    # alert fired once with the spend


def test_windows_bounded():
    rl = RateLimiter(10, 10, 5, maxsize=10)
    for i in range(100):
        rl.allow(f"p{i}")
    assert len(rl._windows) <= 10
