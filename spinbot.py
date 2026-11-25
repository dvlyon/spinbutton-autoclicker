#!/usr/bin/env python3
"""Playwright CDP autoclicker for a SPIN/STOP button inside an iframe.

Attaches to an existing Chrome window over Chrome DevTools Protocol (CDP)
so clicks are dispatched without stealing macOS window focus.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class BotConfig:
    """Runtime configuration for the spin button autoclicker."""

    cdp_url: str = "http://localhost:9222"
    url_match: str = "staging.playin.com"
    iframe_url_match: str = ""
    button_selector: str | None = None
    ready_text: str = "SPIN"
    busy_text: str = "STOP"
    continue_text: str = "CONTINUE"
    canvas_fallback_delay: float = 2.0
    canvas_click_x: float = 0.5
    canvas_click_y: float = 0.8
    show_marker: bool = False
    preview_canvas_click: bool = False
    max_clicks: int = 0
    poll_interval: float = 0.25
    post_click_delay: float = 0.4
    click_timeout_ms: int = 3000
    js_click: bool = False
    inspect: bool = False


def normalize_text(text: str | None) -> str:
    """Collapse whitespace and uppercase text for reliable comparisons."""
    if not text:
        return ""
    return " ".join(text.split()).strip().upper()


def classify_button_text(
    text: str | None,
    ready_text: str = "SPIN",
    busy_text: str = "STOP",
) -> str:
    """Classify a button's text as 'ready', 'busy', or 'other'."""
    normalized = normalize_text(text)
    if not normalized:
        return "other"
    if normalized == normalize_text(ready_text):
        return "ready"
    if normalized == normalize_text(busy_text):
        return "busy"
    return "other"


def is_regular_page_url(url: str) -> bool:
    """Return True for normal web pages (ignoring DevTools/extension pages)."""
    lowered = url.lower()
    return not (
        lowered.startswith("devtools://")
        or lowered.startswith("chrome-extension://")
        or lowered.startswith("chrome://")
    )


def find_matching_page(browser: Any, url_match: str) -> Any | None:
    """Find the first open tab matching `url_match` across all browser contexts."""
    needle = url_match.strip().lower()
    for context in browser.contexts:
        for page in context.pages:
            page_url = getattr(page, "url", "") or ""
            if not is_regular_page_url(page_url):
                continue
            if not needle or needle in page_url.lower():
                return page
    return None


def _collect_frame_tree(root_frames: list[Any], main_frame: Any | None) -> list[Any]:
    """Recursively collect frames, including nested child/content frames."""
    ordered: list[Any] = []
    seen: set[int] = set()

    def visit(frame: Any) -> None:
        if frame is None or id(frame) in seen:
            return
        seen.add(id(frame))

        # Visit nested frames first so deepest game iframes are checked first.
        for child in getattr(frame, "child_frames", []) or []:
            visit(child)

        if hasattr(frame, "locator"):
            try:
                iframe_loc = frame.locator("iframe")
                count = iframe_loc.count()
                for idx in range(count):
                    handle = iframe_loc.nth(idx).element_handle(timeout=300)
                    if handle is not None:
                        visit(handle.content_frame())
            except Exception:
                pass

        if frame is not main_frame:
            ordered.append(frame)

    for frame in root_frames:
        if frame is not main_frame:
            visit(frame)
    if main_frame is not None and main_frame in root_frames:
        visit(main_frame)
        ordered.append(main_frame)

    return ordered


def find_matching_frames(page: Any, iframe_url_match: str) -> list[Any]:
    """Return frames on `page` matching `iframe_url_match`, or all frames if empty."""
    needle = iframe_url_match.strip().lower()
    root_frames = list(getattr(page, "frames", []) or [])
    main_frame = getattr(page, "main_frame", None)
    frames = _collect_frame_tree(root_frames, main_frame)

    if needle:
        return [
            frame
            for frame in frames
            if needle in ((getattr(frame, "url", "") or "").lower())
        ]
    return frames


