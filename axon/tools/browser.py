"""Browser automation tools — opening websites, YouTube video navigation, searching, and clicking links."""

import re
import time
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional, Dict, Any, Tuple


SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "bing": "https://www.bing.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "yt": "https://www.youtube.com/results?search_query={}",
}


def _get_first_youtube_video(query: str) -> Tuple[Optional[str], Optional[str]]:
    """Query YouTube search results to extract the top video ID and URL.
    
    Returns:
        (video_id, watch_url) or (None, None)
    """
    try:
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://www.youtube.com/results?search_query={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            # Extract video IDs from /watch?v= URLs
            matches = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
            if matches:
                # Deduplicate while preserving order
                seen = set()
                unique_vids = [v for v in matches if not (v in seen or seen.add(v))]
                if unique_vids:
                    first_id = unique_vids[0]
                    return first_id, f"https://www.youtube.com/watch?v={first_id}"
    except Exception:
        pass
    return None, None


def _focus_browser_window() -> bool:
    """Attempt to bring the active or any open browser window into the foreground."""
    try:
        from axon.tools.desktop import desktop_switch_window
        for target in ("youtube", "chrome", "edge", "msedge", "firefox", "brave", "opera", "browser"):
            res = desktop_switch_window(target)
            if res.get("status") == "success" and res.get("switched"):
                return True
    except Exception:
        pass
    return False


def browser_open(url: str) -> Dict[str, Any]:
    """Open a URL in the default web browser. Also supports 'yt' or 'youtube' shortcuts.
    
    Args:
        url: The web URL or address to open (e.g. 'https://github.com', 'youtube.com', or 'yt').
    """
    if not url or not url.strip():
        return {"error": "No URL provided"}

    target = url.strip()
    target_lower = target.lower()

    # Friendly shortcuts
    if target_lower in ("yt", "youtube"):
        target = "https://www.youtube.com"
    elif target_lower.startswith("yt ") or target_lower.startswith("youtube "):
        query = target.split(" ", 1)[1].strip()
        return browser_youtube_search(query=query, play_first=False)
    elif not (target.startswith("http://") or target.startswith("https://") or target.startswith("file://")):
        target = "https://" + target

    try:
        opened = webbrowser.open(target)
        return {
            "status": "success" if opened else "dispatched",
            "url": target,
        }
    except Exception as e:
        return {"error": f"Failed to open browser: {e}"}


def browser_search(query: str, engine: str = "google") -> Dict[str, Any]:
    """Search the web or YouTube using the default web browser.
    
    Args:
        query: Search keywords or question.
        engine: Search engine to use ('google', 'duckduckgo', 'bing', 'youtube'). Defaults to 'google'.
    """
    if not query or not query.strip():
        return {"error": "No search query provided"}

    eng = engine.lower().strip()
    if eng in ("youtube", "yt"):
        return browser_youtube_search(query=query, play_first=False)

    template = SEARCH_ENGINES.get(eng, SEARCH_ENGINES["google"])
    encoded_query = urllib.parse.quote_plus(query.strip())
    search_url = template.format(encoded_query)

    try:
        opened = webbrowser.open(search_url)
        return {
            "status": "success" if opened else "dispatched",
            "query": query.strip(),
            "engine": eng,
            "url": search_url,
        }
    except Exception as e:
        return {"error": f"Failed to execute web search: {e}"}


def browser_youtube_search(query: str, play_first: bool = False) -> Dict[str, Any]:
    """Search YouTube for videos. If play_first is True, automatically clicks/plays the first video result.
    
    Args:
        query: Search keywords for YouTube (e.g. 'polynomial', 'python tutorial').
        play_first: If True, immediately opens and plays the first video result. Defaults to False.
    """
    if not query or not query.strip():
        return {"error": "No YouTube search query provided"}

    clean_query = query.strip()

    if play_first:
        vid, video_url = _get_first_youtube_video(clean_query)
        if vid and video_url:
            opened = webbrowser.open(video_url)
            return {
                "status": "success" if opened else "dispatched",
                "action": "played_first_video",
                "query": clean_query,
                "video_id": vid,
                "url": video_url,
            }
        else:
            # Fallback: open YouTube search results page and click first item
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean_query)}"
            webbrowser.open(search_url)
            time.sleep(1.8)
            click_res = browser_click_first_result()
            return {
                "status": "success",
                "action": "opened_search_and_clicked_first_result",
                "query": clean_query,
                "url": search_url,
                "click_result": click_res,
            }
    else:
        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean_query)}"
        opened = webbrowser.open(search_url)
        return {
            "status": "success" if opened else "dispatched",
            "action": "searched_youtube",
            "query": clean_query,
            "url": search_url,
        }


def browser_play_video(query: str) -> Dict[str, Any]:
    """Search YouTube and immediately open and play the top video result.
    
    Args:
        query: The video title or topic to play (e.g. 'polynomial', 'lofi beats').
    """
    return browser_youtube_search(query=query, play_first=True)


