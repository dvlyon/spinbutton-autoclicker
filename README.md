# spinbutton-autoclicker

Python + Playwright bot that attaches to an existing Chrome window over Chrome DevTools Protocol (CDP) and clicks a `SPIN` button inside an `<iframe>` without stealing window focus.

## Setup

1. Create and activate the virtual environment, then install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Make the Chrome launcher executable (once):

   ```bash
   chmod +x launch_chrome.sh
   ```

## Usage

### 1. Start Chrome with Remote Debugging (`--remote-debugging-port=9222`)

Run the helper script:

```bash
./launch_chrome.sh
```

> **Note:** Modern Chrome blocks `--remote-debugging-port` on your default user profile, so `launch_chrome.sh` uses a dedicated profile at `~/.chrome-spinbot-profile`. Sign in once in that window and your session will persist across restarts.

### 2. Inspect the page & iframe (dry run)

Make sure the game is open in that Chrome window, then run:

```bash
.venv/bin/python spinbot.py --inspect
```

This prints all open tabs, all frames on the matched tab, and whether the `SPIN`/`STOP` button was detected—without clicking anything.

### 3. Run the autoclicker

Click up to 50 times:

```bash
.venv/bin/python spinbot.py --max-clicks 50
```

Click indefinitely until `Ctrl+C`:

```bash
.venv/bin/python spinbot.py
```

### Useful options

- `--url-match "staging.playin.com"` — substring to match the browser tab URL (pass `""` to use the first tab).
- `--iframe-match ""` — substring to match the iframe URL (default `""` scans all frames, child frames first).
- `--button-selector "..."` — optional CSS selector if you want to target a specific element inside the iframe.
- `--ready-text "SPIN"` / `--busy-text "STOP"` — customize the button states.
- `--continue-text "CONTINUE"` — comma-separated popup button text(s) to click when a win/summary overlay appears (does not count toward `--max-clicks`; pass `""` to disable).
- `--canvas-fallback-delay 2.0` — seconds with no `SPIN`/`STOP` button before clicking the game `<canvas>` (for canvas-rendered `Continue` overlays; `0` = disabled).
- `--canvas-click-x 0.5` / `--canvas-click-y 0.8` — relative `(x, y)` coordinates on the `<canvas>` for the fallback click (default `0.5, 0.8` = horizontal center, 20% from the bottom).
- `--preview-canvas-click` — draw a 5-second target marker on the `<canvas>` without clicking so you can tune `--canvas-click-x` / `--canvas-click-y`.
- `--show-marker` — flash the target marker whenever a canvas fallback click runs.
- `--poll-interval 0.25` — seconds between checks.
- `--post-click-delay 0.4` — seconds to pause after each click.
- `--js-click` — use `element.click()` in JS if an overlay intercepts standard pointer clicks.
