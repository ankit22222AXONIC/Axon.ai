"""Tests for AXON browser automation — YouTube search, video playback, and link clicking."""

from unittest.mock import patch, MagicMock
import pytest

from axon.core import Axon
from axon.tools.browser import (
    browser_open,
    browser_search,
    browser_youtube_search,
    browser_play_video,
    browser_click_first_result,
    browser_click_link,
    _get_first_youtube_video,
)
from axon.tools.applications import applications_open


def test_browser_tools_registered_in_axon():
    """Verify all browser tools are properly registered in Axon runtime."""
    axon = Axon().start()
    assert axon.registry.exists("browser.open")
    assert axon.registry.exists("browser.search")
    assert axon.registry.exists("browser.youtube_search")
    assert axon.registry.exists("browser.play_video")
    assert axon.registry.exists("browser.click_first_result")
    assert axon.registry.exists("browser.click_link")
    axon.shutdown()


def test_browser_open_handles_shortcuts():
    """Verify browser_open handles standard URLs and yt/youtube shortcuts."""
    with patch("webbrowser.open", return_value=True) as mock_open:
        res1 = browser_open("https://github.com")
        assert res1["status"] == "success"
        assert res1["url"] == "https://github.com"
        mock_open.assert_called_with("https://github.com")

        res2 = browser_open("yt")
        assert res2["status"] == "success"
        assert res2["url"] == "https://www.youtube.com"
        mock_open.assert_called_with("https://www.youtube.com")

        res3 = browser_open("youtube")
        assert res3["status"] == "success"
        assert res3["url"] == "https://www.youtube.com"


def test_browser_search_with_youtube_engine():
    """Verify browser_search routes to YouTube when engine='youtube' or 'yt'."""
    with patch("webbrowser.open", return_value=True) as mock_open:
        res = browser_search("polynomial", engine="youtube")
        assert res["status"] == "success"
        assert "results?search_query=polynomial" in res["url"]


def test_browser_youtube_search_play_first():
    """Verify browser_youtube_search fetches the top video and opens it when play_first=True."""
    with patch("axon.tools.browser._get_first_youtube_video", return_value=("vid12345678", "https://www.youtube.com/watch?v=vid12345678")):
        with patch("webbrowser.open", return_value=True) as mock_open:
            res = browser_youtube_search("polynomial", play_first=True)
            assert res["status"] == "success"
            assert res["action"] == "played_first_video"
            assert res["video_id"] == "vid12345678"
            assert res["url"] == "https://www.youtube.com/watch?v=vid12345678"
            mock_open.assert_called_with("https://www.youtube.com/watch?v=vid12345678")


def test_browser_play_video_shortcut():
    """Verify browser_play_video calls youtube search with play_first=True."""
    with patch("axon.tools.browser._get_first_youtube_video", return_value=("abc12345678", "https://www.youtube.com/watch?v=abc12345678")):
        with patch("webbrowser.open", return_value=True):
            res = browser_play_video("lofi beats")
            assert res["status"] == "success"
            assert res["video_id"] == "abc12345678"


def test_browser_click_first_result():
    """Verify browser_click_first_result computes screen coordinates and triggers click."""
    with patch("axon.tools.browser._focus_browser_window", return_value=True):
        with patch("axon.tools.desktop.get_screen_bounds", return_value=(1920, 1080)):
            with patch("axon.tools.desktop.mouse_move", return_value={"status": "success"}):
                with patch("axon.tools.desktop.mouse_click", return_value={"status": "success"}) as mock_click:
                    res = browser_click_first_result()
                    assert res["status"] == "success"
                    assert res["action"] == "clicked_first_result"
                    # target_x = int(1920 * 0.38) = 729, target_y = int(1080 * 0.33) = 356
                    assert res["coordinates"]["x"] == 729
                    assert res["coordinates"]["y"] == 356
                    mock_click.assert_called_with(729, 356)


def test_browser_click_link():
    """Verify browser_click_link executes find-and-activate keyboard sequence."""
    with patch("axon.tools.browser._focus_browser_window", return_value=True):
        with patch("axon.tools.desktop.keyboard_hotkey") as mock_hotkey:
            with patch("axon.tools.desktop.keyboard_type") as mock_type:
                with patch("axon.tools.desktop.keyboard_press") as mock_press:
                    res = browser_click_link("Subscribe")
                    assert res["status"] == "success"
                    assert res["action"] == "clicked_link"
                    assert res["text"] == "Subscribe"
                    mock_hotkey.assert_called_with("ctrl+f")
                    mock_type.assert_called_with("Subscribe")
                    assert mock_press.call_count == 2  # escape then enter


def test_applications_open_handles_yt_alias():
    """Verify applications_open handles 'yt' and 'youtube' aliases gracefully."""
    with patch("os.startfile", return_value=None) as mock_startfile:
        res = applications_open("yt")
        assert res["status"] == "success"
        mock_startfile.assert_called_with("https://www.youtube.com")
