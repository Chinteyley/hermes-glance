---
name: glance
description: Look at the running app before calling a UI change done. When to call glance_check, how to read its verdicts, and why the MEDIA line stays in the reply.
---

# Glance

Glance screenshots the booted iOS Simulator (or, when none is booted, the running Android
emulator) right before your first UI edit and keeps that screen as the baseline. A UI edit is a `write_file` or `patch` on a `.tsx`, `.jsx`, `.css`,
`.scss`, `.vue`, `.svelte`, `.swift`, `.kt` or `.dart` file.

## When to call glance_check

- After a UI edit, before you tell the user the change is done.
- After each fix, when an earlier glance_check did not pass.

If you finish without looking, Glance sends you back once with a message asking for glance_check.

## Reading the verdict

| Verdict | Meaning | What to do |
|---|---|---|
| PASS | The screen changed. `regions` lists where. | Confirm the changed regions match what was asked, then finish. |
| NO_CHANGE | The edit changed nothing on screen. | You likely edited a file the screen does not use, or a style that was already in effect. Find the component that renders the screen and edit that. |
| ERROR_SCREEN | The app shows the React Native or Expo error overlay. | Read the error with your tools, fix the code, check again. |
| BLANK | The screen is empty or one colour. | A component returns nothing or the root failed to render. Fix it and check again. |
| NO_BASELINE | There was no before-screenshot. The current screen is now the baseline. | Make the change, then call glance_check again. |
| NO_TARGET | No simulator or emulator is running. | Say in your reply that the change was not checked on a device. |

If `settled` is false, the screen was still moving when Glance gave up waiting; call glance_check
once more before you trust the verdict.

PASS means the screen changed, not that it changed correctly. Look at `regions` and the compare
image before you claim the change matches the request.

## The compare image

`compare_png` is one PNG: the before screen on the left, the after screen on the right with
changed regions outlined in red, and a verdict bar along the bottom. Glance appends a
`MEDIA:<compare_png>` line to your reply. Leave it in place; it is how the user sees the comparison.

## Baselines

Glance takes the baseline itself. Call `glance_baseline` only when the right starting screen
is a different one, for example after you navigate to the screen you are about to change.
