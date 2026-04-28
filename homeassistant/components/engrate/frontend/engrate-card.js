/**
 * Engrate Card - Lovelace card showing yearly energy costs.
 *
 * Usage in Lovelace:
 *   type: custom:engrate-card
 */

class EngrateCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loading && !this._loaded) {
      this._loading = true;
      this._loadData();
    }
  }

  async _loadData() {
    try {
      const entries = await this._hass.callWS({
        type: "config_entries/get",
        domain: "engrate",
      });

      if (!entries || entries.length === 0) {
        this._render({ error: "No Engrate integration configured." });
        return;
      }

      const result = await this._hass.callWS({
        type: "engrate/tariff_data",
        entry_id: entries[0].entry_id,
      });

      this._loaded = true;
      this._loading = false;
      this._render({ data: result });
    } catch (err) {
      this._loading = false;
      this._render({ error: "Failed to load data: " + err.message });
    }
  }

  _render({ data, error }) {
    if (error) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div class="content error">${this._escapeHtml(error)}</div>
        </ha-card>
      `;
      return;
    }

    const logoHtml = data.system_operator_logo_url
      ? `<img class="logo" src="${this._escapeHtml(data.system_operator_logo_url)}" alt="" />`
      : "";

    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 16px;
        }
        .header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
        }
        .logo {
          max-width: 32px;
          max-height: 32px;
        }
        .title {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .period {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-bottom: 12px;
        }
        .cost-row {
          display: flex;
          justify-content: space-between;
          padding: 6px 0;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .cost-row.total {
          font-weight: 600;
          border-bottom: none;
          padding-top: 8px;
        }
        .cost-label {
          font-size: 14px;
          color: var(--secondary-text-color);
        }
        .cost-value {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .last-updated {
          font-size: 11px;
          color: var(--secondary-text-color);
          text-align: right;
          margin-top: 8px;
        }
        .error {
          color: var(--error-color, #db4437);
          text-align: center;
          padding: 16px;
        }
      </style>
      <ha-card>
        <div class="header">
          ${logoHtml}
          <div class="title">${this._escapeHtml(this._config.title || "Engrate")}</div>
        </div>
        <div class="period">${this._formatPeriod(data.period_start, data.period_end)}</div>
        <div class="cost-row">
          <span class="cost-label">Grid cost</span>
          <span class="cost-value">${this._formatCost(data.grid_cost)}</span>
        </div>
        <div class="cost-row">
          <span class="cost-label">Energy cost</span>
          <span class="cost-value">${this._formatCost(data.energy_cost)}</span>
        </div>
        <div class="cost-row total">
          <span class="cost-label">Total cost</span>
          <span class="cost-value">${this._formatCost(data.total_cost)}</span>
        </div>
        ${data.last_calculated ? `<div class="last-updated">Last calculated: ${this._formatDate(data.last_calculated)}</div>` : ""}
      </ha-card>
    `;
  }

  _escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  _formatCost(value) {
    if (value == null) return "\u2014";
    return value.toFixed(2) + " SEK";
  }

  _formatDate(isoString) {
    if (!isoString) return "";
    const d = new Date(isoString);
    return d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  }

  _formatPeriod(startIso, endIso) {
    if (!startIso || !endIso) return "";
    const start = new Date(startIso);
    const end = new Date(endIso);
    const opts = {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    };
    return (
      start.toLocaleString(undefined, opts) +
      " \u2013 " +
      end.toLocaleString(undefined, opts)
    );
  }

  getCardSize() {
    return 3;
  }

  static getStubConfig() {
    return {};
  }
}

customElements.define("engrate-card", EngrateCard);

// Register with HA's custom card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "engrate-card",
  name: "Engrate Costs",
  description: "Displays yearly energy costs calculated by Engrate.",
});
