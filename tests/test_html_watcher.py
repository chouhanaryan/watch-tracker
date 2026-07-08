from app.watchers import html_watcher


def test_extract_text_strips_scripts_and_styles():
    html = """
    <html><head><style>.x{color:red}</style>
    <script>var token = "abc123";</script></head>
    <body><h1>Kurono   Tokyo</h1>
    <p>New drop coming soon</p>
    <script>analytics("xyz")</script></body></html>
    """
    text = html_watcher.extract_text(html)
    assert "Kurono Tokyo" in text
    assert "New drop coming soon" in text
    assert "token" not in text
    assert "color:red" not in text


def test_hash_stable_across_dynamic_noise():
    a = '<html><script>nonce="111"</script><body><p>Same  content</p></body></html>'
    b = '<html><script>nonce="222"</script><body><p>Same content</p></body></html>'
    assert html_watcher.content_hash(html_watcher.extract_text(a)) == \
           html_watcher.content_hash(html_watcher.extract_text(b))


def test_summarize_diff_reports_added_and_removed():
    old = "Home\nAbout\nSold out"
    new = "Home\nAbout\nNew drop: Toki available now"
    summary = html_watcher.summarize_diff(old, new)
    assert "Added: New drop: Toki available now" in summary
    assert "Removed: Sold out" in summary


def test_summarize_diff_caps_output():
    old = "\n".join(f"line {i}" for i in range(100))
    new = "\n".join(f"line {i} changed" for i in range(100))
    summary = html_watcher.summarize_diff(old, new)
    assert "more change(s)" in summary
    assert len(summary.splitlines()) <= html_watcher.MAX_DIFF_LINES + 1