def _pick_matching_locator(
    locator: Any,
    ready_text: str,
    busy_text: str,
) -> tuple[Any, str] | None:
    """Inspect elements matched by `locator` and return the first ready/busy match."""
    try:
        count = locator.count()
    except Exception:
        return None

    for idx in range(count):
        candidate = locator.nth(idx)
        try:
            if not candidate.is_visible():
                continue
            text = candidate.inner_text(timeout=1000)
            state = classify_button_text(text, ready_text, busy_text)
            if state == "other":
                aria = candidate.get_attribute("aria-label", timeout=500)
                state = classify_button_text(aria, ready_text, busy_text)
        except Exception:
            continue

        if state in ("ready", "busy"):
            return candidate, state
    return None


def locate_spin_button(frames: Iterable[Any], config: BotConfig) -> tuple[Any, Any, str] | None:
    """Search candidate frames for the SPIN/STOP button.

    Returns `(frame, locator, state)` if found, otherwise `None`.
    """
    for frame in frames:
        if config.button_selector:
            found = _pick_matching_locator(
                frame.locator(config.button_selector),
                config.ready_text,
                config.busy_text,
            )
            if found:
                return frame, found[0], found[1]
            continue

        # Agnostic lookup: check standard button elements first, then exact text nodes.
        found = _pick_matching_locator(
            frame.locator('button, [role="button"]'),
            config.ready_text,
            config.busy_text,
        )
        if found:
            return frame, found[0], found[1]

        for target_text in (config.ready_text, config.busy_text):
            pattern = re.compile(rf"^\s*{re.escape(target_text)}\s*$", re.IGNORECASE)
            found = _pick_matching_locator(
                frame.get_by_text(pattern),
                config.ready_text,
                config.busy_text,
            )
            if found:
                return frame, found[0], found[1]

    return None


def parse_continue_labels(continue_text: str) -> list[str]:
    """Split comma-separated popup button labels into normalized non-empty strings."""
    return [part.strip() for part in continue_text.split(",") if part.strip()]


def locate_continue_button(
    frames: Iterable[Any], config: BotConfig
) -> tuple[Any, Any, str] | None:
    """Search candidate frames for a popup Continue/dismiss button."""
    labels = parse_continue_labels(config.continue_text)
    if not labels:
        return None

    for frame in frames:
        for label in labels:
            found = _pick_matching_locator(
                frame.locator('button, [role="button"]'),
                label,
                "__unused__",
            )
            if found and found[1] == "ready":
                return frame, found[0], label

            pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
            found = _pick_matching_locator(
                frame.get_by_text(pattern),
                label,
                "__unused__",
            )
            if found and found[1] == "ready":
                return frame, found[0], label

    return None


