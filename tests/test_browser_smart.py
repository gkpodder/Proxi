"""Tests for smart browser automation features."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from proxi.tools.browser_smart import SmartElementFinder, ObstacleDetector


@pytest.mark.asyncio
async def test_smart_element_finder_tries_multiple_strategies():
    """Test that SmartElementFinder tries cascading strategies."""
    
    # Mock page that fails CSS but succeeds with text search
    mock_page = AsyncMock()
    
    # First strategy (CSS hint) fails
    mock_css_locator = AsyncMock()
    mock_css_locator.count.return_value = 0
    
    # Second strategy (text search) succeeds
    mock_text_locator = AsyncMock()
    mock_text_locator.count.return_value = 1
    mock_text_locator.is_visible.return_value = True
    
    mock_page.locator.return_value.first = mock_css_locator
    mock_page.get_by_text.return_value.first = mock_text_locator
    
    finder = SmartElementFinder(mock_page)
    locator, strategy = await finder.find(
        intent="search button",
        hint="#nonexistent",
        timeout=2.0
    )
    
    assert locator is not None
    assert strategy in ["exact_text", "partial_text"]
    assert mock_page.locator.called  # Tried CSS first


@pytest.mark.asyncio
async def test_smart_element_finder_returns_none_when_all_fail():
    """Test that finder returns None when all strategies fail."""
    
    mock_page = AsyncMock()
    
    # All strategies fail
    mock_locator = AsyncMock()
    mock_locator.count.return_value = 0
    
    mock_page.locator.return_value.first = mock_locator
    mock_page.get_by_text.return_value.first = mock_locator
    mock_page.get_by_placeholder.return_value.first = mock_locator
    mock_page.get_by_label.return_value.first = mock_locator
    mock_page.get_by_role.return_value = mock_locator
    
    finder = SmartElementFinder(mock_page)
    locator, strategy = await finder.find(
        intent="nonexistent element",
        timeout=0.5
    )
    
    assert locator is None
    assert strategy == "none"


@pytest.mark.asyncio
async def test_obstacle_detector_finds_cookie_banner():
    """Test that obstacle detector can identify cookie banners."""
    
    mock_page = AsyncMock()
    
    # Cookie banner is visible
    mock_cookie_elem = AsyncMock()
    mock_cookie_elem.is_visible.return_value = True
    
    mock_page.query_selector_all.return_value = [mock_cookie_elem]
    mock_page.locator.return_value.first.is_visible.return_value = True
    mock_page.locator.return_value.first.click = AsyncMock()
    
    detector = ObstacleDetector(mock_page)
    result = await detector.detect_and_clear(timeout=1.0)
    
    assert "cookie_banner" in result["obstacles_found"]
    assert result["success"]


@pytest.mark.asyncio
async def test_obstacle_detector_returns_empty_when_clean_page():
    """Test that detector returns empty results on clean pages."""
    
    mock_page = AsyncMock()
    
    # No obstacles visible
    mock_page.query_selector_all.return_value = []
    mock_locator = AsyncMock()
    mock_locator.is_visible.return_value = False
    mock_page.locator.return_value.first = mock_locator
    
    detector = ObstacleDetector(mock_page)
    result = await detector.detect_and_clear(timeout=0.5)
    
    assert result["obstacles_found"] == []
    assert result["obstacles_cleared"] == []
    assert result["success"]


@pytest.mark.asyncio
async def test_smart_finder_tries_aria_role():
    """Test that finder can match by ARIA role."""
    
    mock_page = AsyncMock()
    
    # CSS fails, ARIA succeeds
    mock_css = AsyncMock()
    mock_css.count.return_value = 0
    
    mock_aria = AsyncMock()
    mock_aria.count.return_value = 1
    mock_aria.is_visible.return_value = True
    
    mock_page.locator.return_value.first = mock_css
    mock_page.get_by_role.return_value = mock_aria
    
    finder = SmartElementFinder(mock_page)
    locator, strategy = await finder.find(
        intent="submit button",
        timeout=1.0
    )
    
    assert locator is not None
    assert "aria_role" in strategy


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
