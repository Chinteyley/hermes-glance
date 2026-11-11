# Glance

**It said done. It never looked.**

Glance is a Hermes plugin that won't let the agent call a UI change done until it has looked at the running app. It screenshots the iOS Simulator (or an Android emulator) right before the agent's first UI edit, screenshots it again when the agent checks its work, and diffs the two. If the edit changed nothing, crashed to an error screen, or left the screen blank, Glance sends the agent back to fix it.

Verdicts are deterministic image checks. Glance makes no model calls and no network calls.

## Install

```bash
hermes plugins install Chinteyley/hermes-glance
hermes plugins enable glance
```

Hermes asks for consent to install the one Python dependency, Pillow. To see the before/after slider in Hermes Desktop, also turn on Glance's desktop half in **Capabilities → Plugins**; it ships off, like every desktop plugin.

Check that Glance can see a device:

```text
$ hermes glance doctor
Data dir:  ~/.hermes/plugin-data/glance
Device setting: (empty: first booted simulator, then first adb device)
Device:    iPhone 18 Pro (ios, 5D8B63E1-0A6F-4D15-B973-26F8D799E4B9)
Capture:   ok, 1206x2622 in 457 ms (~/.hermes/plugin-data/glance/doctor.png)
```

To pin a device, set its simulator UDID or adb serial in the plugin's `device` setting (Plugins page, or `plugins.entries.glance.settings.device` in `config.yaml`).

## How it works

1. **Baseline.** When the agent calls `write_file` or `patch` on a UI file (`.tsx`, `.jsx`, `.css`, `.scss`, `.sass`, `.less`, `.vue`, `.svelte`, `.swift`, `.kt`, `.dart`), the `pre_tool_call` hook screenshots the screen before the edit lands. Capture is capped at about 3.6 s and never blocks or fails the edit; a typical simulator screenshot takes 0.45 s.
2. **Check.** The agent calls `glance_check`. Glance waits until at least 2 s after the last UI edit for Fast Refresh, then screenshots until two frames in a row match, for up to 5 s. If the screen never stops moving, the result says `settled: false` instead of guessing. It diffs the settled frame against the baseline and writes one compare PNG: before and after side by side, changed regions boxed in red, a verdict bar along the bottom.
3. **Gate.** When the agent tries to finish after editing UI files, the `pre_verify` hook sends it back if it never called `glance_check`, if it edited again after the last check, or if the last check failed. It nudges at most twice per turn.
4. **Show.** The `transform_llm_output` hook appends `MEDIA:<compare.png>` to the final reply once per check, so every surface delivers the image. Hermes Desktop draws it as a before/after slider.

State lives in `plugin_db`, so a gateway restart keeps the baseline and the last verdict.

## Verdicts

| Verdict | When | Agent is sent back |
|---|---|---|
| `PASS` | The screen changed. `regions` lists up to 8 boxes as fractions of the frame. | No |
| `NO_CHANGE` | Under 0.02% of pixels changed outside the status bar. | Yes |
| `ERROR_SCREEN` | The screen shows the React Native LogBox error screen (Expo's red error, Metro's "Failed to compile"). | Yes |
| `BLANK` | One colour covers 97% or more of the screen below the status bar. | Yes |
| `NO_BASELINE` | No before-screenshot existed; the current screen becomes the baseline. | No |
| `NO_TARGET` | No simulator or emulator is running. | No |

`PASS` means the screen changed, not that it changed correctly; the bundled `glance` skill tells the agent to read the regions and the compare image before claiming the change matches the request.

The top 7% of the frame is masked so the status bar clock does not count as a change. Every threshold was calibrated on real iPhone 18 Pro screenshots in `tests/fixtures/`:

```text
$ python tests/eval_fixtures.py
...
11/11 caught, no model calls
```

## What Glance runs and stores

- **Subprocesses.** `xcrun simctl list devices booted -j` and `xcrun simctl io <udid> screenshot` for the iOS Simulator. When no simulator matches, `adb devices -l` and `adb -s <serial> exec-out screencap -p` for Android. If the adb server is not running, `adb devices` starts it, and it keeps running in the background as adb's own daemon.
- **Files.** Screenshots and compare PNGs under `~/.hermes/plugin-data/glance/shots/<session>/`, and a SQLite database at `~/.hermes/plugin-data/glance/data.db`. They stay on your machine. Glance never deletes them; remove the folder to clear them.
- **Nothing else.** No network calls, no model calls, no credentials, no reads outside its own data and the screenshots it takes.

## Limits

- Android capture is implemented and unit-tested but has not been run against a live emulator.
- UI files are recognised by extension, so an edit to a `.ts` or `.js` file that changes the screen does not take a baseline.
- The status bar band is a fixed share of the frame, tuned for Dynamic Island iPhones.
- Error screens are recognised by React Native LogBox's colours, not by native crash dialogs.

## Development

```bash
python -m unittest discover -s tests        # with the Python Hermes runs plugins under
python tests/eval_fixtures.py
hermes plugins validate . --install-deps
```

## License

MIT
