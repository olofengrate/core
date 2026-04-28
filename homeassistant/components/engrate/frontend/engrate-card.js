/**
 * Engrate Card - Lovelace card showing the system operator name.
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
        .content {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .logo {
          max-width: 40px;
          max-height: 40px;
        }
        .name {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .label {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .error {
          color: var(--error-color, #db4437);
          justify-content: center;
        }
      </style>
      <ha-card header="${this._escapeHtml(this._config.title || "System Operator")}">
        <div class="content">
          ${logoHtml}
          <div>
            <div class="name">${this._escapeHtml(data.system_operator_name || "Unknown")}</div>
          </div>
        </div>
      </ha-card>
    `;
  }

  _escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  getCardSize() {
    return 2;
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
  name: "Engrate System Operator",
  description: "Displays the system operator for your Engrate tariff.",
});