def browser_click_first_result() -> Dict[str, Any]:
    """Click on the first video or search result link in the currently open browser window."""
    try:
        from axon.tools.desktop import get_screen_bounds, mouse_move, mouse_click

        # Focus browser
        switched = _focus_browser_window()
        time.sleep(0.3)

        w, h = get_screen_bounds()
        # In YouTube and Google Search, the first video/result is centered in the main column
        # approximately at 38% width, 33% height
        target_x = int(w * 0.38)
        target_y = int(h * 0.33)

        mouse_move(target_x, target_y)
        time.sleep(0.1)
        click_res = mouse_click(target_x, target_y)

        return {
            "status": "success",
            "action": "clicked_first_result",
            "browser_focused": switched,
            "coordinates": {"x": target_x, "y": target_y},
            "click": click_res,
        }
    except Exception as e:
        return {"error": f"Failed to click first result: {e}"}


def browser_click_link(text: str) -> Dict[str, Any]:
    """Find and click a link with matching text in the active browser window.
    
    Uses browser in-page search to find the text and activate the hyperlink.
    
    Args:
        text: The text or title of the link/video to click.
    """
    if not text or not text.strip():
        return {"error": "No link text provided to click"}

    clean_text = text.strip()

    try:
        from axon.tools.desktop import keyboard_hotkey, keyboard_type, keyboard_press

        # Focus browser
        switched = _focus_browser_window()
        time.sleep(0.3)

        # Trigger Find in page: Ctrl+F -> type text -> Escape (leaves element focused) -> Enter
        keyboard_hotkey("ctrl+f")
        time.sleep(0.15)
        keyboard_type(clean_text)
        time.sleep(0.25)
        keyboard_press("escape")
        time.sleep(0.1)
        keyboard_press("enter")

        return {
            "status": "success",
            "action": "clicked_link",
            "text": clean_text,
            "browser_focused": switched,
            "method": "browser_find_and_activate",
        }
    except Exception as e:
        return {"error": f"Failed to click link '{clean_text}': {e}"}


def browser_close_tab(tab_title: Optional[str] = None) -> Dict[str, Any]:
    """Close the currently active browser tab or a tab matching tab_title.
    
    Uses browser shortcut Ctrl+W to close the active tab. Does NOT require approval.
    
    Args:
        tab_title: Optional title or keyword to switch to before closing the tab.
    """
    try:
        from axon.tools.desktop import desktop_switch_window, keyboard_hotkey

        focused = False
        if tab_title and str(tab_title).strip():
            target = str(tab_title).strip()
            switch_res = desktop_switch_window(target)
            if switch_res.get("status") == "success" and switch_res.get("switched"):
                focused = True

        if not focused:
            focused = _focus_browser_window()

        time.sleep(0.15)
        hotkey_res = keyboard_hotkey("ctrl+w")

        if hotkey_res.get("status") != "success":
            return {"error": f"Failed to send close tab hotkey: {hotkey_res.get('error')}"}

        return {
            "status": "success",
            "action": "closed_tab",
            "tab_title": tab_title or "active",
            "browser_focused": focused,
            "method": "ctrl_w",
            "message": f"Closed browser tab{f' matching \"{tab_title}\"' if tab_title else ''}",
        }
    except Exception as e:
        return {"error": f"Failed to close browser tab: {e}"}


def browser_close_window(browser_name: Optional[str] = None) -> Dict[str, Any]:
    """Close an entire browser window gracefully (Chrome, Edge, Firefox, etc.).
    
    Warning: Requires user approval to avoid losing unsaved tabs or ongoing work.
    
    Args:
        browser_name: Optional name of the browser (e.g. 'chrome', 'edge', 'firefox'). Defaults to active browser.
    """
    try:
        from axon.tools.desktop import desktop_close_window, desktop_get_active_window

        target_name = (browser_name or "").strip().lower()
        if not target_name:
            # Check if active window is a browser
            active = desktop_get_active_window()
            active_title = str(active.get("title", "")).lower()
            active_proc = str(active.get("process", "")).lower()
            found_browser = None
            for b in ("chrome", "edge", "msedge", "firefox", "brave", "opera"):
                if b in active_title or b in active_proc:
                    found_browser = b
                    break
            target_name = found_browser or "chrome"

        # Map common browser aliases
        alias_map = {
            "google chrome": "chrome",
            "microsoft edge": "edge",
            "msedge": "edge",
        }
        target_name = alias_map.get(target_name, target_name)

        close_res = desktop_close_window(target_name)
        if close_res.get("status") == "success":
            return {
                "status": "success",
                "action": "closed_window",
                "browser": target_name,
                "method": close_res.get("method", "wm_close"),
                "message": f"Successfully closed browser window for '{target_name}'",
            }
        else:
            return {
                "error": close_res.get("error") or f"Could not find or close open window for browser '{target_name}'",
                "browser": target_name,
            }
    except Exception as e:
        return {"error": f"Failed to close browser window: {e}"}

