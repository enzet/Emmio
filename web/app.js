import { initCheck } from "./js/check-session.js";
import {
    initCurate,
    initCuratedList,
    initCuratedLists,
} from "./js/curate-session.js";
import { initLearn } from "./js/learn-session.js";
import { initLexicon, initLexicons, initNewLexicon } from "./js/lexicon-pages.js";
import { initLexiconWords } from "./js/lexicon-words.js";
import { initHome, initLanguage, initNewLanguage } from "./js/home-pages.js";
import { initLanding, initLogin, initRegister } from "./js/auth-pages.js";
import { initCourse, initCourses, initLearning, initNewCourse, initNewLearning } from "./js/course-pages.js";
import { clearToken } from "./js/api.js";
import { isRelease } from "./js/config.js";
import { initProfile } from "./js/profile.js";

// The parts of Emmio still being worked out — courses/learnings and the SFWR
// curation tooling — carry `data-experimental` in the markup: the two nav
// entries, the Courses sections, and the whole `<body>` of the pages behind
// them. A release deployment (`EMMIO_RELEASE`, see `RELEASE` in
// `emmio/api/app.py`) does not show them. They start hidden (see the
// `data-experimental` rule in `base.css`) and are revealed only once
// `/config` says this is a development deployment, so a slow answer shows
// nothing rather than showing everything and taking it back.
//
// The sub-pages are marked too, not just the two entry points: they are only
// reachable through those, so leaving them live would just be a way to
// bookmark past a hidden door.
//
// The answer comes from `js/config.js`, shared with the pages that skip
// fetching data only these parts would show, so a page load asks once.

// Dispatch on the page.

document.addEventListener("DOMContentLoaded", async () => {
    // Log out lives on the profile page; wire it when present.
    const logout = document.getElementById("logout");
    if (logout) {
        logout.addEventListener("click", () => {
            clearToken();
            location.href = "login";
        });
    }

    const page = document.body.dataset.page;

    // The answer only decides whether the experimental parts become visible,
    // so the page's own loading does not wait for it.
    const release = isRelease().then((release) => {
        document.documentElement.dataset.release = String(release);
        return release;
    });

    // An experimental page has nothing to show on a release deployment, so
    // it is the one case that waits, rather than loading data it would then
    // throw away.
    if (document.body.hasAttribute("data-experimental") && (await release)) {
        location.href = "index";
        return;
    }

    if (page === "landing") initLanding();
    else if (page === "login") initLogin();
    else if (page === "register") initRegister();
    else if (page === "home") initHome();
    else if (page === "language") initLanguage();
    else if (page === "new-language") initNewLanguage();
    else if (page === "lexicons") initLexicons();
    else if (page === "lexicon") initLexicon();
    else if (page === "lexicon-words") initLexiconWords();
    else if (page === "new-lexicon") initNewLexicon();
    else if (page === "check") initCheck();
    else if (page === "curated-lists") initCuratedLists();
    else if (page === "curated-list") initCuratedList();
    else if (page === "curate") initCurate();
    else if (page === "courses") initCourses();
    else if (page === "course") initCourse();
    else if (page === "new-course") initNewCourse();
    else if (page === "new-learning") initNewLearning();
    else if (page === "learning") initLearning();
    else if (page === "learn") initLearn();
    else if (page === "profile") initProfile();
});
