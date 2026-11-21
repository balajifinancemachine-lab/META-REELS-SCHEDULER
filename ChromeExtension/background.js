const API = "http://127.0.0.1:8765";

const pingServer = async (state, detail = {}) => {
  try {
    await fetch(`${API}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state, detail, at: new Date().toISOString() })
    });
  } catch (e) {}
};

// Immediate ping on service worker execution
pingServer("BACKGROUND_LOADED", { version: "2.2.0" });

chrome.runtime.onInstalled.addListener(() => {
  pingServer("EXTENSION_INSTALLED", { version: "2.2.0" });
});

chrome.runtime.onStartup.addListener(() => {
  pingServer("EXTENSION_STARTUP", {});
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.url && (tab.url.includes("facebook.com") || tab.url.includes("meta.com"))) {
    pingServer("TAB_URL_LOADED", { tabId, status: changeInfo.status, url: tab.url, title: tab.title });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "GET_TASK") {
    fetch(`${API}/next-task?page_id=${encodeURIComponent(msg.pageId || "")}`)
      .then(r => r.json())
      .then(data => sendResponse(data?.task || null))
      .catch(() => sendResponse(null));
    return true;
  }

  if (msg?.type === "REPORT") {
    fetch(`${API}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(msg.payload || {})
    })
      .then(r => r.json())
      .then(sendResponse)
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg?.type === "CLOSE_TAB") {
    const tabId = sender.tab?.id;
    if (tabId) {
      console.log("[Extension Background] Closing completed sender tab:", tabId);
      chrome.tabs.remove(tabId).catch(e => console.warn("Could not remove tab:", e));
    } else {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs && tabs[0]?.id) {
          console.log("[Extension Background] Closing active tab:", tabs[0].id);
          chrome.tabs.remove(tabs[0].id).catch(e => console.warn("Could not remove tab:", e));
        }
      });
    }
    sendResponse({ ok: true });
    return true;
  }

  if (msg?.type === "GET_VIDEO_BLOB") {
    fetch(`${API}/api/video?page_id=${encodeURIComponent(msg.pageId || "")}`)
      .then(r => r.blob())
      .then(async blob => {
        const reader = new FileReader();
        reader.onloadend = () => {
          sendResponse({ ok: true, base64: reader.result, type: blob.type || "video/mp4", size: blob.size });
        };
        reader.readAsDataURL(blob);
      })
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
});