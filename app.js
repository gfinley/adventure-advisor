/* ==========================================================================
   Nordic Atlas — Interactive Expedition, Hotel Room & Booking Evaluator
   ========================================================================== */

(() => {
  "use strict";

  const STORAGE_KEY = "nordic-atlas-state-v1";

  const state = {
    dataset: null,
    selectedMonth: "all", // "all" or monthId like "2026-12"
    searchQuery: "",
    category: "all",
    region: "all",
    duration: "all",
    maxBudget: 12000,
    sortBy: "chronological",
    activeAdventureId: null,
    compareIds: [],
    shortlistIds: [],
    // Per-adventure user customizations:
    // { [advId]: { hotelIndex: 0, nights: number, includeVehicle: boolean, travelerMode: "solo"|"split", enabledActivities: number[] } }
    configs: {},
  };

  // ---------- Persistence ----------
  function loadPersisted() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed.shortlistIds)) state.shortlistIds = parsed.shortlistIds;
      if (Array.isArray(parsed.compareIds)) state.compareIds = parsed.compareIds.slice(0, 4);
      if (parsed.configs && typeof parsed.configs === "object") state.configs = parsed.configs;
    } catch {
      // ignore storage errors
    }
  }

  function savePersisted() {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          shortlistIds: state.shortlistIds,
          compareIds: state.compareIds,
          configs: state.configs,
        })
      );
    } catch {
      // ignore storage errors
    }
  }

  // ---------- Helpers ----------
  const fmtUsd = (n) =>
    "$" + Math.round(Number(n) || 0).toLocaleString("en-US");

  const escapeHtml = (str) =>
    String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function getAllAdventures() {
    if (!state.dataset) return [];
    const list = [];
    for (const month of state.dataset.months) {
      for (const adv of month.adventures) {
        list.push({ ...adv, _month: month });
      }
    }
    return list;
  }

  function findAdventure(advId) {
    if (!state.dataset) return null;
    for (const month of state.dataset.months) {
      for (const adv of month.adventures) {
        if (adv.id === advId) return { adv, month };
      }
    }
    return null;
  }

  function getConfig(adv) {
    const existing = state.configs[adv.id];
    const defaultEnabled = adv.activities
      .map((a, idx) => (!a.optional ? idx : -1))
      .filter((i) => i >= 0);

    if (!existing) {
      return {
        hotelIndex: 0,
        nights: adv.nights,
        includeVehicle: Boolean(adv.vehicle && adv.vehicle.needed),
        travelerMode: "solo",
        enabledActivities: defaultEnabled,
      };
    }

    return {
      hotelIndex: Math.min(existing.hotelIndex ?? 0, adv.hotels.length - 1),
      nights: Math.max(2, Math.min(21, existing.nights ?? adv.nights)),
      includeVehicle:
        existing.includeVehicle !== undefined
          ? existing.includeVehicle
          : Boolean(adv.vehicle && adv.vehicle.needed),
      travelerMode: existing.travelerMode === "split" ? "split" : "solo",
      enabledActivities: Array.isArray(existing.enabledActivities)
        ? existing.enabledActivities
        : defaultEnabled,
    };
  }

  function updateConfig(adv, patch) {
    const cur = getConfig(adv);
    state.configs[adv.id] = { ...cur, ...patch };
    savePersisted();
  }

  function calculatePricing(adv) {
    const cfg = getConfig(adv);
    const nights = cfg.nights;
    const days = nights + 1;
    const hotel = adv.hotels[cfg.hotelIndex] || adv.hotels[0];
    const isSplit = cfg.travelerMode === "split";
    const splitDivisor = isSplit ? 2 : 1;

    const flightsUsd = Math.round(adv.flights.estimatedRoundtripUsd);

    // For solo vs split: standard hotel rooms & 4x4 rentals split 50/50 per person,
    // while cruise solo cabins / per-person huts approximate 85% per person when paired.
    const isCruise = adv.categories.includes("Cruise");
    const lodgingRaw = hotel.nightlyRateUsd * nights;
    const lodgingUsd = Math.round(
      isSplit ? (isCruise ? lodgingRaw * 0.78 : lodgingRaw / 2) : lodgingRaw
    );

    let vehicleRaw = 0;
    if (adv.vehicle.needed) {
      if (cfg.includeVehicle) {
        const rentalDays = Math.max(1, days);
        const fuelScaled = Math.round(
          (adv.vehicle.insuranceAndFuelUsd / Math.max(1, adv.days)) * days
        );
        vehicleRaw = adv.vehicle.dailyRateUsd * rentalDays + fuelScaled;
      } else {
        vehicleRaw = Math.round(adv.vehicle.insuranceAndFuelUsd * 0.55);
      }
    } else {
      vehicleRaw = adv.vehicle.insuranceAndFuelUsd || 0;
    }
    const vehicleUsd = Math.round(
      adv.vehicle.needed && cfg.includeVehicle ? vehicleRaw / splitDivisor : vehicleRaw
    );

    const activitiesUsd = Math.round(
      adv.activities.reduce((sum, act, idx) => {
        return cfg.enabledActivities.includes(idx) ? sum + act.costUsd : sum;
      }, 0)
    );

    const foodUsd = Math.round(adv.foodAndMiscPerDayUsd * days);
    const totalUsd = flightsUsd + lodgingUsd + vehicleUsd + activitiesUsd + foodUsd;

    let budgetTier = "sweet";
    let budgetTierLabel = "Sweet Spot ($3k–$6k)";
    if (totalUsd < 3000) {
      budgetTier = "value";
      budgetTierLabel = "High Value (<$3k)";
    } else if (totalUsd > 6000) {
      budgetTier = "splurge";
      budgetTierLabel = "Expedition Splurge";
    }

    return {
      cfg,
      hotel,
      nights,
      days,
      flightsUsd,
      lodgingUsd,
      vehicleUsd,
      activitiesUsd,
      foodUsd,
      totalUsd,
      budgetTier,
      budgetTierLabel,
    };
  }

  function tagClass(cat) {
    if (cat === "Scuba") return "tag tag-scuba";
    if (cat === "Hut Hiking") return "tag tag-hut";
    if (cat === "Cold Solitude Resort") return "tag tag-solitude";
    return "tag";
  }

  // ---------- Filtering & Sorting ----------
  function matchesFilters(adv) {
    const pricing = calculatePricing(adv);

    if (pricing.totalUsd > state.maxBudget) return false;

    if (state.category !== "all" && !adv.categories.includes(state.category)) {
      return false;
    }

    if (state.region !== "all") {
      if (state.region === "nordic" && !adv.isNordic) return false;
      else if (state.region === "wildcard" && adv.isNordic) return false;
      else if (state.region === "Norway") {
        if (!adv.country.toLowerCase().includes("norway") && !adv.country.toLowerCase().includes("svalbard")) {
          return false;
        }
      } else if (
        state.region !== "nordic" &&
        state.region !== "wildcard" &&
        !adv.country.toLowerCase().includes(state.region.toLowerCase())
      ) {
        return false;
      }
    }

    if (state.duration === "strike" && adv.days > 6) return false;
    if (state.duration === "expedition" && adv.days < 7) return false;

    if (state.searchQuery.trim()) {
      const q = state.searchQuery.trim().toLowerCase();
      const hay = [
        adv.title,
        adv.country,
        adv.region,
        adv.tagline,
        adv.whyNow,
        adv.categories.join(" "),
        adv.hotels.map((h) => `${h.name} ${h.roomType} ${h.style}`).join(" "),
        adv.activities.map((a) => `${a.name} ${a.operator}`).join(" "),
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }

    return true;
  }

  function sortAdventures(list) {
    const copy = [...list];
    switch (state.sortBy) {
      case "offseason":
        copy.sort((a, b) => b.offSeasonScore - a.offSeasonScore);
        break;
      case "price-asc":
        copy.sort((a, b) => calculatePricing(a).totalUsd - calculatePricing(b).totalUsd);
        break;
      case "price-desc":
        copy.sort((a, b) => calculatePricing(b).totalUsd - calculatePricing(a).totalUsd);
        break;
      case "days-asc":
        copy.sort((a, b) => a.days - b.days);
        break;
      default:
        break;
    }
    return copy;
  }

  // ---------- Rendering ----------
  function renderHeaderStats() {
    const meta = state.dataset.meta;
    const generated = new Date(meta.generatedAt);
    document.getElementById("meta-generated").textContent =
      "Researched " +
      generated.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });

    document.getElementById("stat-total-adventures").textContent = String(meta.adventureCount);
    const pct = Math.round((meta.nordicCount / Math.max(1, meta.adventureCount)) * 100);
    document.getElementById("stat-nordic-ratio").textContent = `${pct}%`;
    const openCount = state.dataset.months.filter((m) => m.availabilityStatus === "open").length;
    document.getElementById("stat-open-months").textContent = String(openCount);

    renderShortlistHeader();
  }

  function renderShortlistHeader() {
    let total = 0;
    let count = 0;
    for (const id of state.shortlistIds) {
      const found = findAdventure(id);
      if (found) {
        count++;
        total += calculatePricing(found.adv).totalUsd;
      }
    }
    document.getElementById("header-shortlist-count").textContent = String(count);
    document.getElementById("header-shortlist-cost").textContent = fmtUsd(total);
  }

  function renderMonthRibbon() {
    const container = document.getElementById("month-ribbon");
    const html = state.dataset.months
      .map((m) => {
        const isActive = state.selectedMonth === m.monthId;
        const prices = m.adventures.map((a) => calculatePricing(a).totalUsd);
        const minP = Math.min(...prices);
        const maxP = Math.max(...prices);
        const shortlistedInMonth = m.adventures.filter((a) =>
          state.shortlistIds.includes(a.id)
        ).length;

        const statusLabel =
          m.availabilityStatus === "open"
            ? "Open"
            : m.availabilityStatus === "partial"
            ? "NOLS Ext"
            : "Busy";

        const eventPreview =
          m.calendarEvents.length > 0
            ? m.calendarEvents.map((e) => e.title).join(" · ")
            : "Open all month (8–14d)";

        return `
          <button
            type="button"
            class="month-tile ${isActive ? "active" : ""}"
            role="tab"
            aria-selected="${isActive}"
            data-month-id="${escapeHtml(m.monthId)}"
          >
            <div class="month-tile-top">
              <span class="month-tile-name">${escapeHtml(m.shortLabel)}</span>
              <span class="month-tile-status">
                <i class="dot dot-${escapeHtml(m.availabilityStatus)}"></i>
                ${statusLabel}
              </span>
            </div>
            <div class="month-tile-event" title="${escapeHtml(eventPreview)}">${escapeHtml(eventPreview)}</div>
            <div class="month-tile-foot">
              <span class="mono">${fmtUsd(minP)}–${fmtUsd(maxP)}</span>
              ${
                shortlistedInMonth > 0
                  ? `<span class="month-shortlist-badge">★ ${shortlistedInMonth}</span>`
                  : `<span>${m.adventures.length} opts</span>`
              }
            </div>
          </button>
        `;
      })
      .join("");

    container.innerHTML = html;

    container.querySelectorAll(".month-tile").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.monthId;
        state.selectedMonth = state.selectedMonth === id ? "all" : id;
        renderAll();
      });
    });

    renderMonthBriefing();
  }

  function renderMonthBriefing() {
    const el = document.getElementById("month-briefing");
    if (state.selectedMonth === "all") {
      el.hidden = true;
      return;
    }

    const month = state.dataset.months.find((m) => m.monthId === state.selectedMonth);
    if (!month) {
      el.hidden = true;
      return;
    }

    el.hidden = false;
    const statusLabel =
      month.availabilityStatus === "open"
        ? "Wide Open · 8–14d Expeditions"
        : month.availabilityStatus === "partial"
        ? "NOLS Extension Window"
        : "Busy Calendar · 4–6d Strikes";

    const eventsHtml =
      month.calendarEvents.length > 0
        ? `<ul class="briefing-cal-list">
            ${month.calendarEvents
              .map(
                (e) =>
                  `<li><span class="mono">${escapeHtml(e.start.slice(5))} → ${escapeHtml(
                    e.end.slice(5)
                  )}</span> · <strong>${escapeHtml(e.title)}</strong> (${escapeHtml(e.status)})</li>`
              )
              .join("")}
          </ul>`
        : `<p style="margin:0 0 10px;color:var(--ink-secondary)">No conflicting trips on your Adventure Calendar.</p>`;

    el.innerHTML = `
      <div>
        <div class="briefing-title-row">
          <h3>${escapeHtml(month.monthLabel)} — ${escapeHtml(month.seasonTag)}</h3>
          <span class="status-tag ${escapeHtml(month.availabilityStatus)}">${statusLabel}</span>
        </div>
        <p class="briefing-note">${escapeHtml(month.advisorNote)}</p>
      </div>
      <div class="briefing-calendar-box">
        <div class="briefing-cal-label">Adventure Calendar Commitments</div>
        ${eventsHtml}
        <div class="briefing-cal-label">Open Travel Windows</div>
        <div class="briefing-windows">${escapeHtml(month.openWindows.join("  ·  "))}</div>
      </div>
    `;
  }

  function renderAdventureCard(adv, month) {
    const p = calculatePricing(adv);
    const isShortlisted = state.shortlistIds.includes(adv.id);
    const isCompared = state.compareIds.includes(adv.id);

    return `
      <article class="adventure-card" data-adv-id="${escapeHtml(adv.id)}">
        <div class="card-media" data-open-eval="${escapeHtml(adv.id)}">
          <img
            src="assets/images/${escapeHtml(adv.heroImage)}.jpg"
            alt="${escapeHtml(adv.title)}"
            loading="lazy"
          />
          <div class="card-media-overlay">
            <div class="media-top">
              <span class="media-badge ${adv.isNordic ? "nordic" : ""}">
                ${adv.isNordic ? "Nordic / Arctic" : "Mountain Wildcard"}
              </span>
              <span class="media-score" title="Off-Season Optimality Score">
                Off-Season ${adv.offSeasonScore}/100
              </span>
            </div>
            <div class="media-bottom">
              <span class="media-coords">${escapeHtml(adv.coordinates)}</span>
              <span class="media-window mono">${escapeHtml(adv.window)}</span>
            </div>
          </div>
        </div>

        <div class="card-body">
          <div class="card-kicker-row">
            <span class="card-country">${escapeHtml(adv.country)} · ${escapeHtml(adv.region)}</span>
            <span class="mono">${p.days}d / ${p.nights}n · ${escapeHtml(adv.activityIntensity)}</span>
          </div>

          <h3 class="card-title" data-open-eval="${escapeHtml(adv.id)}">${escapeHtml(adv.title)}</h3>
          <p class="card-tagline">${escapeHtml(adv.tagline)}</p>

          <div class="tag-row">
            ${adv.categories.map((c) => `<span class="${tagClass(c)}">${escapeHtml(c)}</span>`).join("")}
          </div>

          <div class="card-lodging-preview">
            <div class="lodging-preview-row">
              <span class="lodging-preview-name" title="${escapeHtml(p.hotel.name)}">${escapeHtml(p.hotel.name)}</span>
              <span class="lodging-preview-rate">${fmtUsd(p.hotel.nightlyRateUsd)}/nt</span>
            </div>
            <div class="lodging-preview-sub">
              ${escapeHtml(p.hotel.roomType)} · ${adv.hotels.length} room options ·
              ${adv.vehicle.needed ? `4x4 ${fmtUsd(adv.vehicle.dailyRateUsd)}/d` : "No car needed"}
            </div>
          </div>

          <div class="card-cost-bar">
            <div>
              <span class="cost-label">${p.cfg.travelerMode === "split" ? "Per-Person (Split)" : "Est. Solo Total"} · From SEA</span>
              <span class="cost-value">${fmtUsd(p.totalUsd)}</span>
            </div>
            <span class="budget-badge ${p.budgetTier}">${p.budgetTierLabel}</span>
          </div>

          <div class="card-actions">
            <button type="button" class="btn btn-primary btn-sm" data-open-eval="${escapeHtml(adv.id)}">
              Evaluate Rooms &amp; Costs
            </button>
            <button
              type="button"
              class="btn btn-sm ${isShortlisted ? "btn-shortlisted" : "btn-subtle"}"
              data-toggle-shortlist="${escapeHtml(adv.id)}"
              title="Add or remove from your 2027 plan"
            >
              ${isShortlisted ? "★ Saved" : "☆ Plan"}
            </button>
            <label class="compare-check" title="Select up to 4 trips to compare side-by-side">
              <input type="checkbox" data-toggle-compare="${escapeHtml(adv.id)}" ${isCompared ? "checked" : ""} />
              <span>Cmp</span>
            </label>
          </div>
        </div>
      </article>
    `;
  }

  function renderAdventures() {
    const container = document.getElementById("adventures-container");
    const countEl = document.getElementById("results-count");

    const targetMonths =
      state.selectedMonth === "all"
        ? state.dataset.months
        : state.dataset.months.filter((m) => m.monthId === state.selectedMonth);

    // If sorting non-chronologically across all months, show a flat sorted grid;
    // if chronological, preserve clean month headers!
    if (state.sortBy !== "chronological" && state.selectedMonth === "all") {
      const flat = [];
      for (const m of targetMonths) {
        for (const a of m.adventures) {
          if (matchesFilters(a)) flat.push({ adv: a, month: m });
        }
      }
      const sorted = sortAdventures(flat.map((x) => x.adv));
      countEl.textContent = `${sorted.length} of ${state.dataset.meta.adventureCount} expeditions shown`;

      if (sorted.length === 0) {
        container.innerHTML = renderEmptyState();
        bindEmptyReset();
        return;
      }

      container.innerHTML = `<div class="cards-grid">${sorted
        .map((adv) => {
          const m = findAdventure(adv.id).month;
          return renderAdventureCard(adv, m);
        })
        .join("")}</div>`;
      bindCardEvents(container);
      return;
    }

    let totalShown = 0;
    const sectionsHtml = targetMonths
      .map((month) => {
        const filtered = sortAdventures(month.adventures.filter(matchesFilters));
        if (filtered.length === 0) return "";
        totalShown += filtered.length;

        const statusLabel =
          month.availabilityStatus === "open"
            ? "Open Month"
            : month.availabilityStatus === "partial"
            ? "NOLS Extension"
            : "Short Strike Month";

        return `
          <section class="month-group" aria-label="${escapeHtml(month.monthLabel)}">
            <div class="month-group-header">
              <h3 class="month-group-title">
                <span>${escapeHtml(month.monthLabel)}</span>
                <span class="status-tag ${escapeHtml(month.availabilityStatus)}">${statusLabel}</span>
              </h3>
              <span class="month-group-meta">${escapeHtml(month.seasonTag)} · ${escapeHtml(month.recommendedDuration)}</span>
            </div>
            <div class="cards-grid">
              ${filtered.map((adv) => renderAdventureCard(adv, month)).join("")}
            </div>
          </section>
        `;
      })
      .join("");

    countEl.textContent = `${totalShown} of ${state.dataset.meta.adventureCount} expeditions shown`;

    if (totalShown === 0) {
      container.innerHTML = renderEmptyState();
      bindEmptyReset();
      return;
    }

    container.innerHTML = sectionsHtml;
    bindCardEvents(container);
  }

  function renderEmptyState() {
    return `
      <div class="empty-state">
        <h3>No expeditions match those exact filters</h3>
        <p>Try widening your budget ceiling, switching back to All 12 Months, or clearing your search query.</p>
        <button type="button" class="btn btn-primary" id="empty-reset-btn">Reset All Filters</button>
      </div>
    `;
  }

  function bindEmptyReset() {
    const btn = document.getElementById("empty-reset-btn");
    if (btn) btn.addEventListener("click", resetFilters);
  }

  function bindCardEvents(root) {
    root.querySelectorAll("[data-open-eval]").forEach((el) => {
      el.addEventListener("click", () => openEvaluator(el.dataset.openEval));
    });

    root.querySelectorAll("[data-toggle-shortlist]").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleShortlist(btn.dataset.toggleShortlist);
      });
    });

    root.querySelectorAll("[data-toggle-compare]").forEach((chk) => {
      chk.addEventListener("change", () => {
        toggleCompare(chk.dataset.toggleCompare, chk.checked);
      });
    });
  }

  // ---------- Shortlist & Compare Actions ----------
  function toggleShortlist(advId) {
    const idx = state.shortlistIds.indexOf(advId);
    if (idx >= 0) {
      state.shortlistIds.splice(idx, 1);
    } else {
      state.shortlistIds.push(advId);
    }
    savePersisted();
    renderShortlistHeader();
    renderMonthRibbon();
    renderAdventures();
    if (state.activeAdventureId === advId) renderEvaluatorContent(advId);
  }

  function toggleCompare(advId, checked) {
    const idx = state.compareIds.indexOf(advId);
    if (checked && idx < 0) {
      if (state.compareIds.length >= 4) {
        state.compareIds.shift();
      }
      state.compareIds.push(advId);
    } else if (!checked && idx >= 0) {
      state.compareIds.splice(idx, 1);
    }
    savePersisted();
    renderCompareTray();
    renderAdventures();
    if (state.activeAdventureId === advId) renderEvaluatorContent(advId);
  }

  function renderCompareTray() {
    const tray = document.getElementById("compare-tray");
    const itemsEl = document.getElementById("compare-tray-items");

    if (state.compareIds.length === 0) {
      tray.hidden = true;
      return;
    }

    tray.hidden = false;
    itemsEl.innerHTML = state.compareIds
      .map((id) => {
        const found = findAdventure(id);
        if (!found) return "";
        const total = calculatePricing(found.adv).totalUsd;
        return `
          <span class="tray-pill">
            <span>${escapeHtml(found.month.shortLabel)}: <strong>${escapeHtml(found.adv.country)}</strong> (${fmtUsd(total)})</span>
            <button type="button" data-remove-compare="${escapeHtml(id)}" aria-label="Remove from compare">✕</button>
          </span>
        `;
      })
      .join("");

    itemsEl.querySelectorAll("[data-remove-compare]").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleCompare(btn.dataset.removeCompare, false);
      });
    });
  }

  // ---------- Expedition Evaluator Drawer ----------
  function openEvaluator(advId) {
    state.activeAdventureId = advId;
    const modal = document.getElementById("evaluator-modal");
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    renderEvaluatorContent(advId);
  }

  function closeEvaluator() {
    state.activeAdventureId = null;
    document.getElementById("evaluator-modal").hidden = true;
    document.body.style.overflow = "";
  }

  function renderEvaluatorContent(advId) {
    const found = findAdventure(advId);
    if (!found) return;
    const { adv, month } = found;
    const p = calculatePricing(adv);
    const isShortlisted = state.shortlistIds.includes(adv.id);
    const isCompared = state.compareIds.includes(adv.id);

    document.getElementById("eval-month-badge").textContent = month.monthLabel;
    document.getElementById("eval-window-badge").textContent =
      `Suggested Window: ${adv.window} · ${adv.coordinates}`;

    const totalForBar = Math.max(1, p.totalUsd);
    const pct = (v) => ((v / totalForBar) * 100).toFixed(1) + "%";

    const hotelsHtml = adv.hotels
      .map((h, idx) => {
        const selected = idx === p.cfg.hotelIndex;
        const stayTotal = h.nightlyRateUsd * p.nights;
        return `
          <div class="hotel-option ${selected ? "selected" : ""}" data-select-hotel="${idx}" role="radio" aria-checked="${selected}" tabindex="0">
            <div class="hotel-option-top">
              <div>
                <div class="hotel-option-name">${selected ? "● " : "○ "}${escapeHtml(h.name)}</div>
                <div class="hotel-room-line">${escapeHtml(h.location)} · <strong>${escapeHtml(h.roomType)}</strong> (${escapeHtml(h.style)})</div>
              </div>
              <div class="hotel-option-price">
                <strong>${fmtUsd(h.nightlyRateUsd)}/nt</strong>
                <span>${fmtUsd(stayTotal)} (${p.nights}n)</span>
              </div>
            </div>
            <ul class="hotel-highlights">
              ${h.highlights.map((hl) => `<li>${escapeHtml(hl)}</li>`).join("")}
            </ul>
            <div class="hotel-footer-row">
              <span class="mono">${h.soloFriendly ? "✓ Solo-friendly room/pricing" : "Check single supplement"}</span>
              <a href="${escapeHtml(h.bookingUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Official Property ↗</a>
            </div>
          </div>
        `;
      })
      .join("");

    const vehicleHtml = adv.vehicle.needed
      ? `
        <div class="vehicle-box">
          <div class="vehicle-top">
            <strong>${escapeHtml(adv.vehicle.recommendedClass)}</strong>
            <span class="mono" style="color:var(--accent-copper);font-weight:600">${fmtUsd(adv.vehicle.dailyRateUsd)}/day</span>
          </div>
          <p style="margin:0 0 8px;font-size:0.84rem;color:var(--ink-secondary)">
            Provider: <strong>${escapeHtml(adv.vehicle.provider)}</strong> · Est. insurance/fuel/tolls: <span class="mono">${fmtUsd(adv.vehicle.insuranceAndFuelUsd)}</span>
          </p>
          <p style="margin:0 0 10px;font-size:0.82rem;color:var(--ink-muted)">${escapeHtml(adv.vehicle.notes)}</p>
          <label style="display:inline-flex;align-items:center;gap:8px;font-size:0.84rem;font-weight:600;cursor:pointer">
            <input type="checkbox" id="eval-vehicle-toggle" ${p.cfg.includeVehicle ? "checked" : ""} style="accent-color:var(--accent-pine)" />
            Include 4x4 rental in theoretical booking (uncheck to estimate transit/shuttle transfers)
          </label>
        </div>
      `
      : `
        <div class="vehicle-box">
          <div class="vehicle-top">
            <strong>${escapeHtml(adv.vehicle.recommendedClass)}</strong>
            <span class="mono" style="color:var(--accent-pine);font-weight:600">${fmtUsd(adv.vehicle.insuranceAndFuelUsd)} est.</span>
          </div>
          <p style="margin:0;font-size:0.84rem;color:var(--ink-secondary)">
            ${escapeHtml(adv.vehicle.provider)} — ${escapeHtml(adv.vehicle.notes)}
          </p>
        </div>
      `;

    const activitiesHtml = adv.activities
      .map((act, idx) => {
        const checked = p.cfg.enabledActivities.includes(idx);
        return `
          <div class="activity-item">
            <label class="activity-check">
              <input type="checkbox" data-toggle-act="${idx}" ${checked ? "checked" : ""} />
              <div>
                <div style="font-weight:600;font-size:0.9rem">
                  ${escapeHtml(act.name)}
                  ${act.optional ? `<span class="tag" style="margin-left:6px">Optional Add-On</span>` : ""}
                </div>
                <div class="activity-meta">
                  Operator: ${escapeHtml(act.operator)} ·
                  <a href="${escapeHtml(act.url)}" target="_blank" rel="noopener noreferrer">Website ↗</a>
                </div>
              </div>
            </label>
            <span class="mono" style="font-weight:600;white-space:nowrap">${fmtUsd(act.costUsd)}</span>
          </div>
        `;
      })
      .join("");

    document.getElementById("evaluator-body").innerHTML = `
      <div class="evaluator-layout">
        <div>
          <img class="eval-hero-img" src="assets/images/${escapeHtml(adv.heroImage)}.jpg" alt="${escapeHtml(adv.title)}" />
          <h2 class="eval-title" id="eval-title">${escapeHtml(adv.title)}</h2>
          <div class="eval-meta-strip">
            <span><strong>${escapeHtml(adv.country)}</strong> — ${escapeHtml(adv.region)}</span>
            <span>·</span>
            <span class="mono">Off-Season Score: ${adv.offSeasonScore}/100</span>
            <span>·</span>
            <span>Crowds: <strong>${escapeHtml(adv.crowdLevel)}</strong></span>
            <span>·</span>
            <span>Intensity: <strong>${escapeHtml(adv.activityIntensity)}</strong></span>
          </div>

          <div class="eval-callout">
            <strong>Calendar Fit:</strong> ${escapeHtml(adv.calendarFit)}<br/>
            <strong>Why Off-Season Now:</strong> ${escapeHtml(adv.whyNow)}
          </div>

          <section class="eval-section">
            <div class="eval-section-head">
              <h3>Select Hotel Room / Cabin / Hut Tier</h3>
              <span class="eval-section-hint">Click any option to recalculate total</span>
            </div>
            <div class="hotel-options" role="radiogroup" aria-label="Hotel room options">
              ${hotelsHtml}
            </div>
          </section>

          <section class="eval-section">
            <div class="eval-section-head">
              <h3>4x4 Vehicle &amp; Local Transport</h3>
              <span class="eval-section-hint">${adv.vehicle.needed ? "AWD/4x4 recommended" : "Car-free expedition"}</span>
            </div>
            ${vehicleHtml}
          </section>

          <section class="eval-section">
            <div class="eval-section-head">
              <h3>Active Guides, Scuba &amp; Hut Permits</h3>
              <span class="eval-section-hint">Toggle items to customize booking</span>
            </div>
            <div class="activity-list">
              ${activitiesHtml}
            </div>
          </section>

          <section class="eval-section">
            <div class="eval-section-head">
              <h3>Active Field Itinerary</h3>
              <span class="eval-section-hint">${adv.days}-day baseline routing</span>
            </div>
            <ol class="itinerary-list">
              ${adv.itinerary.map((step) => `<li>${escapeHtml(step.replace(/^Day\s+\d+:\s*/i, ""))}</li>`).join("")}
            </ol>
          </section>

          <section class="eval-section">
            <div class="eval-section-head">
              <h3>Flights from Seattle (SEA) &amp; Research Sources</h3>
            </div>
            <p style="margin:0 0 8px;font-size:0.88rem">
              <strong>${escapeHtml(adv.flights.route)}</strong> (${escapeHtml(adv.flights.airlines)} · ${escapeHtml(adv.flights.duration)}) — Est. <span class="mono">${fmtUsd(adv.flights.estimatedRoundtripUsd)}</span> roundtrip.
            </p>
            <p style="margin:0 0 12px;font-size:0.84rem;color:var(--ink-secondary)">${escapeHtml(adv.flights.notes)}</p>
            <div class="tag-row">
              ${adv.sources.map((s) => `<span class="tag">Source: ${escapeHtml(s)}</span>`).join("")}
            </div>
          </section>
        </div>

        <!-- Sticky Right Column: Live Theoretical Booking Calculator -->
        <aside class="calculator-card" aria-label="Theoretical Booking Calculator">
          <div class="calc-header">
            <h3>Theoretical Booking</h3>
            <span class="budget-badge ${p.budgetTier}">${p.budgetTierLabel}</span>
          </div>

          <div class="calc-controls">
            <div class="calc-control-box">
              <label>Trip Length</label>
              <div class="stepper">
                <button type="button" id="eval-nights-minus" aria-label="Decrease nights">−</button>
                <span class="mono" style="font-weight:600">${p.days}d / ${p.nights}n</span>
                <button type="button" id="eval-nights-plus" aria-label="Increase nights">+</button>
              </div>
            </div>
            <div class="calc-control-box">
              <label>Occupancy Basis</label>
              <div class="mode-toggle">
                <button type="button" data-mode="solo" class="${p.cfg.travelerMode === "solo" ? "active" : ""}">Solo 1x</button>
                <button type="button" data-mode="split" class="${p.cfg.travelerMode === "split" ? "active" : ""}">Split 2x</button>
              </div>
            </div>
          </div>

          <div class="cost-bar-visual" aria-hidden="true">
            <div class="seg-flights" style="width:${pct(p.flightsUsd)}" title="Flights"></div>
            <div class="seg-lodging" style="width:${pct(p.lodgingUsd)}" title="Lodging"></div>
            <div class="seg-vehicle" style="width:${pct(p.vehicleUsd)}" title="4x4 & Transport"></div>
            <div class="seg-activities" style="width:${pct(p.activitiesUsd)}" title="Guides & Scuba"></div>
            <div class="seg-food" style="width:${pct(p.foodUsd)}" title="Food & Buffer"></div>
          </div>

          <table class="receipt-table">
            <tbody>
              <tr>
                <td><span class="receipt-dot seg-flights"></span>Flights (${escapeHtml(adv.flights.route)})</td>
                <td>${fmtUsd(p.flightsUsd)}</td>
              </tr>
              <tr>
                <td><span class="receipt-dot seg-lodging"></span>${escapeHtml(p.hotel.name)} (${p.nights}n)</td>
                <td>${fmtUsd(p.lodgingUsd)}</td>
              </tr>
              <tr>
                <td><span class="receipt-dot seg-vehicle"></span>${adv.vehicle.needed && p.cfg.includeVehicle ? "4x4 Rental + Ins/Fuel" : "Local Transfers / Rail"}</td>
                <td>${fmtUsd(p.vehicleUsd)}</td>
              </tr>
              <tr>
                <td><span class="receipt-dot seg-activities"></span>Guides, Scuba &amp; Huts (${p.cfg.enabledActivities.length})</td>
                <td>${fmtUsd(p.activitiesUsd)}</td>
              </tr>
              <tr>
                <td><span class="receipt-dot seg-food"></span>Food &amp; Field Buffer (${p.days}d × $${adv.foodAndMiscPerDayUsd})</td>
                <td>${fmtUsd(p.foodUsd)}</td>
              </tr>
              <tr class="receipt-total-row">
                <td>${p.cfg.travelerMode === "split" ? "Est. Per-Person (2x)" : "Est. Solo Total"}</td>
                <td>${fmtUsd(p.totalUsd)}</td>
              </tr>
            </tbody>
          </table>

          <div class="booking-strategy">
            <div><strong>Target Book-By:</strong> ${escapeHtml(adv.theoreticalBooking.targetBookBy)}</div>
            <div><strong>Cancellation Flex:</strong> ${escapeHtml(adv.theoreticalBooking.cancellationFlex)}</div>
            <div><strong>Solo Cost Note:</strong> ${escapeHtml(adv.theoreticalBooking.budgetNote)}</div>
          </div>

          <div class="calc-action-stack">
            <button type="button" class="btn ${isShortlisted ? "btn-shortlisted" : "btn-primary"}" id="eval-shortlist-btn">
              ${isShortlisted ? "★ Saved in My 2027 Plan" : "☆ Add to My 2027 Plan"}
            </button>
            <button type="button" class="btn btn-subtle" id="eval-compare-btn">
              ${isCompared ? "✓ In Side-by-Side Compare" : "+ Add to Side-by-Side Compare"}
            </button>
            <button type="button" class="btn btn-subtle" id="eval-ics-btn">
              ↓ Export Tentative Event (.ics)
            </button>
          </div>
        </aside>
      </div>
    `;

    // Bind evaluator interactive controls
    const body = document.getElementById("evaluator-body");

    body.querySelectorAll("[data-select-hotel]").forEach((card) => {
      const select = () => {
        updateConfig(adv, { hotelIndex: Number(card.dataset.selectHotel) });
        renderEvaluatorContent(advId);
        renderAdventures();
        renderMonthRibbon();
        renderShortlistHeader();
      };
      card.addEventListener("click", select);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          select();
        }
      });
    });

    const vehToggle = document.getElementById("eval-vehicle-toggle");
    if (vehToggle) {
      vehToggle.addEventListener("change", () => {
        updateConfig(adv, { includeVehicle: vehToggle.checked });
        renderEvaluatorContent(advId);
        renderAdventures();
        renderShortlistHeader();
      });
    }

    body.querySelectorAll("[data-toggle-act]").forEach((chk) => {
      chk.addEventListener("change", () => {
        const idx = Number(chk.dataset.toggleAct);
        const cur = new Set(getConfig(adv).enabledActivities);
        if (chk.checked) cur.add(idx);
        else cur.delete(idx);
        updateConfig(adv, { enabledActivities: Array.from(cur).sort((a, b) => a - b) });
        renderEvaluatorContent(advId);
        renderAdventures();
        renderShortlistHeader();
      });
    });

    document.getElementById("eval-nights-minus").addEventListener("click", () => {
      updateConfig(adv, { nights: Math.max(2, p.nights - 1) });
      renderEvaluatorContent(advId);
      renderAdventures();
      renderShortlistHeader();
    });

    document.getElementById("eval-nights-plus").addEventListener("click", () => {
      updateConfig(adv, { nights: Math.min(18, p.nights + 1) });
      renderEvaluatorContent(advId);
      renderAdventures();
      renderShortlistHeader();
    });

    body.querySelectorAll("[data-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        updateConfig(adv, { travelerMode: btn.dataset.mode });
        renderEvaluatorContent(advId);
        renderAdventures();
        renderShortlistHeader();
      });
    });

    document.getElementById("eval-shortlist-btn").addEventListener("click", () => {
      toggleShortlist(adv.id);
    });

    document.getElementById("eval-compare-btn").addEventListener("click", () => {
      toggleCompare(adv.id, !state.compareIds.includes(adv.id));
    });

    document.getElementById("eval-ics-btn").addEventListener("click", () => {
      downloadIcs([adv]);
    });
  }

  // ---------- Side-by-Side Compare Modal ----------
  function openCompareModal() {
    const modal = document.getElementById("compare-modal");
    const body = document.getElementById("compare-modal-body");
    const items = state.compareIds.map(findAdventure).filter(Boolean);

    if (items.length === 0) {
      body.innerHTML = `<p>Select 2 to 4 expeditions using the <strong>Cmp</strong> checkbox on any card to evaluate them side by side.</p>`;
    } else {
      const priced = items.map((x) => ({ ...x, p: calculatePricing(x.adv) }));
      const cols = priced
        .map(
          ({ adv, month }) =>
            `<td style="min-width:220px"><strong style="font-family:var(--font-serif);font-size:1.05rem">${escapeHtml(
              adv.title
            )}</strong><br/><span class="mono" style="font-size:0.76rem;color:var(--accent-pine)">${escapeHtml(
              month.shortLabel
            )} · ${escapeHtml(adv.country)}</span></td>`
        )
        .join("");

      const row = (label, fn) =>
        `<tr><th>${label}</th>${priced.map((x) => `<td>${fn(x)}</td>`).join("")}</tr>`;

      body.innerHTML = `
        <div class="compare-table-wrap">
          <table class="compare-table">
            <tbody>
              <tr><th>Expedition</th>${cols}</tr>
              ${row("Window & Length", ({ adv, p }) => `<span class="mono">${escapeHtml(adv.window)}</span><br/>${p.days}d / ${p.nights}n`)}
              ${row("Total Cost", ({ p }) => `<strong class="mono" style="font-size:1.1rem">${fmtUsd(p.totalUsd)}</strong><br/><span class="budget-badge ${p.budgetTier}">${p.budgetTierLabel}</span>`)}
              ${row("Selected Room", ({ p }) => `<strong>${escapeHtml(p.hotel.name)}</strong><br/>${escapeHtml(p.hotel.roomType)}<br/><span class="mono">${fmtUsd(p.hotel.nightlyRateUsd)}/nt (${fmtUsd(p.lodgingUsd)} total)</span>`)}
              ${row("Flights (SEA)", ({ adv, p }) => `<span class="mono">${fmtUsd(p.flightsUsd)}</span><br/>${escapeHtml(adv.flights.route)}`)}
              ${row("4x4 / Transport", ({ adv, p }) => `<span class="mono">${fmtUsd(p.vehicleUsd)}</span><br/>${escapeHtml(adv.vehicle.recommendedClass)}`)}
              ${row("Scuba / Guides", ({ p }) => `<span class="mono">${fmtUsd(p.activitiesUsd)}</span> (${p.cfg.enabledActivities.length} selected)`)}
              ${row("Off-Season Score", ({ adv }) => `<span class="mono">${adv.offSeasonScore}/100</span> · Crowds: ${escapeHtml(adv.crowdLevel)}`)}
              ${row("Categories", ({ adv }) => `<div class="tag-row">${adv.categories.map((c) => `<span class="${tagClass(c)}">${escapeHtml(c)}</span>`).join("")}</div>`)}
              ${row("Calendar Fit", ({ adv }) => escapeHtml(adv.calendarFit))}
              ${row("Actions", ({ adv }) => `<button type="button" class="btn btn-primary btn-sm" data-jump-eval="${escapeHtml(adv.id)}">Customize Rooms</button>`)}
            </tbody>
          </table>
        </div>
      `;

      body.querySelectorAll("[data-jump-eval]").forEach((btn) => {
        btn.addEventListener("click", () => {
          modal.hidden = true;
          openEvaluator(btn.dataset.jumpEval);
        });
      });
    }

    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  // ---------- Annual Shortlist & Export Modal ----------
  function openPlannerModal() {
    const modal = document.getElementById("planner-modal");
    const body = document.getElementById("planner-modal-body");

    const items = state.shortlistIds
      .map(findAdventure)
      .filter(Boolean)
      .sort((a, b) => a.month.monthId.localeCompare(b.month.monthId));

    if (items.length === 0) {
      body.innerHTML = `
        <div class="empty-state">
          <h3>Your 2026–2027 Adventure Shortlist is Empty</h3>
          <p>Click <strong>☆ Plan</strong> on any expedition card (or inside the Room Evaluator) to assemble your year-in-adventure budget and export directly to Google Calendar (.ics).</p>
          <button type="button" class="btn btn-primary" id="planner-close-go">Browse Expeditions</button>
        </div>
      `;
      document.getElementById("planner-close-go").addEventListener("click", () => {
        modal.hidden = true;
        document.body.style.overflow = "";
      });
    } else {
      const priced = items.map((x) => ({ ...x, p: calculatePricing(x.adv) }));
      const totalSpend = priced.reduce((s, x) => s + x.p.totalUsd, 0);
      const totalDays = priced.reduce((s, x) => s + x.p.days, 0);
      const avgTrip = totalSpend / priced.length;

      body.innerHTML = `
        <div class="planner-summary-grid">
          <div class="planner-stat"><span>Shortlisted Trips</span><strong>${priced.length}</strong></div>
          <div class="planner-stat"><span>Total Travel Days</span><strong>${totalDays}d</strong></div>
          <div class="planner-stat"><span>Annual Budget Est.</span><strong>${fmtUsd(totalSpend)}</strong></div>
          <div class="planner-stat"><span>Avg Cost / Trip</span><strong>${fmtUsd(avgTrip)}</strong></div>
        </div>

        <div class="planner-list">
          ${priced
            .map(
              ({ adv, month, p }) => `
              <div class="planner-row">
                <div>
                  <div class="mono" style="font-size:0.76rem;color:var(--accent-pine);font-weight:600">
                    ${escapeHtml(month.monthLabel)} · ${escapeHtml(adv.window)} (${p.days}d / ${p.nights}n)
                  </div>
                  <div style="font-family:var(--font-serif);font-size:1.15rem;font-weight:500">${escapeHtml(adv.title)}</div>
                  <div style="font-size:0.82rem;color:var(--ink-secondary)">
                    Room: <strong>${escapeHtml(p.hotel.name)}</strong> (${escapeHtml(p.hotel.roomType)}, ${fmtUsd(p.hotel.nightlyRateUsd)}/nt)
                  </div>
                </div>
                <div style="display:flex;align-items:center;gap:12px">
                  <strong class="mono" style="font-size:1.1rem">${fmtUsd(p.totalUsd)}</strong>
                  <button type="button" class="btn btn-subtle btn-sm" data-plan-eval="${escapeHtml(adv.id)}">Edit</button>
                  <button type="button" class="text-btn" data-plan-remove="${escapeHtml(adv.id)}">Remove</button>
                </div>
              </div>
            `
            )
            .join("")}
        </div>

        <div class="planner-actions-bar">
          <div style="display:flex;flex-wrap:wrap;gap:10px">
            <button type="button" class="btn btn-primary" id="export-plan-ics">↓ Export All to Google Calendar (.ics)</button>
            <button type="button" class="btn btn-subtle" id="export-plan-md">↓ Download Markdown Dossier (.md)</button>
          </div>
          <button type="button" class="text-btn" id="clear-plan-btn">Clear Shortlist</button>
        </div>
      `;

      body.querySelectorAll("[data-plan-eval]").forEach((btn) => {
        btn.addEventListener("click", () => {
          modal.hidden = true;
          openEvaluator(btn.dataset.planEval);
        });
      });

      body.querySelectorAll("[data-plan-remove]").forEach((btn) => {
        btn.addEventListener("click", () => {
          toggleShortlist(btn.dataset.planRemove);
          openPlannerModal();
        });
      });

      document.getElementById("export-plan-ics").addEventListener("click", () => {
        downloadIcs(priced.map((x) => x.adv));
      });

      document.getElementById("export-plan-md").addEventListener("click", () => {
        downloadMarkdown(priced);
      });

      document.getElementById("clear-plan-btn").addEventListener("click", () => {
        state.shortlistIds = [];
        savePersisted();
        renderShortlistHeader();
        renderMonthRibbon();
        renderAdventures();
        openPlannerModal();
      });
    }

    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  // ---------- Antigravity Research Agents Modal ----------
  function openAgentsModal() {
    const modal = document.getElementById("agents-modal");
    const body = document.getElementById("agents-modal-body");
    const meta = state.dataset.meta;

    body.innerHTML = `
      <p style="margin-top:0;color:var(--ink-secondary)">
        This dossier was compiled by <strong>4 parallel Antigravity research subagents</strong> running live web searches across Nordic boutique lodges, DNT/STF/FÍ mountain hut networks, drysuit scuba operators, 4x4 winter/highland rental agencies, Hurtigruten/Havila/expedition cruises, and Seattle (SEA) flight routes — then validated and merged via <code>scripts/build_dataset.py</code>.
      </p>

      <div class="agent-card-grid">
        ${meta.researchAgents
          .map(
            (ag) => `
            <div class="agent-card">
              <h4>${escapeHtml(ag.id)} · ${escapeHtml(ag.scope)}</h4>
              <p>${escapeHtml(ag.focus)}</p>
              <div class="mono" style="margin-top:8px;font-size:0.74rem;color:var(--ink-muted)">Source: ${escapeHtml(ag.file)}</div>
            </div>
          `
          )
          .join("")}
      </div>

      <div class="booking-strategy" style="margin-bottom:0">
        <div><strong>Calendar Sync Source:</strong> ${escapeHtml(meta.calendarSource)}</div>
        <div><strong>Home Hub:</strong> ${escapeHtml(meta.homeAirport)}</div>
        <div><strong>Dataset Built:</strong> <span class="mono">${escapeHtml(meta.generatedAt)}</span></div>
        <div><strong>How to Refresh:</strong> Ask Antigravity to re-run any quarterly agent (e.g., <em>"Refresh Q4 hotel &amp; Havila solo cabin rates in adventure-advisor"</em>), rebuild with <code>python3 scripts/build_dataset.py</code>, and push to update GitHub Pages live.</div>
      </div>
    `;

    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  // ---------- Exports (.ics & Markdown) ----------
  function parseWindowStart(windowStr) {
    // Handles formats like "Dec 6–11, 2026" or "Jun 29–Jul 4, 2027"
    const m = windowStr.match(/([A-Z][a-z]{2})\s+(\d{1,2}).*?(\d{4})/);
    if (!m) return new Date(2027, 0, 15);
    const months = {
      Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
      Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
    };
    return new Date(Number(m[3]), months[m[1]] ?? 0, Number(m[2]));
  }

  function fmtIcsDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}${m}${day}`;
  }

  function downloadIcs(adventures) {
    const lines = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//Nordic Atlas//Antigravity Adventure Advisor//EN",
      "CALSCALE:GREGORIAN",
    ];

    for (const adv of adventures) {
      const p = calculatePricing(adv);
      const start = parseWindowStart(adv.window);
      const end = new Date(start);
      end.setDate(end.getDate() + p.days); // exclusive all-day end date

      const desc = [
        `Tentative Adventure (${fmtUsd(p.totalUsd)} est. solo)`,
        `Hotel: ${p.hotel.name} (${p.hotel.roomType}) - ${fmtUsd(p.hotel.nightlyRateUsd)}/nt`,
        `Flights: ${adv.flights.route} (${fmtUsd(p.flightsUsd)})`,
        `Vehicle: ${adv.vehicle.recommendedClass} (${fmtUsd(p.vehicleUsd)})`,
        `Target Book-By: ${adv.theoreticalBooking.targetBookBy}`,
      ].join("\\n");

      lines.push(
        "BEGIN:VEVENT",
        `UID:${adv.id}@nordic-atlas.github.io`,
        `DTSTART;VALUE=DATE:${fmtIcsDate(start)}`,
        `DTEND;VALUE=DATE:${fmtIcsDate(end)}`,
        `SUMMARY:[Tentative] ${adv.title}`,
        `LOCATION:${adv.region}, ${adv.country}`,
        `DESCRIPTION:${desc}`,
        "END:VEVENT"
      );
    }

    lines.push("END:VCALENDAR");
    triggerDownload(
      "nordic-atlas-adventures.ics",
      lines.join("\r\n"),
      "text/calendar;charset=utf-8"
    );
  }

  function downloadMarkdown(pricedItems) {
    const total = pricedItems.reduce((s, x) => s + x.p.totalUsd, 0);
    const lines = [
      "# 2026–2027 Nordic & Alpine Adventure Shortlist",
      "",
      `Generated from Nordic Atlas · Total Estimated Spend: **${fmtUsd(total)}**`,
      "",
    ];

    for (const { adv, month, p } of pricedItems) {
      lines.push(
        `## ${month.monthLabel} — ${adv.title}`,
        `- **Window:** ${adv.window} (${p.days}d / ${p.nights}n)`,
        `- **Region:** ${adv.region}, ${adv.country} (${adv.coordinates})`,
        `- **Selected Room:** ${p.hotel.name} — ${p.hotel.roomType} (${fmtUsd(p.hotel.nightlyRateUsd)}/nt · ${fmtUsd(p.lodgingUsd)} total)`,
        `- **Flights:** ${adv.flights.route} (${fmtUsd(p.flightsUsd)})`,
        `- **4x4 / Transport:** ${adv.vehicle.recommendedClass} (${fmtUsd(p.vehicleUsd)})`,
        `- **Activities:** ${fmtUsd(p.activitiesUsd)} | **Food & Buffer:** ${fmtUsd(p.foodUsd)}`,
        `- **Estimated Total:** **${fmtUsd(p.totalUsd)}** (${p.cfg.travelerMode === "split" ? "per person split" : "solo"})`,
        `- **Book-By:** ${adv.theoreticalBooking.targetBookBy}`,
        ""
      );
    }

    triggerDownload(
      "adventure-plan-2026-2027.md",
      lines.join("\n"),
      "text/markdown;charset=utf-8"
    );
  }

  function triggerDownload(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // ---------- Controls & Lifecycle ----------
  function resetFilters() {
    state.selectedMonth = "all";
    state.searchQuery = "";
    state.category = "all";
    state.region = "all";
    state.duration = "all";
    state.maxBudget = 12000;
    state.sortBy = "chronological";

    document.getElementById("search-input").value = "";
    document.getElementById("region-filter").value = "all";
    document.getElementById("duration-filter").value = "all";
    document.getElementById("sort-select").value = "chronological";
    document.getElementById("budget-slider").value = "12000";
    document.getElementById("budget-slider-val").textContent = "$12,000";
    document.querySelectorAll("#category-chips .chip").forEach((c) => {
      c.classList.toggle("active", c.dataset.category === "all");
    });

    renderAll();
  }

  function renderAll() {
    renderMonthRibbon();
    renderAdventures();
    renderCompareTray();
    renderShortlistHeader();
  }

  function bindGlobalUI() {
    document.getElementById("show-all-months-btn").addEventListener("click", () => {
      state.selectedMonth = "all";
      renderAll();
    });

    document.getElementById("hero-sweet-spot-btn").addEventListener("click", () => {
      state.maxBudget = 6000;
      document.getElementById("budget-slider").value = "6000";
      document.getElementById("budget-slider-val").textContent = "$6,000";
      renderAll();
      document.getElementById("expeditions-section").scrollIntoView({ behavior: "smooth" });
    });

    document.getElementById("search-input").addEventListener("input", (e) => {
      state.searchQuery = e.target.value;
      renderAdventures();
    });

    document.getElementById("region-filter").addEventListener("change", (e) => {
      state.region = e.target.value;
      renderAdventures();
    });

    document.getElementById("duration-filter").addEventListener("change", (e) => {
      state.duration = e.target.value;
      renderAdventures();
    });

    document.getElementById("sort-select").addEventListener("change", (e) => {
      state.sortBy = e.target.value;
      renderAdventures();
    });

    document.getElementById("budget-slider").addEventListener("input", (e) => {
      state.maxBudget = Number(e.target.value);
      document.getElementById("budget-slider-val").textContent = fmtUsd(state.maxBudget);
      renderAdventures();
    });

    document.getElementById("reset-filters-btn").addEventListener("click", resetFilters);

    document.querySelectorAll("#category-chips .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        state.category = chip.dataset.category;
        document.querySelectorAll("#category-chips .chip").forEach((c) => {
          c.classList.toggle("active", c === chip);
        });
        renderAdventures();
      });
    });

    // Modals
    document.getElementById("close-evaluator-btn").addEventListener("click", closeEvaluator);
    document.getElementById("evaluator-modal").addEventListener("click", (e) => {
      if (e.target.id === "evaluator-modal") closeEvaluator();
    });

    document.getElementById("open-compare-btn").addEventListener("click", openCompareModal);
    document.getElementById("clear-compare-btn").addEventListener("click", () => {
      state.compareIds = [];
      savePersisted();
      renderCompareTray();
      renderAdventures();
    });
    document.getElementById("close-compare-btn").addEventListener("click", () => {
      document.getElementById("compare-modal").hidden = true;
      document.body.style.overflow = "";
    });
    document.getElementById("compare-modal").addEventListener("click", (e) => {
      if (e.target.id === "compare-modal") {
        e.currentTarget.hidden = true;
        document.body.style.overflow = "";
      }
    });

    document.getElementById("open-planner-btn").addEventListener("click", openPlannerModal);
    document.getElementById("close-planner-btn").addEventListener("click", () => {
      document.getElementById("planner-modal").hidden = true;
      document.body.style.overflow = "";
    });
    document.getElementById("planner-modal").addEventListener("click", (e) => {
      if (e.target.id === "planner-modal") {
        e.currentTarget.hidden = true;
        document.body.style.overflow = "";
      }
    });

    document.getElementById("open-agents-btn").addEventListener("click", openAgentsModal);
    document.getElementById("footer-agents-btn").addEventListener("click", openAgentsModal);
    document.getElementById("close-agents-btn").addEventListener("click", () => {
      document.getElementById("agents-modal").hidden = true;
      document.body.style.overflow = "";
    });
    document.getElementById("agents-modal").addEventListener("click", (e) => {
      if (e.target.id === "agents-modal") {
        e.currentTarget.hidden = true;
        document.body.style.overflow = "";
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeEvaluator();
        document.getElementById("compare-modal").hidden = true;
        document.getElementById("planner-modal").hidden = true;
        document.getElementById("agents-modal").hidden = true;
        document.body.style.overflow = "";
      }
    });
  }

  async function init() {
    loadPersisted();
    bindGlobalUI();

    try {
      const res = await fetch("data/adventures.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.dataset = await res.json();
      renderHeaderStats();
      renderAll();
    } catch (err) {
      document.getElementById("adventures-container").innerHTML = `
        <div class="empty-state">
          <h3>Unable to load adventure dataset</h3>
          <p class="mono">${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
