/**
 * Instagram Media Downloader — Frontend Logic
 */

const API_BASE = window.location.pathname.replace(/\/+$/, "");  // Auto-detect subpath

// Proxy URL helper — only used for downloads (fetch needs CORS proxy)
function proxyUrl(url) {
    return `${API_BASE}/api/proxy/media?url=${encodeURIComponent(url)}`;
}

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
const contentTabs = document.getElementById("content-tabs");
const tabStories = document.getElementById("tab-stories");
const tabPosts = document.getElementById("tab-posts");
const storyCountBadge = document.getElementById("story-count-badge");
const postCountBadge = document.getElementById("post-count-badge");
const downloadAllSection = document.getElementById("download-all-section");
const downloadAllBtn = document.getElementById("download-all-btn");
const storiesGrid = document.getElementById("stories-grid");
const postsGrid = document.getElementById("posts-grid");
const skeletonLoading = document.getElementById("skeleton-loading");
const noContent = document.getElementById("no-content");
const noContentText = document.getElementById("no-content-text");

// State
let currentStories = [];
let currentPosts = [];
let activeTab = "stories";
let currentUsername = "";
let renderedPostCount = 0;
const POST_BATCH_SIZE = 30;

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
        sessionWarning.hidden = false;
    }
}

init();

// ---------------------------------------------------------------------------
// Tab Switching
// ---------------------------------------------------------------------------

tabStories.addEventListener("click", () => switchTab("stories"));
tabPosts.addEventListener("click", () => switchTab("posts"));

