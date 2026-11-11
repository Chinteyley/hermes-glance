GLANCE_CHECK = {
    "name": "glance_check",
    "description": (
        "Look at the running app after a UI change. Waits for the screen to settle, screenshots the "
        "booted iOS Simulator, diffs it against the screenshot Glance took before your first UI edit, "
        "and returns a verdict: PASS (the screen changed), NO_CHANGE (your edit changed nothing on "
        "screen), ERROR_SCREEN (the app crashed to an error overlay), BLANK (the screen is empty), "
        "NO_BASELINE (no before-screenshot yet; the current screen is saved as one) or NO_TARGET "
        "(no simulator is running). Call it after editing UI files and before saying the change is "
        "done. Keep the MEDIA: line for compare_png in your reply so the user sees the comparison."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

GLANCE_BASELINE = {
    "name": "glance_baseline",
    "description": (
        "Save the current simulator screen as the before-screenshot for the next glance_check. "
        "Glance does this on its own right before your first UI edit; call it only when the right "
        "starting screen is a different one (after navigating to the screen you are about to change)."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}
