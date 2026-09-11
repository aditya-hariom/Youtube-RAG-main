// =========================================================
// CONFIG
// =========================================================

const API_ASK_URL = "http://127.0.0.1:8000/ask";
const API_PROCESS_URL = "http://127.0.0.1:8000/process";

let CURRENT_VIDEO_ID = "";
let CHAT_HISTORY = [];

const messages = document.getElementById("messages");
const questionInput = document.getElementById("question");
const sendButton = document.getElementById("sendButton");
const newChatBtn = document.getElementById("newChatBtn");
const themeBtn = document.getElementById("themeBtn");
const processVideoBtn = document.getElementById("processVideoBtn");
const videoUrlInput = document.getElementById("videoUrlInput");

let player = null;
let playerReady = false;

// =========================================================
// PROCESS VIDEO
// =========================================================
function applyVideoData(data) {
  if (!data) return;
  CURRENT_VIDEO_ID = data.video_id;
  try {
    sessionStorage.setItem("last_video_data", JSON.stringify(data));
  } catch (e) {}

  // Update UI Title
  const titleEl = document.querySelector(".video-title");
  if (titleEl)
    titleEl.textContent = data.title || "Video processed successfully";

  // Update Channel & Avatar
  const channelEl = document.getElementById("channelName");
  if (channelEl) channelEl.textContent = data.channel || "YouTube Channel";
  const avatarEl = document.getElementById("channelAvatar");
  if (avatarEl)
    avatarEl.textContent = (data.channel || "YT").slice(0, 2).toUpperCase();
  const subEl = document.getElementById("channelSubscribers");
  if (subEl) subEl.textContent = "Verified Channel";

  // Update Chapters Count Badge
  const countBadge = document.getElementById("chaptersCount");
  const chapters = data.chapters || [];
  if (countBadge) {
    countBadge.textContent =
      chapters.length > 0 ? `${chapters.length} chapters` : "0 chapters";
  }

  // Update Chapters List
  const chaptersContainer = document.getElementById("videoChaptersList");
  if (chaptersContainer) {
    if (chapters.length > 0) {
      chaptersContainer.innerHTML = "";
      chapters.forEach((ch) => {
        const chBtn = document.createElement("button");
        chBtn.type = "button";
        chBtn.className = "chapter-pill";
        const mins = Math.floor(ch.start_time / 60);
        const secs = Math.floor(ch.start_time % 60);
        const timeStr = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
        chBtn.innerHTML = `<span class="chapter-time">▶ ${timeStr}</span> <span class="chapter-title">${ch.title}</span>`;
        chBtn.onclick = () => seekVideo(ch.start_time);
        chaptersContainer.appendChild(chBtn);
      });
    } else {
      chaptersContainer.innerHTML = `<p class="empty-hint">No explicit chapters found for this video. You can still ask questions and navigate using cited timestamps in chat answers.</p>`;
    }
  }

  // Initialize YouTube player for this video
  initPlayer(CURRENT_VIDEO_ID);
}

// Auto-restore last video details on refresh
window.addEventListener("DOMContentLoaded", () => {
  try {
    const saved = sessionStorage.getItem("last_video_data");
    if (saved) {
      const data = JSON.parse(saved);
      applyVideoData(data);
    }
  } catch (e) {}
});

processVideoBtn.addEventListener("click", async () => {
  const url = videoUrlInput.value.trim();
  if (!url) {
    showToast("Please enter a valid YouTube URL");
    return;
  }

  processVideoBtn.textContent = "Processing...";
  processVideoBtn.disabled = true;
  showToast("Indexing video transcript. This takes just a few seconds...");

  try {
    const res = await fetch(API_PROCESS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`Processing failed: ${errorText}`);
    }

    const data = await res.json();
    CHAT_HISTORY = []; // Reset history for new video

    applyVideoData(data);

    showToast("Video processed successfully!");

    // Clear chat
    messages.innerHTML = `
        <div class="message assistant">
          <div class="assistant-row">
            <div class="mini-ai">✦</div>
            <div class="assistant-card">
              <div class="assistant-label">YouTube RAG Assistant</div>
              <div class="assistant-markdown">
                <p>Successfully indexed <strong>${data.title}</strong>! You can now ask questions about the video content.</p>
              </div>
            </div>
          </div>
        </div>
    `;
  } catch (err) {
    showToast(err.message);
  } finally {
    processVideoBtn.textContent = "Process";
    processVideoBtn.disabled = false;
  }
});

// =========================================================
// YOUTUBE IFRAME API
// =========================================================

const ytScript = document.createElement("script");
ytScript.src = "https://www.youtube.com/iframe_api";
document.head.appendChild(ytScript);

let ytAPIReady = false;

