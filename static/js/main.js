(function () {
  "use strict";

  // Mobile nav
  var toggle = document.getElementById("navToggle");
  var nav = document.getElementById("mainNav");
  var header = document.querySelector(".site-header");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && header) {
        nav.style.top = header.getBoundingClientRect().bottom + "px";
      }
    });
  }

  // Mobile search toggle
  var searchToggle = document.getElementById("searchToggle");
  var searchOverlay = document.getElementById("searchOverlay");
  if (searchToggle && searchOverlay) {
    searchToggle.addEventListener("click", function () {
      var open = searchOverlay.classList.toggle("open");
      searchToggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        if (header) searchOverlay.style.top = header.getBoundingClientRect().bottom + "px";
        var input = searchOverlay.querySelector("input");
        if (input) setTimeout(function () { input.focus(); }, 250);
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
      mainImg.src = thumb.getAttribute("data-large") || thumb.src;
      document.querySelectorAll(".gallery-thumbs img").forEach(function (t) { t.classList.remove("active"); });
      thumb.classList.add("active");
    });
  });

  // Scroll-reveal: fade+rise elements marked .reveal into place once, the
  // first time they enter the viewport. Progressive enhancement only - the
  // CSS keeps .reveal fully visible unless JS adds .is-visible, and this
  // script itself just adds that class, so content is never hidden if JS
  // fails to run.
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
      revealTargets.forEach(function (el) { revealObserver.observe(el); });
    }
  } else {
    document.querySelectorAll(".reveal").forEach(function (el) { el.classList.add("is-visible"); });
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
