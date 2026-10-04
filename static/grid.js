// The background grid's movement (the grid itself is body::before in theme.css).
//
// The grid drifts slowly and endlessly (the CSS animation "grid-drift", one
// loop = 2 squares across and 1 down). Every page is a fresh start for the
// browser, so on its own the grid would jump back to the same spot on each
// page. This script:
//   1. carries on from where the grid was on the previous page (the position
//      is kept for this browser tab only, in sessionStorage), and
//   2. plays the "rush" on each page load: a burst of speed in the same drift,
//      starting from where the grid is and slowing back into the drift from
//      wherever the rush took it.
// If anything here isn't available, the grid simply drifts as before.
(() => {
  const RUSH_SECONDS = 1.3;
  const RUSH_LOOPS = 24; // how far the rush goes, in drift loops (about 2,800 pixels)
  const KEY = "gridPosition";

  let drift;
  try {
    drift = document.getAnimations().find((a) => a.animationName === "grid-drift");
  } catch (error) {
    return;
  }
  // No drift (e.g. "reduce motion" is on: the grid stays still), nothing to do.
  if (!drift) return;
  const loopMs = drift.effect.getComputedTiming().duration;

  // Where the grid is, in loops (0 to 1).
  const position = () => ((drift.currentTime || 0) / loopMs) % 1;
  const moveTo = (loops) => { drift.currentTime = (((loops % 1) + 1) % 1) * loopMs; };

  // 1. Pick up from the previous page, including the moment spent loading this one.
  let start = 0;
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
    if (saved) start = saved.position + (Date.now() - saved.at) / loopMs;
  } catch (error) {}
  moveTo(start);

  // Remember where the grid is when leaving this page (or switching tabs).
  const save = () => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ position: position(), at: Date.now() }));
    } catch (error) {}
  };
  addEventListener("pagehide", save);
  document.addEventListener("visibilitychange", () => document.hidden && save());

  // 2. The rush: fast at first, easing out into the normal drift speed.
  // It's timed from the first frame actually drawn, so a page opened in a
  // background tab rushes when you first look at it.
  drift.pause();
  let began = null;
  const step = (now) => {
    if (began === null) began = now;
    const elapsed = now - began;
    const t = Math.min(elapsed / (RUSH_SECONDS * 1000), 1);
    const eased = 1 - Math.pow(1 - t, 3); // ease-out: slows down smoothly
    moveTo(start + RUSH_LOOPS * eased + elapsed / loopMs);
    if (t < 1) {
      requestAnimationFrame(step);
    } else {
      drift.play(); // carry on drifting from here
    }
  };
  requestAnimationFrame(step);
})();