function switchTab(tab) {
    activeTab = tab;
    tabStories.classList.toggle("active", tab === "stories");
    tabPosts.classList.toggle("active", tab === "posts");
    storiesGrid.hidden = tab !== "stories";
    postsGrid.hidden = tab !== "posts";
    noContent.hidden = true;

    // Update download all visibility
    const items = tab === "stories" ? currentStories : currentPosts;
    downloadAllSection.hidden = items.length === 0;

    // Show "no content" if empty (but not while posts are still loading)
    if (items.length === 0 && currentUsername && !postsLoadingEl) {
        noContentText.textContent = tab === "stories"
            ? "現在ストーリーはありません"
            : "投稿が見つかりません";
        noContent.hidden = false;
    }
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = usernameInput.value.trim().replace(/^@/, "");
    if (!username) return;

    currentUsername = username;

    // Reset UI
    hideError();
    userProfile.hidden = true;
    contentTabs.hidden = true;
    downloadAllSection.hidden = true;
    storiesGrid.innerHTML = "";
    removeSentinel();
    postsGrid.innerHTML = "";
    noContent.hidden = true;
    currentStories = [];
    currentPosts = [];
    renderedPostCount = 0;

    // Show loading
    setLoading(true);

    try {
        // 1. Fetch stories (fast) — shows profile + stories
        const storiesCtrl = new AbortController();
        const storiesTimeout = setTimeout(() => storiesCtrl.abort(), 15000);

        const storiesResp = await fetch(
            `${API_BASE}/api/stories/${encodeURIComponent(username)}`,
            { signal: storiesCtrl.signal },
        );
        clearTimeout(storiesTimeout);

        if (storiesResp.ok) {
            const storiesData = await storiesResp.json();
            showProfile(storiesData.user);
            showStories(storiesData.stories);
        } else {
            const err = await storiesResp.json().catch(() => ({ detail: "エラー" }));
            if (storiesResp.status === 404) throw new Error(err.detail);
        }

        // Show tabs + stories immediately
        contentTabs.hidden = false;
        switchTab("stories");
        setLoading(false);

        // 2. Fetch posts (may take longer) — loading indicator on posts tab
        setPostsLoading(true);
        const postsCtrl = new AbortController();
        const postsTimeout = setTimeout(() => postsCtrl.abort(), 120000);

        const postsResp = await fetch(
            `${API_BASE}/api/posts/${encodeURIComponent(username)}?count=200`,
            { signal: postsCtrl.signal },
        );
        clearTimeout(postsTimeout);

        if (postsResp.ok) {
            const postsData = await postsResp.json();
            if (userProfile.hidden) showProfile(postsData.user);
            showPosts(postsData.posts);
        }
        setPostsLoading(false);

    } catch (err) {
        setPostsLoading(false);
        if (err.name === "AbortError") {
            showError("リクエストがタイムアウトしました。数分後に再試行してください。");
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
    if (!user) return;
    profilePic.src = proxyUrl(user.profile_pic_url);
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
    storyCountBadge.textContent = stories.length;

    const fragment = document.createDocumentFragment();
    stories.forEach((story, index) => {
        fragment.appendChild(createStoryCard(story, index));
    });
    storiesGrid.appendChild(fragment);
}

function createStoryCard(story, index) {
    const card = document.createElement("div");
    card.className = "story-card";
    if (index < 6) {
        card.style.animationDelay = `${index * 0.08}s`;
    } else {
        card.style.animation = "none";
    }

    const mediaWrapper = document.createElement("div");
    mediaWrapper.className = "story-media-wrapper";

    if (story.media_type === "video") {
        const video = document.createElement("video");
        video.muted = true;
        video.loop = true;
        video.playsInline = true;
        video.preload = "none";
        video.referrerPolicy = "no-referrer";
        video.poster = story.thumbnail_url || "";
        video.dataset.src = story.url;
        card.addEventListener("mouseenter", () => {
            if (video.dataset.src) { video.src = video.dataset.src; delete video.dataset.src; }
            video.play().catch(() => { });
        });
        card.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
        mediaWrapper.appendChild(video);
    } else {
        const img = document.createElement("img");
        img.alt = "Story";
        img.referrerPolicy = "no-referrer";
        img.src = story.url;
        mediaWrapper.appendChild(img);
    }

    const badge = document.createElement("span");
    badge.className = "media-type-badge";
    badge.textContent = story.media_type === "video" ? "動画" : "画像";
    mediaWrapper.appendChild(badge);

    const footer = document.createElement("div");
    footer.className = "story-card-footer";

    const timestamp = document.createElement("span");
    timestamp.className = "story-timestamp";
    timestamp.textContent = formatTimestamp(story.timestamp);

    const dlBtn = createDownloadButton();
    dlBtn.addEventListener("click", () => downloadMedia(story));

    footer.appendChild(timestamp);
    footer.appendChild(dlBtn);
    card.appendChild(mediaWrapper);
    card.appendChild(footer);

    return card;
}

// ---------------------------------------------------------------------------
// Posts Display — batch rendering with infinite scroll
// ---------------------------------------------------------------------------

let postSentinel = null;
const postSentinelObserver = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) renderPostBatch();
}, { rootMargin: "400px" });

function showPosts(posts) {
    currentPosts = posts;
    postCountBadge.textContent = posts.length;
    renderedPostCount = 0;
    removeSentinel();
    renderPostBatch();
}

function renderPostBatch() {
    if (renderedPostCount >= currentPosts.length) return;
    removeSentinel();

    const end = Math.min(renderedPostCount + POST_BATCH_SIZE, currentPosts.length);
    const fragment = document.createDocumentFragment();
    for (let i = renderedPostCount; i < end; i++) {
        fragment.appendChild(createPostCard(currentPosts[i], i));
    }
    postsGrid.appendChild(fragment);
    renderedPostCount = end;

    if (renderedPostCount < currentPosts.length) {
        postSentinel = document.createElement("div");
        postSentinel.className = "post-sentinel";
        postSentinel.style.height = "1px";
        postsGrid.appendChild(postSentinel);
        postSentinelObserver.observe(postSentinel);
    }
}

function removeSentinel() {
    if (postSentinel) {
        postSentinelObserver.unobserve(postSentinel);
        postSentinel.remove();
        postSentinel = null;
    }
}

