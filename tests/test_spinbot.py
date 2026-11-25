import unittest
from types import SimpleNamespace

from spinbot import (
    BotConfig,
    classify_button_text,
    find_matching_frames,
    find_matching_page,
    normalize_text,
    parse_args,
    parse_continue_labels,
)


class SpinbotUnitTests(unittest.TestCase):
    def test_normalize_text(self) -> None:
        self.assertEqual(normalize_text("  spin \n "), "SPIN")
        self.assertEqual(normalize_text("Stop"), "STOP")
        self.assertEqual(normalize_text(None), "")

    def test_classify_button_text(self) -> None:
        self.assertEqual(classify_button_text("SPIN"), "ready")
        self.assertEqual(classify_button_text("  spin  "), "ready")
        self.assertEqual(classify_button_text("STOP"), "busy")
        self.assertEqual(classify_button_text("AUTOPLAY"), "other")
        self.assertEqual(classify_button_text(""), "other")

    def test_find_matching_page_skips_devtools_and_matches_url(self) -> None:
        devtools = SimpleNamespace(url="devtools://devtools/bundled/inspector.html")
        other = SimpleNamespace(url="https://example.com/")
        target = SimpleNamespace(
            url="https://staging.playin.com/playin/tournaments/zwm3s2x5ss1x/play"
        )
        browser = SimpleNamespace(
            contexts=[SimpleNamespace(pages=[devtools, other, target])]
        )

        self.assertIs(find_matching_page(browser, "staging.playin.com"), target)
        self.assertIs(find_matching_page(browser, ""), other)
        self.assertIsNone(find_matching_page(browser, "not-found.example"))

    def test_find_matching_frames(self) -> None:
        inner_frame = SimpleNamespace(
            url="https://fansite2.uat1.evo-test.com/frontend/evo/r1/#inner"
        )
        evo_frame = SimpleNamespace(
            url="https://fansite2.uat1.evo-test.com/frontend/evo/r1/#provider=netent",
            child_frames=[inner_frame],
        )
        main_frame = SimpleNamespace(url="https://staging.playin.com/play")
        page = SimpleNamespace(main_frame=main_frame, frames=[main_frame, evo_frame])

        self.assertEqual(
            find_matching_frames(page, "evo-test.com"), [inner_frame, evo_frame]
        )
        # Empty match prioritizes deepest child frames before main frame.
        self.assertEqual(
            find_matching_frames(page, ""), [inner_frame, evo_frame, main_frame]
        )

    def test_parse_args(self) -> None:
        cfg = parse_args(
            ["--max-clicks", "25", "--iframe-match", "evo/r1", "--show-marker"]
        )
        self.assertEqual(cfg.max_clicks, 25)
        self.assertEqual(cfg.iframe_url_match, "evo/r1")
        self.assertEqual(cfg.cdp_url, "http://localhost:9222")
        self.assertEqual(cfg.continue_text, "CONTINUE")
        self.assertEqual(cfg.canvas_fallback_delay, 2.0)
        self.assertEqual(cfg.canvas_click_x, 0.5)
        self.assertEqual(cfg.canvas_click_y, 0.8)
        self.assertTrue(cfg.show_marker)
        self.assertFalse(cfg.preview_canvas_click)
        self.assertIsInstance(cfg, BotConfig)

    def test_parse_continue_labels(self) -> None:
        self.assertEqual(parse_continue_labels("CONTINUE"), ["CONTINUE"])
        self.assertEqual(parse_continue_labels("Continue, OK , "), ["Continue", "OK"])
        self.assertEqual(parse_continue_labels(""), [])


if __name__ == "__main__":
    unittest.main()
