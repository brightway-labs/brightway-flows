/*
 * Draws the mermaid fences on a documentation page.
 *
 * `documentation.py` renders the markdown per request and recognises the
 * `mermaid` fence, which leaves `<pre class="mermaid"><code>` holding the
 * diagram's source.  Until this file existed nothing drew it, so a page whose
 * argument is a diagram published the diagram's source instead -- readable, and
 * not the point.
 *
 * Loaded only by the documentation template, because it is the only place a
 * fence can appear and `mermaid.min.js` is three and a half megabytes.
 *
 * Two things this has to get right beyond calling `run()`:
 *
 *   * The source has to be kept.  Mermaid replaces the element's content with
 *     the drawing, so a second render -- which the theme toggle needs -- has
 *     nothing left to read unless the text was put somewhere first.
 *   * A failure has to fall back to the source.  The fence is still legible
 *     prose, `app.css` labels an undrawn one "Diagram source", and a reader
 *     with no JavaScript, a blocked script or a diagram mermaid cannot parse
 *     sees what they saw before this file existed rather than a blank.
 *   * One drawing at a time, and only when the theme has changed.  `app.js`
 *     writes `data-theme` on every load, with the value the inline script in
 *     `layout.html` already set, and that write lands after the first draw
 *     has started.  Redrawing on it drew every page twice; and `run()` is
 *     asynchronous, so a second draw started while the first is measuring
 *     replaces the element's content under it.
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var blocks = [].slice.call(document.querySelectorAll("pre.mermaid"));
  if (!blocks.length || typeof window.mermaid === "undefined") return;

  /* Kept before the first draw, for the redraws. */
  blocks.forEach(function (block) {
    block.dataset.source = block.textContent;
  });

  function theme() {
    if (root.getAttribute("data-theme")) {
      return root.getAttribute("data-theme") === "dark" ? "dark" : "default";
    }
    /* No stored choice, so ask the OS.  Guarded because a drawing is not worth
       losing to an environment without `matchMedia`: `app.js` may not have set
       the attribute yet, and light is the right thing to assume. */
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "default";
    } catch (_err) {
      return "default";
    }
  }

  /* The theme of the drawing on the page, and the draw in progress.  The
     first draw is queued behind a resolved promise so every draw goes through
     the same chain. */
  var drawn = null;
  var drawing = Promise.resolve();

  function draw() {
    var wanted = theme();
    if (wanted === drawn) return;
    drawn = wanted;
    drawing = drawing
      .then(function () {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: wanted,
          /* The pages are prose: a diagram should read at the width of a
             paragraph, not at whatever mermaid's default font gives it.  What
             is inherited is the drawn element's face, which `app.css` sets to
             the page's, not the code block's. */
          fontFamily: "inherit",
          flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
            /* Mermaid's 50 and 50.  Every diagram here is a decision chain
               drawn top to bottom and scaled to fit a paragraph, and a
               labelled edge puts its label in a rank of its own, so each
               question costs two gaps.  At 50 the chart on `deciding/index`
               stood 1,138 units tall for twelve boxes; at 30 it stands
               1,018. */
            rankSpacing: 30,
            nodeSpacing: 30,
          },
        });
        blocks.forEach(function (block) {
          block.textContent = block.dataset.source;
          delete block.dataset.processed;
          block.removeAttribute("data-processed");
        });
        return window.mermaid.run({ nodes: blocks });
      })
      .catch(function () {
        /* Leave the source showing.  A diagram that will not parse is a bug
           in the page, and the page still says what it says. */
      });
  }

  draw();

  /* `app.js` sets `data-theme` on the root when the reader toggles.  A drawing
     carries its palette inside the SVG, so it has to be made again. */
  new MutationObserver(function (records) {
    if (records.some(function (r) { return r.attributeName === "data-theme"; })) {
      draw();
    }
  }).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
})();
