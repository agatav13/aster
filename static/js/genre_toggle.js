(function () {
  "use strict";

  function setupGrid(grid) {
    var visible = parseInt(grid.getAttribute("data-visible-count") || "10", 10);
    if (!Number.isFinite(visible) || visible <= 0) {
      return;
    }

    var options = Array.prototype.slice.call(
      grid.querySelectorAll(".genre-option")
    );
    if (options.length <= visible) {
      return;
    }

    // Auto-expand if the user already had a genre selected past the
    // threshold (common on the edit page) so a ticked pill is never hidden.
    var hiddenOptions = options.slice(visible);
    var hasCheckedHidden = hiddenOptions.some(function (option) {
      var input = option.querySelector("input[type='checkbox']");
      return input && input.checked;
    });

    var wrapper = grid.parentElement;
    var toggle = wrapper ? wrapper.querySelector("[data-genre-toggle]") : null;
    if (!toggle) {
      return;
    }

    var labelEl = toggle.querySelector("[data-genre-toggle-label]");
    var iconEl = toggle.querySelector("[data-genre-toggle-icon]");
    var moreLabel = toggle.getAttribute("data-label-more") || "Pokaż więcej";
    var lessLabel = toggle.getAttribute("data-label-less") || "Pokaż mniej";

    function render(expanded) {
      hiddenOptions.forEach(function (option) {
        option.classList.toggle("genre-option--collapsed", !expanded);
      });
      if (labelEl) {
        labelEl.textContent = expanded ? lessLabel : moreLabel;
      }
      if (iconEl) {
        iconEl.classList.toggle("bi-chevron-down", !expanded);
        iconEl.classList.toggle("bi-chevron-up", expanded);
      }
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    }

    toggle.hidden = false;
    render(hasCheckedHidden);

    toggle.addEventListener("click", function () {
      var currentlyExpanded = toggle.getAttribute("aria-expanded") === "true";
      render(!currentlyExpanded);
    });
  }

  function init() {
    var grids = document.querySelectorAll("[data-genre-grid]");
    grids.forEach(setupGrid);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