window.onYouTubeIframeAPIReady = function () {
  ytAPIReady = true;
  // If a video was already loaded before API was ready, initialize the player now
  if (CURRENT_VIDEO_ID && !player) {
    initPlayer(CURRENT_VIDEO_ID);
  }
};

function initPlayer(videoId) {
  if (!ytAPIReady) {
    // YT API not loaded yet — set iframe src directly so video at least shows
    let iframe = document.getElementById("youtubePlayer");
    if (iframe && iframe.tagName === "IFRAME") {
      iframe.src = `https://www.youtube.com/embed/${videoId}?enablejsapi=1&rel=0`;
    }
    return;
  }

  try {
    playerReady = false;
    // Destroy old player if exists
    if (player && typeof player.destroy === "function") {
      try {
        player.destroy();
      } catch (e) {
        /* ignore */
      }
    }
    player = null;

    // Ensure the container div exists (replace iframe if needed)
    let container = document.getElementById("youtubePlayer");
    if (container && container.tagName === "IFRAME") {
      // Replace iframe with a div so YT.Player can create its own iframe cleanly
      const div = document.createElement("div");
      div.id = "youtubePlayer";
      container.parentNode.replaceChild(div, container);
    }

    player = new YT.Player("youtubePlayer", {
      videoId: videoId,
      playerVars: {
        enablejsapi: 1,
        rel: 0,
        modestbranding: 1,
      },
      events: {
        onReady: function () {
          playerReady = true;
          console.log("YT Player ready!");
        },
      },
    });
  } catch (e) {
    console.error("Failed to init YT Player:", e);
    // Fallback: just set iframe src directly
    let iframe = document.getElementById("youtubePlayer");
    if (iframe && iframe.tagName === "IFRAME") {
      iframe.src = `https://www.youtube.com/embed/${videoId}?enablejsapi=1&rel=0`;
    }
  }
}

function seekVideo(seconds) {
  seconds = Math.floor(seconds);
  const timeLabel = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  if (!CURRENT_VIDEO_ID) {
    showToast("No video loaded yet");
    return;
  }

  // Try 1: YT Player API (smooth, no reload) — only if actually ready
  if (player && playerReady && typeof player.seekTo === "function") {
    try {
      player.seekTo(seconds, true);
      player.playVideo();
      showToast(`▶ Jumping to ${timeLabel}`);
      return;
    } catch (e) {
      console.warn("YT seekTo failed, using iframe fallback:", e);
    }
  }

  // Try 2: Always-works fallback — set iframe src with ?start=
  // Works even when YT Player API is not initialized
  let el = document.getElementById("youtubePlayer");
  // YT.Player wraps the iframe in a div — find the actual iframe
  let iframe =
    el && el.tagName === "IFRAME" ? el : el && el.querySelector("iframe");

  if (iframe) {
    iframe.src = `https://www.youtube.com/embed/${CURRENT_VIDEO_ID}?start=${seconds}&autoplay=1&enablejsapi=1&rel=0`;
    showToast(`▶ Jumping to ${timeLabel}`);
  } else {
    // Last resort: rebuild the player div entirely
    const videoWrap = document.querySelector(".video-wrap");
    if (videoWrap) {
      const newIframe = document.createElement("iframe");
      newIframe.id = "youtubePlayer";
      newIframe.src = `https://www.youtube.com/embed/${CURRENT_VIDEO_ID}?start=${seconds}&autoplay=1&enablejsapi=1&rel=0`;
      newIframe.title = "YouTube Video";
      newIframe.setAttribute(
        "allow",
        "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share",
      );
      newIframe.setAttribute("allowfullscreen", "");
      newIframe.style.cssText =
        "width:100%;height:100%;display:block;border:0;";
      // Remove old player element and replace with iframe
      if (el) el.parentNode.removeChild(el);
      videoWrap.appendChild(newIframe);
      showToast(`▶ Jumping to ${timeLabel}`);
      // Reset player state so initPlayer can re-run next time
      player = null;
      playerReady = false;
    } else {
      showToast("Could not find video player");
    }
  }
}

// Event delegation for timestamp clicks (avoids inline onclick stripped by DOMPurify)
document.addEventListener("click", function (e) {
  const ts = e.target.closest(".inline-timestamp");
  if (ts) {
    e.preventDefault();
    const seconds = parseInt(ts.getAttribute("data-seconds"), 10);
    if (!isNaN(seconds)) {
      seekVideo(seconds);
    }
  }
});

// =========================================================
// TOAST
// =========================================================

let toastTimer;

function showToast(text) {
  const toast = document.getElementById("toast");
  toast.textContent = text;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 3000); // slightly longer toast for process updates
}

// =========================================================
// ADD USER MESSAGE
// =========================================================

