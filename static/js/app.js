/* Equipment Manager — the page behaviour the UI needs, without a framework. */

(function () {
  "use strict";

  /* ---------- Theme ---------- */
  // The inline script in <head> applies the stored theme; this only toggles it.

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
  // Selecting a filter submits straight away.

  // Delegated, and through control.form, so it also covers the filters in
  // the table's column headers: those sit outside the <form> (tied to it by
  // form="...") and are redrawn whenever the list refreshes.
  document.addEventListener("change", function (event) {
    var control = event.target;
    if (!control.matches || !control.matches("select, input[type=checkbox]")) return;
    var form = control.form;
    if (!form || !form.hasAttribute("data-autosubmit")) return;
    form.requestSubmit ? form.requestSubmit() : form.submit();
  });

  /* ---------- Section tabs ---------- */
  // <div class="tabs" data-tabs> holds <button data-tab-target="key">; sibling
  // [data-tab-panel="key"] elements show/hide — client-side, no page reload.
  // The first tab is active by default; @media print shows every panel.

  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-tab-target]");
    if (!tab) return;
    var tabs = tab.closest("[data-tabs]");
    if (!tabs) return;
    var key = tab.getAttribute("data-tab-target");
    tabs.querySelectorAll("[data-tab-target]").forEach(function (btn) {
      btn.classList.toggle("active", btn === tab);
    });
    var panels = tabs.getAttribute("data-tabs-for");
    document.querySelectorAll('[data-tab-panel][data-tabs-group="' + panels + '"]').forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-tab-panel") !== key;
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

  // <button data-row-add="station-assets"> clones <template id="station-assets-empty">
  // into #station-assets (a plain list, no formset count); __n__ becomes a
  // fresh number so every search box has its own id. data-row-remove drops
  // its row.
  var rowCounter = 0;
  document.addEventListener("click", function (event) {
    var add = event.target.closest("[data-row-add]");
    if (add) {
      var name = add.getAttribute("data-row-add");
      var tpl = document.getElementById(name + "-empty");
      var list = document.getElementById(name);
      if (!tpl || !list) return;
      rowCounter += 1;
      list.insertAdjacentHTML("beforeend", tpl.innerHTML.replace(/__n__/g, "new" + rowCounter));
      // Not focused: a focused search box opens its list, which would push
      // this button away from under a second click.
      return;
    }
    var remove = event.target.closest("[data-row-remove]");
    if (remove) {
      event.preventDefault();
      remove.closest(".station-asset, .station-model").remove();
    }
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
      if (event.target.closest("a, button, input, select, textarea, label, form, .col-select")) return;
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

    // A click outside the box (on the backdrop) closes it. Only a click that
    // starts there too: selecting text inside and letting go outside must not.
    var pressedOutside = false;
    box.addEventListener("mousedown", function (event) { pressedOutside = event.target === box; });
    box.addEventListener("click", function (event) {
      if (event.target.closest("[data-qa-close]")) { box.close(); return; }
      if (event.target === box && pressedOutside) box.close();
      pressedOutside = false;
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
    syncShown(box);
    syncNextNo(box);
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
  // A search box instead of a dropdown of every asset: at most twenty matches,
  // the assets that carry this part first.

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

  // On a phone the first touch on a result would close the on-screen
  // keyboard, the page reflows under the finger and the tap lands elsewhere.
  // Choosing on pointerdown, before the keyboard goes, makes one tap enough;
  // the click that follows then finds the list already closed.
  document.addEventListener("pointerdown", function (event) {
    var item = event.target.closest(".picker-item");
    if (!item || item.disabled || event.button > 0) return;
    event.preventDefault();          // keep the focus where it is: no keyboard jump
    var picker = item.closest("[data-picker]");
    choose(picker, item.getAttribute("data-id"), item.getAttribute("data-label"));
    picker._chosenAt = Date.now();
  });

  document.addEventListener("click", function (event) {
    // The click that ends that same tap must not land on the × that just appeared.
    var tapped = event.target.closest && event.target.closest("[data-picker]");
    if (tapped && tapped._chosenAt && Date.now() - tapped._chosenAt < 700) {
      tapped._chosenAt = 0;
      event.preventDefault();
      return;
    }
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
    var buttons = document.querySelectorAll("[data-bulk-delete], [data-bulk-labels]");
    if (!buttons.length) return;
    var boxes = document.querySelectorAll("input[data-bulk]");
    var ticked = document.querySelectorAll("input[data-bulk]:checked");
    buttons.forEach(function (button) {
      button.hidden = ticked.length === 0;
      var count = button.querySelector("[data-bulk-count]");
      if (count) count.textContent = ticked.length;
    });
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
    var labels = event.target.closest("[data-bulk-labels]");
    if (labels) {
      // The ticked assets' labels, in a pop-up like a single asset's.
      var picked = Array.prototype.map.call(
        document.querySelectorAll("input[data-bulk]:checked"), function (box) { return box.value; }
      );
      if (!picked.length) return;
      var link = document.createElement("a");
      link.href = labels.getAttribute("data-bulk-labels") + "?ids=" + picked.join(",");
      link.setAttribute("data-frame-dialog", picked.length + " labels");
      link.hidden = true;
      document.body.appendChild(link);
      link.click();
      link.remove();
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

  /* ---------- Equipment No: the last one of the type, and the next one free ---------- */
  // <div data-next-no="/equipment/next-no/"> under the Equipment No field shows,
  // for the type chosen, the last number in use and offers the next one.

  function syncNextNo(scope) {
    (scope || document).querySelectorAll("[data-next-no]").forEach(function (box) {
      var form = box.closest("form") || document;
      var category = form.querySelector("select[name='category']");
      var field = form.querySelector("input[name='equipment_no']");
      if (!category || !field) return;
      if (!category.value) { box.textContent = ""; return; }
      fetch(box.getAttribute("data-next-no") + "?category=" + encodeURIComponent(category.value), {
        credentials: "same-origin",
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          box.innerHTML = "";
          if (!data.next) return;
          var text = document.createElement("span");
          text.textContent = data.last ? "Last " + data.last + " · " : "None yet · ";
          var use = document.createElement("button");
          use.type = "button";
          use.className = "next-no-use";
          use.textContent = "Use " + data.next;
          use.addEventListener("click", function () { field.value = data.next; field.dispatchEvent(new Event("input", { bubbles: true })); });
          box.appendChild(text);
          box.appendChild(use);
        })
        .catch(function () { box.textContent = ""; });
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches("select[name='category']") && event.target.form &&
        event.target.form.querySelector("[data-next-no]")) {
      syncNextNo(event.target.form);
    }
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { syncNextNo(document); });
  } else {
    syncNextNo(document);
  }

  /* ---------- A page in a pop-up (the label print page) ---------- */
  // <a href="..." data-frame-dialog="Title"> opens the page inside a dialog
  // over the current one instead of a new tab; ctrl/shift-click still opens
  // it on its own.

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-frame-dialog]");
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    var box = document.createElement("dialog");
    box.className = "frame-dialog";
    var head = document.createElement("div");
    head.className = "qa-head";
    var title = document.createElement("span");
    title.className = "fw-600";
    title.textContent = link.getAttribute("data-frame-dialog") || "";
    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn-ghost btn-icon btn-sm";
    close.setAttribute("aria-label", "Close");
    close.innerHTML = '<i class="bi bi-x-lg"></i>';
    head.appendChild(title);
    head.appendChild(close);
    var frame = document.createElement("iframe");
    frame.src = link.href;
    frame.title = title.textContent;
    box.appendChild(head);
    box.appendChild(frame);
    document.body.appendChild(box);
    close.addEventListener("click", function () { box.close(); });
    box.addEventListener("click", function (e) { if (e.target === box) box.close(); });
    box.addEventListener("close", function () { box.remove(); });
    box.showModal();
  });

  // The label pop-up reports labels that printed: tick them in the list
  // behind it (the server has already saved the tick).
  window.addEventListener("message", function (event) {
    if (event.origin !== window.location.origin || !event.data || event.data.type !== "ema-labelled") return;
    (event.data.ids || []).forEach(function (id) {
      document.querySelectorAll('.label-tick[data-asset="' + Number(id) + '"]').forEach(function (tick) {
        tick.checked = true;
      });
    });
  });

  /* ---------- Asset name = Manufacturer + Model ---------- */
  // <input data-auto-name> follows the Manufacturer and Model fields of its
  // form as they are typed, until someone types a name of their own.

  function autoName(form) {
    var name = form.querySelector("[data-auto-name]");
    var maker = form.querySelector("input[name='manufacturer']");
    var model = form.querySelector("input[name='model_number']");
    if (!name || !maker || !model) return;
    var made = [maker.value.trim(), model.value.trim()].filter(Boolean).join(" ").toUpperCase();
    // Follow only while the name is empty or still the one made last time
    // (on an edit form, data-made says the saved name was made this way).
    var norm = function (value) { return (value || "").replace(/\s+/g, " ").trim().toUpperCase(); };
    if (norm(name.value) === "" || norm(name.value) === norm(name.getAttribute("data-made"))) {
      name.value = made;
      name.setAttribute("data-made", made);
    }
  }

  document.addEventListener("input", function (event) {
    var target = event.target;
    if (target.form && (target.name === "manufacturer" || target.name === "model_number")) autoName(target.form);
  });

  /* ---------- Fields shown only for one choice of another field ---------- */
  // <input data-shown-when="id_kind=NG"> is on the form only while the field
  // with that id holds that value; hidden, it is not sent either.

  function syncShown(scope) {
    (scope || document).querySelectorAll("[data-shown-when]").forEach(function (field) {
      var rule = field.getAttribute("data-shown-when").split("=");
      var other = (field.form || document).querySelector("#" + rule[0]);
      if (!other) return;
      var shown = other.value === rule[1];
      field.disabled = !shown;
      var wrap = field.closest(".mb-3") || field.parentElement;
      if (wrap) wrap.hidden = !shown;
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.id && document.querySelector('[data-shown-when^="' + event.target.id + '="]')) {
      syncShown(event.target.form || document);
    }
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { syncShown(document); });
  } else {
    syncShown(document);
  }

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

  /* ---------- Photos on a form: sent the moment they are taken ---------- */
  // Each picture is uploaded as soon as it is picked or taken, and comes back
  // with the form as a token (<name>__staged). A form returned with an error
  // keeps its photos, and a phone that drops the page while its camera is
  // open loses nothing already sent. Each preview shows its state: sending,
  // sent (✓) or failed (tap to try again); × takes it out.

  function csrfToken() {
    var field = document.querySelector("[name=csrfmiddlewaretoken]");
    if (field) return field.value;
    try { return JSON.parse(document.body.getAttribute("hx-headers"))["X-CSRFToken"]; } catch (e) { return ""; }
  }

  function photoStage(input) {
    var stage = (input.form || document).querySelector('[data-photo-stage-for="' + input.id + '"]');
    if (!stage) {
      // A form drawn whole ({{ form|crispy }}) has no preview box: add one.
      stage = document.createElement("div");
      stage.className = "photo-stage";
      stage.setAttribute("data-photo-stage-for", input.id);
      input.insertAdjacentElement("afterend", stage);
    }
    return stage;
  }

  function stageNote(form, text) {
    if (!form) return;
    var note = form.querySelector(".photo-stage-note");
    if (!note && text) {
      note = document.createElement("div");
      note.className = "photo-stage-note";
      note.setAttribute("role", "status");
      var submit = form.querySelector("[type=submit]");
      (submit ? submit.parentNode : form).insertBefore(note, submit || null);
    }
    if (note) { note.textContent = text || ""; note.hidden = !text; }
  }

  function photosSettled(form) {
    if (!form || !form._waitingForPhotos) return;
    if (form.querySelector(".photo-stage-item.is-sending")) return;
    form._waitingForPhotos = false;
    if (form.querySelector(".photo-stage-item.is-failed")) {
      stageNote(form, "A photo did not upload. Tap it to try again, or × to leave it out, then save.");
      return;
    }
    stageNote(form, "");
    form.requestSubmit ? form.requestSubmit() : form.submit();
  }

  function sendPhoto(input, item) {
    var url = document.body.getAttribute("data-photo-stage-url");
    item.classList.remove("is-failed", "is-done");
    item.classList.add("is-sending");
    var body = new FormData();
    body.append("photo", item._file, item._file.name || "photo.jpg");
    fetch(url, { method: "POST", body: body, credentials: "same-origin", headers: { "X-CSRFToken": csrfToken() } })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok || !data.token) throw new Error(data.error || "The photo could not be sent.");
          return data.token;
        });
      })
      .then(function (token) {
        var keep = document.createElement("input");
        keep.type = "hidden";
        keep.name = input.name + "__staged";
        keep.value = token;
        item.appendChild(keep);
        item.classList.remove("is-sending");
        item.classList.add("is-done");
        item.title = "";
      })
      .catch(function (error) {
        item.classList.remove("is-sending");
        item.classList.add("is-failed");
        item.title = (error && error.message ? error.message : "The photo could not be sent.") + " Tap to try again.";
      })
      .then(function () { photosSettled(input.form); });
  }

  function stagePhoto(input, file) {
    var stage = photoStage(input);
    if (!stage) return;
    var item = document.createElement("div");
    item.className = "photo-stage-item";
    item._file = file;
    var img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    img.alt = "";
    var drop = document.createElement("button");
    drop.type = "button";
    drop.title = "Take this photo out";
    drop.setAttribute("aria-label", "Take this photo out");
    drop.setAttribute("data-photo-unstage", "");
    drop.innerHTML = '<i class="bi bi-x-lg"></i>';
    item.appendChild(img);
    item.appendChild(drop);
    stage.appendChild(item);
    sendPhoto(input, item);
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("input[type=file][data-photo-stage]")) return;
    if (!document.body.getAttribute("data-photo-stage-url")) return;    // not signed in: plain upload
    var seen = input._seen || (input._seen = []);
    Array.prototype.forEach.call(input.files, function (file) {
      var key = [file.name, file.size, file.lastModified].join("|");
      if (seen.indexOf(key) !== -1) return;        // the same picture picked twice
      seen.push(key);
      stagePhoto(input, file);
    });
    // The pictures travel as tokens now, not with the form.
    input.value = "";
    input.required = false;
  });

  document.addEventListener("click", function (event) {
    var drop = event.target.closest("[data-photo-unstage]");
    if (drop) {
      event.preventDefault();
      var gone = drop.closest(".photo-stage-item");
      var form = gone.closest("form");
      gone.remove();
      photosSettled(form);
      return;
    }
    var failed = event.target.closest(".photo-stage-item.is-failed");
    if (failed && failed._file) {
      var stage = failed.closest("[data-photo-stage-for]");
      var input = (stage.closest("form") || document).querySelector("#" + CSS.escape(stage.getAttribute("data-photo-stage-for")));
      if (input) sendPhoto(input, failed);
    }
  });

  // Saving waits for photos still on their way, then goes ahead by itself.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.querySelector || !form.querySelector(".photo-stage-item.is-sending, .photo-stage-item.is-failed")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (form.querySelector(".photo-stage-item.is-sending")) {
      form._waitingForPhotos = true;
      stageNote(form, "Waiting for the photos to finish uploading…");
    } else {
      stageNote(form, "A photo did not upload. Tap it to try again, or × to leave it out, then save.");
    }
  }, true);

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

