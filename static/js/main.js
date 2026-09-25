(function () {
  "use strict";

  // Flip the safety switch first: CSS keeps .reveal (and other progressively
  // enhanced states) fully visible until this class exists, so content only
  // ever hides once we've proven script actually ran.
  document.documentElement.classList.add("js-ready");

  // Shared dim backdrop behind the mobile nav drawer / search overlay.
  var scrim = document.createElement("div");
  scrim.className = "scrim";
  document.body.appendChild(scrim);
  var openPanel = null; // "nav" | "search" | null

  function closeOpenPanel() {
    if (openPanel === "nav" && nav) {
      nav.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
      if (bottomMenuToggle) bottomMenuToggle.classList.remove("active");
    } else if (openPanel === "search" && searchOverlay) {
      searchOverlay.classList.remove("open");
      searchToggle.setAttribute("aria-expanded", "false");
    }
    scrim.classList.remove("visible");
    openPanel = null;
  }
  scrim.addEventListener("click", closeOpenPanel);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openPanel) closeOpenPanel();
  });

  // Mobile nav - opened from either the header hamburger or the bottom
  // tab bar's "Menu" button, so the toggling logic lives in one place.
  var toggle = document.getElementById("navToggle");
  var nav = document.getElementById("mainNav");
  var bottomMenuToggle = document.getElementById("bottomMenuToggle");
  var header = document.querySelector(".site-header");
  function toggleNav() {
    if (openPanel === "search") closeOpenPanel();
    var open = nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (bottomMenuToggle) bottomMenuToggle.classList.toggle("active", open);
    if (open) {
      if (header) nav.style.top = header.getBoundingClientRect().bottom + "px";
      scrim.classList.add("visible");
      openPanel = "nav";
    } else {
      scrim.classList.remove("visible");
      openPanel = null;
    }
  }
  if (toggle && nav) {
    toggle.addEventListener("click", toggleNav);
    if (bottomMenuToggle) bottomMenuToggle.addEventListener("click", toggleNav);
  }

  // Mobile search toggle
  var searchToggle = document.getElementById("searchToggle");
  var searchOverlay = document.getElementById("searchOverlay");
  if (searchToggle && searchOverlay) {
    searchToggle.addEventListener("click", function () {
      if (openPanel === "nav") closeOpenPanel();
      var open = searchOverlay.classList.toggle("open");
      searchToggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        if (header) searchOverlay.style.top = header.getBoundingClientRect().bottom + "px";
        scrim.classList.add("visible");
        openPanel = "search";
        var input = searchOverlay.querySelector("input");
        if (input) setTimeout(function () { input.focus(); }, 250);
      } else {
        scrim.classList.remove("visible");
        openPanel = null;
      }
    });
  }

  // Sticky header scroll state - subtle border/shadow once the page has scrolled
  if (header) {
    var setScrolled = function () {
      header.classList.toggle("is-scrolled", window.scrollY > 4);
    };
    setScrolled();
    window.addEventListener("scroll", setScrolled, { passive: true });
  }

  // Quantity steppers: <div class="qty-stepper"><button data-step="-1">-</button><input>...<button data-step="1">+</button></div>
  document.querySelectorAll(".qty-stepper").forEach(function (stepper) {
    var input = stepper.querySelector("input");
    if (!input) return;
    var max = parseInt(input.getAttribute("max") || "10", 10);
    var min = parseInt(input.getAttribute("min") || "1", 10);
    stepper.querySelectorAll("button[data-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var step = parseInt(btn.getAttribute("data-step"), 10);
        var value = parseInt(input.value || min, 10) + step;
        value = Math.max(min, Math.min(max, value));
        input.value = value;
        input.dispatchEvent(new Event("change"));
      });
    });
  });

  // Auto-submit cart quantity changes
  document.querySelectorAll(".cart-line form.qty-form input[type=number]").forEach(function (input) {
    input.addEventListener("change", function () {
      input.closest("form").submit();
    });
  });

  // Product gallery thumbnails
  var mainImg = document.getElementById("galleryMain");
  document.querySelectorAll(".gallery-thumbs img").forEach(function (thumb) {
    thumb.addEventListener("click", function () {
      if (!mainImg) return;
      mainImg.classList.add("is-swapping");
      window.setTimeout(function () {
        mainImg.src = thumb.getAttribute("data-large") || thumb.src;
        mainImg.classList.remove("is-swapping");
      }, 140);
      document.querySelectorAll(".gallery-thumbs img").forEach(function (t) { t.classList.remove("active"); });
      thumb.classList.add("active");
    });
  });

  // Scroll-reveal: fade+rise elements marked .reveal into place once, the
  // first time they enter the viewport. Progressive enhancement only - see
  // the .reveal / .js-ready rules in style.css for the no-JS safety net.
  // Anything already in the viewport on load (the hero, mostly) reveals
  // right away instead of waiting on the observer's first async callback -
  // above-the-fold content should never sit invisible for even a second.
  if ("IntersectionObserver" in window) {
    var revealTargets = document.querySelectorAll(".reveal");
    if (revealTargets.length) {
      var revealObserver = new IntersectionObserver(function (entries, obs) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            obs.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12 });
      revealTargets.forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.top < window.innerHeight && r.bottom > 0) {
          el.classList.add("is-visible");
        } else {
          revealObserver.observe(el);
        }
      });
    }
  } else {
    document.querySelectorAll(".reveal").forEach(function (el) { el.classList.add("is-visible"); });
  }

  // Cart count: a quiet pulse when it changes between page loads (added to
  // cart, removed an item, etc). Purely decorative - the number itself is
  // always server-rendered, this just notices a change and animates it.
  // Two badges share the same count (header + bottom tab bar on mobile).
  var cartCounts = [document.getElementById("cartCount"), document.getElementById("bottomCartCount")].filter(Boolean);
  if (cartCounts.length) {
    var current = cartCounts[0].textContent.trim();
    var previous = null;
    try { previous = window.localStorage.getItem("moromokeh_cart_count"); } catch (e) {}
    if (previous !== null && previous !== current) {
      cartCounts.forEach(function (el) {
        el.classList.add("pulse");
        var clearPulse = function () { el.classList.remove("pulse"); };
        el.addEventListener("animationend", clearPulse, { once: true });
        setTimeout(clearPulse, 800); // safety net if animationend doesn't fire (e.g. a backgrounded tab)
      });
    }
    try { window.localStorage.setItem("moromokeh_cart_count", current); } catch (e) {}
  }

  // Flash messages auto-dismiss
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity .3s ease";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 300);
    }, 6000);
  });
})();