def inspect_browser(browser: Any, config: BotConfig) -> int:
    """Print open pages, matching frames, and detected button state without clicking."""
    print(f"Connected to CDP at {config.cdp_url}")
    print("\nOpen pages:")
    for ctx_idx, context in enumerate(browser.contexts):
        for page_idx, page in enumerate(context.pages):
            print(f"  [{ctx_idx}:{page_idx}] {page.url}")

    page = find_matching_page(browser, config.url_match)
    if page is None:
        print(f"\nNo page matched --url-match={config.url_match!r}")
        return 1

    print(f"\nMatched page: {page.url}")
    all_frames = list(page.frames)
    print(f"Frames on page ({len(all_frames)}):")
    for idx, frame in enumerate(all_frames):
        frame_name = getattr(frame, "name", "") or ""
        print(f"  [{idx}] url={frame.url!r} name={frame_name!r}")

    matched_frames = find_matching_frames(page, config.iframe_url_match)
    print(
        f"\nFrames matching --iframe-match={config.iframe_url_match!r}: "
        f"{len(matched_frames)}"
    )

    result = locate_spin_button(matched_frames, config)
    continue_result = locate_continue_button(matched_frames, config)

    if continue_result is not None:
        c_frame, _, c_label = continue_result
        print(f"Found continue button ({c_label!r}) in frame: {c_frame.url!r}")
    else:
        print(f"Continue button ({config.continue_text!r}) was not found.")

    if result is not None:
        frame, locator, state = result
        print(f"Found spin button in frame: {frame.url!r}")
        text = normalize_text(locator.inner_text()) or normalize_text(
            locator.get_attribute("aria-label")
        )
        print(f"Current spin state: {state} (label={text!r})")
    else:
        print(
            f"Button with text {config.ready_text!r} or {config.busy_text!r} "
            "was not found in matching frames."
        )

    if result is None or continue_result is None:
        for idx, frame in enumerate(matched_frames):
            try:
                btn_count = frame.locator('button, [role="button"]').count()
                body_preview = normalize_text(frame.locator("body").inner_text(timeout=1000))[:160]
                diag = frame.evaluate(
                    """() => {
                        const body = document.body;
                        if (!body) return { htmlLen: 0, canvases: 0, iframes: [], matches: [], buttons: [] };
                        const canvases = document.querySelectorAll('canvas').length;
                        const iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({
                            id: f.id || '',
                            name: f.name || '',
                            src: (f.getAttribute('src') || '').slice(0, 120),
                        }));
                        const buttons = [];
                        const matches = [];
                        const walk = (root) => {
                            for (const el of root.querySelectorAll('*')) {
                                const txt = (el.innerText || el.textContent || '').trim();
                                const attrs = [el.id, el.className, el.getAttribute('aria-label'), el.getAttribute('data-role')]
                                    .filter(Boolean).join(' ');
                                if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') {
                                    if (buttons.length < 20) {
                                        buttons.push(`${el.tagName.toLowerCase()}[${txt.slice(0,30)}](aria=${el.getAttribute('aria-label') || ''})`);
                                    }
                                }
                                if (/spin|stop|continue/i.test(txt) || /spin|continue/i.test(attrs)) {
                                    if (matches.length < 15 && txt.length < 80) {
                                        matches.push(`${el.tagName.toLowerCase()}#${el.id}.${String(el.className).slice(0,30)}[${txt.slice(0,40)}]`);
                                    }
                                }
                                if (el.shadowRoot) walk(el.shadowRoot);
                            }
                        };
                        walk(document);
                        return { htmlLen: body.innerHTML.length, canvases, iframes, matches, buttons };
                    }"""
                )
                print(
                    f"  Frame [{idx}] ({frame.url!r}): "
                    f"buttons={btn_count}, canvases={diag['canvases']}, iframes={len(diag['iframes'])}, "
                    f"html_len={diag['htmlLen']}, text_preview={body_preview!r}"
                )
                if diag["buttons"]:
                    print(f"    buttons: {diag['buttons']}")
                if diag["matches"]:
                    print(f"    spin/stop/continue matches: {diag['matches']}")
            except Exception as exc:
                print(f"  Frame [{idx}] ({frame.url!r}): unreadable ({exc})")

    return 0 if (result is not None or continue_result is not None) else 1


def click_locator(locator: Any, config: BotConfig) -> None:
    """Click the target button without stealing window focus."""
    if config.js_click:
        locator.evaluate("el => el.click()")
    else:
        locator.click(timeout=config.click_timeout_ms, no_wait_after=True)


def locate_largest_canvas(frames: Iterable[Any]) -> tuple[Any, dict[str, float]] | None:
    """Find the largest visible `<canvas>` across candidate frames."""
    best: tuple[float, Any, dict[str, float]] | None = None
    for frame in frames:
        try:
            canvases = frame.locator("canvas")
            count = canvases.count()
        except Exception:
            continue

        for idx in range(count):
            canvas = canvases.nth(idx)
            try:
                if not canvas.is_visible():
                    continue
                box = canvas.bounding_box()
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    continue
                area = box["width"] * box["height"]
                if best is None or area > best[0]:
                    best = (area, canvas, box)
            except Exception:
                continue

    if best is None:
        return None
    return best[1], best[2]