/* ---------- Drag a column's edge to widen it ---------- */
// Tables with fixed columns (Equipment, Stations, Spare parts) get a handle on
// the right edge of each heading. Dragging it sets that column's width;
// double-clicking it puts the column back. Widths are remembered in this
// browser for that page, and kept when a filter or search redraws the table.
// Text cut short in a cell shows in full on hover.
(function () {
  var MIN = 40;                       // px, narrowest a column may be dragged to
  var FREE_MIN = 192;                 // px kept for the column with no set width

  function key(table) {
    var tables = Array.prototype.indexOf.call(document.querySelectorAll("table.fixed-cols"), table);
    return "ema-colw:" + location.pathname + ":" + tables + ":" + table.tHead.rows[0].cells.length;
  }

  function load(table) {
    try { return JSON.parse(localStorage.getItem(key(table)) || "{}"); } catch (e) { return {}; }
  }

  function save(table, widths) {
    try { localStorage.setItem(key(table), JSON.stringify(widths)); } catch (e) { /* not kept */ }
  }

  // The table grows instead of squeezing the free column to nothing.
  function fitTable(table) {
    var total = 0, free = false;
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th) {
      if (th.style.width) total += th.getBoundingClientRect().width;
      else free = true;
    });
    if (free) total += FREE_MIN;
    var base = parseFloat(table.getAttribute("data-table-min") || "0");
    table.style.setProperty("--table-min", Math.max(total, base) + "px");
  }

  function setup(table) {
    if (!table.tHead || table._resizable) return;
    table._resizable = true;
    var cells = table.tHead.rows[0].cells;
    // Remember the page's own minimum and each column's own width, for resets.
    var min = getComputedStyle(table).getPropertyValue("--table-min").trim();
    if (min) {
      var probe = document.createElement("div");
      probe.style.width = min;
      document.body.appendChild(probe);
      table.setAttribute("data-table-min", probe.getBoundingClientRect().width);
      probe.remove();
    }
    var widths = load(table);
    Array.prototype.forEach.call(cells, function (th, index) {
      th.setAttribute("data-default-width", th.style.width || "");
      if (widths[index]) th.style.width = widths[index] + "px";
      if (index === cells.length - 1 || th.classList.contains("col-select")) return;
      var grip = document.createElement("span");
      grip.className = "col-resize";
      grip.title = "Drag to widen · double-click to reset";
      grip.setAttribute("aria-hidden", "true");
      th.appendChild(grip);

      grip.addEventListener("click", function (event) { event.preventDefault(); event.stopPropagation(); });
      grip.addEventListener("dblclick", function (event) {
        event.preventDefault();
        event.stopPropagation();
        th.style.width = th.getAttribute("data-default-width");
        var kept = load(table);
        delete kept[index];
        save(table, kept);
        fitTable(table);
      });
      grip.addEventListener("pointerdown", function (event) {
        event.preventDefault();
        event.stopPropagation();
        var startX = event.clientX;
        var startW = th.getBoundingClientRect().width;
        grip.setPointerCapture(event.pointerId);
        table.classList.add("is-resizing");
        function move(e) {
          th.style.width = Math.max(MIN, Math.round(startW + e.clientX - startX)) + "px";
          fitTable(table);
        }
        function done() {
          grip.removeEventListener("pointermove", move);
          grip.removeEventListener("pointerup", done);
          grip.removeEventListener("pointercancel", done);
          table.classList.remove("is-resizing");
          var kept = load(table);
          kept[index] = Math.round(th.getBoundingClientRect().width);
          save(table, kept);
        }
        grip.addEventListener("pointermove", move);
        grip.addEventListener("pointerup", done);
        grip.addEventListener("pointercancel", done);
      });
    });
    fitTable(table);
  }

  function setupAll() {
    document.querySelectorAll("table.fixed-cols").forEach(setup);
  }

  // Full text of a cut-short cell on hover.
  document.addEventListener("mouseover", function (event) {
    var cell = event.target.closest && event.target.closest("table.fixed-cols td");
    if (cell && !cell.title && cell.scrollWidth > cell.clientWidth + 1) {
      cell.title = cell.textContent.replace(/\s+/g, " ").trim();
    }
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setupAll);
  else setupAll();
  document.addEventListener("htmx:afterSettle", setupAll);
})();

