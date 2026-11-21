(() => {
  if (window !== window.top) return; // Strictly ignore iframes
  if (document.documentElement.dataset.metaReelsActive === "true") {
    console.log("[MetaReels] Already active in DOM, skipping duplicate instance.");
    return;
  }
  document.documentElement.dataset.metaReelsActive = "true";
  if (window.__metaReelsSchedulerLoaded) return;
  window.__metaReelsSchedulerLoaded = true;

  const API_DIRECT = "http://127.0.0.1:8765";
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const norm = s => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));

  const pageId = () => {
    try {
      const q = new URLSearchParams(location.search);
      let id = q.get("page_id") || q.get("asset_id") || q.get("global_scope_id") || q.get("business_id") || "";
      if (!id && location.hash) {
        const hashPart = location.hash.includes('?') ? location.hash.split('?')[1] : location.hash;
        const hq = new URLSearchParams(hashPart);
        id = hq.get("page_id") || hq.get("asset_id") || hq.get("global_scope_id") || "";
      }
      if (!id) {
        const m = location.pathname.match(/\b(\d{14,18})\b/);
        if (m) id = m[1];
      }
      if (id) {
        try { sessionStorage.setItem('meta_reels_page_id', id); } catch(e) {}
        return id;
      }
      try {
        const cached = sessionStorage.getItem('meta_reels_page_id');
        if (cached) return cached;
      } catch(e) {}
    } catch(e) {}
    return "";
  };

  const report = async (state, detail = {}) => {
    const payload = {
      page_id: pageId(),
      state,
      detail,
      url: location.href,
      title: document.title,
      at: new Date().toISOString()
    };
    try {
      if (chrome?.runtime?.sendMessage) {
        chrome.runtime.sendMessage({ type: "REPORT", payload });
      }
    } catch (e) {}

    try {
      const res = await fetch(`${API_DIRECT}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) return;
    } catch (err) {}
  };

  const getTask = async () => {
    try {
      if (chrome?.runtime?.sendMessage) {
        const res = await chrome.runtime.sendMessage({ type: "GET_TASK", pageId: pageId() });
        if (res && res.video) return res;
      }
    } catch (e) {}
    try {
      const resp = await fetch(`${API_DIRECT}/next-task?page_id=${encodeURIComponent(pageId())}`);
      const data = await resp.json();
      return data?.task || null;
    } catch (e) {
      return null;
    }
  };

  // Modern React 18+ Synthetic Event Pointer Dispatcher
  const dispatchPointerClick = el => {
    if (!el) return false;
    try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch(e) {}
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const opts = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      screenX: (window.screenX || 0) + x,
      screenY: (window.screenY || 0) + y
    };

    try { el.dispatchEvent(new PointerEvent('pointerover', opts)); } catch(e) {}
    try { el.dispatchEvent(new MouseEvent('mouseover', opts)); } catch(e) {}
    try { el.dispatchEvent(new PointerEvent('pointerdown', { ...opts, button: 0, buttons: 1 })); } catch(e) {}
    try { el.dispatchEvent(new MouseEvent('mousedown', { ...opts, button: 0, buttons: 1 })); } catch(e) {}
    try { el.focus(); } catch(e) {}
    try { el.dispatchEvent(new PointerEvent('pointerup', { ...opts, button: 0, buttons: 0 })); } catch(e) {}
    try { el.dispatchEvent(new MouseEvent('mouseup', { ...opts, button: 0, buttons: 0 })); } catch(e) {}
    try { el.dispatchEvent(new MouseEvent('click', { ...opts, button: 0, buttons: 0 })); } catch(e) {}
    try { el.click(); } catch(e) {}
    return true;
  };

  const isButtonEnabled = b => {
    if (!b) return false;
    if (b.disabled) return false;
    const ad = b.getAttribute('aria-disabled');
    if (ad === 'true' || ad === '') return false;
    if (b.classList.contains('disabled') && !b.classList.contains('enabled')) return false;
    return true;
  };

  const allButtons = () => [
    ...document.querySelectorAll('button, [role="button"], [role="tab"], div[tabindex="0"], a[role="button"]')
  ].filter(visible);

  const buttonByText = texts => {
    const names = texts.map(norm);
    return allButtons().find(b => {
      const bText = norm(b.innerText || b.getAttribute('aria-label') || b.title || "");
      return names.includes(bText) || names.some(n => bText.startsWith(n));
    });
  };

  const isPrimaryNavButton = b => {
    if (!b || !isButtonEnabled(b)) return false;
    const r = b.getBoundingClientRect();
    // Exclude thumbnail pagination/carousel arrows (which are < 45px wide and have no visible text)
    if (r.width < 45 || r.height < 25) return false;
    // Exclude top stepper / breadcrumb bar elements
    if (r.top < 180 && b.closest('[role="tablist"], nav, ol, ul, [data-testid*="stepper" i], div[class*="stepper" i]')) {
      return false;
    }
    // Exclude anything inside the thumbnail or suggestion containers
    if (b.closest('[aria-label*="thumbnail" i], [data-testid*="thumbnail" i], div[class*="thumbnail" i], div[class*="carousel" i]')) {
      return false;
    }
    return true;
  };

  const findAddVideoButton = () => {
    // 1. Direct interactive candidate matching
    const candidates = allButtons().filter(b => {
      const t = norm(b.innerText || b.getAttribute('aria-label') || b.title || "");
      return (
        t === 'add video' ||
        t === 'upload video' ||
        t === 'add media' ||
        t === 'upload media' ||
        t === 'select video' ||
        t === 'choose video' ||
        t.startsWith('add video') ||
        t.startsWith('upload video') ||
        t.startsWith('add media')
      );
    });
    if (candidates.length > 0) return candidates[0];

    // 2. Button or label encapsulating an input[type="file"]
    const fileInput = document.querySelector('input[type="file"]');
    if (fileInput) {
      const p = fileInput.closest('button, [role="button"], label, div[tabindex="0"]');
      if (p && visible(p)) return p;
      if (fileInput.parentElement && visible(fileInput.parentElement)) return fileInput.parentElement;
    }

    // 3. Fallback: Any visible text node with "Add video" or "Upload video" inside a clickable container
    const textNodes = [...document.querySelectorAll('span, div, p, b')].filter(el => {
      if (!visible(el)) return false;
      const t = norm(el.innerText || '');
      return t === 'add video' || t === 'upload video' || t === 'add media';
    });
    for (const el of textNodes) {
      const clickable = el.closest('button, [role="button"], [tabindex="0"]') || el.parentElement || el;
      if (visible(clickable)) return clickable;
    }

    // 4. Broad button match: text includes 'add' and 'video'
    const broad = allButtons().find(b => {
      const t = norm(b.innerText || b.getAttribute('aria-label') || "");
      return t.includes('add') && (t.includes('video') || t.includes('media'));
    });
    if (broad) return broad;

    return null;
  };

  const findNextButton = () => {
    // 1. Look for buttons that explicitly contain visible text starting with "next", "continue", "proceed"
    const candidates = allButtons().filter(b => {
      if (!isPrimaryNavButton(b)) return false;
      const t = norm(b.innerText || b.getAttribute('aria-label') || b.title || "");
      return (
        t === 'next' ||
        t === 'next step' ||
        t === 'continue' ||
        t === 'proceed' ||
        t.startsWith('next')
      );
    });
    if (candidates.length > 0) {
      candidates.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
      return candidates[0];
    }

    // 2. Spatial Heuristic: Look for footer navigation bar
    // In Meta composer dialog, there is often a [ Back ] button on the left, and the [ Next ] button is on the right!
    const backBtn = buttonByText(['Back', 'back']);
    if (backBtn) {
      const backRect = backBtn.getBoundingClientRect();
      const rightCandidates = allButtons().filter(b => {
        if (b === backBtn || !isPrimaryNavButton(b)) return false;
        const r = b.getBoundingClientRect();
        const t = norm(b.innerText || b.getAttribute('aria-label') || "");
        if (t === 'back' || t === 'cancel' || t === 'discard' || t.includes('feedback')) return false;
        return r.left >= backRect.right - 10 && Math.abs(r.top - backRect.top) < 60;
      });
      if (rightCandidates.length > 0) {
        rightCandidates.sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
        const best = rightCandidates[0];
        const t = norm(best.innerText || best.getAttribute('aria-label') || "");
        if (!t.startsWith('share') && !t.startsWith('publish')) {
          return best;
        }
      }
    }

    // 3. Fallback: aria-label="Next" in bottom half of viewport
    const ariaCandidates = allButtons().filter(b => {
      if (!isPrimaryNavButton(b)) return false;
      const a = norm(b.getAttribute('aria-label') || b.title || "");
      const r = b.getBoundingClientRect();
      return (a === 'next' || a.startsWith('next')) && r.top > 250;
    });
    if (ariaCandidates.length > 0) {
      ariaCandidates.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
      return ariaCandidates[0];
    }

    return null;
  };

  const findShareButton = (requireEnabled = true) => {
    // 1. Interactive candidate elements with explicit text or aria
    const interactiveElements = [
      ...document.querySelectorAll(
        'button, [role="button"], [tabindex="0"], a[role="button"], div[aria-label], span[aria-label], div[class*="button" i], [data-testid*="publish" i], [data-testid*="share" i]'
      )
    ].filter(visible);

    const candidates = interactiveElements.filter(b => {
      const r = b.getBoundingClientRect();
      // CRITICAL: Must be in lower/footer area of screen (never the top stepper tab at top ~59px)
      if (r.top < 200) return false;
      if (r.width < 35 || r.height < 18) return false;
      if (b.closest('[role="tablist"], nav, ol, ul, [data-testid*="stepper" i], div[class*="stepper" i], [aria-label*="thumbnail" i], [data-testid*="thumbnail" i], div[class*="thumbnail" i], div[class*="carousel" i]')) {
        return false;
      }
      if (requireEnabled && !isButtonEnabled(b)) return false;
      const t = norm(b.innerText || b.getAttribute('aria-label') || b.title || "");
      return (
        t === 'share' ||
        t === 'share now' ||
        t === 'share reel' ||
        t === 'publish' ||
        t === 'publish now' ||
        t === 'post' ||
        t === 'post now' ||
        t.startsWith('share') ||
        t.startsWith('publish')
      );
    });

    if (candidates.length > 0) {
      candidates.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
      return candidates[0];
    }

    // 2. Spatial Heuristic on Step 3:
    // If Step 3 (Share) is active or "Checking for copyrighted content" is present,
    // look for the [ Back ] button in footer and pick the button directly to the right!
    const backBtn = buttonByText(['Back', 'back']);
    if (backBtn) {
      const backRect = backBtn.getBoundingClientRect();
      const footerBtns = allButtons().filter(b => {
        if (b === backBtn) return false;
        const r = b.getBoundingClientRect();
        if (r.top < 200) return false;
        if (requireEnabled && !isButtonEnabled(b)) return false;
        if (r.width < 40 || r.height < 20) return false;
        const t = norm(b.innerText || b.getAttribute('aria-label') || "");
        if (t === 'back' || t === 'cancel' || t === 'discard' || t.includes('feedback')) return false;
        return r.left >= backRect.right - 10 && Math.abs(r.top - backRect.top) < 60;
      });
      if (footerBtns.length > 0) {
        footerBtns.sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
        return footerBtns[0];
      }
    }

    // 3. Fallback: Scan text nodes strictly containing "Share", "Share now", "Share reel", or "Publish"
    const textNodes = [...document.querySelectorAll('span, div, p, b, strong')].filter(el => {
      if (!visible(el)) return false;
      const t = norm(el.innerText || '');
      if (t !== 'share' && t !== 'share now' && t !== 'share reel' && t !== 'publish' && t !== 'publish now' && t !== 'post') return false;
      const r = el.getBoundingClientRect();
      if (r.top < 200) return false; // Never stepper tab
      if (el.closest('[role="tablist"], nav, ol, ul, [data-testid*="stepper" i], div[class*="stepper" i]')) return false;
      return r.width > 20 && r.height > 15;
    });

    for (const el of textNodes) {
      const clickable = el.closest('button, [role="button"], [tabindex="0"], div[aria-label]') || el.parentElement || el;
      if (requireEnabled && !isButtonEnabled(clickable)) continue;
      const cr = clickable.getBoundingClientRect();
      if (cr.top >= 200) return clickable;
    }

    return null;
  };

  const isShareScreenActive = () => {
    // 1. Check if a genuine Share/Publish button exists in footer (top >= 200)
    const shareBtn = findShareButton(false);
    if (shareBtn) return true;

    // 2. Progress step headers: Step 3 (Share) active/selected
    const stepElements = [...document.querySelectorAll('[role="tab"], [role="button"], div[class*="step"], div, span')];
    for (const s of stepElements) {
      const txt = norm(s.innerText || '');
      if (txt === 'share' || txt === '3 share' || txt === 'share reel' || txt === 'publish') {
        const isSelected = s.getAttribute('aria-selected') === 'true' ||
                           s.getAttribute('aria-current') === 'step' ||
                           s.classList.contains('active') ||
                           s.closest('[aria-current="step"]');
        if (isSelected) return true;
      }
    }

    // 3. Screen navigation state: On composer with "Back" button but NO "Next" button and NO "Add video" button
    const hasBack = !!buttonByText(['Back']);
    const hasNext = !!findNextButton();
    const hasAddVideo = !!findAddVideoButton();
    if (hasBack && !hasNext && !hasAddVideo) {
      return true;
    }

    return false;
  };

  const findDoneButton = () => {
    const interactiveElements = [
      ...document.querySelectorAll('button, [role="button"], [tabindex="0"], a[role="button"], div[aria-label], span[aria-label]')
    ].filter(visible);

    const candidates = interactiveElements.filter(b => {
      if (!isButtonEnabled(b)) return false;
      const t = norm(b.innerText || b.getAttribute('aria-label') || "");
      return (
        t === 'done' ||
        t === 'close' ||
        t === 'got it' ||
        t === 'ok' ||
        t === 'finish' ||
        t === 'dismiss' ||
        t.startsWith('done')
      );
    });
    if (candidates.length > 0) {
      candidates.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
      return candidates[0];
    }

    // Modal dialog primary button match
    const dialogs = [...document.querySelectorAll('[role="dialog"], [aria-modal="true"], div[class*="modal" i], div[class*="dialog" i]')].filter(visible);
    for (const d of dialogs) {
      const dText = norm(d.innerText || '');
      if (dText.includes('reel processing') || dText.includes('finishes') || dText.includes('published') || dText.includes('shared')) {
        const btns = [...d.querySelectorAll('button, [role="button"], div[tabindex="0"]')].filter(b => visible(b) && isButtonEnabled(b));
        if (btns.length > 0) {
          btns.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
          return btns[0];
        }
      }
    }

    // Fallback: any visible text node with "Done"
    const textNodes = [...document.querySelectorAll('span, div, p, b')].filter(el => {
      if (!visible(el)) return false;
      const t = norm(el.innerText || '');
      return t === 'done' || t === 'got it';
    });
    for (const el of textNodes) {
      const clickable = el.closest('button, [role="button"], [tabindex="0"]') || el.parentElement || el;
      if (isButtonEnabled(clickable)) return clickable;
    }
    return null;
  };

  const clickNavButton = async (btn, actionName) => {
    if (!btn) return false;
    try { btn.scrollIntoView({ block: 'center', inline: 'center' }); } catch(e) {}
    await sleep(250);
    const r = btn.getBoundingClientRect();

    // 1. Send hardware click request to Python DesktopCommander with exact screen coordinates
    // This generates genuine isTrusted: true events to bypass Meta React's publish guard!
    await report('NAV_CLICK_REQUEST', {
      action: actionName,
      text: (btn.innerText || '').trim(),
      target: { x: r.left + r.width / 2, y: r.top + r.height / 2, left: r.left, top: r.top, width: r.width, height: r.height },
      window: {
        screenX: window.screenX,
        screenY: window.screenY,
        outerWidth: window.outerWidth,
        outerHeight: window.outerHeight,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio || 1
      }
    });

    // 2. Dispatch genuine synthetic pointer click directly in DOM for all actions (NEXT, SHARE, PUBLISH, DONE)
    dispatchPointerClick(btn);
    return true;
  };

  const isTagsBox = el => {
    if (!el) return false;
    const p = (el.getAttribute('placeholder') || '').toLowerCase();
    const a = (el.getAttribute('aria-label') || '').toLowerCase();
    const dp = (el.getAttribute('data-placeholder') || '').toLowerCase();
    const parentText = (el.parentElement?.innerText || '').toLowerCase();
    return /tag|keyword|help people find/i.test(p + ' ' + a + ' ' + dp + ' ' + parentText);
  };

  const isBlankPage = () => {
    const text = norm(pageText());
    const hasAdd = !!findAddVideoButton();
    const hasNext = !!findNextButton();
    const hasShare = !!findShareButton();
    const hasDetails = text.includes('reel details') || text.includes('create reel');
    if (hasAdd || hasNext || hasShare || hasDetails) return false;
    return text.length < 50;
  };

  const findCaptionBox = () => {
    // 1. Lexical Editor (the standard Meta Reels composer editor)
    const lexicals = [...document.querySelectorAll('[data-lexical-editor="true"], [role="combobox"][contenteditable="true"]')].filter(visible);
    const validLexical = lexicals.find(el => !isTagsBox(el));
    if (validLexical) return validLexical;

    // 2. Contenteditable inside "Reel details" or "Text" section
    const headings = [...document.querySelectorAll('div, span, h2, h3, h4, [role="heading"]')].filter(visible);
    const detailHeading = headings.find(h => /^(reel details|text)$/i.test((h.innerText || '').trim()));
    if (detailHeading) {
      let p = detailHeading.parentElement;
      for (let i = 0; i < 8 && p && p !== document.body; i++) {
        const box = p.querySelector('[contenteditable="true"], [role="textbox"], textarea');
        if (box && visible(box) && !isTagsBox(box)) return box;
        p = p.parentElement;
      }
    }

    // 3. Textbox with placeholder / aria-label matching reel caption
    const editables = [...document.querySelectorAll('[contenteditable="true"], [role="textbox"], textarea')].filter(el => visible(el) && !isTagsBox(el));
    let found = editables.find(el => {
      const txt = [
        el.getAttribute('placeholder') || '',
        el.getAttribute('aria-label') || '',
        el.getAttribute('data-placeholder') || '',
        el.parentElement?.innerText || ''
      ].join(' ').toLowerCase();
      return /let viewers know|what your reel is about|write something|describe your reel|caption/i.test(txt);
    });
    if (found) return found;

    return null;
  };

  const findReelDetailsContainer = () => {
    const headings = [...document.querySelectorAll('div, span, h2, h3, h4, [role="heading"]')].filter(visible);
    const detailHeading = headings.find(h => /^(reel details|text)$/i.test((h.innerText || '').trim()));
    if (detailHeading) {
      let p = detailHeading.parentElement;
      for (let i = 0; i < 8 && p && p !== document.body; i++) {
        if (p.querySelector('[contenteditable="true"], [role="combobox"], [role="textbox"], textarea')) {
          return p;
        }
        p = p.parentElement;
      }
    }
    const cap = findCaptionBox();
    if (cap) {
      let p = cap.parentElement;
      for (let i = 0; i < 8 && p && p !== document.body; i++) {
        const btns = p.querySelectorAll('button, [role="button"], div[tabindex="0"]');
        if (btns.length >= 3) return p;
        p = p.parentElement;
      }
    }
    return document.body;
  };

  const findToolbarButtonsBelowCaption = () => {
    const captionEl = findCaptionBox();
    if (!captionEl) return [];
    const container = findReelDetailsContainer();
    const captionRect = captionEl.getBoundingClientRect();
    
    // Find all clickable buttons or icon divs inside container
    const all = [...container.querySelectorAll('button, [role="button"], div[tabindex="0"], [aria-label]')].filter(visible);
    const below = all.filter(b => {
      if (b === captionEl || b.contains(captionEl) || captionEl.contains(b)) return false;
      const r = b.getBoundingClientRect();
      if (r.width < 12 || r.width > 120 || r.height < 12 || r.height > 80) return false;
      return r.top >= captionRect.bottom - 15 && r.top <= captionRect.bottom + 150;
    });

    // Deduplicate any child/parent duplicates
    const unique = [];
    for (const b of below) {
      if (!unique.some(u => u.contains(b) || b.contains(u))) {
        unique.push(b);
      }
    }

    // Sort horizontally from left to right:
    // 1st (leftmost) = Messenger CTA
    // 2nd (center) = Location pin
    // 3rd (rightmost) = Tag people
    unique.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
    return unique;
  };

  const findMessageButton = () => {
    // 1. Check aria-label / title / tooltip
    const candidates = [...document.querySelectorAll('button, [role="button"], div[tabindex="0"], [data-tooltip-content], [aria-label]')].filter(visible);
    let btn = candidates.find(b => {
      const s = [b.getAttribute('aria-label'), b.getAttribute('data-tooltip-content'), b.title, b.innerText].join(' ');
      return /get message|send message|messaging|messenger|chat/i.test(s);
    });
    if (btn) return btn;

    // 2. SVG match for messenger bubble / lightning
    const svgs = [...document.querySelectorAll('svg')].filter(visible);
    const msgSvg = svgs.find(s => {
      const p = s.closest('button, [role="button"], div[tabindex="0"]');
      const txt = [s.getAttribute('aria-label'), p?.getAttribute('aria-label'), p?.getAttribute('data-tooltip-content')].join(' ');
      if (/message|chat|lightning|messenger/i.test(txt)) return true;
      const d = (s.innerHTML || '').toLowerCase();
      return d.includes('m12') && (d.includes('lightning') || d.includes('bubble') || d.includes('messenger'));
    });
    if (msgSvg) {
      const p = msgSvg.closest('button, [role="button"], div[tabindex="0"]');
      if (p) return p;
    }

    // 3. Toolbar below caption: 1st icon on the left is Messenger!
    const below = findToolbarButtonsBelowCaption();
    if (below.length > 0) {
      const matching = below.find(b => /message|chat|messenger/i.test([b.getAttribute('aria-label'), b.title, b.innerText].join(' ')));
      if (matching) return matching;
      return below[0]; // Leftmost icon is Messenger CTA
    }

    return null;
  };

  const findLocationButton = () => {
    // 1. Check aria-label / title / tooltip
    const candidates = [...document.querySelectorAll('button, [role="button"], div[tabindex="0"], [data-tooltip-content], [aria-label]')].filter(visible);
    let btn = candidates.find(b => {
      const s = [b.getAttribute('aria-label'), b.getAttribute('data-tooltip-content'), b.title, b.innerText].join(' ');
      return /location|add location|tag location|place|pin/i.test(s);
    });
    if (btn) return btn;

    // 2. SVG pin match
    const svgs = [...document.querySelectorAll('svg')].filter(visible);
    const pinSvg = svgs.find(s => {
      const p = s.closest('button, [role="button"], div[tabindex="0"]');
      const txt = [s.getAttribute('aria-label'), p?.getAttribute('aria-label'), p?.getAttribute('data-tooltip-content')].join(' ');
      return /location|place|pin/i.test(txt);
    });
    if (pinSvg) {
      const p = pinSvg.closest('button, [role="button"], div[tabindex="0"]');
      if (p) return p;
    }

    // 3. Toolbar below caption: 2nd icon (middle) is Location pin!
    const below = findToolbarButtonsBelowCaption();
    if (below.length >= 2) {
      const matching = below.find(b => /location|place|pin/i.test([b.getAttribute('aria-label'), b.title, b.innerText].join(' ')));
      if (matching) return matching;
      return below[1]; // Middle icon is Location pin
    } else if (below.length === 1) {
      return below[0];
    }

    return null;
  };

  // Modern MutationObserver-backed waitFor with fallback interval
  const waitFor = (fn, timeout = 60000, interval = 500) => {
    return new Promise(resolve => {
      let resolved = false;
      let timer = null;
      let observer = null;

      const check = () => {
        if (resolved) return;
        try {
          const v = fn();
          if (v) {
            cleanup();
            resolve(v);
          }
        } catch (e) {}
      };

      const cleanup = () => {
        resolved = true;
        if (timer) clearInterval(timer);
        if (observer) observer.disconnect();
      };

      // Check immediately
      try {
        const init = fn();
        if (init) return resolve(init);
      } catch (e) {}

      // Observe DOM mutations
      observer = new MutationObserver(() => check());
      observer.observe(document.body || document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true
      });

      // Periodic check as fallback
      timer = setInterval(check, interval);

      // Timeout
      setTimeout(() => {
        if (!resolved) {
          cleanup();
          resolve(null);
        }
      }, timeout);
    });
  };

  const pageText = () => (document.body?.innerText || "").slice(0, 40000);

  const securityCheck = () => {
    const t = norm(pageText());
    if (/confirm your identity|unusual activity|security check|two-factor|enter login code|verify it's you|captcha/.test(t)) {
      return "SECURITY_CHALLENGE";
    }
    if (document.querySelector('input[type="password"]') || (/log in to facebook/.test(t) && /email address|phone number/.test(t))) {
      return "NEEDS_LOGIN";
    }
    return "";
  };

  const detectCurrentStage = () => {
    const t = norm(pageText());
    if (t.includes('reel processing') || t.includes('once your reel finishes') || findDoneButton()) {
      return "DONE_MODAL";
    }
    if (isShareScreenActive()) {
      return "SCREEN_3_SHARE";
    }
    if ((t.includes('audio') && t.includes('crop')) || t.includes('optimizations')) {
      return "SCREEN_2_EDIT";
    }
    if (t.includes('create reel') || t.includes('reel details') || t.includes('media')) {
      return "SCREEN_1_CREATE";
    }
    const sec = securityCheck();
    if (sec) return sec;
    return "UNKNOWN";
  };

  const setText = (el, text) => {
    if (!el) return false;
    try { el.focus(); } catch(e) {}
    if (el.isContentEditable || el.getAttribute('contenteditable') === 'true') {
      try {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(el);
        sel.removeAllRanges();
        sel.addRange(range);
      } catch (e) {}
      
      // Method 1: DataTransfer paste event (standard clipboard paste simulation)
      try {
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        const pasteEv = new ClipboardEvent('paste', {
          bubbles: true,
          cancelable: true,
          clipboardData: dt
        });
        el.dispatchEvent(pasteEv);
      } catch(e) {}

      // Method 2: InputEvent beforeinput + insertText
      try {
        el.dispatchEvent(new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          inputType: 'insertText',
          data: text
        }));
      } catch(e) {}

      // Method 3: InputEvent input
      try {
        el.dispatchEvent(new InputEvent('input', {
          bubbles: true,
          inputType: 'insertText',
          data: text
        }));
      } catch(e) {}
    } else {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(el, text);
      else el.value = text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return true;
  };

  const uploadPreviewDetected = filename => {
    const body = norm(pageText());
    const baseName = (filename || '').split(/[\\/]/).pop() || '';
    const prefix = baseName.replace(/\.[^/.]+$/, '').slice(0, 10).toLowerCase();
    const hasName = prefix && body.includes(prefix);

    // Look for real delete/remove button next to uploaded media
    const deleteBtn = [...document.querySelectorAll('button, [role="button"]')].find(b => {
      const a = (b.getAttribute('aria-label') || b.title || '').toLowerCase();
      return (a.includes('delete') || a.includes('remove') || a.includes('trash')) && visible(b);
    });
    const hasDelete = !!deleteBtn;

    // Check for upload progress percentage: "1%" to "99%" (e.g., 53%)
    const pctMatch = body.match(/\b([1-9]|[1-9]\d)\s*%/);
    const hasProgressPct = !!(pctMatch && parseInt(pctMatch[1], 10) < 100);
    const has100Text = /\b100\s*%\b/.test(body) || /video uploaded|upload complete/i.test(body);

    const isUploadingText = /uploading\b|processing video|preparing video|uploading video/i.test(body);
    const nextBtn = findNextButton();
    const hasNext = !!(nextBtn && isButtonEnabled(nextBtn));

    // A genuine video tag or blob thumbnail attached to composer (never generic canvas)
    const hasVideoTag = !!document.querySelector('video, img[src^="blob:"], [style*="blob:"]') || /change video|replace video/i.test(body);
    const hasSafeNotice = /safe to publish|no copyright issues|video uploaded|upload complete/i.test(body);

    // A video upload is ACTIVELY BUSY if:
    // 1. Progress percentage < 100% exists (e.g. 53%)
    // 2. OR text explicitly says "uploading" / "processing video"
    // 3. OR media has actually been selected (delete button or file name present) while Next is not yet enabled
    const isBusy = hasProgressPct || isUploadingText || (!hasNext && (hasDelete || hasName));

    // A video upload is ONLY COMPLETED if:
    // 1. Next button IS ENABLED (Meta only enables Next when upload and processing are done!)
    // 2. AND upload is NOT busy (no 53%, no uploading text)
    // 3. AND there is evidence of video (100% text, delete button, video tag, safe notice, or Next is enabled)
    const hasMediaEvidence = hasDelete || has100Text || hasVideoTag || hasSafeNotice || (hasName && hasNext) || hasNext;
    const isCompleted = hasNext && !isBusy && hasMediaEvidence;

    return {
      ok: isCompleted,
      busy: isBusy,
      hasDelete,
      hasNext,
      has100Text,
      progressPct: pctMatch ? pctMatch[1] : (has100Text ? "100" : "")
    };
  };

  const selectMessages = async () => {
    await report('SELECTING_MESSAGES_START', {});
    const reelCard = findReelDetailsContainer();
    if (reelCard && reelCard !== document.body) {
      try { reelCard.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch(e) {}
      await sleep(350);
    }
    const msgBtn = await waitFor(() => findMessageButton(), 10000, 300);
    if (!msgBtn) {
      console.warn("Message CTA button not found or disabled on this page");
      await report('MESSAGES_BUTTON_NOT_FOUND', {});
      return false;
    }

    try { msgBtn.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch(e) {}
    await sleep(250);
    await report('MESSAGES_BUTTON_CLICKING', {
      aria: msgBtn.getAttribute('aria-label'),
      title: msgBtn.title
    });
    dispatchPointerClick(msgBtn);
    await sleep(1000);
    await report('MESSAGES_BUTTON_CLICKED', {});
    return true;
  };

  const findLocationSaveButton = () => {
    const dialogs = [...document.querySelectorAll('[role="dialog"], [aria-modal="true"], div[class*="dialog"], div[class*="modal"]')].filter(visible);
    for (const d of dialogs) {
      const btns = [...d.querySelectorAll('button, [role="button"]')].filter(visible);
      const save = btns.find(b => {
        const t = norm(b.innerText || b.getAttribute('aria-label') || b.title || "");
        return (t === 'save' || t === 'done' || t === 'apply') && isButtonEnabled(b);
      });
      if (save) return save;
    }
    const all = allButtons();
    return all.find(b => {
      const t = norm(b.innerText || b.getAttribute('aria-label') || "");
      return (t === 'save' || t === 'done') && isButtonEnabled(b);
    }) || null;
  };

  const selectLocation = async locationName => {
    if (!locationName) return true;
    const normLoc = norm(locationName);
    const body = norm(pageText());
    if (body.includes(normLoc) && /is in|location|tagged/.test(body)) {
      return true;
    }

    await report('SELECTING_LOCATION_START', { location: locationName });

    const reelCard = findReelDetailsContainer();
    if (reelCard && reelCard !== document.body) {
      try { reelCard.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch(e) {}
      await sleep(350);
    }

    const locButton = await waitFor(() => findLocationButton(), 10000, 300);
    if (!locButton) {
      console.warn("Location button not found");
      await report('LOCATION_BUTTON_NOT_FOUND', {});
      return false;
    }

    try { locButton.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch(e) {}
    await sleep(250);
    await report('LOCATION_BUTTON_CLICKING', { text: locButton.innerText, aria: locButton.getAttribute('aria-label') });
    dispatchPointerClick(locButton);
    await sleep(1500);

    const searchInput = await waitFor(() => {
      const inputs = [...document.querySelectorAll('input, [role="combobox"], [role="searchbox"]')].filter(visible);
      return inputs.find(el => /search|location|place|where are you|find a place/i.test(
        [el.getAttribute('placeholder'), el.getAttribute('aria-label'), el.title].join(' ')
      )) || inputs.find(el => el.tagName === 'INPUT' && (el.type === 'text' || !el.type));
    }, 15000, 300);

    if (!searchInput) {
      await report('LOCATION_SEARCH_INPUT_NOT_FOUND', {});
      return false;
    }

    setText(searchInput, locationName);
    await sleep(2000);

    const firstOption = await waitFor(() => {
      const results = [...document.querySelectorAll('[role="option"], [role="listbox"] [role="button"], [role="listbox"] div[tabindex], [role="menuitem"], li, [data-testid*="result"]')]
        .filter(visible);
      const matching = results.filter(el => norm(el.innerText).includes(normLoc));
      return matching[0] || results[0] || null;
    }, 15000, 300);

    if (!firstOption) {
      await report('LOCATION_FIRST_OPTION_NOT_FOUND', {});
      return false;
    }

    await report('LOCATION_OPTION_CLICKING', { optionText: firstOption.innerText });
    dispatchPointerClick(firstOption);
    await sleep(1200);

    // Step: Click Save button in Location modal
    await report('WAITING_FOR_LOCATION_SAVE_BUTTON', {});
    const saveBtn = await waitFor(() => findLocationSaveButton(), 8000, 300);
    if (saveBtn) {
      await report('LOCATION_SAVE_CLICKING', { text: saveBtn.innerText });
      dispatchPointerClick(saveBtn);
      // Wait for modal to disappear
      await waitFor(() => !findLocationSaveButton(), 8000, 300);
      await sleep(1500);
    } else {
      // Fallback: press Enter on searchInput
      try {
        searchInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
        searchInput.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
      } catch(e) {}
      await sleep(1000);
    }

    // Verify modal is closed
    const modalRemaining = findLocationSaveButton();
    if (modalRemaining) {
      try {
        document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true }));
      } catch(e) {}
      await sleep(1000);
    }

    await report('LOCATION_MODAL_HANDLED', { location: locationName });
    return true;
  };

  const performVideoUpload = async (task, addVideoBtn) => {
    // 1. Direct DataTransfer injection if an input[type="file"] already exists
    let fileInput = document.querySelector('input[type="file"]');
    if (fileInput) {
      try {
        let blob = null;
        try {
          const fetchRes = await fetch(`${API_DIRECT}/api/video?page_id=${encodeURIComponent(task.id || "")}`);
          if (fetchRes.ok) blob = await fetchRes.blob();
        } catch (e) {}

        if (blob) {
          const filename = (task.video || "reel.mp4").split(/[\\/]/).pop();
          const file = new File([blob], filename, { type: blob.type || "video/mp4" });
          const dt = new DataTransfer();
          dt.items.add(file);
          fileInput.files = dt.files;
          fileInput.dispatchEvent(new Event('input', { bubbles: true }));
          fileInput.dispatchEvent(new Event('change', { bubbles: true }));
          await report('DATA_TRANSFER_FILE_INJECTED', { filename, size: blob.size });
          await sleep(1500);
        }
      } catch (e) {
        console.warn("Direct DataTransfer injection notice:", e);
      }
    }

    // 2. Notify Python desktop assistant to perform calibrated hardware click + Windows Open dialog interaction
    if (addVideoBtn) {
      try { addVideoBtn.scrollIntoView({ block: 'center', inline: 'center' }); } catch(e) {}
      await sleep(200);

      const r = addVideoBtn.getBoundingClientRect();
      await report('FILE_PICKER_REQUEST', {
        video: task.video,
        target: { x: r.left + r.width / 2, y: r.top + r.height / 2, left: r.left, top: r.top, width: r.width, height: r.height },
        window: {
          screenX: window.screenX,
          screenY: window.screenY,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight,
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          devicePixelRatio: window.devicePixelRatio || 1
        }
      });
      // Allow Python desktop helper to perform calibrated hardware click
      try { dispatchPointerClick(addVideoBtn); } catch(e) {}
      await sleep(1000);
    }
  };

  // Modular execution actions mapped directly to REST API and WebSocket
  const executeAction = async (action, params = {}) => {
    switch (action) {
      case "UPLOAD": {
        const addBtn = findAddVideoButton();
        const task = await getTask() || { video: params.video || "" };
        await performVideoUpload(task, addBtn);
        return { ok: true, action: "UPLOAD" };
      }
      case "SET_CAPTION": {
        const capBox = await waitFor(() => findCaptionBox(), 10000, 300);
        if (!capBox) return { ok: false, error: "Caption box not found" };
        setText(capBox, params.caption || "loan");
        await sleep(500);
        await report('CAPTION_FILLED', { caption: params.caption || "loan" });
        return { ok: true, action: "SET_CAPTION", caption: params.caption || "loan" };
      }
      case "SET_LOCATION": {
        const locOk = await selectLocation(params.location || "Mumbai");
        return { ok: locOk, action: "SET_LOCATION", location: params.location || "Mumbai" };
      }
      case "SELECT_MESSAGES": {
        const msgOk = await selectMessages();
        return { ok: msgOk, action: "SELECT_MESSAGES" };
      }
      case "NEXT_EDIT":
      case "NEXT": {
        const nextBtn = await waitFor(() => findNextButton(), 10000, 300);
        if (!nextBtn) return { ok: false, error: "Next button not found or disabled" };
        dispatchPointerClick(nextBtn);
        await sleep(1500);
        await report('NEXT_CLICKED', { text: nextBtn.innerText });
        return { ok: true, action: "NEXT" };
      }
      case "SHARE":
      case "PUBLISH": {
        let shareBtn = await waitFor(() => findShareButton(true), 15000, 300);
        if (!shareBtn) {
          shareBtn = findShareButton(false);
        }
        if (!shareBtn) return { ok: false, error: "Share button not found" };
        await clickNavButton(shareBtn, 'SHARE');
        await sleep(1500);
        await report('SHARE_BUTTON_CLICKED', {});
        return { ok: true, action: "SHARE" };
      }
      case "DONE": {
        let doneBtn = await waitFor(() => findDoneButton() || buttonByText(['Done']), 15000, 300);
        if (!doneBtn) return { ok: false, error: "Done button not found" };
        await clickNavButton(doneBtn, 'DONE');
        await sleep(1500);
        await report('DONE_BUTTON_CLICKED', {});
        return { ok: true, action: "DONE" };
      }
      case "CLOSE": {
        try { chrome?.runtime?.sendMessage({ type: "CLOSE_TAB" }); } catch(e) {}
        try { window.close(); } catch(e) {}
        return { ok: true, action: "CLOSE" };
      }
      case "STATUS":
      case "DOM_STATUS": {
        return {
          ok: true,
          page_id: pageId(),
          stage: detectCurrentStage(),
          preview: uploadPreviewDetected(),
          nextEnabled: !!findNextButton(),
          shareEnabled: !!findShareButton(),
          doneVisible: !!(findDoneButton() || buttonByText(['Done']))
        };
      }
      case "RUN_PIPELINE": {
        const pTask = params.task || await getTask();
        if (pTask) runTask(pTask);
        return { ok: true, action: "RUN_PIPELINE" };
      }
      default:
        return { ok: false, error: `Unknown action: ${action}` };
    }
  };

  // Two-way WebSocket connection to local scheduler
  const setupWebSocket = () => {
    try {
      const pid = pageId();
      if (!pid) return;
      const wsUrl = `ws://127.0.0.1:8765/ws/page/${encodeURIComponent(pid)}`;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        report('WS_CONNECTED', { page_id: pid });
      };

      ws.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "EXEC_ACTION") {
            const res = await executeAction(data.action, data.params || {});
            ws.send(JSON.stringify({ type: "ACTION_RESULT", id: data.id, page_id: pid, ...res }));
          }
        } catch (e) {
          console.error("WS command processing error:", e);
        }
      };

      ws.onerror = () => {};
      ws.onclose = () => {
        setTimeout(setupWebSocket, 3000);
      };
    } catch (e) {}
  };

  const stepFillCaption = async task => {
    if (!task.caption) return true;
    await report('FILLING_CAPTION_START', { caption: task.caption });
    const captionField = await waitFor(() => findCaptionBox(), 30000, 500);
    if (captionField) {
      captionField.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(500);
      setText(captionField, task.caption);
      await sleep(400);

      // Fallback: Verify text landed, otherwise dispatch OS-level clipboard paste
      const cur = (captionField.innerText || captionField.textContent || captionField.value || '').trim();
      if (!cur || cur.length < 2) {
        try {
          await fetch(`${API_DIRECT}/api/action/paste-clipboard`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ page_id: task.id || pageId(), text: task.caption })
          });
          await sleep(500);
        } catch(e) {}
      }

      await sleep(800);
      await report('CAPTION_FILLED', { caption: task.caption });
      return true;
    } else {
      await report('CAPTION_BOX_NOT_FOUND', { message: 'Caption box not found in Reel details.' });
      return false;
    }
  };

  const stepFillLocation = async task => {
    if (!task.location) return true;
    const ok = await selectLocation(task.location);
    if (ok) await report('LOCATION_SELECTED', { location: task.location });
    return ok;
  };

  const stepFillMessages = async () => {
    return await selectMessages();
  };

  const stepUploadVideo = async (task, composer) => {
    const addVideo = composer?.add || findAddVideoButton();
    if (!addVideo) {
      await report('ADD_VIDEO_BUTTON_NOT_FOUND', { message: 'Add Video button not found.' });
      return false;
    }
    await performVideoUpload(task, addVideo);

    await report('WAITING_FOR_VIDEO_UPLOAD', {});
    let uploadWaitCount = 0;
    const uploaded = await waitFor(() => {
      uploadWaitCount++;
      const sec = securityCheck(); if (sec) return { security: sec };
      const v = uploadPreviewDetected(task.video);
      if (v.ok && !v.busy) return v;

      // Stall Recovery: If after 14s there is NO upload activity (not busy, no preview, no progress %)
      // Re-trigger performVideoUpload every 14s!
      if (uploadWaitCount >= 14 && uploadWaitCount % 14 === 0 && !v.busy && !v.progressPct && !v.ok) {
        console.log(`[StallRecovery] Upload not progressing after ${uploadWaitCount}s. Re-triggering file picker...`);
        report('VIDEO_UPLOAD_RETRYING', { elapsed: uploadWaitCount });
        const curAdd = findAddVideoButton();
        if (curAdd) performVideoUpload(task, curAdd);
      }

      if (uploadWaitCount % 3 === 0) {
        report('WAITING_FOR_VIDEO_UPLOAD_TICK', {
          elapsed_seconds: uploadWaitCount,
          busy: v.busy,
          hasNext: v.hasNext,
          progress: v.progressPct ? `${v.progressPct}%` : 'Waiting for upload to finish...'
        });
      }
      return null;
    }, 600000, 1000); // Wait up to 10 minutes for full upload completion

    if (!uploaded) {
      await report('UPLOAD_NOT_VERIFIED', { message: 'Video upload did not complete within timeout.' });
      return false;
    }
    if (uploaded.security) {
      await report(uploaded.security, { message: 'Meta security check appeared during upload.' });
      return false;
    }
    await report('VIDEO_UPLOAD_DONE', uploaded);
    await sleep(2000);

    // Safeguard: Check if caption was preserved during video attachment; if cleared, re-paste it!
    if (task.caption) {
      const cap = findCaptionBox();
      if (cap) {
        const curText = (cap.innerText || cap.textContent || cap.value || '').trim();
        if (!curText || curText.length < 2) {
          console.log("Re-verifying caption after video attachment...");
          setText(cap, task.caption);
          await sleep(500);
        }
      }
    }
    return true;
  };

  const runTask = async task => {
    await report('TASK_STARTED', { name: task.name || '', auto_publish: !!task.auto_publish, video: task.video });
    let security = securityCheck();
    if (security) {
      await report(security, { message: 'Meta login or security verification is required. Complete it manually.' });
      return;
    }

    await report('WAITING_FOR_COMPOSER', {});
    const composer = await waitFor(() => {
      security = securityCheck();
      if (security) return { security };
      const add = findAddVideoButton();
      const text = norm(pageText());
      if (add || (text.includes('create reel') && text.includes('reel details'))) return { add };
      return null;
    }, 180000, 1000);

    if (!composer) {
      await report('COMPOSER_NOT_FOUND', { message: 'Reel composer not found within 3 minutes.' });
      return;
    }
    if (composer.security) {
      await report(composer.security, { message: 'Meta login/security screen detected.' });
      return;
    }

    await report('COMPOSER_READY', {});

    // Intelligent Step Sequence Dispatcher
    // Default / Recommended: Caption -> Location -> Messages -> Video Upload
    const seqMode = task.step_sequence || 'caption_first';
    let stepOrder = task.composer_step_order;
    if (!stepOrder || !Array.isArray(stepOrder) || stepOrder.length === 0) {
      if (seqMode === 'video_first') {
        stepOrder = ['video_upload', 'caption', 'location', 'messages'];
      } else if (seqMode === 'caption_messages_location') {
        stepOrder = ['caption', 'messages', 'location', 'video_upload'];
      } else {
        // caption_first (User requested: Caption -> Location -> Messages -> Video Upload)
        stepOrder = ['caption', 'location', 'messages', 'video_upload'];
      }
    }

    await report('SEQUENCE_DISPATCHING', { mode: seqMode, order: stepOrder });

    for (const stepKey of stepOrder) {
      if (stepKey === 'caption') {
        let capBox = findCaptionBox();
        if (!capBox) {
          console.log("Caption box not yet mounted in DOM. Waiting up to 5s...");
          capBox = await waitFor(() => findCaptionBox(), 5000, 500);
        }
        if (!capBox && stepOrder.includes('video_upload')) {
          console.log("Caption box requires video attachment to mount. Uploading video first...");
          const upOk = await stepUploadVideo(task, composer);
          if (!upOk) return;
          await sleep(1500);
        }
        await stepFillCaption(task);
        await sleep(700);
      } else if (stepKey === 'location') {
        await stepFillLocation(task);
        await sleep(700);
      } else if (stepKey === 'messages') {
        await stepFillMessages();
        await sleep(700);
      } else if (stepKey === 'video_upload') {
        const v = uploadPreviewDetected(task.video);
        if (!v.ok) {
          const upOk = await stepUploadVideo(task, composer);
          if (!upOk) return;
          await sleep(1500);
        }
      }
    }

    // Step 7, 8, 9, 10: State-aware Navigation & Final Publication Flow
    await sleep(1500);

    const checkShareScreen = () => isShareScreenActive();

    // Step 7: Screen 1 -> Screen 2 (or jump straight to Share if already there)
    if (checkShareScreen()) {
      await report('STAGE_ALREADY_ON_SHARE_SCREEN', { message: 'Composer already reached Share screen.' });
    } else {
      await report('SCREEN1_NEXT_WAITING', {});
      const next1 = await waitFor(() => {
        if (checkShareScreen()) return 'ALREADY_SHARE';
        const btn = findNextButton();
        return (btn && isButtonEnabled(btn)) ? btn : null;
      }, 60000, 500);

      if (next1 === 'ALREADY_SHARE' || checkShareScreen()) {
        await report('STAGE_ALREADY_ON_SHARE_SCREEN', {});
      } else if (!next1) {
        if (checkShareScreen()) {
          await report('STAGE_ALREADY_ON_SHARE_SCREEN', {});
        } else {
          await report('SCREEN1_NEXT_NOT_FOUND', {});
          return;
        }
      } else {
        await report('SCREEN1_NEXT_CLICKING', { text: (next1.innerText || '').trim() });
        await clickNavButton(next1, 'SCREEN1_NEXT');
        await sleep(2500);
      }
    }

    // Step 8: Screen 2 -> Screen 3 (or jump straight to Share if already there)
    if (checkShareScreen() || findShareButton(false)) {
      await report('STAGE_ALREADY_ON_SHARE_SCREEN', { message: 'Composer directly reached Share screen (Edit screen skipped).' });
    } else {
      await report('WAITING_FOR_EDIT_SCREEN', {});
      const step2Outcome = await waitFor(() => {
        if (checkShareScreen() || findShareButton(false)) return { action: 'ALREADY_SHARE' };
        const nextBtn = findNextButton();
        if (nextBtn && isButtonEnabled(nextBtn)) return { action: 'CLICK_NEXT', btn: nextBtn };
        return null;
      }, 15000, 400);

      if (step2Outcome && step2Outcome.action === 'CLICK_NEXT' && step2Outcome.btn) {
        await report('SCREEN2_NEXT_CLICKING', { text: (step2Outcome.btn.innerText || '').trim() });
        await clickNavButton(step2Outcome.btn, 'SCREEN2_NEXT');
        await sleep(2500);
      } else if ((step2Outcome && step2Outcome.action === 'ALREADY_SHARE') || checkShareScreen() || findShareButton(false)) {
        await report('STAGE_ALREADY_ON_SHARE_SCREEN', {});
      } else {
        if (checkShareScreen() || findShareButton(false)) {
          await report('STAGE_ALREADY_ON_SHARE_SCREEN', {});
        } else {
          await report('SCREEN2_NEXT_NOT_FOUND', {});
          return;
        }
      }
    }

    // Step 9: Screen 3 (Share Step) -> Wait for Share button & Click
    await report('WAITING_FOR_SHARE_SCREEN', {});
    // Direct detection: Try enabled share button first (fast check up to 10s)
    let shareBtn = await waitFor(() => findShareButton(true), 10000, 400);
    // If optional copyright check is still spinning, but visible Share button is present, click it directly!
    if (!shareBtn) {
      shareBtn = findShareButton(false);
      if (!shareBtn) {
        shareBtn = await waitFor(() => findShareButton(false), 10000, 400);
      }
    }

    if (!shareBtn) {
      await report('SHARE_BUTTON_NOT_FOUND', {});
      return;
    }

    if (!task.auto_publish) {
      await report('READY_FOR_REVIEW', { message: 'All details filled (video, caption, location, messages, steps 1-2). Auto-publish is OFF; click Share manually.' });
      return;
    }

    await report('SHARE_BUTTON_CLICKING', { text: (shareBtn.innerText || '').trim() });
    await clickNavButton(shareBtn, 'SHARE');
    await sleep(3500);

    // Step 10: Active Publish & Modal Verification Loop (up to 90s)
    await report('WAITING_FOR_PROCESSING_MODAL', {});
    let published = false;
    const publishDeadline = Date.now() + 90000;
    while (Date.now() < publishDeadline && !published) {
      // 1. Check if Done button or "Reel processing" modal appeared
      const doneBtn = findDoneButton() || buttonByText(['Done']);
      const t = norm(pageText());
      if (doneBtn || t.includes('reel processing') || t.includes('once your reel finishes') || t.includes('notified')) {
        const btnToClick = doneBtn || buttonByText(['Done']);
        if (btnToClick) {
          await report('DONE_BUTTON_CLICKING', { text: (btnToClick.innerText || '').trim() });
          await report('PUBLISHED', { verification: 'DONE_MODAL_ACKNOWLEDGED' });
          await clickNavButton(btnToClick, 'DONE');
        } else {
          await report('PUBLISHED', { verification: 'REEL_PROCESSING_TEXT_DETECTED' });
        }
        published = true;
        await sleep(2000);
        try { if (chrome?.runtime?.sendMessage) chrome.runtime.sendMessage({ type: "CLOSE_TAB" }); } catch (e) {}
        try { window.close(); } catch (e) {}
        return;
      }

      // 2. If modal hasn't appeared yet, check if Share button is still visible on screen
      const curShare = findShareButton(true) || findShareButton(false);
      if (curShare) {
        console.log("[ActivePublish] Share button still present. Re-dispatching Share click...");
        await report('SHARE_BUTTON_CLICKING', { text: (curShare.innerText || '').trim(), retry: true });
        await clickNavButton(curShare, 'SHARE');
      }

      // 3. Check if Next button is present (in case page stepped back)
      const curNext = findNextButton();
      if (curNext && isButtonEnabled(curNext)) {
        console.log("[ActivePublish] Next button present. Clicking Next...");
        await clickNavButton(curNext, 'NEXT_STEP_RETRY');
      }

      await sleep(3500);
    }

    // Step 11: Final Verification & Clean Close
    const success = await waitFor(() => {
      const t = norm(pageText());
      if (/your reel has been shared|reel has been published|reel was published|successfully shared|published successfully|reel processing/.test(t)) {
        return 'SUCCESS_TEXT';
      }
      const hasComposer = !!buttonByText(['Add Video', 'Next', 'Share now', 'Publish now']);
      if (!hasComposer && /published|posts|content/.test(t)) return 'COMPOSER_CLOSED';
      return null;
    }, 45000, 1000);

    if (success) {
      await report('PUBLISHED', { verification: success });
      await sleep(1500);
      try {
        if (chrome?.runtime?.sendMessage) {
          chrome.runtime.sendMessage({ type: "CLOSE_TAB" });
        }
      } catch (e) {}
      try { window.close(); } catch (e) {}
    } else {
      await report('PUBLISH_UNCERTAIN', { message: 'Share was clicked and publication is processing.' });
    }
  };

  const start = async () => {
    const pid = pageId();
    await report('HELPER_CONNECTED', { href: location.href, page_id: pid });
    setupWebSocket();

    // Heartbeat every 3s to guarantee scheduler connection acknowledgment
    const heartbeatTimer = setInterval(async () => {
      await report('HELPER_CONNECTED', { href: location.href, page_id: pageId() });
    }, 3000);

    // Ensure DOM structure is ready before querying elements
    if (document.readyState === 'loading') {
      await new Promise(r => {
        window.addEventListener('DOMContentLoaded', r, { once: true });
        setTimeout(r, 2500);
      });
    }

    // Auto-recovery watchdog: If composer rendered blank white for > 8s, auto-reload
    setTimeout(async () => {
      if (isBlankPage()) {
        console.warn("[MetaReels] Blank white page detected. Triggering page reload...");
        await report('COMPOSER_BLANK_DETECTED', { message: 'Composer rendered blank white. Auto-reloading page...' });
        window.location.reload();
      }
    }, 8000);

    let task = null;
    while (!task) {
      const sec = securityCheck();
      if (sec) {
        await report(sec, { message: 'Manual login/security verification required.' });
        return;
      }
      task = await getTask();
      if (task && task.id) {
        try { sessionStorage.setItem('meta_reels_page_id', String(task.id)); } catch(e) {}
      }
      if (!task || !task.video) {
        await sleep(1500);
        task = null;
        continue;
      }
      break;
    }
    try {
      await runTask(task);
    } catch (e) {
      await report('TASK_FAILED', { error: String(e), stack: e?.stack || '' });
    }
  };

  // Start immediately upon content script injection
  start();
})();
