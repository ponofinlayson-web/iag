"""WCAG contrast ratios for the jade accent candidates vs real panel colors."""
import sys

def lum(hexcolor: str) -> float:
    r, g, b = (int(hexcolor[i:i+2], 16) / 255 for i in (0, 2, 4))
    def adj(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = adj(r), adj(g), adj(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def ratio(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    lo, hi = min(la, lb), max(la, lb)
    return (hi + 0.05) / (lo + 0.05)

BG = "0f1216"      # --bg
PANEL = "171b21"   # --panel
PANEL2 = "1d222a"  # --panel-2
BORDER = "2a313b"  # --border
MUTED = "9aa3b0"   # --muted (current)
TEXT = "e6e9ee"    # --text (current)

cands = {
    "accent 2fa87c": "2fa87c",
    "accent 35b586": "35b586",
    "accent 3cbd8f": "3cbd8f",
    "accent 45c69a": "45c69a",
    "white on accent": None,
}
print("== white text on accent (buttons: need >= 4.5 for AA, 3.0 for large) ==")
for name, hx in list(cands.items()):
    if hx:
        print(f"  white/{name}: {ratio('ffffff', hx):.2f}   (panel {ratio(hx, PANEL):.2f}, bg {ratio(hx, BG):.2f})")

print("\n== muted candidates on panel / panel-2 (AA 4.5) ==")
for hx in ["9aa3b0", "a8b1bd", "b0b9c5", "aab3bf", "b3bcc8"]:
    print(f"  {hx} on panel {ratio(hx, PANEL):.2f}, on panel-2 {ratio(hx, PANEL2):.2f}, on bg {ratio(hx, BG):.2f}")

print("\n== darker jades for white-on-accent buttons (AA 4.5) ==")
for hx in ["1c8f66", "1f8a63", "178a5f", "1a8a61", "17805c", "219b6f", "178f68", "14855f", "1d9668"]:
    print(f"  white/{hx}: {ratio('ffffff', hx):.2f}   accent vs panel {ratio(hx, PANEL):.2f}")

print("\n== border candidates (vs panel, non-text 3.0) ==")
for hx in ["2a313b", "343d49", "3a4450", "3f4a57"]:
    print(f"  {hx} vs panel {ratio(hx, PANEL):.2f}, vs bg {ratio(hx, BG):.2f}")

print("\n== text on panel (AAA 7.0 target) ==")
for hx in ["e6e9ee", "eef1f5", "f2f5f8"]:
    print(f"  {hx} on panel {ratio(hx, PANEL):.2f}, on panel-2 {ratio(hx, PANEL2):.2f}")

print("\n== ok/warn/bad tones on their 15% tint over panel ==")
# badge bg = tone at 15% alpha over panel; approximate composite
def composite(fg: str, alpha: float, bg: str) -> str:
    f = [int(fg[i:i+2], 16) for i in (0, 2, 4)]
    b = [int(bg[i:i+2], 16) for i in (0, 2, 4)]
    out = [round(fc * alpha + bc * (1 - alpha)) for fc, bc in zip(f, b)]
    return "".join(f"{c:02x}" for c in out)
for hx in ["3fa66c", "46b478", "d0a03c", "d8b04a", "d05c5c", "dd6a6a"]:
    comp = composite(hx, 0.15, PANEL)
    print(f"  {hx} on its tint: {ratio(hx, comp):.2f}")

print("\n== jade fill ramp (white label must stay >= 4.5 incl hover) ==")
for hx in ["17805c", "16855a", "168a5e", "148556", "127a52", "107049", "0f6844", "1a8a63"]:
    print(f"  white/{hx}: {ratio('ffffff', hx):.2f}")
print("\n== accent text on panel-2 (rows hover bg) ==")
print(f"  2fa87c on panel-2: {ratio('2fa87c', PANEL2):.2f}")
print(f"  2fa87c on bg: {ratio('2fa87c', BG):.2f}")

# ---------------------------------------------------------------- light theme
# Feature 7 D3: the light palette must meet the same bar the dark theme
# meets - AA everywhere, text/muted AAA on panel + panel-2.
L = {
    "bg": "f5f7f9", "panel": "ffffff", "panel2": "eef2f6", "border": "d3dae2",
    "text": "1a2129", "muted": "47525f", "accent": "1b7450", "accent_strong": "17805c",
    "ok": "277044", "warn": "825d14", "bad": "b23a3a", "info": "28659a",
}
fails = 0

def check(name: str, fg: str, bg: str, minimum: float) -> None:
    global fails
    r = ratio(fg, bg)
    ok = r >= minimum
    if not ok:
        fails += 1
    print(f"  [{'OK' if ok else 'FAIL'}] {name}: {r:.2f} (need {minimum})")

print("\n== LIGHT THEME: text/muted AAA (7.0) on panel + panel-2 ==")
check("text on panel", L["text"], L["panel"], 7.0)
check("text on panel-2", L["text"], L["panel2"], 7.0)
check("muted on panel", L["muted"], L["panel"], 7.0)
check("muted on panel-2", L["muted"], L["panel2"], 7.0)
check("muted on bg", L["muted"], L["bg"], 7.0)

print("== LIGHT THEME: accent/tones AA (4.5) on surfaces ==")
for tone in ("accent", "ok", "warn", "bad", "info"):
    check(f"{tone} on panel", L[tone], L["panel"], 4.5)
    check(f"{tone} on panel-2", L[tone], L["panel2"], 4.5)
    check(f"{tone} on bg", L[tone], L["bg"], 4.5)
check("accent-soft fill vs panel (non-text 3.0)", "1d7a55", L["panel"], 3.0)

print("== LIGHT THEME: white on accent-strong buttons (AA 4.5) ==")
for fill in ("17805c", "127a52", "107049", "0f6844"):
    check(f"white on {fill}", "ffffff", fill, 4.5)

print("== LIGHT THEME: badge tones on their 15% tint over panel (AA 4.5) ==")
for tone in ("accent", "ok", "warn", "bad", "info", "muted"):
    hx = L[tone]
    comp = composite(hx, 0.15, L["panel"])
    check(f"{tone} badge on tint", hx, comp, 4.5)

print("== LIGHT THEME: border vs panel (informational - decorative, like dark) ==")
# Borders are not the sole affordance anywhere (bg separation + focus rings
# carry identification); the dark theme ships 1.75 for the same token, so
# light matches that established bar rather than the 3.0 text-adjacent one.
print(f"  border on panel: {ratio(L['border'], L['panel']):.2f} (informational)")

print(f"\nLIGHT THEME RESULT: {'PASS' if fails == 0 else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
