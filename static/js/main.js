(function () {
  "use strict";

  // Mobile nav
  var toggle = document.getElementById("navToggle");
  var nav = document.getElementById("mainNav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
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

  // Flash messages auto-dismiss
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity .3s ease";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 300);
    }, 6000);
  });
})();
