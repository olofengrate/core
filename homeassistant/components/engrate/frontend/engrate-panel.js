/**
 * Engrate Panel - Sidebar page showing tariff and system operator information.
 *
 * This is a plain web component (no build step required).
 * It connects to the Home Assistant websocket API to fetch tariff data.
 */

class EngratePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._loadData();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  async _loadData() {
    const entries = await this._hass.callWS({
      type: "config_entries/get",
      domain: "engrate",
    });

    if (!entries || entries.length === 0) {
      this._renderError("No Engrate integration configured.");
      return;
    }

    try {
      const result = await this._hass.callWS({
        type: "engrate/tariff_data",
        entry_id: entries[0].entry_id,
      });
      this._renderData(result);
    } catch (err) {
      this._renderError("Failed to load tariff data: " + err.message);
    }
  }

  _renderData(data) {
    const logoHtml = data.system_operator_logo_url
      ? `<img class="logo" src="${this._escapeHtml(data.system_operator_logo_url)}" alt="${this._escapeHtml(data.system_operator_name || "")}" />`
      : "";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 24px;
          font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
          color: var(--primary-text-color, #212121);
          background: var(--primary-background-color, #fafafa);
          min-height: 100vh;
        }
        .container {
          max-width: 600px;
          margin: 0 auto;
        }
        h1 {
          font-size: 24px;
          font-weight: 400;
          margin-bottom: 24px;
          color: var(--primary-text-color);
        }
        .card {
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          padding: 24px;
          box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
          margin-bottom: 16px;
        }
        .card h2 {
          font-size: 18px;
          font-weight: 500;
          margin: 0 0 8px 0;
        }
        .card p {
          margin: 4px 0;
          color: var(--secondary-text-color, #727272);
          line-height: 1.5;
        }
        .logo {
          max-width: 120px;
          max-height: 60px;
          margin-bottom: 12px;
        }
        .label {
          font-size: 12px;
          text-transform: uppercase;
          font-weight: 500;
          letter-spacing: 0.5px;
          color: var(--secondary-text-color, #727272);
          margin-bottom: 4px;
        }
        .value {
          font-size: 16px;
          margin-bottom: 16px;
        }
        .header {
          text-align: center;
          margin-bottom: 24px;
        }
        .engrate-logo {
          height: 48px;
        }
        .toggle-btn {
          background: var(--primary-color, #03a9f4);
          color: #fff;
          border: none;
          border-radius: 4px;
          padding: 8px 16px;
          cursor: pointer;
          font-size: 14px;
          margin-top: 8px;
        }
        .toggle-btn:hover {
          opacity: 0.85;
        }
        .json-block {
          background: var(--secondary-background-color, #f5f5f5);
          border-radius: 8px;
          padding: 16px;
          margin-top: 12px;
          overflow-x: auto;
          font-size: 12px;
          line-height: 1.4;
          white-space: pre-wrap;
          word-break: break-word;
          color: var(--primary-text-color, #212121);
        }
      </style>
      <div class="container">
        <div class="header">
          <img class="engrate-logo" src="https://engrate.io/app/themes/engrateio/assets/img/engrate-logo.svg" alt="Engrate" />
        </div>
        <div class="card">
          <div class="label">System Operator</div>
          ${logoHtml}
          <div class="value">${this._escapeHtml(data.system_operator_name || "Unknown")}</div>
          ${data.system_operator_description ? `<p>${this._escapeHtml(data.system_operator_description)}</p>` : ""}
        </div>
        <div class="card">
          <div class="label">Tariff</div>
          <div class="value">${this._escapeHtml(data.tariff_name)}</div>
          ${data.tariff_summary ? `<p>${this._escapeHtml(data.tariff_summary)}</p>` : ""}
          ${data.tariff_annotations ? `<p><em>${this._escapeHtml(data.tariff_annotations)}</em></p>` : ""}
          <button class="toggle-btn" id="toggle-json">Show tariff JSON</button>
          <pre class="json-block" id="tariff-json" style="display:none">${this._escapeHtml(JSON.stringify(data.tariff_raw, null, 2))}</pre>
        </div>
      </div>
    `;

    this.shadowRoot
      .getElementById("toggle-json")
      .addEventListener("click", () => {
        const pre = this.shadowRoot.getElementById("tariff-json");
        const btn = this.shadowRoot.getElementById("toggle-json");
        if (pre.style.display === "none") {
          pre.style.display = "block";
          btn.textContent = "Hide tariff JSON";
        } else {
          pre.style.display = "none";
          btn.textContent = "Show tariff JSON";
        }
      });
  }

  _renderError(message) {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 24px;
          font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
          color: var(--primary-text-color, #212121);
          background: var(--primary-background-color, #fafafa);
          min-height: 100vh;
        }
        .error {
          max-width: 600px;
          margin: 48px auto;
          padding: 24px;
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
          text-align: center;
          color: var(--error-color, #db4437);
        }
      </style>
      <div class="error">${this._escapeHtml(message)}</div>
    `;
  }

  _escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

customElements.define("engrate-panel", EngratePanel);
