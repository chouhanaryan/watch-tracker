from app import notifier


def test_drop_subject_is_prioritized():
    events = [
        {"kind": "page_change", "title": "Page content changed", "details": "", "url": ""},
        {"kind": "new_drop", "title": "New product: Calendrier Type 2",
         "details": "Price: 4200.00", "url": "https://kuronotokyo.com/products/x"},
    ]
    subject = notifier.build_subject("Kurono Tokyo", events)
    assert "NEW DROP" in subject
    assert "Calendrier Type 2" in subject


def test_plain_update_subject():
    events = [{"kind": "page_change", "title": "Page content changed", "details": "", "url": ""}]
    subject = notifier.build_subject("Kurono Tokyo", events)
    assert "Kurono Tokyo updated" in subject


def test_html_body_escapes_content():
    events = [{"kind": "new_drop", "title": "New product: <script>x</script>",
               "details": "a & b", "url": "https://x.example"}]
    body = notifier.build_html_body("Brand<>", events)
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body
    assert "a &amp; b" in body
