from PIL import Image, ImageDraw, ImageFont

from archive_workbench.ocr import is_digitisation_watermark, ocr_tesseract, parse_ocr_json, regions_from_vision_json


def test_scanner_footer_is_a_watermark():
    assert is_digitisation_watermark("Scanned by Camera Scanner")
    assert not is_digitisation_watermark("The department scanned by hand a long minute about revenue policy in Dharwar")


def test_parse_ocr_json_accepts_fences_and_prose():
    assert parse_ocr_json('```json\n{"blocks": []}\n```') == {"blocks": []}
    assert parse_ocr_json('Note: {"blocks": [], "confidence": 0.4}')["confidence"] == 0.4


def test_tesseract_reads_a_printed_line():
    image = Image.new("RGB", (1400, 280), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 72)
    draw.text((40, 80), "Kittur revenue minute", fill="black", font=font)
    regions = ocr_tesseract(image, langs="eng")
    text = " ".join(region["text"] for region in regions)
    assert "Kittur" in text
    assert regions[0]["w"] > 10 and regions[0]["h"] > 10


def test_missing_vision_box_becomes_a_band():
    regions, lang, _conf = regions_from_vision_json(
        {"language": "en", "confidence": 0.8, "blocks": [
            {"type": "paragraph", "text": "Hello", "confidence": 0.8},
        ]},
        1000, 800,
    )
    assert lang == "en"
    assert regions[0]["text"] == "Hello"
    assert regions[0]["w"] > 0 and regions[0]["h"] > 0
