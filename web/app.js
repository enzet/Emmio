import { initCheck } from "./js/check-session.js";
import {
    initCurate,
    initCuratedList,
    initCuratedLists,
} from "./js/curate-session.js";
import { initLearn } from "./js/learn-session.js";
import { initLexicon, initLexicons, initNewLexicon } from "./js/lexicon-pages.js";
import { initLexiconWords } from "./js/lexicon-words.js";
import { initHome, initLanguage } from "./js/home-pages.js";
import { initLanding, initLogin, initRegister } from "./js/auth-pages.js";
import { initCourse, initCourses, initLearning, initNewCourse, initNewLearning } from "./js/course-pages.js";
import { clearToken } from "./js/api.js";
import { initProfile } from "./js/profile.js";
import { initLanguages } from "./js/language-knowledge.js";

// Dispatch on the page.

document.addEventListener("DOMContentLoaded", () => {
    // Log out lives on the profile page; wire it when present.
    const logout = document.getElementById("logout");
    if (logout) {
        logout.addEventListener("click", () => {
            clearToken();
            location.href = "login";
        });
    }

    const page = document.body.dataset.page;
    if (page === "landing") initLanding();
    else if (page === "login") initLogin();
    else if (page === "register") initRegister();
    else if (page === "home") initHome();
    else if (page === "language") initLanguage();
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
    else if (page === "languages") initLanguages();
});