def draw_canvas_marker(
    canvas: Any,
    x_ratio: float,
    y_ratio: float,
    duration_ms: int = 2500,
) -> None:
    """Render a temporary non-interactive crosshair on the canvas at `(x_ratio, y_ratio)`."""
    label = f"({int(round(x_ratio * 100))}%, {int(round(y_ratio * 100))}%)"
    canvas.evaluate(
        """(el, args) => {
            const rect = el.getBoundingClientRect();
            const x = rect.left + rect.width * args.xRatio;
            const y = rect.top + rect.height * args.yRatio;

            const old = document.getElementById('__spinbot_click_marker');
            if (old) old.remove();

            const root = document.createElement('div');
            root.id = '__spinbot_click_marker';
            Object.assign(root.style, {
                position: 'fixed',
                left: `${x}px`,
                top: `${y}px`,
                transform: 'translate(-50%, -50%)',
                pointerEvents: 'none',
                zIndex: '2147483647',
            });

            const ring = document.createElement('div');
            Object.assign(ring.style, {
                width: '28px',
                height: '28px',
                borderRadius: '50%',
                border: '3px solid #ff2d55',
                boxShadow: '0 0 0 2px #ffffff, 0 0 10px rgba(0,0,0,0.8)',
                background: 'rgba(255, 45, 85, 0.2)',
                position: 'relative',
            });

            const dot = document.createElement('div');
            Object.assign(dot.style, {
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: '#ff2d55',
                border: '1px solid #ffffff',
                position: 'absolute',
                left: '50%',
                top: '50%',
                transform: 'translate(-50%, -50%)',
            });
            ring.appendChild(dot);

            const badge = document.createElement('div');
            badge.textContent = args.label;
            Object.assign(badge.style, {
                marginTop: '4px',
                padding: '2px 6px',
                borderRadius: '4px',
                background: 'rgba(0, 0, 0, 0.85)',
                color: '#ffffff',
                fontFamily: 'monospace',
                fontSize: '12px',
                fontWeight: 'bold',
                textAlign: 'center',
                whiteSpace: 'nowrap',
            });

            root.appendChild(ring);
            root.appendChild(badge);
            document.body.appendChild(root);

            setTimeout(() => {
                if (root.parentNode) root.remove();
            }, args.durationMs);
        }""",
        {"xRatio": x_ratio, "yRatio": y_ratio, "label": label, "durationMs": duration_ms},
    )


def click_canvas_fallback(frames: Iterable[Any], config: BotConfig) -> bool:
    """Click relative `(canvas_click_x, canvas_click_y)` on the largest visible canvas."""
    found = locate_largest_canvas(frames)
    if found is None:
        return False

    canvas, box = found
    if config.show_marker:
        try:
            draw_canvas_marker(canvas, config.canvas_click_x, config.canvas_click_y)
        except Exception:
            pass

    pos_x = box["width"] * config.canvas_click_x
    pos_y = box["height"] * config.canvas_click_y
    canvas.click(
        position={"x": pos_x, "y": pos_y},
        timeout=config.click_timeout_ms,
        no_wait_after=True,
    )
    return True


