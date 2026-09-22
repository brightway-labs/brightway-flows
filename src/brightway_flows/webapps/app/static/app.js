/* Progressive enhancement only.  Every page works with this file blocked.
 *
 * Ten jobs: remember the theme the reader chose, open the Browse panel and
 * the mobile menu, open a documentation page's sidebar as a drawer on a
 * phone, show the keyboard map, focus the search box on `/`, apply a filter
 * when its dropdown changes, fetch a history section on demand, turn the
 * citation formats on Download into tabs with a Copy button, and step through
 * the homepage's examples.  Each is an addition to a page that is already
 * complete without it -- the theme falls back to the OS setting, Browse and
 * the menu icon are links to `/browse/`, the documentation sidebar is a plain
 * anchor target, the shortcuts dialog is a <dialog> the browser can open on
 * its own, the search box is a box to click, every filter form has a submit
 * button, every fetched section is also a plain link to the same page, the
 * citations are all on the page, one under another, and so is every example.
 */
(function () {
  "use strict";

  var THEME_KEY = "bwf-theme";
  var root = document.documentElement;

  /* --- theme ---------------------------------------------------------- */

  function storedTheme() {
    try {
      return window.localStorage.getItem(THEME_KEY);
    } catch (_err) {
      /* Private browsing, or storage disabled.  The OS setting still works. */
      return null;
    }
  }

  function storeTheme(value) {
    try {
      window.localStorage.setItem(THEME_KEY, value);
    } catch (_err) {
      /* Not fatal: the choice lasts for this page instead of forever. */
    }
  }

  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function forgetTheme() {
    try {
      window.localStorage.removeItem(THEME_KEY);
    } catch (_err) {
      /* Nothing was stored, then. */
    }
  }

  /* `choice` is "system", "light" or "dark".  System stamps whatever the OS
   * says now and follows it when it changes; the other two are stamped as they
   * are. */
  function applyTheme(choice) {
    root.setAttribute("data-theme", choice === "system" ? systemTheme() : choice);
  }

  function initTheme() {
    var stored = storedTheme();
    var choice = stored === "light" || stored === "dark" ? stored : "system";
    applyTheme(choice);

    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function () {
        if (!storedTheme()) applyTheme("system");
      });

    var group = document.querySelector("[data-theme-switch]");
    if (!group) return;
    var radio = group.querySelector('input[value="' + choice + '"]');
    if (radio) radio.checked = true;
    group.hidden = false;
    group.addEventListener("change", function (event) {
      var value = event.target.value;
      if (value === "system") {
        forgetTheme();
      } else {
        storeTheme(value);
      }
      applyTheme(value);
    });
  }

  /* --- top bar -------------------------------------------------------- */

  /* Swap the `/browse/` link for the button drawn beside it, hidden, in the
   * markup.  The link is what a reader without this file follows. */
  function swapIn(linkSelector, buttonSelector) {
    var link = document.querySelector(linkSelector);
    var button = document.querySelector(buttonSelector);
    if (!link || !button) return null;
    link.hidden = true;
    button.hidden = false;
    return button;
  }

  /* The Browse panel: plain links under a disclosure button, not a menu, so
   * Tab is the whole keyboard story.  Esc closes it and puts focus back on
   * the button; a click anywhere outside closes it and leaves focus where the
   * reader clicked. */
  function initBrowse() {
    var panel = document.getElementById("browse-panel");
    var button = swapIn("[data-browse-link]", "[data-browse-toggle]");
    if (!panel || !button) return;

    /* The panel hangs from Browse's left edge, and at 44rem it is wider than
     * the room to its right in a window just over the 60rem breakpoint:
     * there it moves left, keeping 16px clear of the edge. */
    function keepOnScreen() {
      if (panel.hidden) return;
      panel.style.left = "";
      var gutter = 16;
      var over = panel.getBoundingClientRect().right -
        (document.documentElement.clientWidth - gutter);
      if (over > 0) panel.style.left = -over + "px";
    }

    function setOpen(open) {
      panel.hidden = !open;
      button.setAttribute("aria-expanded", open ? "true" : "false");
      keepOnScreen();
    }

    button.addEventListener("click", function () {
      setOpen(panel.hidden);
    });
    window.addEventListener("resize", keepOnScreen);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !panel.hidden) {
        setOpen(false);
        button.focus();
      }
    });
    document.addEventListener("click", function (event) {
      if (panel.hidden) return;
      if (panel.contains(event.target) || button.contains(event.target)) return;
      setOpen(false);
    });
  }

  /* The mobile menu.  While it is open it covers the page, so focus stays
   * inside it and the button that closes it: Tab from the last link goes back
   * to the button, Shift+Tab from the button to the last link. */
  function initMenu() {
    var menu = document.getElementById("mobile-menu");
    var button = swapIn("[data-menu-link]", "[data-menu-toggle]");
    if (!menu || !button) return;
    var narrow = window.matchMedia("(max-width: 60rem)");

    function setOpen(open) {
      menu.hidden = !open;
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }

    button.addEventListener("click", function () {
      setOpen(menu.hidden);
    });

    document.addEventListener("keydown", function (event) {
      if (menu.hidden) return;
      if (event.key === "Escape") {
        setOpen(false);
        button.focus();
        return;
      }
      if (event.key !== "Tab") return;
      var links = menu.querySelectorAll("a[href]");
      if (!links.length) return;
      var last = links[links.length - 1];
      var active = document.activeElement;
      if (event.shiftKey && active === button) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        button.focus();
      } else if (active !== button && !menu.contains(active)) {
        event.preventDefault();
        button.focus();
      }
    });

    /* Widened past the breakpoint with the menu open: the menu is gone from
     * view, so it must not go on holding focus. */
    var onChange = function (event) {
      if (!event.matches && !menu.hidden) setOpen(false);
    };
    if (typeof narrow.addEventListener === "function") {
      narrow.addEventListener("change", onChange);
    }
  }

  /* --- documentation ---------------------------------------------------- */

  /* The mobile "Contents" bar on a documentation page.  Without this file it
   * is a plain link to the sidebar, which `documentation.html` renders after
   * the article so the jump lands somewhere real.  Here the link is swapped
   * for the button beside it, and the same sidebar opens as a drawer instead
   * -- `data-docs-drawer` is what tells the stylesheet to draw it as one,
   * only below the 60rem breakpoint the desktop columns use `order` at. */
  function initDocsToc() {
    var nav = document.getElementById("docs-nav");
    var button = swapIn("[data-docs-toc-link]", "[data-docs-toc-toggle]");
    if (!nav || !button) return;
    nav.setAttribute("data-docs-drawer", "");
    var narrow = window.matchMedia("(max-width: 60rem)");

    /* Above the breakpoint the sidebar is always the left-hand column,
     * whatever `open` says: there is no drawer to close. */
    function setOpen(open) {
      var asDrawer = narrow.matches;
      nav.hidden = asDrawer && !open;
      button.setAttribute("aria-expanded", asDrawer && open ? "true" : "false");
    }

    setOpen(false);

    button.addEventListener("click", function () {
      setOpen(nav.hidden);
    });

    document.addEventListener("keydown", function (event) {
      if (!narrow.matches || nav.hidden || event.key !== "Escape") return;
      setOpen(false);
      button.focus();
    });

    document.addEventListener("click", function (event) {
      if (!narrow.matches || nav.hidden) return;
      if (nav.contains(event.target) || button.contains(event.target)) return;
      setOpen(false);
    });

    /* Crossed the breakpoint either way: recompute rather than guess which
     * state the reader would want carried over. */
    if (typeof narrow.addEventListener === "function") {
      narrow.addEventListener("change", function () {
        setOpen(false);
      });
    }
  }

  /* --- keyboard ------------------------------------------------------- */

  function isTyping(event) {
    var el = event.target;
    if (!el) return false;
    if (el.isContentEditable) return true;
    var tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  }

  function initShortcuts() {
    var dialog = document.getElementById("shortcuts");
    if (!dialog || typeof dialog.showModal !== "function") return;

    document.addEventListener("keydown", function (event) {
      if (isTyping(event) || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (event.key === "?") {
        event.preventDefault();
        if (dialog.open) {
          dialog.close();
        } else {
          dialog.showModal();
        }
      }
    });

    var closer = dialog.querySelector("[data-close]");
    if (closer) {
      closer.addEventListener("click", function () {
        dialog.close();
      });
    }
  }

  /* `/` focuses the search box, unless the reader is already typing.  The
   * top bar's box when it is showing; below 60rem it is not, and the box on
   * `/search` itself, or the homepage's lookup box, is the one there is.  Only once this has run is the `/`
   * hint beside the box shown: without the script the key does nothing. */
  function initSearch() {
    var hint = document.querySelector("[data-search-hint]");
    if (hint) hint.hidden = false;

    function visibleBox() {
      var boxes = [
        document.getElementById("site-search"),
        document.getElementById("search-q"),
        document.getElementById("home-q"),
      ];
      for (var i = 0; i < boxes.length; i++) {
        if (boxes[i] && boxes[i].getClientRects().length) return boxes[i];
      }
      return null;
    }

    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || isTyping(event)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      var dialog = document.getElementById("shortcuts");
      if (dialog && dialog.open) return;
      var box = visibleBox();
      if (!box) return;
      event.preventDefault();
      box.focus();
      box.select();
    });
  }

  /* --- filters -------------------------------------------------------- */

  /* A `[data-autosubmit]` field submits its form when its value changes.
   *
   * The macro that renders every filter select has emitted this attribute
   * since the filters were written, and nothing implemented it: choosing an
   * outcome on `/merge/outcomes`, or a unit on `/flows/`, changed the dropdown
   * and left the table alone until the reader found the Search button.
   *
   * Enhancement, not mechanism: each of these selects sits in a form with a
   * visible submit button, so with this file blocked the filter still applies
   * -- it takes the button. The form carries no `page`, so a new filter starts
   * at the first page rather than at whichever page the old one was on. */
  function initAutosubmit() {
    var fields = document.querySelectorAll("[data-autosubmit]");
    Array.prototype.forEach.call(fields, function (field) {
      field.addEventListener("change", function () {
        var form = field.form;
        if (!form) return;
        if (typeof form.requestSubmit === "function") {
          form.requestSubmit();
        } else {
          form.submit();
        }
      });
    });
  }

  /* --- on-demand fragments -------------------------------------------- */

  /* A `<details data-fragment="URL">` fetches that URL the first time it is
   * opened and replaces its contents with the response, once.
   *
   * Every one of these wraps a plain link to the same page, so with this file
   * blocked the reader still gets there -- they navigate instead of expanding.
   * That is the arrangement: a detail page reads no history unless somebody
   * asks for it, and asking for it does not have to cost a page load. */
  function initFragments() {
    var blocks = document.querySelectorAll("details[data-fragment]");
    Array.prototype.forEach.call(blocks, function (block) {
      var loaded = false;
      block.addEventListener("toggle", function () {
        if (!block.open || loaded) return;
        loaded = true;

        var target = block.querySelector("[data-fragment-target]");
        if (!target) return;
        var url = block.getAttribute("data-fragment");
        target.setAttribute("aria-busy", "true");

        window
          .fetch(url, { headers: { Accept: "text/html" } })
          .then(function (response) {
            if (!response.ok) throw new Error(String(response.status));
            return response.text();
          })
          .then(function (html) {
            target.innerHTML = html;
          })
          .catch(function () {
            /* The link is still there in the markup below; leaving it is a
             * better failure than an error message replacing it. */
            loaded = false;
          })
          .then(function () {
            target.removeAttribute("aria-busy");
          });
      });
    });
  }

  /* --- citation ------------------------------------------------------- */

  /* Download's "Cite this release".  Without this file the three formats are
   * one after another, each under its own heading.  Here the headings give
   * way to tabs -- arrow keys, Home and End move between them, and only the
   * selected tab is in the Tab order -- and each format gets a Copy button.
   *
   * No clipboard (a page served over plain HTTP has none) means no button:
   * the text is selectable either way, and a button that cannot copy is
   * worse than none. */
  function initCite() {
    var section = document.querySelector("[data-cite]");
    if (!section) return;

    var list = section.querySelector('[role="tablist"]');
    var tabs = list
      ? Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'))
      : [];
    if (tabs.length) {
      var select = function (tab, focus) {
        tabs.forEach(function (other) {
          var selected = other === tab;
          other.setAttribute("aria-selected", selected ? "true" : "false");
          other.tabIndex = selected ? 0 : -1;
          var panel = document.getElementById(other.getAttribute("aria-controls"));
          if (panel) panel.hidden = !selected;
        });
        if (focus) tab.focus();
      };

      tabs.forEach(function (tab, index) {
        var panel = document.getElementById(tab.getAttribute("aria-controls"));
        if (panel) panel.setAttribute("role", "tabpanel");
        tab.addEventListener("click", function () {
          select(tab, false);
        });
        tab.addEventListener("keydown", function (event) {
          var next = {
            ArrowRight: tabs[(index + 1) % tabs.length],
            ArrowLeft: tabs[(index - 1 + tabs.length) % tabs.length],
            Home: tabs[0],
            End: tabs[tabs.length - 1],
          }[event.key];
          if (!next) return;
          event.preventDefault();
          select(next, true);
        });
      });

      section.setAttribute("data-cite-tabs", "");
      list.hidden = false;
      select(tabs[0], false);
    }

    if (!navigator.clipboard) return;
    var buttons = section.querySelectorAll("[data-copy]");
    Array.prototype.forEach.call(buttons, function (button) {
      var body = button.parentNode.querySelector(".cite__body");
      if (!body) return;
      var label = button.textContent;
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(body.textContent).then(
          function () {
            button.textContent = "Copied";
            window.setTimeout(function () {
              button.textContent = label;
            }, 2000);
          },
          function () {
            /* Refused (permissions, or the page lost focus): the text is
             * still there to select by hand. */
          }
        );
      });
    });
  }

  /* --- homepage examples ----------------------------------------------- */

  /* The homepage's example cards.  Without this file every example is on the
   * page, one under another, which is the whole list and is only longer.  Here
   * one is shown at a time and the arrows step between them, so the page
   * reaches its footer on a screen rather than a screen and a half.
   *
   * The arrows are in the markup and hidden; they are shown only once there is
   * a second card to reach, since one example and a pair of arrows that go
   * nowhere is worse than one example. */
  function initExamples() {
    var region = document.querySelector("[data-examples]");
    if (!region) return;

    var cards = Array.prototype.slice.call(
      region.querySelectorAll("[data-example]")
    );
    var nav = region.querySelector("[data-examples-nav]");
    var count = region.querySelector("[data-examples-count]");
    var steps = region.querySelectorAll("[data-examples-step]");
    if (cards.length < 2 || !nav || !steps.length) return;

    var current = 0;
    var show = function (index) {
      current = (index + cards.length) % cards.length;
      cards.forEach(function (card, position) {
        card.hidden = position !== current;
      });
      if (count) count.textContent = current + 1 + " of " + cards.length;
    };

    Array.prototype.forEach.call(steps, function (button) {
      var step = parseInt(button.getAttribute("data-examples-step"), 10);
      button.addEventListener("click", function () {
        show(current + step);
      });
    });

    /* What tells the stylesheet the cards are no longer stacked, so it drops
     * the rule that separates one from the next.  Set here rather than written
     * into the markup: without this file the cards are stacked and the rule is
     * the only thing between them. */
    region.setAttribute("data-examples-stepped", "");
    nav.hidden = false;
    show(0);
  }

  /* Download's "Copy DOI" and "Copy SHA-256" buttons: same rule as the
   * citation Copy buttons above -- no clipboard means no button, and the
   * value lives in the button's own `data-copy-value` rather than a sibling
   * element, since a checksum has nowhere on the page to be shown as text. */
  function initCopyValues() {
    if (!navigator.clipboard) return;
    var buttons = document.querySelectorAll("[data-copy-value]");
    Array.prototype.forEach.call(buttons, function (button) {
      var value = button.getAttribute("data-copy-value");
      var label = button.textContent;
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(value).then(
          function () {
            button.textContent = "Copied";
            window.setTimeout(function () {
              button.textContent = label;
            }, 2000);
          },
          function () {
            /* Refused (permissions, or the page lost focus): nothing else
             * on the page can show the value instead. */
          }
        );
      });
    });
  }

  function init() {
    initTheme();
    initBrowse();
    initMenu();
    initDocsToc();
    initShortcuts();
    initSearch();
    initAutosubmit();
    initFragments();
    initCite();
    initExamples();
    initCopyValues();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
