from drizzler.ascii_render import render_latency_histogram, render_timeline


def test_histogram_empty():
    assert "No latency data" in render_latency_histogram([])


def test_timeline_empty():
    assert "No timeline data" in render_timeline({})