/* ---------- Calibration on the asset form: ticked by type, checked on save ---------- */
// <select name=category data-calibration-types="3,7,..."> lists the types that
// need calibration. Picking one ticks "Requires calibration". Saving asks
// first when such an asset is left unticked, or is ticked with no dates (it
// would show "Calibration date unknown").
(function () {
  function parts(form) {
    var category = form.querySelector("select[name=category][data-calibration-types]");
    var tick = form.querySelector("input[name=is_measuring_device]");
    if (!category || !tick) return null;
    return {
      category: category,
      tick: tick,
      last: form.querySelector("[name=calibration_last]"),
      next: form.querySelector("[name=calibration_next]"),
      needs: category.getAttribute("data-calibration-types").split(",").indexOf(category.value) !== -1 && category.value !== "",
      typeName: category.value ? category.options[category.selectedIndex].text.split(" — ").pop() : "",
    };
  }

  document.addEventListener("change", function (event) {
    var select = event.target;
    if (!select.matches || !select.matches("select[name=category][data-calibration-types]") || !select.form) return;
    var p = parts(select.form);
    if (p && p.needs && !p.tick.checked) {
      p.tick.checked = true;
      p.tick.dispatchEvent(new Event("change", { bubbles: true }));     // opens the date fields
    }
  });

  // The question is drawn by the page, not window.confirm(): a browser lets
  // people switch its own pop-ups off for good, and this one must always ask.
  // The server asks too (calibration_confirmed) if this never runs.
  function ask(form, question, onYes, onNo) {
    var box = document.createElement("dialog");
    box.className = "confirm-dialog";
    box.innerHTML =
      '<div class="confirm-body"><i class="bi bi-exclamation-triangle"></i><div class="confirm-text"></div></div>' +
      '<div class="confirm-actions"><button type="button" class="btn btn-default" data-answer="no">Go back</button>' +
      '<button type="button" class="btn btn-warning" data-answer="yes">Save anyway</button></div>';
    question.split("\n\n").forEach(function (line) {
      var p = document.createElement("p");
      p.textContent = line;
      box.querySelector(".confirm-text").appendChild(p);
    });
    document.body.appendChild(box);
    var answered = false;
    box.addEventListener("click", function (event) {
      var button = event.target.closest("[data-answer]");
      if (!button) return;
      answered = true;
      box.close();
      (button.getAttribute("data-answer") === "yes" ? onYes : onNo)();
    });
    box.addEventListener("close", function () {
      box.remove();
      if (!answered) onNo();               // Esc counts as going back
    });
    box.showModal();
    box.querySelector("[data-answer=no]").focus();
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.querySelector || form._calibrationAsked) return;
    var p = parts(form);
    if (!p) return;
    var confirmed = form.querySelector("input[name=calibration_confirmed]");
    if (confirmed && confirmed.checked) return;          // ticked on the form the server sent back
    var question = "";
    if (p.needs && !p.tick.checked) {
      question = p.typeName + " normally needs calibration, but “Requires calibration” is not ticked.\n\nSave it without calibration?";
    } else if (p.tick.checked && !(p.last && p.last.value) && !(p.next && p.next.value)) {
      question = "No calibration dates are filled in.\n\nThe asset will show “Calibration date unknown” and must not be used for measuring until it is calibrated.\n\nSave anyway?";
    }
    if (!question) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    ask(form, question, function () {
      var yes = form.querySelector("input[type=hidden][name=calibration_confirmed]");
      if (!yes) {
        yes = document.createElement("input");
        yes.type = "hidden";
        yes.name = "calibration_confirmed";
        form.appendChild(yes);
      }
      yes.value = "on";
      form._calibrationAsked = true;       // asked once; a wait for photos re-submits without asking again
      form.requestSubmit ? form.requestSubmit() : form.submit();
    }, function () {
      (p.tick.checked ? (p.last || p.tick) : p.tick).focus();
    });
  }, true);
})();

/* ---------- <form data-confirm="Question?"> asks before it is sent ---------- */
// Drawn by the page (see the calibration question): Go back or Yes.
(function () {
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute || !form.hasAttribute("data-confirm") || form._confirmed) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    var box = document.createElement("dialog");
    box.className = "confirm-dialog";
    box.innerHTML =
      '<div class="confirm-body"><i class="bi bi-question-circle"></i><div class="confirm-text"><p></p></div></div>' +
      '<div class="confirm-actions"><button type="button" class="btn btn-default" data-answer="no">Go back</button>' +
      '<button type="button" class="btn btn-primary" data-answer="yes">Yes</button></div>';
    box.querySelector(".confirm-text p").textContent = form.getAttribute("data-confirm");
    document.body.appendChild(box);
    box.addEventListener("click", function (e) {
      var button = e.target.closest("[data-answer]");
      if (!button) return;
      box.close();
      if (button.getAttribute("data-answer") === "yes") {
        form._confirmed = true;
        form.requestSubmit ? form.requestSubmit() : form.submit();
      }
    });
    box.addEventListener("close", function () { box.remove(); });
    box.showModal();
    box.querySelector("[data-answer=yes]").focus();
  }, true);
})();
