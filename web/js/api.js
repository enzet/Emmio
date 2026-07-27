// Minimal vanilla-JS client for the Emmio API. Holds the access token in
// localStorage and attaches it as a bearer token on each request. No build
// step, no framework; pages dispatch on `<body data-page="...">`.

const API = "/api/v1";

const TOKEN_KEY = "emmio_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);

export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// Call the API. `form` sends URL-encoded fields (for OAuth2 login); `body`
// sends JSON. A 401 clears the token and returns to the login page.
export async function api(path, { method = "GET", body, form } = {}) {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let payload;
    if (form) {
        payload = new URLSearchParams(form);
    } else if (body) {
        headers["Content-Type"] = "application/json";
        payload = JSON.stringify(body);
    }

    const response = await fetch(API + path, {
        method,
        headers,
        body: payload,
    });
    if (response.status === 401) {
        clearToken();
        location.href = "login";
        throw new Error("Not authenticated");
    }
    return response;
}

export function requireAuth() {
    if (!getToken()) location.href = "login";
}
