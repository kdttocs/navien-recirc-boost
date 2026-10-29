/*
 * Navien NaviLink Recirc Boost - weekly schedule card.
 *
 * A 7-day time grid: drag across a day (or several days at once) to paint
 * recirculation on or off, then Save. Only the days you changed are sent to
 * the heater, in one change, through navien_recirc_boost.set_week_schedule.
 *
 *   type: custom:navien-schedule-card
 *   entity: sensor.redland_recirc_boost_schedule   # optional, found automatically
 *   step: 30                                        # minutes per cell: 15, 30 or 60
 *   first_day: sunday                               # or monday
 *   title: Hot water schedule
 */
(() => {
  const DOMAIN = "navien_recirc_boost";
  const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  const SHORT = { sunday: "Sun", monday: "Mon", tuesday: "Tue", wednesday: "Wed", thursday: "Thu", friday: "Fri", saturday: "Sat" };
  const MAX_WINDOWS = 4;

  const pad = (n) => String(n).padStart(2, "0");

  function parseWindows(text) {
    const t = String(text || "").trim().toLowerCase();
    if (!t || t === "off" || t === "none" || t === "unknown") return [];
    const out = [];
    for (const part of t.split(/[,;]/)) {
      const m = part.trim().match(/^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$/);
      if (!m) continue;
      out.push([+m[1] * 60 + +m[2], +m[3] * 60 + +m[4]]);
    }
    return out;
  }

  function hm12(mins) {
    if (mins >= 1439) return "midnight";
    const h = Math.floor(mins / 60), m = mins % 60;
    const ap = h < 12 ? "am" : "pm";
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return m ? `${h12}:${pad(m)}${ap}` : `${h12}${ap}`;
  }

  class NavienScheduleCard extends HTMLElement {
    static getConfigForm() {
      return {
        schema: [
          { name: "entity", selector: { entity: { domain: "sensor", integration: DOMAIN } } },
          { name: "title", selector: { text: {} } },
          {
            type: "grid",
            name: "",
            schema: [
              { name: "step", selector: { select: { mode: "dropdown", options: [
                { value: "15", label: "15 minutes" }, { value: "30", label: "30 minutes" }, { value: "60", label: "1 hour" },
              ] } } },
              { name: "first_day", selector: { select: { mode: "dropdown", options: [
                { value: "sunday", label: "Sunday" }, { value: "monday", label: "Monday" },
              ] } } },
            ],
          },
        ],
        computeLabel: (s) => ({ entity: "Schedule sensor", title: "Title", step: "Grid step", first_day: "Week starts on" }[s.name]),
      };
    }

    static getStubConfig(hass) {
      const entity = NavienScheduleCard.findEntity(hass);
      return entity ? { entity } : {};
    }

    static findEntity(hass) {
      return Object.keys(hass.states).find((id) => {
        if (!id.startsWith("sensor.")) return false;
        const a = hass.states[id].attributes;
        return a && "schedule" in a && "monday" in a && "last_read" in a;
      });
    }

    setConfig(config) {
      const step = parseInt(config.step || 30, 10);
      if (![15, 30, 60].includes(step)) throw new Error("step must be 15, 30 or 60");
      this._config = { ...config, step };
      this._slots = (24 * 60) / step;
      this._draft = null;
      this._built = false;
      if (this._hass) this._sync(true);
    }

    set hass(hass) {
      this._hass = hass;
      this._sync(false);
    }

    getCardSize() { return 6; }
    getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

    // ----- entities -----
    get _entityId() {
      return this._config.entity || NavienScheduleCard.findEntity(this._hass);
    }

    _sibling(domain, suffix) {
      const ents = this._hass.entities || {};
      const me = ents[this._entityId];
      const ids = Object.keys(this._hass.states).filter((id) => id.startsWith(domain + "."));
      const same = me ? ids.filter((id) => ents[id] && ents[id].device_id === me.device_id) : [];
      return same.find((id) => id.endsWith(suffix)) || same[0] || ids.find((id) => id.endsWith(suffix) && id.includes("recirc_boost"));
    }

    // ----- data -----
    _fromState() {
      const st = this._hass.states[this._entityId];
      const res = {};
      for (const d of DAYS) {
        const cells = new Array(this._slots).fill(false);
        const windows = st ? parseWindows(st.attributes[d]) : [];
        for (const [a, b] of windows) {
          for (let i = 0; i < this._slots; i++) {
            const s = i * this._config.step, e = s + this._config.step;
            const overlap = Math.min(b, e) - Math.max(a, s);
            if (overlap * 2 >= this._config.step) cells[i] = true;
          }
        }
        res[d] = cells;
      }
      return res;
    }

    _windows(cells) {
      const out = [];
      let start = null;
      for (let i = 0; i <= cells.length; i++) {
        if (i < cells.length && cells[i]) { if (start === null) start = i; }
        else if (start !== null) {
          const a = start * this._config.step;
          const b = Math.min(i * this._config.step, 1439);
          out.push([a, b]);
          start = null;
        }
      }
      return out;
    }

    _text(cells) {
      const w = this._windows(cells);
      if (!w.length) return "off";
      return w.map(([a, b]) => `${pad(Math.floor(a / 60))}:${pad(a % 60)}-${pad(Math.floor(b / 60))}:${pad(b % 60)}`).join(", ");
    }

    _sync(force) {
      if (!this._config || !this._hass) return;
      const st = this._hass.states[this._entityId];
      const key = st ? JSON.stringify([DAYS.map((d) => st.attributes[d]), st.state]) : "missing";
      const sw = this._sibling("switch", "_weekly_schedule");
      const boost = this._sibling("binary_sensor", "_boost_running");
      const extra = JSON.stringify([sw && this._hass.states[sw]?.state, boost && this._hass.states[boost]?.state, st?.attributes.last_read]);
      if (!this._built) this._build();
      if (force || key !== this._key) {
        this._key = key;
        this._orig = this._fromState();
        if (force || !this._dirtyDays().length) this._draft = this._fromState();
        this._renderRows();
      }
      if (force || extra !== this._extra) {
        this._extra = extra;
        this._renderHeader();
      }
    }

    _dirtyDays() {
      if (!this._draft || !this._orig) return [];
      return DAYS.filter((d) => this._draft[d].some((v, i) => v !== this._orig[d][i]));
    }

    _order() {
      let first = this._config.first_day;
      if (!first) {
        const fw = this._hass?.locale?.first_weekday;
        first = DAYS.includes(fw) ? fw : "sunday";
      }
      const i = DAYS.indexOf(first);
      return [...DAYS.slice(i), ...DAYS.slice(0, i)];
    }

    // ----- rendering -----
    _build() {
      this._built = true;
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      const hours = [0, 3, 6, 9, 12, 15, 18, 21].map((h) =>
        `<span style="left:${(h / 24) * 100}%">${h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? h + "a" : h - 12 + "p"}</span>`).join("");
      root.innerHTML = `
        <style>
          ha-card { padding: 12px 16px 16px; }
          .top { display: flex; align-items: center; gap: 12px; }
          .title { flex: 1; font-size: 1.15em; font-weight: 500; }
          .toggle { display: flex; align-items: center; gap: 6px; font-size: .9em; color: var(--secondary-text-color); cursor: pointer; }
          .sub { font-size: .8em; color: var(--secondary-text-color); margin: 2px 0 10px; }
          .grid { display: grid; grid-template-columns: 38px 1fr; row-gap: 6px; touch-action: none; user-select: none; -webkit-user-select: none; }
          .hours { position: relative; height: 14px; font-size: .7em; color: var(--secondary-text-color); }
          .hours span { position: absolute; transform: translateX(-2px); }
          .day { font-size: .85em; align-self: center; color: var(--primary-text-color); }
          .day.dirty { font-weight: 700; color: var(--primary-color); }
          .track { display: grid; grid-template-columns: repeat(${this._slots}, 1fr); height: 26px; border-radius: 6px; overflow: hidden;
                   background: var(--secondary-background-color, #2224); cursor: crosshair; }
          .c { border-left: 1px solid var(--divider-color, #8883); }
          .c.h { border-left-color: var(--secondary-text-color, #888a); }
          .c:first-child { border-left: none; }
          .c.on { background: var(--state-water_heater-active-color, var(--accent-color, #ff9800)); }
          .c.p-on { background: var(--accent-color, #ff9800); opacity: .6; }
          .c.p-off { background: var(--secondary-background-color, #2224); outline: 1px dashed var(--secondary-text-color); outline-offset: -1px; }
          .win { grid-column: 2; font-size: .75em; color: var(--secondary-text-color); margin-top: -3px; min-height: 1em; }
          .win.bad { color: var(--error-color, #db4437); }
          .bar { display: flex; gap: 8px; align-items: center; margin-top: 12px; min-height: 36px; }
          .msg { flex: 1; font-size: .85em; color: var(--secondary-text-color); }
          .msg.err { color: var(--error-color, #db4437); }
          button { font: inherit; font-size: .9em; padding: 7px 16px; border-radius: 18px; border: 1px solid var(--divider-color); cursor: pointer;
                   background: transparent; color: var(--primary-text-color); }
          button.save { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
          button[disabled] { opacity: .45; cursor: default; }
          .hint { font-size: .75em; color: var(--secondary-text-color); margin-top: 8px; }
        </style>
        <ha-card>
          <div class="top">
            <div class="title"></div>
            <label class="toggle"><span class="tlabel">Schedule</span><ha-switch class="sw"></ha-switch></label>
          </div>
          <div class="sub"></div>
          <div class="grid"><div></div><div class="hours">${hours}</div><div class="rows" style="display:contents"></div></div>
          <div class="bar">
            <div class="msg"></div>
            <button class="discard" disabled>Discard</button>
            <button class="save" disabled>Save</button>
          </div>
          <div class="hint">Drag across a day to turn hot water on, drag over orange to turn it off. Drag down to cover several days.</div>
        </ha-card>`;
      this._rowsEl = root.querySelector(".rows");
      this._msg = root.querySelector(".msg");
      root.querySelector(".save").addEventListener("click", () => this._save());
      root.querySelector(".discard").addEventListener("click", () => {
        this._draft = this._fromState();
        this._setMsg("");
        this._renderRows();
      });
      root.querySelector(".sw").addEventListener("change", (ev) => this._toggle(ev.target.checked));
      const grid = root.querySelector(".grid");
      grid.addEventListener("pointerdown", (e) => this._down(e));
      grid.addEventListener("pointermove", (e) => this._move(e));
      grid.addEventListener("pointerup", (e) => this._up(e));
      grid.addEventListener("pointercancel", () => { this._drag = null; this._paint(); });
    }

    _renderHeader() {
      const root = this.shadowRoot;
      const st = this._hass.states[this._entityId];
      root.querySelector(".title").textContent = this._config.title || "Hot water schedule";
      const sw = this._sibling("switch", "_weekly_schedule");
      const swEl = root.querySelector(".sw");
      root.querySelector(".toggle").style.display = sw ? "" : "none";
      if (sw && this._hass.states[sw]) swEl.checked = this._hass.states[sw].state === "on";
      let sub = "";
      if (!st) sub = `Schedule sensor not found${this._config.entity ? ": " + this._config.entity : ""}.`;
      else if (st.attributes.last_read) {
        const t = new Date(st.attributes.last_read);
        sub = `Read from the heater ${t.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}`;
      } else sub = "Waiting for the heater's schedule...";
      if (sw && this._hass.states[sw]?.state === "off") sub += " · Schedule is off, so none of these run";
      root.querySelector(".sub").textContent = sub;
      this._updateButtons();
    }

    _renderRows() {
      if (!this._draft) return;
      const html = [];
      for (const d of this._order()) {
        const cells = this._draft[d].map((on, i) => {
          const hour = (i * this._config.step) % 60 === 0 && i > 0;
          return `<div class="c${hour ? " h" : ""}${on ? " on" : ""}" data-d="${d}" data-s="${i}"></div>`;
        }).join("");
        html.push(`<div class="day" data-day="${d}">${SHORT[d]}</div><div class="track" data-track="${d}">${cells}</div><div class="win" data-win="${d}"></div>`);
      }
      this._rowsEl.innerHTML = html.join("");
      this._updateLabels();
    }

    _updateLabels() {
      const dirty = this._dirtyDays();
      for (const d of DAYS) {
        // Untouched days show the heater's exact times; edited days show the grid.
        const st = this._hass.states[this._entityId];
        const w = dirty.includes(d) || !st ? this._windows(this._draft[d]) : parseWindows(st.attributes[d]);
        const el = this.shadowRoot.querySelector(`[data-win="${d}"]`);
        const day = this.shadowRoot.querySelector(`[data-day="${d}"]`);
        if (!el) continue;
        const text = w.length ? w.map(([a, b]) => `${hm12(a)}–${hm12(b)}`).join(", ") : "Off all day";
        el.textContent = w.length > MAX_WINDOWS ? `${text} · too many: the heater allows ${MAX_WINDOWS} a day` : text;
        el.classList.toggle("bad", w.length > MAX_WINDOWS);
        day.classList.toggle("dirty", dirty.includes(d));
      }
      this._updateButtons();
    }

    _updateButtons() {
      const root = this.shadowRoot;
      if (!root || !this._draft) return;
      const dirty = this._dirtyDays();
      const bad = DAYS.some((d) => this._windows(this._draft[d]).length > MAX_WINDOWS);
      const boost = this._sibling("binary_sensor", "_boost_running");
      const boosting = boost && this._hass.states[boost]?.state === "on";
      root.querySelector(".save").disabled = !dirty.length || bad || boosting || this._saving;
      root.querySelector(".discard").disabled = !dirty.length || this._saving;
      if (!this._saving && !this._msgSticky) {
        if (boosting) this._setMsg("A boost is running. Save after it finishes.");
        else if (dirty.length) this._setMsg(`${dirty.length} day${dirty.length > 1 ? "s" : ""} changed, not saved yet`);
        else this._setMsg("");
      }
    }

    _setMsg(text, err = false, sticky = false) {
      this._msg.textContent = text;
      this._msg.classList.toggle("err", err);
      this._msgSticky = sticky;
    }

    // ----- painting -----
    _cellAt(e) {
      const el = this.shadowRoot.elementFromPoint(e.clientX, e.clientY);
      if (!el || !el.dataset || el.dataset.s === undefined) return null;
      return { d: el.dataset.d, s: +el.dataset.s };
    }

    _down(e) {
      const c = this._cellAt(e);
      if (!c || this._saving) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      this._msgSticky = false;
      this._drag = { start: c, end: c, value: !this._draft[c.d][c.s] };
      this._paint();
    }

    _move(e) {
      if (!this._drag) return;
      const c = this._cellAt(e);
      if (c && (c.d !== this._drag.end.d || c.s !== this._drag.end.s)) {
        this._drag.end = c;
        this._paint();
      }
    }

    _up() {
      if (!this._drag) return;
      const { days, a, b, value } = this._rect();
      for (const d of days) for (let i = a; i <= b; i++) this._draft[d][i] = value;
      this._drag = null;
      this._paint();
      this._updateLabels();
    }

    _rect() {
      const order = this._order();
      const i1 = order.indexOf(this._drag.start.d), i2 = order.indexOf(this._drag.end.d);
      return {
        days: order.slice(Math.min(i1, i2), Math.max(i1, i2) + 1),
        a: Math.min(this._drag.start.s, this._drag.end.s),
        b: Math.max(this._drag.start.s, this._drag.end.s),
        value: this._drag.value,
      };
    }

    _paint() {
      const r = this._drag ? this._rect() : null;
      for (const el of this.shadowRoot.querySelectorAll(".c")) {
        const d = el.dataset.d, s = +el.dataset.s;
        const inside = r && r.days.includes(d) && s >= r.a && s <= r.b;
        el.classList.toggle("on", !inside && this._draft[d][s]);
        el.classList.toggle("p-on", !!inside && r.value);
        el.classList.toggle("p-off", !!inside && !r.value);
      }
    }

    // ----- actions -----
    async _save() {
      const dirty = this._dirtyDays();
      if (!dirty.length) return;
      const data = {};
      for (const d of dirty) data[d] = this._text(this._draft[d]);
      this._saving = true;
      this._setMsg("Sending to the heater...");
      this._updateButtons();
      try {
        await this._hass.callService(DOMAIN, "set_week_schedule", data);
        // The heater's answer arrives as a state update and becomes the new baseline.
        this._orig = Object.fromEntries(DAYS.map((d) => [d, [...this._draft[d]]]));
        this._saving = false;
        this._updateLabels();
        this._setMsg("Saved to the heater", false, true);
      } catch (err) {
        this._saving = false;
        this._setMsg(`Not saved: ${err && err.message ? err.message : err}`, true, true);
        this._updateButtons();
      }
    }

    async _toggle(on) {
      const sw = this._sibling("switch", "_weekly_schedule");
      if (!sw) return;
      try {
        await this._hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: sw });
      } catch (err) {
        this._setMsg(`Could not change the schedule: ${err && err.message ? err.message : err}`, true, true);
        this._extra = null;
        this._renderHeader();
      }
    }
  }

  if (!customElements.get("navien-schedule-card")) {
    customElements.define("navien-schedule-card", NavienScheduleCard);
    window.customCards = window.customCards || [];
    window.customCards.push({
      type: "navien-schedule-card",
      name: "Navien hot water schedule",
      description: "Drag to set the Navien recirculation schedule for each day.",
      preview: false,
      documentationURL: "https://github.com/kdttocs/navien-recirc-boost",
    });
  }
})();