function addUserMessage(text) {
  const message = document.createElement("div");
  message.className = "message user";

  const bubble = document.createElement("div");
  bubble.className = "user-bubble";
  bubble.textContent = text;

  const meta = document.createElement("div");
  meta.className = "user-meta";
  meta.textContent = "Just now ✓✓";

  message.appendChild(bubble);
  message.appendChild(meta);

  messages.appendChild(message);
  messages.scrollTop = messages.scrollHeight;
}

// =========================================================
// ADD ASSISTANT MESSAGE
// =========================================================

function addAssistantMessage() {
  const message = document.createElement("div");
  message.className = "message assistant";

  const row = document.createElement("div");
  row.className = "assistant-row";

  const icon = document.createElement("div");
  icon.className = "mini-ai";
  icon.textContent = "✦";

  const card = document.createElement("div");
  card.className = "assistant-card";

  const label = document.createElement("div");
  label.className = "assistant-label";
  label.textContent = "YouTube RAG Assistant";

  const bubble = document.createElement("div");
  bubble.className = "assistant-markdown";

  row.appendChild(icon);
  row.appendChild(card);

  card.appendChild(label);
  card.appendChild(bubble);

  message.appendChild(row);
  messages.appendChild(message);

  messages.scrollTop = messages.scrollHeight;

  return bubble;
}

// =========================================================
// SEND QUESTION + STREAM RESPONSE
// =========================================================

async function sendQuestion() {
  const question = questionInput.value.trim();

  if (!question || sendButton.disabled) {
    return;
  }

  if (!CURRENT_VIDEO_ID) {
    showToast("Please process a video first using the URL bar.");
    return;
  }

  addUserMessage(question);
  CHAT_HISTORY.push({ role: "user", content: question });

  questionInput.value = "";
  questionInput.style.height = "auto";
  updateSendButtonState();
  sendButton.disabled = true;

  const answerBubble = addAssistantMessage();

  answerBubble.innerHTML = `
    <div class="typing">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;

  try {
    const response = await fetch(API_ASK_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question: question,
        video_id: CURRENT_VIDEO_ID,
        chat_history: CHAT_HISTORY,
      }),
    });

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}`);
    }

    if (!response.body) {
      throw new Error("Backend did not return a streaming body.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");

    let answer = "";

    answerBubble.textContent = "";

    while (true) {
      const { value, done } = await reader.read();

      if (done) {
        break;
      }

      answer += decoder.decode(value, {
        stream: true,
      });

      answerBubble.textContent = answer;
      messages.scrollTop = messages.scrollHeight;
    }

    answer += decoder.decode();
    CHAT_HISTORY.push({ role: "assistant", content: answer });

    renderMarkdown(answerBubble, answer);

    messages.scrollTop = messages.scrollHeight;
  } catch (error) {
    console.error("RAG Error:", error);

    answerBubble.innerHTML = `
      <p>
        Sorry, I couldn't connect to the RAG backend or an error occurred.
      </p>
      <p>
        Error: ${error.message}
      </p>
    `;
  } finally {
    sendButton.disabled = false;
    updateSendButtonState();
    questionInput.focus();
  }
}

// =========================================================
// MARKDOWN
// =========================================================

