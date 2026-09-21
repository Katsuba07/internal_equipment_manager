/* Equipment Manager — the small amount of interactivity the UI needs.
   No framework: a theme switch, a mobile drawer, and dropdown menus. */

(function () {
  "use strict";

  /* ---------- Theme ---------- */
  // The inline script in <head> has already applied the stored theme, so the
  // page never flashes the wrong colours. This part only handles toggling.

  var root = document.documentElement;

  function setTheme(theme) {
    root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("ema-theme", theme);
    } catch (e) {
      /* Private browsing blocks storage; the theme still applies for this page. */
    }
    document.querySelectorAll("[data-theme-icon]").forEach(function (icon) {
      icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    });
    document.querySelectorAll("[data-theme-label]").forEach(function (label) {
      label.textContent = theme === "dark" ? "Light mode" : "Dark mode";
    });
  }

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    event.preventDefault();
    setTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });

  setTheme(root.getAttribute("data-theme") || "light");

  /* ---------- Mobile navigation drawer ---------- */

  var sidebar = document.getElementById("sidebar");
  var scrim = null;

  function closeNav() {
    if (!sidebar) return;
    sidebar.classList.remove("open");
    if (scrim) {
      scrim.remove();
      scrim = null;
    }
  }

  function openNav() {
    if (!sidebar) return;
    sidebar.classList.add("open");
    scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.addEventListener("click", closeNav);
    document.body.appendChild(scrim);
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-nav-toggle]")) {
      event.preventDefault();
      sidebar && sidebar.classList.contains("open") ? closeNav() : openNav();
    }
  });

  /* ---------- Dropdown menus ---------- */

  function closeMenus(except) {
    document.querySelectorAll(".dropdown-menu.open").forEach(function (menu) {
      if (menu !== except) menu.classList.remove("open");
    });
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-dropdown]");
    if (trigger) {
      event.preventDefault();
      var menu = trigger.parentElement.querySelector(".dropdown-menu");
      if (menu) {
        closeMenus(menu);
        menu.classList.toggle("open");
      }
      return;
    }
    if (!event.target.closest(".dropdown-menu")) closeMenus();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeMenus();
      closeNav();
    }

    // "/" jumps to the search box, the way most list UIs behave.
    if (event.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) {
      var search = document.querySelector(".search-input");
      if (search) {
        event.preventDefault();
        search.focus();
        search.select();
      }
    }
  });

  /* ---------- Dismissible alerts ---------- */

  document.addEventListener("click", function (event) {
    var close = event.target.closest(".alert .close");
    if (close) close.closest(".alert").remove();
  });

  /* ---------- Filters apply on change ---------- */
  // Selecting a filter submits straight away; nobody should have to find a
  // separate "apply" button after every choice.

  document.querySelectorAll("[data-autosubmit] select, [data-autosubmit] input[type=checkbox]").forEach(function (select) {
    select.addEventListener("change", function () {
      select.form.requestSubmit ? select.form.requestSubmit() : select.form.submit();
    });
  });

  /* ---------- "Add row" for any formset ---------- */
  // <button data-formset-add="roles"> clones <template id="roles-empty"> into
  // <tbody id="roles-rows"> and bumps id_roles-TOTAL_FORMS.

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-formset-add]");
    if (!button) return;
    var prefix = button.getAttribute("data-formset-add");
    var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    var tpl = document.getElementById(prefix + "-empty");
    var rows = document.getElementById(prefix + "-rows");
    if (!total || !tpl || !rows) return;
    var index = parseInt(total.value, 10);
    rows.insertAdjacentHTML("beforeend", tpl.innerHTML.replace(/__prefix__/g, index));
    total.value = index + 1;
    var first = rows.lastElementChild && rows.lastElementChild.querySelector("input:not([type=hidden]), select");
    if (first) first.focus();
  });

  /* ---------- Products page: selection and the detail panel ---------- */

  document.addEventListener("click", function (event) {
    var item = event.target.closest("[data-select]");
    if (!item) return;
    document.querySelectorAll("[data-select].sel").forEach(function (el) { el.classList.remove("sel"); });
    item.classList.add("sel");
  });

  // On a phone the panel sits under the list: bring it into view when it fills.
  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "panel" && window.innerWidth < 992) {
      event.detail.target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  // A click anywhere on a product's row opens it, not only on its code.
  document.addEventListener("click", function (event) {
    var row = event.target.closest("[data-row-link]");
    if (!row || event.target.closest("a, button, input, select, textarea, label, summary, [draggable=true]")) return;
    if (window.getSelection && String(window.getSelection())) return;      // selecting text to copy
    var link = row.querySelector(".prod-code");
    if (link) link.click();
  });

  // The panels opened in turn, so "Back" returns to the previous one. A panel
  // names itself with data-panel (one entry per product, process or set);
  // forms carry no name, so Back from a form returns to what it was opened from.
  var panelTrail = [];
  var panelGoingBack = false;

  function panelShown() {
    var panel = document.getElementById("panel");
    if (!panel) return;
    var card = panel.querySelector("[data-panel]");
    if (card) {
      var entry = { key: card.dataset.panel, url: card.dataset.panelUrl, page: card.dataset.pageUrl };
      var top = panelTrail[panelTrail.length - 1];
      if (top && top.key === entry.key) panelTrail[panelTrail.length - 1] = entry;
      else if (!panelGoingBack) panelTrail.push(entry);
    }
    panelGoingBack = false;
    var head = panel.querySelector(".card-head");
    var split = document.querySelector("[data-split]");
    // Widening only applies while something is open, so the list never goes missing.
    if (split) split.classList.toggle("has-panel", !!head);
    if (!head) return;
    var canGoBack = card ? panelTrail.length > 1 : panelTrail.length > 0;
    if (canGoBack && !head.querySelector("[data-panel-back]")) {
      head.insertAdjacentHTML("afterbegin",
        '<button type="button" class="btn btn-sm btn-default panel-back" data-panel-back title="Back to the previous panel">' +
        '<i class="bi bi-arrow-left"></i> Back</button>');
    }
    if (!head.querySelector("[data-panel-wide]")) {
      head.insertAdjacentHTML("beforeend",
        '<button type="button" class="btn btn-sm btn-ghost btn-icon panel-wide" data-panel-wide></button>');
    }
    showPanelWidth();
  }

  function showPanelWidth() {
    var split = document.querySelector("[data-split]");
    if (!split) return;
    var wide = split.classList.contains("is-wide");
    document.querySelectorAll("[data-panel-wide]").forEach(function (button) {
      button.title = wide ? "Show the list again" : "Widen this panel";
      button.innerHTML = '<i class="bi bi-arrows-angle-' + (wide ? "contract" : "expand") + '"></i>';
    });
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-panel-wide]")) {
      var split = document.querySelector("[data-split]");
      if (!split) return;
      split.classList.toggle("is-wide");
      try { localStorage.setItem("ema-panel-wide", split.classList.contains("is-wide") ? "1" : ""); } catch (e) {}
      showPanelWidth();
      return;
    }
    if (!event.target.closest("[data-panel-back]")) return;
    var card = document.querySelector("#panel [data-panel]");
    var top = panelTrail[panelTrail.length - 1];
    if (card && top && top.key === card.dataset.panel) panelTrail.pop();
    var target = panelTrail[panelTrail.length - 1];
    if (!target) return;
    panelGoingBack = true;
    htmx.ajax("GET", target.url, { target: "#panel" });
    try { history.replaceState(history.state, "", target.page); } catch (e) {}
    document.querySelectorAll("[data-select].sel").forEach(function (el) { el.classList.remove("sel"); });
    var chosen = document.querySelector('[data-select][href="' + target.page + '"]');
    if (chosen) chosen.classList.add("sel");
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "panel") panelShown();
  });
  document.addEventListener("htmx:historyRestore", panelShown);
  (function () {
    var split = document.querySelector("[data-split]");
    try { if (split && localStorage.getItem("ema-panel-wide")) split.classList.add("is-wide"); } catch (e) {}
    panelShown();
  })();

  /* ---------- Products page: drag a process box to reorder the route ---------- */
  // Only rendered draggable for managers. The new order is posted as a list of
  // ids; the page then reloads so every panel and arrow reflects the saved order.
  // Touch screens have no drag and drop; the arrows in the product panel remain.

  var dragged = null;

  function clearMarks(flow) {
    flow.querySelectorAll(".drop-before, .drop-after").forEach(function (el) {
      el.classList.remove("drop-before", "drop-after");
    });
  }

  document.addEventListener("dragstart", function (event) {
    var step = event.target.closest && event.target.closest(".flow-step[draggable=true]");
    if (!step) return;
    dragged = step;
    step.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", step.getAttribute("data-step-id"));
  });

  document.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var target = event.target.closest(".flow-step");
    if (!target || target === dragged || target.parentNode !== dragged.parentNode) return;
    event.preventDefault();
    clearMarks(target.parentNode);
    var box = target.getBoundingClientRect();
    target.classList.add(event.clientX < box.left + box.width / 2 ? "drop-before" : "drop-after");
  });

  document.addEventListener("drop", function (event) {
    if (!dragged) return;
    var target = event.target.closest(".flow-step");
    if (!target || target === dragged || target.parentNode !== dragged.parentNode) return;
    event.preventDefault();
    var flow = target.parentNode;
    var after = target.classList.contains("drop-after");
    clearMarks(flow);
    flow.insertBefore(dragged, after ? target.nextSibling : target);
    var order = Array.prototype.map.call(flow.querySelectorAll(".flow-step"), function (el) {
      return el.getAttribute("data-step-id");
    });
    var body = new FormData();
    body.append("order", order.join(","));
    var token = document.querySelector("[name=csrfmiddlewaretoken]");
    fetch(flow.getAttribute("data-reorder-url"), {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": token ? token.value : "" },
    }).then(function (response) {
      if (!response.ok) alert("The new order could not be saved.");
      window.location.reload();
    });
  });

  document.addEventListener("dragend", function () {
    if (!dragged) return;
    dragged.classList.remove("dragging");
    clearMarks(dragged.parentNode);
    dragged = null;
  });

  /* ---------- Quick-look drawer on list pages ---------- */
  // Clicking a row with data-preview-url loads its preview into the drawer.
  // Ctrl/Shift/middle-click on a link still opens the full page as usual.

  var drawer = document.getElementById("preview");
  var drawerBody = document.getElementById("preview-body");
  var previewRow = null;

  function closePreview() {
    if (!drawer) return;
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    if (previewRow) previewRow.classList.remove("row-sel");
    previewRow = null;
  }

  if (drawer) {
    document.addEventListener("click", function (event) {
      if (event.target.closest("[data-preview-close]")) { closePreview(); return; }
      var row = event.target.closest("tr[data-preview-url]");
      if (!row || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.target.closest("button, input, select, textarea, label, form, .col-select")) return;
      event.preventDefault();
      if (previewRow === row && drawer.classList.contains("open")) { closePreview(); return; }
      if (previewRow) previewRow.classList.remove("row-sel");
      previewRow = row;
      row.classList.add("row-sel");
      fetch(row.getAttribute("data-preview-url"), {
        headers: { "HX-Request": "true" }, credentials: "same-origin",
      })
        .then(function (response) { return response.text(); })
        .then(function (html) {
          drawerBody.innerHTML = html;
          drawer.classList.add("open");
          drawer.setAttribute("aria-hidden", "false");
          drawer.scrollTop = 0;
        });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) closePreview();
    });
  }

  /* ---------- Photo lightbox ---------- */
  // <a href="full.jpg" data-lightbox> opens the image large; click or Esc closes.

  var lightbox = null;
  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-lightbox]");
    if (!link) return;
    event.preventDefault();
    if (!lightbox) {
      lightbox = document.createElement("dialog");
      lightbox.className = "lightbox";
      lightbox.addEventListener("click", function () { lightbox.close(); });
      document.body.appendChild(lightbox);
    }
    lightbox.innerHTML = "";
    var img = new Image();
    img.src = link.getAttribute("href");
    img.alt = link.getAttribute("title") || "";
    lightbox.appendChild(img);
    lightbox.showModal();
  });

  /* ---------- "+ New" next to a dropdown ---------- */
  // The button opens a small pop-up form. When it saves, the new entry is added
  // to every dropdown of the same kind on the page and chosen in the one whose
  // button was pressed — no page reload, nothing typed so far is lost.
  //
  //   <button data-quick-add="/quick-add/part/" data-target="id_x">   explicit select
  //   <tr data-qa-scope> ... <select> ... <button data-quick-add=...>  nearest select

  // Two dialogs, so they can stack: a form (edit, status, receive, issue) and
  // the small "+ New" pop-up, which may open on top of it without throwing
  // away what has been typed in the form underneath.
  var dialogs = {};
  var targetSelect = null;

  function ensureDialog(kind) {
    if (dialogs[kind]) return dialogs[kind];
    var box = document.createElement("dialog");
    box.className = "quick-add";
    document.body.appendChild(box);
    dialogs[kind] = box;

    box.addEventListener("click", function (event) {
      if (event.target.closest("[data-qa-close]")) { box.close(); return; }
      // A click on the backdrop closes the small pop-up, but never a form
      // that may hold a minute's worth of typing.
      if (event.target === box && kind === "quick") box.close();
    });
    // Drop the closed form so no stale fields linger in the page.
    box.addEventListener("close", function () { box.innerHTML = ""; });
    box.addEventListener("submit", function (event) {
      event.preventDefault();
      var form = event.target;
      var button = form.querySelector("[type=submit]");
      if (button) button.disabled = true;
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest", "HX-Request": "true" },
        credentials: "same-origin",
      })
        .then(function (response) {
          var type = response.headers.get("Content-Type") || "";
          if (type.indexOf("application/json") !== -1) {
            return response.json().then(function (data) {
              if (data.reload) {
                box.close();
                window.location.reload();
                return;
              }
              addOption(data);
              box.close();
            });
          }
          return response.text().then(function (html) { showForm(kind, html); });
        })
        .catch(function () {
          if (button) button.disabled = false;
          alert("Could not save. Check the connection and try again.");
        });
    });
    return box;
  }

  function showForm(kind, html) {
    var box = ensureDialog(kind);
    box.innerHTML = html;
    if (!box.open) box.showModal();
    syncIssueTarget(box);
    syncNeeds(box);
    var first = box.querySelector("input:not([type=hidden]), select, textarea");
    if (first) first.focus();
  }

  function addOption(data) {
    if (!targetSelect) return;
    if (targetSelect.matches("[data-picker]")) {
      choose(targetSelect, String(data.id), data.label);
      return;
    }
    var kind = targetSelect.getAttribute("data-qa-kind");
    var selects = kind
      ? Array.prototype.slice.call(document.querySelectorAll('select[data-qa-kind="' + kind + '"]'))
      : [targetSelect];
    // Rows added later are cloned from a <template>; give those the option too.
    document.querySelectorAll("template").forEach(function (tpl) {
      if (kind) selects = selects.concat(Array.prototype.slice.call(
        tpl.content.querySelectorAll('select[data-qa-kind="' + kind + '"]')));
    });
    selects.forEach(function (select) {
      var option = new Option(data.label, data.id);
      select.appendChild(option);
    });
    targetSelect.value = String(data.id);
    targetSelect.dispatchEvent(new Event("change", { bubbles: true }));
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-quick-add], [data-modal-form]");
    if (!button) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey) return;   // let it open as a page
    event.preventDefault();
    var url = button.getAttribute("data-quick-add");
    var kind = "quick";
    if (url) {
      var id = button.getAttribute("data-target");
      var scope = button.closest("[data-qa-scope]");
      // Look inside the button's own form first: an edit dialog opened over a
      // list page shares ids like id_category with the list's filter bar.
      var root = button.closest("form") || document;
      targetSelect = id
        ? root.querySelector("#" + CSS.escape(id)) || document.getElementById(id)
        : scope && (scope.querySelector("select") || scope.querySelector("[data-picker]"));
    } else {
      // A form that only saves (edit, change status, receive, issue): no
      // dropdown to fill, the page reloads when it saves.
      targetSelect = null;
      kind = "form";
      url = button.getAttribute("data-modal-form");
    }
    fetch(url, { headers: { "HX-Request": "true" }, credentials: "same-origin" })
      .then(function (response) { return response.text(); })
      .then(function (html) { showForm(kind, html); });
  });

  /* ---------- Asset picker (issue a part to an asset) ---------- */
  // A dropdown of every asset would be a scroll hunt, so the field is a search
  // box: it asks the server as you type and shows at most twenty matches. The
  // assets that carry this part are listed first, and before anything is typed
  // they are the whole list.

  var pickerTimer = null;

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function pickerList(picker) { return picker.querySelector("[data-picker-list]"); }

  function closeList(picker) {
    var list = pickerList(picker);
    list.hidden = true;
    list.innerHTML = "";
    picker.querySelector("[data-picker-input]").setAttribute("aria-expanded", "false");
  }

  function renderResults(picker, results, query) {
    var list = pickerList(picker);
    if (!results.length) {
      list.innerHTML = '<div class="picker-empty">' + esc(
        query ? "No asset matches “" + query + "”." : (picker.getAttribute("data-empty") || "Type a code or name to search.")
      ) + "</div>";
      list.hidden = false;
      return;
    }
    list.innerHTML = results.map(function (row) {
      // Names come from people and imports: never trust them as markup.
      var label = row.code + " " + row.name;
      return '<button type="button" class="picker-item' + (row.busy ? " is-busy" : "") + '"' +
        (row.busy ? " disabled" : "") +
        ' data-id="' + row.id + '" data-label="' + esc(label) + '">' +
        '<span class="picker-main">' +
          '<span class="mono fw-600">' + esc(row.code) + "</span>" +
          '<span class="picker-name">' + esc(row.name) + "</span>" +
          (row.on_list ? '<span class="badge badge-ok">on its parts list</span>' : "") +
          (row.busy ? '<span class="badge badge-warning">in ' + esc(row.busy) + "</span>" : "") +
        "</span>" +
        '<span class="picker-sub subtle">' + esc([row.ids, row.where].filter(Boolean).join(" · ")) + "</span>" +
        "</button>";
    }).join("");
    list.hidden = false;
    picker.querySelector("[data-picker-input]").setAttribute("aria-expanded", "true");
  }

  function search(picker) {
    var input = picker.querySelector("[data-picker-input]");
    var query = input.value.trim();
    var url = picker.getAttribute("data-source");
    url += (url.indexOf("?") === -1 ? "?" : "&") + "q=" + encodeURIComponent(query);
    fetch(url, { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (data) { renderResults(picker, data.results || [], query); })
      .catch(function () { closeList(picker); });
  }

  function choose(picker, id, label) {
    picker.querySelector("[data-picker-value]").value = id;
    var chosen = picker.querySelector("[data-picker-chosen]");
    var parts = label.split(/\s+/);
    chosen.querySelector("[data-picker-label]").innerHTML =
      '<span class="mono fw-600">' + esc(parts.shift()) + "</span> " + esc(parts.join(" "));
    chosen.hidden = false;
    var input = picker.querySelector("[data-picker-input]");
    input.hidden = true;
    input.value = "";
    closeList(picker);
  }

  function clearChoice(picker) {
    picker.querySelector("[data-picker-value]").value = "";
    picker.querySelector("[data-picker-chosen]").hidden = true;
    var input = picker.querySelector("[data-picker-input]");
    input.hidden = false;
    input.focus();
    search(picker);
  }

  document.addEventListener("input", function (event) {
    var picker = event.target.closest("[data-picker]");
    if (!picker || !event.target.matches("[data-picker-input]")) return;
    clearTimeout(pickerTimer);
    pickerTimer = setTimeout(function () { search(picker); }, 180);
  });

  document.addEventListener("focusin", function (event) {
    var picker = event.target.closest("[data-picker]");
    if (picker && event.target.matches("[data-picker-input]") && pickerList(picker).hidden) search(picker);
    // Clicking anywhere else closes an open list.
    document.querySelectorAll("[data-picker]").forEach(function (other) {
      if (other !== picker) closeList(other);
    });
  });

  document.addEventListener("click", function (event) {
    var item = event.target.closest(".picker-item");
    if (item) {
      event.preventDefault();
      choose(item.closest("[data-picker]"), item.getAttribute("data-id"), item.getAttribute("data-label"));
      return;
    }
    if (event.target.closest("[data-picker-clear]")) {
      event.preventDefault();
      clearChoice(event.target.closest("[data-picker]"));
      return;
    }
    if (!event.target.closest("[data-picker]")) {
      document.querySelectorAll("[data-picker]").forEach(closeList);
    }
  });

  document.addEventListener("keydown", function (event) {
    var picker = event.target.closest("[data-picker]");
    if (!picker || !event.target.matches("[data-picker-input]")) return;
    var items = Array.prototype.slice.call(picker.querySelectorAll(".picker-item:not([disabled])"));
    var current = items.indexOf(picker.querySelector(".picker-item.is-on"));
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!items.length) return;
      var next = event.key === "ArrowDown" ? current + 1 : current - 1;
      if (next < 0) next = items.length - 1;
      if (next >= items.length) next = 0;
      items.forEach(function (row) { row.classList.remove("is-on"); });
      items[next].classList.add("is-on");
      items[next].scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      var pick = items[current] || items[0];
      if (pick) {
        event.preventDefault();       // Enter picks; it must not submit the form
        choose(picker, pick.getAttribute("data-id"), pick.getAttribute("data-label"));
      }
    } else if (event.key === "Escape" && !pickerList(picker).hidden) {
      event.preventDefault();         // close the list, keep the dialog open
      event.stopPropagation();
      closeList(picker);
    }
  });

  /* Only an issue has a destination; a receipt or a stocktake does not. */
  function syncIssueTarget(scope) {
    var select = (scope || document).querySelector("select[name=transaction_type]");
    var picker = (scope || document).querySelector("[data-picker]");
    if (!select || !picker) return;
    var row = picker.closest("#div_id_equipment") || picker.closest(".mb-3") || picker.parentElement;
    row.hidden = select.value !== "OUT";
  }

  document.addEventListener("change", function (event) {
    if (event.target.name === "transaction_type") syncIssueTarget(event.target.form || document);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { syncIssueTarget(document); });
  } else {
    syncIssueTarget(document);
  }

  /* ---------- Tick rows, then "Delete selected" ---------- */
  // Administrators get a tick box on each list row. The button in the page
  // header appears once something is ticked and goes to a confirm page that
  // names every record before anything is deleted.

  function syncBulk() {
    var button = document.querySelector("[data-bulk-delete]");
    if (!button) return;
    var boxes = document.querySelectorAll("input[data-bulk]");
    var ticked = document.querySelectorAll("input[data-bulk]:checked");
    button.hidden = ticked.length === 0;
    var count = button.querySelector("[data-bulk-count]");
    if (count) count.textContent = ticked.length;
    var all = document.querySelector("input[data-bulk-all]");
    if (all) {
      all.checked = boxes.length > 0 && ticked.length === boxes.length;
      all.indeterminate = ticked.length > 0 && ticked.length < boxes.length;
    }
    boxes.forEach(function (box) {
      var row = box.closest("tr");
      if (row) row.classList.toggle("row-ticked", box.checked);
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches("input[data-bulk-all]")) {
      document.querySelectorAll("input[data-bulk]").forEach(function (box) {
        box.checked = event.target.checked;
      });
    }
    if (event.target.matches("input[data-bulk], input[data-bulk-all]")) syncBulk();
  });

  document.addEventListener("click", function (event) {
    // The cell around a tick box is a bigger target for the same box.
    var cell = event.target.closest("td.col-select, th.col-select");
    if (cell && !event.target.matches("input")) {
      var box = cell.querySelector("input[type=checkbox]");
      if (box) {
        box.checked = !box.checked;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return;
    }
    var button = event.target.closest("[data-bulk-delete]");
    if (!button) return;
    var ids = Array.prototype.map.call(
      document.querySelectorAll("input[data-bulk]:checked"),
      function (box) { return box.value; }
    );
    if (ids.length) window.location = button.getAttribute("data-bulk-delete") + "?ids=" + ids.join(",");
  });

  // Coming back with the Back button can restore ticked boxes; match the button.
  window.addEventListener("pageshow", syncBulk);

  /* ---------- Next due = last date + interval (asset form) ---------- */
  // <input data-next-from="id_last" data-interval="id_every" data-unit="days|months">
  // is refilled whenever the last date or the interval changes; it can still
  // be typed over by hand.

  function isoDate(d) {
    var m = String(d.getMonth() + 1).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + String(d.getDate()).padStart(2, "0");
  }

  function fillNextDue(next, form) {
    var last = form.querySelector("#" + next.getAttribute("data-next-from"));
    var every = form.querySelector("#" + next.getAttribute("data-interval"));
    var count = every && parseInt(every.value, 10);
    if (!last || !last.value || !count) return;
    var d = new Date(last.value + "T00:00:00");
    if (next.getAttribute("data-unit") === "months") {
      // 31 Jan + 1 month is 28/29 Feb, not 3 Mar — same rule as the server.
      var day = d.getDate();
      d.setDate(1);
      d.setMonth(d.getMonth() + count);
      d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
    } else {
      d.setDate(d.getDate() + count);
    }
    next.value = isoDate(d);
  }

  document.addEventListener("change", function (event) {
    var form = event.target.form;
    if (!form || !event.target.id) return;
    form.querySelectorAll("[data-next-from]").forEach(function (next) {
      if (event.target.id === next.getAttribute("data-next-from")
          || event.target.id === next.getAttribute("data-interval")) {
        fillNextDue(next, form);
      }
    });
  });

  /* ---------- Fields that open only when a tick says so ---------- */
  // <input data-needs="id_maintenance_required"> is shut until that box is
  // ticked, so a date cannot be typed for a schedule that does not apply.

  function syncNeeds(scope) {
    (scope || document).querySelectorAll("[data-needs]").forEach(function (field) {
      var form = field.form || document;
      var tick = form.querySelector("#" + field.getAttribute("data-needs"));
      if (!tick) return;
      field.disabled = !tick.checked;
      var wrap = field.closest(".mb-3") || field.parentElement;
      if (wrap) wrap.classList.toggle("is-shut", !tick.checked);
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.type === "checkbox" && event.target.id &&
        document.querySelector('[data-needs="' + event.target.id + '"]')) {
      syncNeeds(event.target.form || document);
    }
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { syncNeeds(document); });
  } else {
    syncNeeds(document);
  }

  /* ---------- Photos on a form: add more, take one out before saving ---------- */
  // A phone's camera hands back one picture per tap, and a file box normally
  // forgets the last pick when a new one is made. Here every pick is added to
  // the ones before; the previews show what will be saved, each with its ×.

  function sameFile(a, b) {
    return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
  }

  function renderStage(input) {
    var stage = (input.form || document).querySelector('[data-photo-stage-for="' + input.id + '"]');
    if (!stage) return;
    stage.innerHTML = "";
    Array.prototype.forEach.call(input._staged.files, function (file, index) {
      var item = document.createElement("div");
      item.className = "photo-stage-item";
      var img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.alt = file.name;
      var drop = document.createElement("button");
      drop.type = "button";
      drop.title = "Take this photo out";
      drop.setAttribute("aria-label", "Take this photo out");
      drop.setAttribute("data-photo-unstage", index);
      drop.innerHTML = '<i class="bi bi-x-lg"></i>';
      item.appendChild(img);
      item.appendChild(drop);
      stage.appendChild(item);
    });
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("input[type=file][data-photo-stage]")) return;
    var kept = input._staged || new DataTransfer();
    Array.prototype.forEach.call(input.files, function (file) {
      var already = Array.prototype.some.call(kept.files, function (f) { return sameFile(f, file); });
      if (!already) kept.items.add(file);
    });
    input._staged = kept;
    input.files = kept.files;
    renderStage(input);
  });

  document.addEventListener("click", function (event) {
    var drop = event.target.closest("[data-photo-unstage]");
    if (!drop) return;
    event.preventDefault();
    var stage = drop.closest("[data-photo-stage-for]");
    var input = (stage.closest("form") || document).querySelector("#" + CSS.escape(stage.getAttribute("data-photo-stage-for")));
    var skip = parseInt(drop.getAttribute("data-photo-unstage"), 10);
    var kept = new DataTransfer();
    Array.prototype.forEach.call(input._staged.files, function (file, index) {
      if (index !== skip) kept.items.add(file);
    });
    input._staged = kept;
    input.files = kept.files;
    renderStage(input);
  });

  /* ---------- Process frame: a role's type decides which machines it offers ---------- */

  document.addEventListener("change", function (event) {
    var select = event.target;
    if (!select.matches || !select.matches("[data-role-row] select[name$='-category']")) return;
    var picker = select.closest("[data-role-row]").querySelector("[data-picker]");
    if (!picker) return;
    picker.setAttribute("data-source", picker.getAttribute("data-source")
      .replace(/([?&])category=[^&]*/, "$1category=" + encodeURIComponent(select.value)));
    var option = select.options[select.selectedIndex];
    var name = option && select.value ? option.text.split(" — ").pop() : "";
    picker.setAttribute("data-empty", name ? "No " + name + " registered yet." : "");
  });

  /* ---------- Tabs inside a card (a product's documents) ---------- */
  // [data-tabs] holds buttons [data-tab=x] and panes [data-pane=x]. Choosing a
  // tab also preselects that type in the card's upload form.

  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-tabs] [data-tab]");
    if (!tab) return;
    var box = tab.closest("[data-tabs]");
    var key = tab.getAttribute("data-tab");
    box.querySelectorAll("[data-tab]").forEach(function (t) {
      t.classList.toggle("is-on", t === tab);
      t.setAttribute("aria-selected", t === tab ? "true" : "false");
    });
    box.querySelectorAll("[data-pane]").forEach(function (pane) {
      pane.hidden = pane.getAttribute("data-pane") !== key;
    });
    var select = box.querySelector("select[name=section]");
    if (select && tab.getAttribute("data-section")) select.value = tab.getAttribute("data-section");
  });
})();
