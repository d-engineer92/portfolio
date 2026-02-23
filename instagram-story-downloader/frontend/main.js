/**
 * Instagram Story Downloader — Frontend Logic
 */

const API_BASE = "http://localhost:8000";

// DOM Elements
const searchForm = document.getElementById("search-form");
const usernameInput = document.getElementById("username-input");
const searchBtn = document.getElementById("search-btn");
const btnText = searchBtn.querySelector(".btn-text");
const btnLoading = searchBtn.querySelector(".btn-loading");
const sessionWarning = document.getElementById("session-warning");
const errorAlert = document.getElementById("error-alert");
const errorMessage = document.getElementById("error-message");
const userProfile = document.getElementById("user-profile");
const profilePic = document.getElementById("profile-pic");
const profileName = document.getElementById("profile-name");
const profileUsername = document.getElementById("profile-username");
const profileFollowers = document.getElementById("profile-followers");
const storyCountEl = document.getElementById("story-count");
const storyCountBadge = document.getElementById("story-count-badge");
const downloadAllSection = document.getElementById("download-all-section");
const downloadAllBtn = document.getElementById("download-all-btn");
const storiesGrid = document.getElementById("stories-grid");
const skeletonLoading = document.getElementById("skeleton-loading");
const noStories = document.getElementById("no-stories");

// State
let currentStories = [];

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
    try {
        const resp = await fetch(`${API_BASE}/api/session/status`);
        const data = await resp.json();
        if (!data.logged_in) {
            sessionWarning.hidden = false;
        }
    } catch {
        // Backend not running — show warning
        sessionWarning.hidden = false;
    }
}

init();

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = usernameInput.value.trim().replace(/^@/, "");
    if (!username) return;

    // Reset UI
    hideError();
    userProfile.hidden = true;
    downloadAllSection.hidden = true;
    storiesGrid.innerHTML = "";
    noStories.hidden = true;
    currentStories = [];

    // Show loading
    setLoading(true);

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 20000);

        const resp = await fetch(
            `${API_BASE}/api/stories/${encodeURIComponent(username)}`,
            { signal: controller.signal }
        );
        clearTimeout(timeoutId);

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: "エラーが発生しました" }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const data = await resp.json();
        showProfile(data.user);
        showStories(data.stories);
    } catch (err) {
        if (err.name === "AbortError") {
            showError("リクエストがタイムアウトしました。Instagramのレートリミットの可能性があります。数分後に再試行してください。");
        } else {
            showError(err.message);
        }
    } finally {
        setLoading(false);
    }
});

// ---------------------------------------------------------------------------
// Profile Display
// ---------------------------------------------------------------------------

function showProfile(user) {
    profilePic.src = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(user.profile_pic_url)}`;
    profilePic.alt = user.username;
    profileName.textContent = user.full_name || user.username;
    profileUsername.textContent = `@${user.username}`;
    profileFollowers.textContent = `${formatNumber(user.followers)} フォロワー`;
    userProfile.hidden = false;
}

// ---------------------------------------------------------------------------
// Stories Display
// ---------------------------------------------------------------------------

function showStories(stories) {
    currentStories = stories;
    storyCountEl.textContent = stories.length;

    if (stories.length === 0) {
        noStories.hidden = false;
        downloadAllSection.hidden = true;
        return;
    }

    downloadAllSection.hidden = false;

    stories.forEach((story, index) => {
        const card = createStoryCard(story, index);
        storiesGrid.appendChild(card);
    });
}

function createStoryCard(story, index) {
    const card = document.createElement("div");
    card.className = "story-card";
    card.style.animationDelay = `${index * 0.08}s`;

    const mediaWrapper = document.createElement("div");
    mediaWrapper.className = "story-media-wrapper";

    // Media element
    if (story.media_type === "video") {
        const video = document.createElement("video");
        video.src = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(story.url)}`;
        video.poster = story.thumbnail_url
            ? `${API_BASE}/api/proxy/media?url=${encodeURIComponent(story.thumbnail_url)}`
            : "";
        video.muted = true;
        video.loop = true;
        video.playsInline = true;
        video.preload = "metadata";

        // Play on hover
        card.addEventListener("mouseenter", () => video.play().catch(() => { }));
        card.addEventListener("mouseleave", () => {
            video.pause();
            video.currentTime = 0;
        });

        mediaWrapper.appendChild(video);
    } else {
        const img = document.createElement("img");
        img.src = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(story.url)}`;
        img.alt = "Story";
        img.loading = "lazy";
        mediaWrapper.appendChild(img);
    }

    // Type badge
    const badge = document.createElement("span");
    badge.className = "media-type-badge";
    badge.textContent = story.media_type === "video" ? "🎬 動画" : "📷 画像";
    mediaWrapper.appendChild(badge);

    // Footer
    const footer = document.createElement("div");
    footer.className = "story-card-footer";

    const timestamp = document.createElement("span");
    timestamp.className = "story-timestamp";
    timestamp.textContent = formatTimestamp(story.timestamp);

    const dlBtn = document.createElement("button");
    dlBtn.className = "download-btn";
    dlBtn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
    保存
  `;
    dlBtn.addEventListener("click", () => downloadMedia(story));

    footer.appendChild(timestamp);
    footer.appendChild(dlBtn);

    card.appendChild(mediaWrapper);
    card.appendChild(footer);

    return card;
}

// ---------------------------------------------------------------------------
// Download
// ---------------------------------------------------------------------------

async function downloadMedia(story) {
    const ext = story.media_type === "video" ? "mp4" : "jpg";
    const filename = `story_${story.username}_${story.id}.${ext}`;
    const proxyUrl = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(story.url)}`;

    try {
        const resp = await fetch(proxyUrl);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (err) {
        showError(`ダウンロードに失敗しました: ${err.message}`);
    }
}

downloadAllBtn.addEventListener("click", async () => {
    for (const story of currentStories) {
        await downloadMedia(story);
        // Small delay between downloads
        await new Promise((r) => setTimeout(r, 500));
    }
});

// ---------------------------------------------------------------------------
// UI Helpers
// ---------------------------------------------------------------------------

function setLoading(loading) {
    searchBtn.disabled = loading;
    btnText.hidden = loading;
    btnLoading.hidden = !loading;
    skeletonLoading.hidden = !loading;
}

function showError(msg) {
    errorMessage.textContent = msg;
    errorAlert.hidden = false;
}

function hideError() {
    errorAlert.hidden = true;
}

function formatNumber(num) {
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
    return num.toLocaleString();
}

function formatTimestamp(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);

    if (diffMin < 1) return "たった今";
    if (diffMin < 60) return `${diffMin}分前`;
    if (diffHr < 24) return `${diffHr}時間前`;

    return date.toLocaleDateString("ja-JP", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}