def run_bot(config: BotConfig) -> int:
    """Connect to Chrome via CDP and run the autoclick loop."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(config.cdp_url)
        except Exception as exc:
            print(
                f"Failed to connect to Chrome CDP at {config.cdp_url}: {exc}\n"
                "Make sure Chrome was started with --remote-debugging-port=9222 "
                "(e.g. ./launch_chrome.sh).",
                file=sys.stderr,
            )
            return 1

        if config.inspect:
            return inspect_browser(browser, config)

        page = find_matching_page(browser, config.url_match)
        if page is None:
            print(
                f"No open tab matched --url-match={config.url_match!r}. "
                "Run with --inspect to list open tabs.",
                file=sys.stderr,
            )
            return 1

        if config.preview_canvas_click:
            frames = find_matching_frames(page, config.iframe_url_match)
            found = locate_largest_canvas(frames)
            if found is None:
                print("No visible <canvas> found in matching frames.", file=sys.stderr)
                return 1
            canvas, box = found
            draw_canvas_marker(
                canvas, config.canvas_click_x, config.canvas_click_y, duration_ms=5000
            )
            x_pct = int(round(config.canvas_click_x * 100))
            y_pct = int(round(config.canvas_click_y * 100))
            print(
                f"Drew target marker at ({x_pct}%, {y_pct}%) on canvas "
                f"({int(box['width'])}x{int(box['height'])}) for 5s."
            )
            return 0

        limit_label = str(config.max_clicks) if config.max_clicks > 0 else "unlimited"
        print(
            f"Attached to tab: {page.url}\n"
            f"Watching iframe={config.iframe_url_match!r} for "
            f"{config.ready_text!r}/{config.busy_text!r} (max_clicks={limit_label}). "
            "Press Ctrl+C to stop."
        )

        clicks = 0
        last_state: str | None = None
        missing_since: float | None = None

        try:
            while config.max_clicks == 0 or clicks < config.max_clicks:
                frames = find_matching_frames(page, config.iframe_url_match)

                continue_match = locate_continue_button(frames, config)
                if continue_match is not None:
                    missing_since = None
                    _, c_locator, c_label = continue_match
                    try:
                        if c_locator.is_enabled():
                            click_locator(c_locator, config)
                            last_state = "continue"
                            print(f"[popup] Clicked {c_label}")
                            time.sleep(config.post_click_delay)
                            continue
                    except Exception as exc:
                        print(f"Popup click failed ({exc}); retrying...")
                        time.sleep(config.poll_interval)
                        continue

                found = locate_spin_button(frames, config)

                if found is None:
                    now = time.monotonic()
                    if missing_since is None:
                        missing_since = now
                    if last_state != "missing":
                        print("Waiting for SPIN/STOP button to appear in iframe...")
                        last_state = "missing"

                    if (
                        config.canvas_fallback_delay > 0
                        and (now - missing_since) >= config.canvas_fallback_delay
                    ):
                        try:
                            if click_canvas_fallback(frames, config):
                                x_pct = int(round(config.canvas_click_x * 100))
                                y_pct = int(round(config.canvas_click_y * 100))
                                print(
                                    f"[popup] Clicked canvas fallback at ({x_pct}%, {y_pct}%)"
                                )
                                missing_since = time.monotonic()
                                last_state = "canvas_fallback"
                                time.sleep(config.post_click_delay)
                                continue
                        except Exception as exc:
                            print(f"Canvas fallback click failed ({exc}); retrying...")
                            missing_since = time.monotonic()

                    time.sleep(config.poll_interval)
                    continue

                missing_since = None
                _, locator, state = found

                if state == "ready":
                    try:
                        if not locator.is_enabled():
                            if last_state != "disabled":
                                print("Button is SPIN but currently disabled; waiting...")
                                last_state = "disabled"
                            time.sleep(config.poll_interval)
                            continue

                        click_locator(locator, config)
                        clicks += 1
                        last_state = "clicked"
                        print(f"[click {clicks}/{limit_label}] Clicked {config.ready_text}")
                        time.sleep(config.post_click_delay)
                        continue
                    except Exception as exc:
                        print(f"Click attempt failed ({exc}); retrying...")
                        last_state = "error"
                        time.sleep(config.poll_interval)
                        continue

                if state == "busy" and last_state != "busy":
                    print(f"Button is {config.busy_text}; waiting for next {config.ready_text}...")
                    last_state = "busy"

                time.sleep(config.poll_interval)
        except KeyboardInterrupt:
            print(f"\nStopped by user after {clicks} click(s).")
            return 0

        print(f"Reached max clicks ({clicks}). Done!")
        return 0


def parse_args(argv: list[str] | None = None) -> BotConfig:
    """Parse CLI arguments into a `BotConfig`."""
    parser = argparse.ArgumentParser(
        description="Click a SPIN button inside an iframe via Chrome CDP without stealing focus."
    )
    parser.add_argument(
        "--cdp-url",
        default="http://localhost:9222",
        help="Chrome remote debugging endpoint (default: http://localhost:9222)",
    )
    parser.add_argument(
        "--url-match",
        default="staging.playin.com",
        help="Substring to match the target browser tab URL (empty = first tab)",
    )
    parser.add_argument(
        "--iframe-match",
        default="",
        help="Substring to match the target iframe URL (default: '' = scan all frames)",
    )
    parser.add_argument(
        "--button-selector",
        default=None,
        help="Optional CSS selector for the button inside the iframe",
    )
    parser.add_argument(
        "--ready-text",
        default="SPIN",
        help="Button text when clickable (default: SPIN)",
    )
    parser.add_argument(
        "--busy-text",
        default="STOP",
        help="Button text while spinning (default: STOP)",
    )
    parser.add_argument(
        "--continue-text",
        default="CONTINUE",
        help="Comma-separated popup button text(s) to dismiss without counting as a spin; '' = disabled (default: CONTINUE)",
    )
    parser.add_argument(
        "--canvas-fallback-delay",
        type=float,
        default=2.0,
        help="Seconds with no SPIN/STOP button before clicking canvas fallback; 0 = disabled (default: 2.0)",
    )
    parser.add_argument(
        "--canvas-click-x",
        type=float,
        default=0.5,
        help="Relative X position (0.0-1.0) for canvas fallback click (default: 0.5)",
    )
    parser.add_argument(
        "--canvas-click-y",
        type=float,
        default=0.8,
        help="Relative Y position (0.0-1.0) for canvas fallback click (default: 0.8)",
    )
    parser.add_argument(
        "--show-marker",
        action="store_true",
        help="Flash a visual target marker on the canvas when performing a fallback click",
    )
    parser.add_argument(
        "--preview-canvas-click",
        action="store_true",
        help="Draw the canvas fallback target marker for 5s without clicking, then exit",
    )
    parser.add_argument(
        "-n",
        "--max-clicks",
        type=int,
        default=0,
        help="Maximum number of clicks before exiting; 0 = unlimited (default: 0)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.25,
        help="Seconds between status checks (default: 0.25)",
    )
    parser.add_argument(
        "--post-click-delay",
        type=float,
        default=0.4,
        help="Seconds to wait after a click before polling again (default: 0.4)",
    )
    parser.add_argument(
        "--click-timeout-ms",
        type=int,
        default=3000,
        help="Playwright click timeout in milliseconds (default: 3000)",
    )
    parser.add_argument(
        "--js-click",
        action="store_true",
        help="Dispatch DOM element.click() via JS instead of Playwright pointer click",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="List open tabs, frames, and detected button state without clicking",
    )

    args = parser.parse_args(argv)
    if args.max_clicks < 0:
        parser.error("--max-clicks must be >= 0")

    return BotConfig(
        cdp_url=args.cdp_url,
        url_match=args.url_match,
        iframe_url_match=args.iframe_match,
        button_selector=args.button_selector,
        ready_text=args.ready_text,
        busy_text=args.busy_text,
        continue_text=args.continue_text,
        canvas_fallback_delay=args.canvas_fallback_delay,
        canvas_click_x=args.canvas_click_x,
        canvas_click_y=args.canvas_click_y,
        show_marker=args.show_marker,
        preview_canvas_click=args.preview_canvas_click,
        max_clicks=args.max_clicks,
        poll_interval=args.poll_interval,
        post_click_delay=args.post_click_delay,
        click_timeout_ms=args.click_timeout_ms,
        js_click=args.js_click,
        inspect=args.inspect,
    )


def main() -> int:
    config = parse_args()
    return run_bot(config)


if __name__ == "__main__":
    raise SystemExit(main())
