from archive_workbench.ocr_ppocr import merge_regions, quad_to_box


def test_quad_becomes_an_axis_aligned_box():
    x, y, w, h = quad_to_box([[10, 20], [40, 18], [42, 50], [8, 48]])
    assert (x, y) == (8, 18)
    assert w >= 30 and h >= 30


def test_overlapping_lines_keep_the_stronger_reading():
    regions = [
        {"text": "Dept", "x": 10, "y": 10, "w": 80, "h": 20, "confidence": 0.4},
        {"text": "Department", "x": 12, "y": 11, "w": 78, "h": 18, "confidence": 0.9},
        {"text": "Date", "x": 10, "y": 80, "w": 40, "h": 16, "confidence": 0.8},
    ]
    merged = merge_regions(regions)
    texts = [item["text"] for item in merged]
    assert texts == ["Department", "Date"]
