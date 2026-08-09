import { api } from "./api.js";

// This deployment's feature set (`GET /api/v1/config`, see `RELEASE` in
// `emmio/api/app.py`), fetched once per page load and shared by everyone who
// needs the answer: `app.js` reveals the experimental parts of the interface
// with it, and the pages skip fetching data only those parts would show.

let pending = null;

// Best-effort: an unreachable or erroring `/config` shows everything, so a
// backend hiccup degrades to the development view rather than to a
// half-navigable one.
export function isRelease() {
    if (!pending) {
        pending = (async () => {
            try {
                const response = await api("/config");
                if (!response.ok) return false;
                return Boolean((await response.json()).release);
            } catch {
                return false;
            }
        })();
    }
    return pending;
}
