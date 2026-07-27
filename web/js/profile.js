import { renderDefinitionList } from "./format.js";
import { api, clearToken, requireAuth } from "./api.js";

// Profile page.

export async function initProfile() {
    requireAuth();

    const status = document.getElementById("status");
    const profile = document.getElementById("profile");
    const response = await api("/me");
    if (!response.ok) {
        status.textContent = "Could not load profile.";
        return;
    }
    const me = await response.json();
    status.textContent = "";
    profile.hidden = false;
    renderDefinitionList(profile, [
        ["User", me.user_id],
        ["Name", me.name],
        ["Email", me.email || "—"],
    ]);

    // Appearance switchers: persist the choice and apply it immediately.
    // `STYLE_KEY`, `THEME_KEY`, and `applyAppearance` come from theme.js.
    for (const [select, key] of [
        [document.getElementById("style-select"), STYLE_KEY],
        [document.getElementById("theme-select"), THEME_KEY],
    ]) {
        select.value = localStorage.getItem(key) || select.options[0].value;
        select.addEventListener("change", () => {
            localStorage.setItem(key, select.value);
            applyAppearance();
        });
    }

    // Download all of the user's data as a ZIP. The endpoint needs the bearer
    // token, so fetch it as a blob and trigger a download rather than linking.
    const exportStatus = document.getElementById("export-status");
    document
        .getElementById("export-data")
        .addEventListener("click", async () => {
            exportStatus.textContent = "Preparing your archive…";
            const result = await api("/me/export");
            if (!result.ok) {
                exportStatus.textContent = "Could not export your data.";
                return;
            }
            const url = URL.createObjectURL(await result.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = `${me.user_id}-emmio-data.zip`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            exportStatus.textContent = "Downloaded.";
        });

    // Change password: verify the current one server-side, enforce the new
    // one's minimum length, and clear the fields on success. The access token
    // stays valid (a stateless JWT can't be re-signed), so no re-login.
    const passwordStatus = document.getElementById("password-status");
    document
        .getElementById("password-form")
        .addEventListener("submit", async (event) => {
            event.preventDefault();
            const data = new FormData(event.target);
            passwordStatus.textContent = "Saving…";
            const result = await api("/me/password", {
                method: "POST",
                body: {
                    current_password: data.get("current_password"),
                    new_password: data.get("new_password"),
                },
            });
            if (result.ok) {
                event.target.reset();
                passwordStatus.textContent = "Password changed.";
            } else {
                const { detail } = await result.json().catch(() => ({}));
                passwordStatus.textContent =
                    typeof detail === "string"
                        ? detail
                        : "Could not change password.";
            }
        });

    // Deleting the account is irreversible; confirm, then drop the now-useless
    // token and return to login.
    const deleteStatus = document.getElementById("delete-status");
    document
        .getElementById("delete-account")
        .addEventListener("click", async () => {
            if (
                !confirm(
                    "Delete your account and all of your data? This cannot " +
                        "be undone.",
                )
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api("/me", { method: "DELETE" });
            if (result.ok) {
                clearToken();
                location.href = "login";
            } else {
                deleteStatus.textContent = "Could not delete account.";
            }
        });
}
