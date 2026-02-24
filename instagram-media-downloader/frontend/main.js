/**
 * Instagram Media Downloader — Frontend Logic
 */

const API_BASE = window.location.pathname.replace(/\/+$/, "");  // Auto-detect subpath

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

    // Show "no content" if empty
    if (items.length === 0 && currentUsername) {
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
    postsGrid.innerHTML = "";
    noContent.hidden = true;
    currentStories = [];
    currentPosts = [];

    // Show loading
    setLoading(true);

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        // Fetch stories and posts in parallel
        const [storiesResp, postsResp] = await Promise.all([
            fetch(`${API_BASE}/api/stories/${encodeURIComponent(username)}`, { signal: controller.signal }),
            fetch(`${API_BASE}/api/posts/${encodeURIComponent(username)}`, { signal: controller.signal }),
        ]);
        clearTimeout(timeoutId);

        // Handle stories
        if (storiesResp.ok) {
            const storiesData = await storiesResp.json();
            showProfile(storiesData.user);
            showStories(storiesData.stories);
        } else {
            const err = await storiesResp.json().catch(() => ({ detail: "エラー" }));
            // If it's a user not found error, throw
            if (storiesResp.status === 404) throw new Error(err.detail);
        }

        // Handle posts
        if (postsResp.ok) {
            const postsData = await postsResp.json();
            if (!userProfile.hidden === false) showProfile(postsData.user);
            showPosts(postsData.posts);
        }

        // Show tabs
        contentTabs.hidden = false;
        switchTab("stories");

    } catch (err) {
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
    storyCountBadge.textContent = stories.length;

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
        card.addEventListener("mouseenter", () => video.play().catch(() => { }));
        card.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
        mediaWrapper.appendChild(video);
    } else {
        const img = document.createElement("img");
        img.src = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(story.url)}`;
        img.alt = "Story";
        img.loading = "lazy";
        mediaWrapper.appendChild(img);
    }

    const badge = document.createElement("span");
    badge.className = "media-type-badge";
    badge.textContent = story.media_type === "video" ? "🎬 動画" : "📷 画像";
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
// Posts Display
// ---------------------------------------------------------------------------

function showPosts(posts) {
    currentPosts = posts;
    postCountBadge.textContent = posts.length;

    posts.forEach((post, index) => {
        const card = createPostCard(post, index);
        postsGrid.appendChild(card);
    });
}

function createPostCard(post, index) {
    const card = document.createElement("div");
    card.className = "post-card";
    card.style.animationDelay = `${index * 0.05}s`;

    // Thumbnail
    const thumbUrl = post.thumbnail_url || post.url;
    if (post.media_type === "video" && post.thumbnail_url) {
        const img = document.createElement("img");
        img.src = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(post.thumbnail_url)}`;
        img.alt = "Post";
        img.loading = "lazy";
        card.appendChild(img);
    } else {
        const img = document.createElement("img");
        img.src = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(post.url)}`;
        img.alt = "Post";
        img.loading = "lazy";
        card.appendChild(img);
    }

    // Video badge
    if (post.media_type === "video") {
        const videoBadge = document.createElement("div");
        videoBadge.className = "post-video-badge";
        videoBadge.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="white"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        card.appendChild(videoBadge);
    }

    // Carousel badge
    if (post.carousel_total) {
        const carouselBadge = document.createElement("div");
        carouselBadge.className = "post-carousel-badge";
        carouselBadge.textContent = `${(post.carousel_index || 0) + 1}/${post.carousel_total}`;
        card.appendChild(carouselBadge);
    }

    // Hover overlay
    const overlay = document.createElement("div");
    overlay.className = "post-overlay";

    const stats = document.createElement("div");
    stats.className = "post-overlay-stats";
    stats.innerHTML = `<span>♥ ${formatNumber(post.like_count || 0)}</span>`;
    overlay.appendChild(stats);

    const dlBtn = createDownloadButton();
    dlBtn.addEventListener("click", (e) => { e.stopPropagation(); downloadMedia(post); });
    overlay.appendChild(dlBtn);

    card.appendChild(overlay);

    // Caption
    if (post.caption) {
        const caption = document.createElement("div");
        caption.className = "post-caption";
        caption.textContent = post.caption;
        card.appendChild(caption);
    }

    return card;
}

// ---------------------------------------------------------------------------
// Download
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
    const proxyUrl = `${API_BASE}/api/proxy/media?url=${encodeURIComponent(item.url)}`;

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