function renderMarkdown(element, markdown) {
  if (typeof marked === "undefined") {
    element.textContent = markdown;
    return;
  }

  let html = marked.parse(markdown, {
    gfm: true,
    breaks: true,
  });

  if (typeof DOMPurify !== "undefined") {
    html = DOMPurify.sanitize(html);
  }

  element.innerHTML = html;

  // Helper to convert a time string like "02:38" or "1:02:45" into total seconds
  function timeToSeconds(timeStr) {
    const parts = timeStr.split(":").map(Number);
    if (parts.length === 3) {
      return parts[0] * 3600 + parts[1] * 60 + parts[2];
    }
    return parts[0] * 60 + parts[1];
  }

  const rangeTimestampRegex =
    /\[(\d{1,2}(?::\d{2}){1,2})\s*[-–]\s*(\d{1,2}(?::\d{2}){1,2})\]/g;
  const timestampRegex = /\[(\d{1,2}(?::\d{2}){1,2})\]/g;

  // Replace timestamps ONLY in non-code, non-pre elements
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      let parent = node.parentElement;
      while (parent && parent !== element) {
        const tag = parent.tagName;
        if (
          tag === "PRE" ||
          tag === "CODE" ||
          tag === "A" ||
          (parent.classList && parent.classList.contains("code-wrapper"))
        ) {
          return NodeFilter.FILTER_REJECT;
        }
        parent = parent.parentElement;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const textNodes = [];
  while (walker.nextNode()) {
    textNodes.push(walker.currentNode);
  }

  textNodes.forEach((node) => {
    const text = node.nodeValue;
    if (!/\[\d{1,2}(?::\d{2}){1,2}/.test(text)) return;

    let replaced = text.replace(
      rangeTimestampRegex,
      (match, startTime, endTime) => {
        const seconds = timeToSeconds(startTime);
        return `<a href="#" class="inline-timestamp" data-seconds="${seconds}" title="Jump to ${startTime}">▶ ${startTime} - ${endTime}</a>`;
      },
    );
    replaced = replaced.replace(timestampRegex, (match, timeStr) => {
      const seconds = timeToSeconds(timeStr);
      return `<a href="#" class="inline-timestamp" data-seconds="${seconds}" title="Jump to ${match}">▶ ${timeStr}</a>`;
    });

    if (replaced !== text) {
      const span = document.createElement("span");
      span.innerHTML = replaced;
      node.parentNode.replaceChild(span, node);
    }
  });

  const codeBlocks = element.querySelectorAll("pre");

  codeBlocks.forEach((pre) => {
    const code = pre.querySelector("code");

    if (!code) return;

    let language = "code";

    const match = (code.className || "").match(/language-([\w-]+)/);

    if (match) {
      language = match[1];
    }

    const wrapper = document.createElement("div");
    wrapper.className = "code-wrapper";

    const header = document.createElement("div");
    header.className = "code-header";

    const languageLabel = document.createElement("span");
    languageLabel.textContent = language;

    const copyButton = document.createElement("button");
    copyButton.className = "copy-code-btn";
    copyButton.textContent = "Copy";
    copyButton.type = "button";

    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code.innerText);
        copyButton.textContent = "Copied!";

        setTimeout(() => {
          copyButton.textContent = "Copy";
        }, 1400);
      } catch {
        copyButton.textContent = "Failed";
      }
    });

    header.appendChild(languageLabel);
    header.appendChild(copyButton);

    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(header);
    wrapper.appendChild(pre);
  });
}

// =========================================================
// TIMESTAMP DETECTION
// (Previously handled adding buttons at the bottom; now handled inline via renderMarkdown)
// =========================================================

// =========================================================
// ENTER TO SEND
// =========================================================

questionInput.addEventListener("keydown", function (event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendQuestion();
  }
});

// =========================================================
// AUTO RESIZE & SEND BUTTON HIGHLIGHT
// =========================================================

function updateSendButtonState() {
  if (!sendButton || !questionInput) return;
  const hasText = questionInput.value.trim().length > 0;
  if (hasText) {
    sendButton.classList.add("has-input");
  } else {
    sendButton.classList.remove("has-input");
  }
}

function setPrompt(text) {
  if (!questionInput) return;
  questionInput.value = text;
  questionInput.focus();
  questionInput.style.height = "auto";
  questionInput.style.height = Math.min(questionInput.scrollHeight, 120) + "px";
  updateSendButtonState();
}
window.setPrompt = setPrompt;

questionInput.addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
  updateSendButtonState();
});

// =========================================================
// NEW CHAT
// =========================================================

newChatBtn.addEventListener("click", () => {
  CHAT_HISTORY = [];
  messages.innerHTML = `
    <div class="message assistant">
      <div class="assistant-row">
        <div class="mini-ai">✦</div>
        <div class="assistant-card">
          <div class="assistant-label">YouTube RAG Assistant</div>
          <div class="assistant-markdown">
            <p>
              New chat started. Ask me anything about the processed video.
            </p>
          </div>
        </div>
      </div>
    </div>
  `;

  showToast("New chat started");
  questionInput.focus();
});

// =========================================================
// THEME (DARK / LIGHT MODE) CONTROLLER
// Changes ONLY when user clicks the button. Default is Light.
// =========================================================

function applyTheme(theme, showNotification = false) {
  const isDark = theme === "dark";
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");

  const btn = document.getElementById("themeBtn");
  const icon = document.getElementById("themeIcon");

  if (btn) {
    const label = isDark ? "Switch to Crisp Light theme" : "Switch to Obsidian Dark theme";
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
  }

  if (icon) {
    icon.classList.remove("spin-anim");
    void icon.offsetWidth; // Trigger reflow to restart animation
    icon.classList.add("spin-anim");
    icon.textContent = isDark ? "☀️" : "🌙";
  }

  try {
    localStorage.setItem("yt_rag_theme", isDark ? "dark" : "light");
  } catch (e) {}

  if (showNotification) {
    showToast(isDark ? "🌙 Obsidian Dark mode activated" : "☀️ Crisp Light mode activated");
  }
}

function initTheme() {
  let activeTheme = "light";
  try {
    const saved = localStorage.getItem("yt_rag_theme");
    if (saved === "dark") {
      activeTheme = "dark";
    }
  } catch (e) {}

  applyTheme(activeTheme, false);

  const btn = document.getElementById("themeBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      const nextTheme = current === "dark" ? "light" : "dark";
      applyTheme(nextTheme, true);
    });
  }
}

initTheme();
