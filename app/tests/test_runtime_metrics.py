from app.middleware.runtime_metrics import RuntimeMetrics


def test_runtime_metrics_tracks_bounded_latency_and_errors():
    metrics = RuntimeMetrics(latency_window=2)
    metrics.record_request(10.0, 200)
    metrics.record_request(20.0, 503)
    metrics.record_request(30.0, 201)

    snapshot = metrics.snapshot()

    assert snapshot.request_count == 3
    assert snapshot.error_count == 1
    assert snapshot.average_latency_ms == 25.0
    assert snapshot.uptime_seconds >= 0
