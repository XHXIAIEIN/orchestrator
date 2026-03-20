"""Tests for OCRGrounder — word-level Tesseract grounding with fuzzy match."""
import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.gui.grounder_ocr import LocateResult, OCRGrounder

# ---------------------------------------------------------------------------
# Helpers to build mock pytesseract TSV output
# ---------------------------------------------------------------------------

TSV_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
    "\tleft\ttop\twidth\theight\tconf\ttext"
)


def _make_tsv(*rows: tuple) -> str:
    """Build a TSV string from (line_num, word_num, left, top, width, height, conf, text) tuples."""
    lines = [TSV_HEADER]
    for line_num, word_num, left, top, width, height, conf, text in rows:
        lines.append(
            f"5\t1\t1\t1\t{line_num}\t{word_num}\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}"
        )
    return "\n".join(lines)


def _dummy_png() -> bytes:
    """Return a minimal valid PNG as bytes."""
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def grounder():
    return OCRGrounder(min_confidence=70, fuzzy_threshold=80)


@pytest.fixture
def dummy_png():
    return _dummy_png()


# ---------------------------------------------------------------------------
# Test 1: Exact single-word match
# ---------------------------------------------------------------------------

@patch("src.gui.grounder_ocr.pytesseract")
def test_exact_match(mock_tess, grounder, dummy_png):
    """Tesseract returns '我喜欢' at (100,200,60,30) conf=95 → correct LocateResult."""
    tsv = _make_tsv(
        (1, 1, 100, 200, 60, 30, 95, "我喜欢"),
    )
    mock_tess.image_to_data.return_value = tsv

    result = grounder.locate("我喜欢", dummy_png, monitor_id=1)

    assert result is not None
    assert result.x == 130          # 100 + 60//2
    assert result.y == 215          # 200 + 30//2
    assert result.confidence == 95.0
    assert result.monitor_id == 1
    assert result.method == "ocr"


# ---------------------------------------------------------------------------
# Test 2: Merged adjacent words match (same line, two words)
# ---------------------------------------------------------------------------

@patch("src.gui.grounder_ocr.pytesseract")
def test_merged_adjacent_words_match(mock_tess, grounder, dummy_png):
    """'我' and '喜欢' are separate words on the same line → merged '我喜欢' found."""
    tsv = _make_tsv(
        (1, 1, 100, 200, 30, 30, 90, "我"),
        (1, 2, 140, 200, 60, 30, 85, "喜欢"),
    )
    mock_tess.image_to_data.return_value = tsv

    result = grounder.locate("我喜欢", dummy_png, monitor_id=2)

    assert result is not None
    # merged bounding box: left=100, top=200, right=200, bottom=230 → center (150, 215)
    assert result.x == 150
    assert result.y == 215
    assert result.monitor_id == 2
    assert result.method == "ocr"


# ---------------------------------------------------------------------------
# Test 3: No match → None
# ---------------------------------------------------------------------------

@patch("src.gui.grounder_ocr.pytesseract")
def test_not_found(mock_tess, grounder, dummy_png):
    """Tesseract returns '设置' only → locate('退出程序') returns None."""
    tsv = _make_tsv(
        (1, 1, 50, 50, 40, 20, 88, "设置"),
    )
    mock_tess.image_to_data.return_value = tsv

    result = grounder.locate("退出程序", dummy_png)

    assert result is None


# ---------------------------------------------------------------------------
# Test 4: Low confidence rejected
# ---------------------------------------------------------------------------

@patch("src.gui.grounder_ocr.pytesseract")
def test_low_confidence_rejected(mock_tess, grounder, dummy_png):
    """'我喜欢' conf=30 < min_confidence=70 → None (all passes should fail)."""
    tsv = _make_tsv(
        (1, 1, 100, 200, 60, 30, 30, "我喜欢"),
    )
    mock_tess.image_to_data.return_value = tsv

    result = grounder.locate("我喜欢", dummy_png)

    assert result is None


# ---------------------------------------------------------------------------
# Test 5: Fuzzy match (slight typo / partial similarity)
# ---------------------------------------------------------------------------

@patch("src.gui.grounder_ocr.pytesseract")
def test_fuzzy_match(mock_tess, dummy_png):
    """Tesseract returns 'Settings' → fuzzy-matches 'Setting' (ratio ~93)."""
    grounder = OCRGrounder(min_confidence=70, fuzzy_threshold=80)
    tsv = _make_tsv(
        (1, 1, 200, 100, 80, 20, 85, "Settings"),
    )
    mock_tess.image_to_data.return_value = tsv

    result = grounder.locate("Setting", dummy_png, monitor_id=3)

    assert result is not None
    assert result.x == 240   # 200 + 80//2
    assert result.y == 110   # 100 + 20//2
    assert result.monitor_id == 3
    assert result.method == "ocr"