function createPostCard(post, index) {
    const card = document.createElement("div");
    card.className = index < 9 ? "post-card post-card--animated" : "post-card";
    if (index < 9) {
        card.style.animationDelay = `${index * 0.04}s`;
    }
    // Store post index for event delegation
    card.dataset.postIndex = index;

    // Direct CDN URL — async decode, no-referrer to avoid CDN blocking
    const img = document.createElement("img");
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.src = post.thumbnail_url || post.url;
    // Fallback to proxy if CDN blocks direct access
    img.onerror = function () {
        if (!this.dataset.retried) {
            this.dataset.retried = "1";
            this.src = proxyUrl(post.thumbnail_url || post.url);
        }
    };
    card.appendChild(img);

    // Lightweight badges via data attributes (rendered by CSS)
    if (post.media_type === "video") {
        card.dataset.video = "";
    }
    if (post.carousel_total) {
        card.dataset.carousel = `${(post.carousel_index || 0) + 1}/${post.carousel_total}`;
    }

    return card;
}

// ---------------------------------------------------------------------------
// Post grid — event delegation (single listener, no per-card DOM)
// ---------------------------------------------------------------------------

// Shared overlay for hover (PC) — created once, moved on hover
const postOverlay = document.createElement("div");
postOverlay.className = "post-overlay";
postOverlay.innerHTML = `
    <div class="post-overlay-stats"><span class="post-overlay-likes"></span></div>
    <button class="download-btn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        保存
    </button>`;
const overlayLikes = postOverlay.querySelector(".post-overlay-likes");
const overlayDlBtn = postOverlay.querySelector(".download-btn");
let overlayPostIndex = -1;

postsGrid.addEventListener("pointerenter", (e) => {
    const card = e.target.closest(".post-card");
    if (!card || !card.dataset.postIndex) return;
    const idx = parseInt(card.dataset.postIndex);
    if (idx === overlayPostIndex && postOverlay.parentNode === card) return;
    overlayPostIndex = idx;
    const post = currentPosts[idx];
    if (!post) return;
    overlayLikes.textContent = `♥ ${formatNumber(post.like_count || 0)}`;
    card.appendChild(postOverlay);
}, true);

overlayDlBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (overlayPostIndex >= 0 && currentPosts[overlayPostIndex]) {
        downloadMedia(currentPosts[overlayPostIndex]);
    }
});

// Mobile: tap card to download
postsGrid.addEventListener("click", (e) => {
    if (window.matchMedia("(hover: none)").matches) {
        const card = e.target.closest(".post-card");
        if (!card || !card.dataset.postIndex) return;
        downloadMedia(currentPosts[parseInt(card.dataset.postIndex)]);
    }
});

// ---------------------------------------------------------------------------
// Download — uses proxy (fetch needs CORS)
// ---------------------------------------------------------------------------

function createDownloadButton() {
    const btn = document.createElement("button");
    btn.className = "download-btn";
    btn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
    保存
  `;
    return btn;
}

async function downloadMedia(item) {
    const ext = item.media_type === "video" ? "mp4" : "jpg";
    const filename = `${item.username}_${item.id}.${ext}`;

    try {
        const resp = await fetch(proxyUrl(item.url));
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
    const items = activeTab === "stories" ? currentStories : currentPosts;
    for (const item of items) {
        await downloadMedia(item);
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

let postsLoadingEl = null;

function setPostsLoading(loading) {
    if (loading) {
        postsLoadingEl = document.createElement("div");
        postsLoadingEl.className = "posts-loading";
        postsLoadingEl.innerHTML = `<span class="spinner"></span> 投稿を読み込み中...`;
        postsGrid.appendChild(postsLoadingEl);
        tabPosts.classList.add("loading");
    } else {
        if (postsLoadingEl) { postsLoadingEl.remove(); postsLoadingEl = null; }
        tabPosts.classList.remove("loading");
    }
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
