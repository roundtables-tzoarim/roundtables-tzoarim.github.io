// טוען את data/content.json ומרנדר את הפסקה, המדיה והכתבות עבור נושא הדף הנוכחי.
// כדי לעדכן תוכן: עדכנו את קובץ ה-Google Docs והריצו: python scripts/sync_content.py

const ICON_ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7M17 7H8M17 7V16"/></svg>';

// Spotify: כדי לתמוך בהתחלת השמעה מדקה מסוימת (startAt) חובה להשתמש ב-iFrame API הרשמי
// (Spotify אינה תומכת בכך דרך פרמטר ב-URL של iframe רגיל).
let spotifyPending = [];
let spotifySDKRequested = false;

function ensureSpotifySDK() {
  if (spotifySDKRequested) return;
  spotifySDKRequested = true;
  window.onSpotifyIframeApiReady = (IFrameAPI) => {
    spotifyPending.forEach(({ el, uri, startAt }) => {
      const options = { uri, width: "100%", height: "100%" };
      if (startAt) options.startAt = startAt;
      IFrameAPI.createController(el, options, () => {});
    });
    spotifyPending = [];
  };
  const script = document.createElement("script");
  script.src = "https://open.spotify.com/embed/iframe-api/v1";
  script.async = true;
  document.head.appendChild(script);
}

function renderIntro(topic) {
  const el = document.getElementById("intro-text");
  if (!el) return;
  el.textContent = topic.intro || "התוכן לנושא זה יתווסף בקרוב.";
}

function mediaBlockHTML(item, idx) {
  if (item.type === "spotify") {
    const id = `spotify-embed-${idx}`;
    return `
      <div class="media-block">
        ${item.label ? `<p class="media-label">${item.label}</p>` : ""}
        <div class="media-wrapper spotify" id="${id}" data-spotify-uri="${item.uri}" data-spotify-start="${item.startAt || 0}"></div>
        ${item.desc ? `<p class="media-hint">${item.desc}</p>` : ""}
      </div>`;
  }
  if (item.type === "youtube") {
    return `
      <div class="media-block">
        ${item.label ? `<p class="media-label">${item.label}</p>` : ""}
        <div class="media-wrapper video">
          <iframe src="${item.embed}" title="${item.label || "מדיה"}"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
            loading="lazy"></iframe>
        </div>
        ${item.desc ? `<p class="media-hint">${item.desc}</p>` : ""}
      </div>`;
  }
  if (item.type === "video") {
    // וידאו מתארח מקומית (מוריד ב-yt-dlp) - לא דורש חשבון פייסבוק/יוטיוב לצפייה
    return `
      <div class="media-block">
        ${item.label ? `<p class="media-label">${item.label}</p>` : ""}
        <div class="media-wrapper video">
          <video controls preload="metadata" playsinline src="${item.src}"></video>
        </div>
        ${item.desc ? `<p class="media-hint">${item.desc}</p>` : ""}
      </div>`;
  }
  // link-style card (פייסבוק, כאן, וכו')
  return `
    <div class="media-block">
      <a class="article-card" href="${item.url}" target="_blank" rel="noopener noreferrer">
        <img class="thumb" src="${item.image}" alt="${item.label}" loading="lazy" />
        <div class="card-body">
          <span class="card-tag">${item.tag || ""}</span>
          <h3>${item.label}</h3>
          <span class="card-link">לצפייה / האזנה ${ICON_ARROW}</span>
        </div>
      </a>
    </div>`;
}

function renderMedia(topic) {
  const container = document.getElementById("media-container");
  if (!container) return;
  const items = topic.media || [];
  if (items.length === 0) {
    container.innerHTML = `<p class="media-hint">התוכן לנושא זה יתווסף בקרוב.</p>`;
    return;
  }
  container.innerHTML = items.map(mediaBlockHTML).join("");

  const spotifyEls = container.querySelectorAll("[data-spotify-uri]");
  if (spotifyEls.length) {
    spotifyEls.forEach((el) => {
      spotifyPending.push({
        el,
        uri: el.dataset.spotifyUri,
        startAt: Number(el.dataset.spotifyStart) || 0,
      });
    });
    ensureSpotifySDK();
  }
}

function articleCardHTML(article) {
  return `
    <a class="article-card" href="${article.url}" target="_blank" rel="noopener noreferrer">
      <img class="thumb" src="${article.image}" alt="${article.title}" loading="lazy" />
      <div class="card-body">
        <span class="card-tag">${article.tag || ""}</span>
        <h3>${article.title}</h3>
        ${article.desc ? `<p class="card-desc">${article.desc}</p>` : ""}
        <span class="card-link">לכתבה המלאה ${ICON_ARROW}</span>
      </div>
    </a>`;
}

function renderArticles(topic) {
  const container = document.getElementById("articles-container");
  if (!container) return;
  const items = topic.articles || [];
  if (items.length === 0) {
    container.innerHTML = `<p class="media-hint">הכתבות לנושא זה יתווספו בקרוב.</p>`;
    return;
  }
  container.innerHTML = items.map(articleCardHTML).join("");
}

async function loadContent() {
  const topicKey = document.body.dataset.topic;
  if (!topicKey) return;
  try {
    const res = await fetch("data/content.json", { cache: "no-store" });
    if (!res.ok) throw new Error("content.json not found");
    const data = await res.json();
    const topic = data[topicKey] || {};
    renderIntro(topic);
    renderMedia(topic);
    renderArticles(topic);
    document.dispatchEvent(new CustomEvent("content-rendered"));
  } catch (err) {
    console.error("שגיאה בטעינת התוכן:", err);
    const intro = document.getElementById("intro-text");
    if (intro) intro.textContent = "לא ניתן היה לטעון את התוכן. ודאו שהדף מוגש דרך שרת מקומי (python -m http.server) ולא נפתח ישירות כקובץ.";
  }
}

document.addEventListener("DOMContentLoaded", loadContent);
