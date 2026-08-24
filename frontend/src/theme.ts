// Theme store: dark default, light override, sticky per explicit choice.
// The pre-paint script in index.html sets data-theme before this module
// loads, so this file only manages user-initiated changes.

export const THEME_KEY = "iag.theme";

export type Theme = "dark" | "light";

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "light" ? "dark" : "light";
  setTheme(next);
  return next;
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* storage blocked: theme still applies for this session */
  }
}
