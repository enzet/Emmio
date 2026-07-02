"use strict";

// Applies the saved appearance — style ("basic" | "fancy") and color theme
// ("light" | "dark" | "system") — as `data-` attributes on `<html>`, which
// `base.css` and `fancy.css` key off. Loaded from `<head>` without `defer` so
// the attributes are set before first paint and pages never flash the default
// look. The switchers live on the profile page (see `initProfile` in app.js).

const STYLE_KEY = "emmio_style";
const THEME_KEY = "emmio_theme";

const systemDark = matchMedia("(prefers-color-scheme: dark)");

function applyAppearance() {
    const root = document.documentElement;
    root.dataset.style = localStorage.getItem(STYLE_KEY) || "basic";
    const theme = localStorage.getItem(THEME_KEY) || "system";
    root.dataset.theme =
        theme === "system" ? (systemDark.matches ? "dark" : "light") : theme;
}

applyAppearance();
// Follow the OS theme live while the preference is "system".
systemDark.addEventListener("change", applyAppearance);
