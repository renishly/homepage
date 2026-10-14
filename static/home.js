// The home page's tree (see templates/home.html and "Home page" in theme.css).
//
// 1. Draws the dashed lines joining the root card to each leaf, and redraws
//    them when the window changes size.
// 2. The root tech (Ren or Guest): "Log out" shows on hover (on a phone,
//    after holding it). A click goes back to the front page, still signed in;
//    holding it rewrites "Log out" into "Sign out", letter by letter, and
//    then signs this device out. As Ren, its badge turns into a cog while
//    hovered or held, and clicking the cog switches developer mode on or off
//    (always off when the page opens). In developer mode, a leaf tech opens
//    its settings instead of its page, and dragging a leaf tech up or down
//    moves it (the new order is saved).
// 3. Right after signing in (?entered), plays the build: the Login button
//    glides from under the name to the root's place and becomes the root
//    (Ren or Guest), the name fades away, the lines draw themselves out, and
//    the leaves arrive one by one. With "reduce motion" on, it all just appears.
// (Each card in the tree is a "tech", after the "tech tree" it's styled on.)
(() => {
  const tree = document.getElementById("tree");
  if (!tree) return; // signed out: nothing to do
  const svg = tree.querySelector(".tree-lines");
  const root = document.getElementById("tree-root");
  const rootColumn = tree.querySelector(".tree-root-column");
  const NS = "http://www.w3.org/2000/svg";

  const isWide = () => getComputedStyle(tree).flexDirection === "row";

  function drawLines() {
    const box = tree.getBoundingClientRect();
    const x = (v) => Math.round(v - box.left) + 0.5;
    const y = (v) => Math.round(v - box.top) + 0.5;
    const r = root.getBoundingClientRect();
    const badges = [...tree.querySelectorAll(".tree-leaf .tree-badge")].map((b) => b.getBoundingClientRect());
    if (!badges.length) return;
    const nearestLeft = Math.min(...badges.map((b) => b.left));
    const shapes = [];
    if (isWide()) {
      // From the root's right edge to a trunk halfway across, then along to each leaf.
      const sx = x(r.right) + 6;
      const sy = y(r.top + r.height / 2);
      const trunk = Math.round((sx + x(nearestLeft)) / 2) + 0.5;
      for (const b of badges) {
        shapes.push({ d: `M${sx} ${sy} H${trunk} V${y(b.top + b.height / 2)} H${x(b.left) - 4}` });
      }
      // A small arrowhead pointing into the root, as in a tech tree.
      shapes.push({ d: `M${sx + 9} ${sy - 7} L${sx + 1} ${sy} L${sx + 9} ${sy + 7}`, arrow: true });
    } else {
      // From under the root, down a trunk to the left of the leaves, then across to each.
      const c = rootColumn.getBoundingClientRect();
      const sx = x(r.left + r.width / 2);
      const sy = y(c.bottom) + 8;
      const bend = sy + 14;
      const trunk = x(nearestLeft) - 18;
      for (const b of badges) {
        shapes.push({ d: `M${sx} ${sy} V${bend} H${trunk} V${y(b.top + b.height / 2)} H${x(b.left) - 4}` });
      }
    }
    svg.replaceChildren(
      ...shapes.map(({ d, arrow }) => {
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", d);
        if (arrow) path.setAttribute("class", "tree-arrow");
        return path;
      })
    );
  }

  let pending = false;
  addEventListener("resize", () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      drawLines();
    });
  });
  drawLines();
  // Fonts can change the cards' sizes slightly once loaded.
  document.fonts?.ready.then(drawLines);

  // 2. The root tech.
  const HOLD_MS = 450; // on a phone, how long a press counts as "holding"
  const SIGN_OUT_AFTER_MS = 200; // how long a press lasts before "Log out" starts turning into "Sign out"
  const LETTER_MS = 120; // per letter deleted or typed
  const mainLink = root.querySelector(".root-main");
  const word = root.querySelector(".root-out-word");
  const signOutForm = root.querySelector(".root-signout");
  const badge = root.querySelector(".root-badge");
  const status = root.querySelector(".root-status");

  // Watches one element for a touch press held for HOLD_MS. onHold runs when
  // the hold starts; onRelease when the finger lifts after a hold. The click a
  // browser sends after a hold isn't meant as a click, so it's swallowed.
  // Mouse and pen are left alone (they hover instead).
  function watchHold(element, onHold, onRelease) {
    let timer = null;
    let held = false;
    element.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      held = false;
      timer = setTimeout(() => {
        held = true;
        onHold();
      }, HOLD_MS);
    });
    const stop = () => {
      clearTimeout(timer);
      if (held) onRelease?.();
    };
    element.addEventListener("pointerup", stop);
    element.addEventListener("pointercancel", stop);
    element.addEventListener("pointerleave", stop);
    element.addEventListener("click", (event) => {
      if (held) {
        event.preventDefault();
        event.stopImmediatePropagation();
        held = false;
      }
    }, true);
    element.addEventListener("contextmenu", (event) => event.preventDefault());
  }

  // Showing "Log out / Hold to sign out": a mouse hovers (CSS); a finger
  // holds the card first (.is-holding), which lasts 4 seconds or until you
  // touch elsewhere.
  let hideTimer = null;
  const reveal = () => {
    root.classList.add("is-holding");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(stopHolding, 4000);
  };
  const stopHolding = () => {
    clearTimeout(hideTimer);
    if (!signingOut) root.classList.remove("is-holding");
  };
  document.addEventListener("pointerdown", (event) => {
    if (!root.contains(event.target)) stopHolding();
  });

  // Holding "Log out" rewrites it into "Sign out", a letter at a time (the
  // "Log" goes, then "Sign" is typed), and then signs this device out.
  // Letting go before it's finished puts "Log out" back and does nothing.
  let signingOut = false;
  let rewriteTimer = null;
  let typing = null;
  let swallowClick = false;
  const rewrite = () => {
    signingOut = true;
    swallowClick = true;
    clearTimeout(hideTimer);
    word.classList.add("is-typing");
    // "Log" is deleted a letter at a time (as with backspace), then "Sign" is typed in.
    const sequence = ["Lo out", "L out", " out", "S out", "Si out", "Sig out", "Sign out"];
    let index = 0;
    typing = setInterval(() => {
      word.textContent = sequence[index];
      index += 1;
      if (index === sequence.length) {
        clearInterval(typing);
        typing = null;
        word.classList.remove("is-typing");
        setTimeout(() => signOutForm.submit(), 180);
      }
    }, LETTER_MS);
  };
  const cancelRewrite = () => {
    clearTimeout(rewriteTimer);
    if (!signingOut || !typing) return; // not started, or already finished
    clearInterval(typing);
    typing = null;
    signingOut = false;
    word.classList.remove("is-typing");
    word.textContent = "Log out";
    if (root.classList.contains("is-holding")) reveal();
  };
  const startPress = (delay) => {
    swallowClick = false;
    clearTimeout(rewriteTimer);
    rewriteTimer = setTimeout(rewrite, delay);
  };

  mainLink.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "touch") {
      // A finger: the first hold reveals "Log out"; holding on (or holding
      // again once it shows) rewrites it and signs out.
      if (root.classList.contains("is-holding")) {
        startPress(SIGN_OUT_AFTER_MS);
      } else {
        clearTimeout(rewriteTimer);
        rewriteTimer = setTimeout(() => {
          reveal();
          swallowClick = true; // lifting the finger now isn't a tap
          rewriteTimer = setTimeout(rewrite, SIGN_OUT_AFTER_MS + 250);
        }, HOLD_MS);
      }
    } else if (event.button === 0) {
      startPress(SIGN_OUT_AFTER_MS); // a mouse: "Log out" already shows on hover
    }
  });
  for (const type of ["pointerup", "pointercancel", "pointerleave"]) {
    mainLink.addEventListener(type, cancelRewrite);
  }
  // Keyboard: Enter follows the link (to the front page); holding Space signs out.
  mainLink.addEventListener("keydown", (event) => {
    if (event.key === " " && !event.repeat) {
      event.preventDefault();
      startPress(SIGN_OUT_AFTER_MS);
    }
  });
  mainLink.addEventListener("keyup", (event) => {
    if (event.key === " ") cancelRewrite();
  });
  mainLink.addEventListener("click", (event) => {
    // A click goes to the front page (staying signed in), unless it ends a
    // hold, or it's a finger's first tap before "Log out" was revealed.
    if (swallowClick || signingOut) {
      event.preventDefault();
      swallowClick = false;
    } else if (event.pointerType === "touch" && !root.classList.contains("is-holding")) {
      event.preventDefault();
    }
  });
  mainLink.addEventListener("contextmenu", (event) => event.preventDefault());
  mainLink.addEventListener("dragstart", (event) => event.preventDefault());

  // Ren's badge: the cog, and developer mode. Developer mode always starts
  // off when the tree page is opened.
  const settings = document.getElementById("tech-settings");
  const settingsBody = document.getElementById("tech-settings-body");
  const inDeveloperMode = () => root.classList.contains("is-dev");
  if (badge) {
    const setDeveloperMode = (on) => {
      root.classList.toggle("is-dev", on);
      tree.classList.toggle("is-dev-mode", on);
      badge.setAttribute("aria-pressed", String(on));
      if (status) status.textContent = on ? "developer mode" : "signed in";
      badge.classList.remove("is-spinning");
      void badge.offsetWidth; // restart the spin if it's already playing
      badge.classList.add("is-spinning");
    };
    badge.addEventListener("animationend", () => badge.classList.remove("is-spinning"));
    badge.addEventListener("click", () => setDeveloperMode(!inDeveloperMode()));
    watchHold(badge, () => badge.classList.add("is-held"), () => badge.classList.remove("is-held"));
  }

  // In developer mode, clicking a leaf tech opens its settings instead of its page.
  const closeSettings = () => {
    settings?.classList.remove("modal-open");
    if (settingsBody) settingsBody.replaceChildren(); // also hides a shown key
  };
  tree.addEventListener("click", (event) => {
    const leaf = event.target.closest(".tree-leaf");
    if (!leaf || !inDeveloperMode() || !settings || !window.htmx) return;
    event.preventDefault();
    settingsBody.replaceChildren();
    settings.classList.add("modal-open");
    htmx.ajax("GET", `/tree/techs/${encodeURIComponent(leaf.dataset.tech)}/settings`, {
      target: "#tech-settings-body",
      swap: "innerHTML",
    });
  });
  settings?.querySelectorAll("[data-close-settings]").forEach((element) => element.addEventListener("click", closeSettings));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSettings();
  });
  // In developer mode, dragging a leaf tech up or down rearranges the techs.
  // The drag only starts once the pointer has moved a few pixels, so a plain
  // click still opens the settings; the click that ends a drag is ignored.
  const leafList = tree.querySelector(".tree-leaves");
  let drag = null;
  let swallowNextClick = false;

  // Moves an element in the list, sliding the others smoothly to their new places.
  function moveSmoothly(change, others) {
    const before = new Map(others.map((element) => [element, element.getBoundingClientRect().top]));
    change();
    for (const element of others) {
      const shift = before.get(element) - element.getBoundingClientRect().top;
      if (shift) {
        element.animate([{ transform: `translateY(${shift}px)` }, { transform: "none" }],
          { duration: 160, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" });
      }
    }
  }

  function saveOrder() {
    const order = [...leafList.children].map((leaf) => leaf.dataset.tech);
    const body = new URLSearchParams(order.map((slug) => ["order", slug]));
    let token = "";
    try {
      token = JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRF-Token"] || "";
    } catch (error) {}
    fetch("/tree/techs/order", { method: "POST", body, headers: { "X-CSRF-Token": token } })
      .then((response) => {
        if (!response.ok) location.reload(); // not saved: show the order the server has
      })
      .catch(() => location.reload());
  }

  tree.addEventListener("pointerdown", (event) => {
    const leaf = event.target.closest(".tree-leaf");
    if (!leaf || !inDeveloperMode() || event.button > 0) return;
    drag = { leaf, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, started: false, shift: 0 };
  });
  document.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.started) {
      if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 6) return;
      drag.started = true;
      drag.grab = event.clientY - drag.leaf.getBoundingClientRect().top; // where on the card it's held
      drag.leaf.classList.add("is-dragging");
      tree.classList.add("is-reordering");
    }
    event.preventDefault();
    // Past the middle of another tech? Swap places with it.
    const others = [...leafList.children].filter((element) => element !== drag.leaf);
    const next = others.find((element) => {
      const box = element.getBoundingClientRect();
      return event.clientY < box.top + box.height / 2;
    }) || null;
    if (next !== drag.leaf.nextElementSibling) {
      moveSmoothly(() => leafList.insertBefore(drag.leaf, next), others);
    }
    // Keep the dragged tech under the pointer.
    const restingTop = drag.leaf.getBoundingClientRect().top - drag.shift;
    drag.shift = event.clientY - drag.grab - restingTop;
    drag.leaf.style.transform = `translateY(${drag.shift}px)`;
    drawLines();
  });
  const endDrag = (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const { leaf, started } = drag;
    drag = null;
    if (!started) return; // a plain click: the settings open as usual
    swallowNextClick = true;
    setTimeout(() => { swallowNextClick = false; }, 0);
    tree.classList.remove("is-reordering");
    // Settle into its new place, then save the order.
    const shift = leaf.style.transform;
    leaf.style.transform = "";
    leaf.animate([{ transform: shift }, { transform: "none" }], { duration: 160, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" })
      .finished.finally(() => {
        leaf.classList.remove("is-dragging");
        drawLines();
      });
    drawLines();
    saveOrder();
  };
  // Links (like the Dashboard tech) would otherwise start the browser's own
  // "drag this link", which cancels ours.
  tree.addEventListener("dragstart", (event) => {
    if (inDeveloperMode()) event.preventDefault();
  });
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  tree.addEventListener("click", (event) => {
    if (swallowNextClick) {
      event.preventDefault();
      event.stopImmediatePropagation();
      swallowNextClick = false;
    }
  }, true);

  // A changed setting also replaces that tech's card: keep the lines joined.
  document.body.addEventListener("htmx:afterSettle", drawLines);

  // 3. The build, right after signing in.
  if (!tree.classList.contains("is-building")) return;
  const name = document.getElementById("home-name");
  const actions = document.querySelector(".home-actions");
  const ghost = document.getElementById("login-ghost");
  const leaves = [...tree.querySelectorAll(".tree-leaf")];

  const finish = () => {
    tree.classList.remove("is-building");
    name?.remove();
    actions?.remove();
    drawLines();
    // Reloading the page now shows the finished tree, without playing this again.
    try {
      history.replaceState(null, "", "/tree");
    } catch (error) {}
  };

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion || !ghost || !Element.prototype.animate) {
    finish();
    return;
  }

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const show = (element, keyframes, options) =>
    element.animate(keyframes, { fill: "forwards", easing: "cubic-bezier(0.2, 0.8, 0.2, 1)", ...options }).finished;

  (async () => {
    await wait(350); // a beat on the familiar page first
    drawLines();
    // The Login button lifts out of the page and glides to the root's place,
    // growing into the card's shape, while the name fades away.
    const from = ghost.getBoundingClientRect();
    const to = root.getBoundingClientRect();
    Object.assign(ghost.style, {
      position: "fixed", left: `${from.left}px`, top: `${from.top}px`,
      width: `${from.width}px`, height: `${from.height}px`, margin: "0", zIndex: "5",
    });
    name?.animate([{ opacity: 1 }, { opacity: 0, transform: "scaleX(1.1) translateY(-12px)" }],
      { duration: 450, fill: "forwards", easing: "ease-in" });
    await ghost.animate(
      [
        { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` },
        { left: `${to.left}px`, top: `${to.top}px`, width: `${to.width}px`, height: `${to.height}px` },
      ],
      { duration: 800, fill: "forwards", easing: "cubic-bezier(0.65, 0, 0.25, 1)" }
    ).finished;
    // It becomes the root: "Login" gives way to Ren (or Guest).
    show(ghost, [{ opacity: 1 }, { opacity: 0 }], { duration: 220 });
    await show(root, [{ opacity: 0 }, { opacity: 1 }], { duration: 220 });
    ghost.remove();
    // The lines draw themselves out from the root...
    svg.style.opacity = "1";
    const reveal = isWide()
      ? [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }]
      : [{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0 0)" }];
    const lines = show(svg, reveal, { duration: 650, easing: "cubic-bezier(0.45, 0, 0.2, 1)" });
    // ...and the leaves arrive one by one as the lines reach them.
    await wait(300);
    for (const leaf of leaves) {
      show(leaf, [{ opacity: 0, transform: "translateX(-14px)" }, { opacity: 1, transform: "none" }], { duration: 380 });
      await wait(130);
    }
    await lines;
    await wait(400);
    // Hand over to the plain, finished page (and drop the animations' leftover styles).
    for (const element of [root, svg, ...leaves]) {
      element?.getAnimations().forEach((animation) => animation.cancel());
      if (element) element.style.opacity = "";
    }
    finish();
  })();
})();
