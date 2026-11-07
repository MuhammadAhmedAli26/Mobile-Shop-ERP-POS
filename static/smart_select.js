/**
 * MOBILE & ACCESSORIES ERP — SmartSelect Combobox & QuickAdd Registry
 * Upgrades standard <select> elements into fast searchable comboboxes
 * with pinned "+ Add new" options, inline admin renaming, and instantaneous (<100ms) modals.
 */

(function () {
  const instances = new Map();

  class SmartSelect {
    constructor(selectEl) {
      this.select = selectEl;
      this.listKey = selectEl.getAttribute("data-list-key") || "";
      this.entityName = selectEl.getAttribute("data-entity-name") || selectEl.getAttribute("data-list-key") || "Option";
      this.quickAddType = selectEl.getAttribute("data-quickadd") || (this.listKey ? "lookup" : "");
      this.allowRename = selectEl.getAttribute("data-allow-rename") === "true";
      this.isOpen = false;
      this.highlightIndex = -1;
      this.options = [];

      this.initUI();
      this.syncFromSelect();
      instances.set(selectEl, this);
    }

    initUI() {
      // Hide original select
      this.select.style.display = "none";
      this.select.setAttribute("tabindex", "-1");

      // Wrapper
      this.wrapper = document.createElement("div");
      this.wrapper.className = "smart-select-wrapper";
      if (this.select.className) {
        this.wrapper.className += " " + this.select.className.replace("smart-select", "").trim();
      }

      // Control box
      this.control = document.createElement("div");
      this.control.className = "smart-select-control";
      this.control.setAttribute("tabindex", "0");

      this.input = document.createElement("input");
      this.input.type = "text";
      this.input.className = "smart-select-input";
      this.input.placeholder = this.select.getAttribute("placeholder") || `Select or type to search ${this.entityName}...`;
      this.input.autocomplete = "off";

      this.arrow = document.createElement("span");
      this.arrow.className = "smart-select-arrow";
      this.arrow.innerHTML = "▼";

      this.control.appendChild(this.input);
      this.control.appendChild(this.arrow);

      // Dropdown
      this.dropdown = document.createElement("div");
      this.dropdown.className = "smart-select-dropdown";

      this.listEl = document.createElement("ul");
      this.listEl.className = "smart-select-list";

      this.addRow = document.createElement("div");
      this.addRow.className = "smart-select-add-row";
      this.addRow.innerHTML = `<span>➕</span> <span>+ Add new ${this.entityName}</span>`;

      this.dropdown.appendChild(this.listEl);
      if (this.quickAddType) {
        this.dropdown.appendChild(this.addRow);
      }

      this.wrapper.appendChild(this.control);
      this.wrapper.appendChild(this.dropdown);

      // Insert wrapper after select
      this.select.parentNode.insertBefore(this.wrapper, this.select.nextSibling);

      this.bindEvents();
    }

    syncFromSelect() {
      this.options = [];
      let selectedText = "";
      for (let i = 0; i < this.select.options.length; i++) {
        const opt = this.select.options[i];
        const val = opt.value;
        const text = opt.text;
        const id = opt.getAttribute("data-id") || val;
        this.options.push({ value: val, text: text, id: id, selected: opt.selected });
        if (opt.selected && val !== "") {
          selectedText = text;
        }
      }
      this.input.value = selectedText;
      this.renderOptions(this.options);
    }

    renderOptions(filtered) {
      this.listEl.innerHTML = "";
      this.highlightIndex = -1;

      if (filtered.length === 0) {
        const emptyLi = document.createElement("li");
        emptyLi.className = "smart-select-option";
        emptyLi.style.color = "#94a3b8";
        emptyLi.style.cursor = "default";
        emptyLi.innerText = `No matching ${this.entityName} found`;
        this.listEl.appendChild(emptyLi);
      } else {
        filtered.forEach((opt, idx) => {
          const li = document.createElement("li");
          li.className = "smart-select-option";
          if (opt.selected) li.classList.add("selected");
          li.setAttribute("data-value", opt.value);
          li.setAttribute("data-index", idx);

          const span = document.createElement("span");
          span.innerText = opt.text;
          li.appendChild(span);

          // Admin rename icon
          if (this.allowRename && opt.value !== "") {
            const editBtn = document.createElement("button");
            editBtn.type = "button";
            editBtn.className = "smart-select-edit-btn";
            editBtn.title = `Rename ${opt.text}`;
            editBtn.innerText = "✎";
            editBtn.onclick = (e) => {
              e.stopPropagation();
              this.handleRename(opt);
            };
            li.appendChild(editBtn);
          }

          li.onclick = () => {
            this.selectValue(opt.value, opt.text);
            this.close();
          };

          this.listEl.appendChild(li);
        });
      }

      // Update pinned add row text
      const typed = this.input.value.trim();
      if (this.addRow) {
        if (typed && !filtered.some(o => o.text.toLowerCase() === typed.toLowerCase())) {
          this.addRow.innerHTML = `<span>➕</span> <span>+ Add "<strong>${escapeHtml(typed)}</strong>" as new ${this.entityName}</span>`;
        } else {
          this.addRow.innerHTML = `<span>➕</span> <span>+ Add new ${this.entityName}...</span>`;
        }
      }
    }

    filter(query) {
      const q = (typeof window !== 'undefined' && window.normText) ? window.normText(query) : query.toLowerCase().trim();
      if (!q) {
        this.renderOptions(this.options);
        return;
      }
      const matched = this.options.filter(o => {
        const txt = (typeof window !== 'undefined' && window.normText) ? window.normText(o.text) : o.text.toLowerCase();
        return txt.includes(q);
      });
      matched.sort((a, b) => {
        const aTxt = (typeof window !== 'undefined' && window.normText) ? window.normText(a.text) : a.text.toLowerCase();
        const bTxt = (typeof window !== 'undefined' && window.normText) ? window.normText(b.text) : b.text.toLowerCase();
        const aStarts = aTxt.startsWith(q) ? 0 : (aTxt.includes(' ' + q) ? 1 : 2);
        const bStarts = bTxt.startsWith(q) ? 0 : (bTxt.includes(' ' + q) ? 1 : 2);
        return aStarts - bStarts;
      });
      this.renderOptions(matched);
    }

    open() {
      // Close other open smart selects
      document.querySelectorAll(".smart-select-wrapper.open").forEach(w => {
        if (w !== this.wrapper) w.classList.remove("open");
      });
      this.isOpen = true;
      this.wrapper.classList.add("open");
      this.input.select();
      this.filter(this.input.value);
    }

    close() {
      this.isOpen = false;
      this.wrapper.classList.remove("open");
      // Restore selected text if input was left dirty without selection
      const selOpt = this.options.find(o => o.value === this.select.value);
      this.input.value = selOpt ? selOpt.text : "";
    }

    selectValue(val, text) {
      this.select.value = val;
      this.input.value = text;
      this.options.forEach(o => o.selected = (o.value === val));
      
      // Fire native change event
      const event = new Event("change", { bubbles: true });
      this.select.dispatchEvent(event);

      // Fire custom event
      const cEvent = new CustomEvent("smart-select:change", { detail: { value: val, text: text } });
      this.select.dispatchEvent(cEvent);
    }

    handleRename(opt) {
      const newName = prompt(`Rename "${opt.text}" to:`, opt.text);
      if (newName && newName.trim() && newName.trim() !== opt.text) {
        fetch("/api/lookups/rename", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: opt.id, label: newName.trim() })
        })
          .then(r => r.json())
          .then(data => {
            if (data.success) {
              window.QuickAdd.broadcastAdded(this.listKey, { id: opt.id, label: newName.trim() }, true);
            } else {
              alert(data.error || "Failed to rename option");
            }
          });
      }
    }

    bindEvents() {
      this.control.onclick = (e) => {
        if (e.target === this.input) {
          if (!this.isOpen) this.open();
        } else {
          this.isOpen ? this.close() : this.open();
        }
      };

      this.input.onfocus = () => {
        if (!this.isOpen) this.open();
      };

      this.input.oninput = () => {
        if (!this.isOpen) this.open();
        this.filter(this.input.value);
      };

      if (this.addRow) {
        this.addRow.onclick = () => {
          const typed = this.input.value.trim();
          this.close();
          window.QuickAdd.open(this.quickAddType, {
            listKey: this.listKey,
            entityName: this.entityName,
            initialValue: typed,
            triggerSelect: this.select
          });
        };
      }

      // Keyboard navigation
      this.control.onkeydown = (e) => {
        if (!this.isOpen) {
          if (e.key === "ArrowDown" || e.key === "Enter") {
            e.preventDefault();
            this.open();
          }
          return;
        }

        const items = this.listEl.querySelectorAll(".smart-select-option:not([style*='cursor: default'])");
        const totalItems = items.length + (this.addRow ? 1 : 0);

        if (e.key === "ArrowDown") {
          e.preventDefault();
          this.highlightIndex = (this.highlightIndex + 1) % totalItems;
          this.updateHighlight(items);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          this.highlightIndex = (this.highlightIndex - 1 + totalItems) % totalItems;
          this.updateHighlight(items);
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (this.highlightIndex >= 0 && this.highlightIndex < items.length) {
            items[this.highlightIndex].click();
          } else if (this.addRow && (this.highlightIndex === items.length || items.length === 0)) {
            this.addRow.click();
          } else if (items.length > 0) {
            items[0].click();
          } else if (this.addRow) {
            this.addRow.click();
          }
        } else if (e.key === "Escape") {
          this.close();
        } else if (e.key === "Tab") {
          this.close();
        }
      };

      // Close when clicking outside
      document.addEventListener("click", (e) => {
        if (!this.wrapper.contains(e.target)) {
          if (this.isOpen) this.close();
        }
      });
    }

    updateHighlight(items) {
      items.forEach(it => it.classList.remove("highlighted"));
      if (this.addRow) this.addRow.classList.remove("highlighted");

      if (this.highlightIndex >= 0 && this.highlightIndex < items.length) {
        items[this.highlightIndex].classList.add("highlighted");
        items[this.highlightIndex].scrollIntoView({ block: "nearest" });
      } else if (this.addRow && this.highlightIndex === items.length) {
        this.addRow.classList.add("highlighted");
        this.addRow.scrollIntoView({ block: "nearest" });
      }
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.innerText = text;
    return div.innerHTML;
  }

  // GLOBAL QUICKADD REGISTRY
  window.QuickAdd = {
    open(type, context) {
      if (type === "lookup") {
        this.openLookupModal(context);
      } else if (type === "supplier") {
        this.openSupplierModal(context);
      } else if (type === "customer") {
        this.openCustomerModal(context);
      } else if (type === "expense_category") {
        this.openExpenseCategoryModal(context);
      } else if (type === "product_model") {
        this.openProductModelModal(context);
      } else {
        // Fallback to lookup
        this.openLookupModal(context);
      }
    },

    // Broadcast newly added item to all dropdowns sharing the listKey / entity
    broadcastAdded(key, item, isRename = false) {
      document.querySelectorAll(`select[data-list-key="${key}"]`).forEach(sel => {
        let optFound = false;
        for (let i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value == item.label || sel.options[i].value == item.id) {
            if (isRename) sel.options[i].text = item.label;
            optFound = true;
            break;
          }
        }
        if (!optFound && !isRename) {
          const newOpt = document.createElement("option");
          newOpt.value = item.label;
          newOpt.text = item.label;
          newOpt.setAttribute("data-id", item.id);
          sel.appendChild(newOpt);
        }
        const inst = instances.get(sel);
        if (inst) inst.syncFromSelect();
      });

      // Dispatch global event
      window.dispatchEvent(new CustomEvent("smartselect:item-added", { detail: { key, item } }));
    },

    openLookupModal({ listKey, entityName, initialValue, triggerSelect }) {
      const modal = createModalShell(`Add New ${entityName}`);
      const body = modal.querySelector(".quickadd-modal-body");

      body.innerHTML = `
        <div id="qa-dup-warning" style="display:none;" class="quickadd-duplicate-alert">
          <span>⚠️ Item already exists!</span>
          <button type="button" id="qa-use-existing-btn" class="quickadd-btn quickadd-btn-primary" style="padding:4px 10px;font-size:12px;">Use Existing</button>
        </div>
        <div class="quickadd-field">
          <label>${entityName} Name *</label>
          <input type="text" id="qa-lookup-name" value="${escapeHtml(initialValue || '')}" required autofocus />
        </div>
      `;

      const input = body.querySelector("#qa-lookup-name");
      const footer = modal.querySelector(".quickadd-modal-footer");
      footer.innerHTML = `
        <button type="button" class="quickadd-btn quickadd-btn-secondary" onclick="window.QuickAdd.closeModal()">Cancel (Esc)</button>
        <button type="button" id="qa-save-btn" class="quickadd-btn quickadd-btn-primary">Save ${entityName} (Enter)</button>
      `;

      let existingItem = null;

      const save = async () => {
        const val = input.value.trim();
        if (!val) {
          input.focus();
          return;
        }

        const resp = await fetch("/api/lookups/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ list_key: listKey, label: val })
        });
        const data = await resp.json();

        if (data.success) {
          if (data.already_exists) {
            existingItem = data.item;
            const warn = body.querySelector("#qa-dup-warning");
            warn.style.display = "flex";
            body.querySelector("#qa-use-existing-btn").onclick = () => {
              applySelection(data.item);
            };
          } else {
            applySelection(data.item);
          }
        } else {
          alert(data.error || "Failed to add lookup item");
        }
      };

      const applySelection = (item) => {
        this.broadcastAdded(listKey, item);
        if (triggerSelect) {
          triggerSelect.value = item.label;
          const inst = instances.get(triggerSelect);
          if (inst) {
            inst.selectValue(item.label, item.label);
          }
          // Move focus to next input
          focusNextField(triggerSelect);
        }
        this.closeModal();
      };

      footer.querySelector("#qa-save-btn").onclick = save;
      input.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          save();
        }
      };

      setTimeout(() => input.focus(), 60);
    },

    openSupplierModal({ initialValue, triggerSelect }) {
      const modal = createModalShell("Quick Add Supplier");
      const body = modal.querySelector(".quickadd-modal-body");

      body.innerHTML = `
        <div class="quickadd-field">
          <label>Supplier / Vendor Name *</label>
          <input type="text" id="qa-sup-name" value="${escapeHtml(initialValue || '')}" required autofocus />
        </div>
        <div class="quickadd-field">
          <label>Phone Number *</label>
          <input type="text" id="qa-sup-phone" placeholder="03001234567" required />
        </div>
        <div class="quickadd-field">
          <label>Company / Market</label>
          <input type="text" id="qa-sup-company" placeholder="e.g. Hall Road / Hafeez Center" />
        </div>
        <div class="quickadd-field">
          <label>Shop Address</label>
          <input type="text" id="qa-sup-address" placeholder="Shop #, Plaza name" />
        </div>
      `;

      const footer = modal.querySelector(".quickadd-modal-footer");
      footer.innerHTML = `
        <button type="button" class="quickadd-btn quickadd-btn-secondary" onclick="window.QuickAdd.closeModal()">Cancel</button>
        <button type="button" id="qa-sup-save" class="quickadd-btn quickadd-btn-primary">Save Supplier</button>
      `;

      const nameInp = body.querySelector("#qa-sup-name");
      const phoneInp = body.querySelector("#qa-sup-phone");

      const save = async () => {
        const name = nameInp.value.trim();
        const phone = phoneInp.value.trim();
        if (!name) { nameInp.focus(); return; }
        if (!phone) { phoneInp.focus(); return; }

        const resp = await fetch("/api/suppliers/quick-add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name,
            phone: phone,
            company: body.querySelector("#qa-sup-company").value.trim(),
            address: body.querySelector("#qa-sup-address").value.trim()
          })
        });
        const data = await resp.json();

        if (data.success) {
          const sup = data.supplier;
          // Update all supplier selects
          document.querySelectorAll('select[data-quickadd="supplier"], select[name="supplier_id"]').forEach(sel => {
            const opt = document.createElement("option");
            opt.value = sup.id;
            opt.text = `${sup.name} (${sup.phone}) - Bal: Rs. 0`;
            sel.appendChild(opt);
            const inst = instances.get(sel);
            if (inst) inst.syncFromSelect();
          });

          if (triggerSelect) {
            triggerSelect.value = sup.id;
            const inst = instances.get(triggerSelect);
            if (inst) inst.selectValue(sup.id, `${sup.name} (${sup.phone})`);
            focusNextField(triggerSelect);
          }
          this.closeModal();
        } else {
          alert(data.error || "Failed to create supplier");
        }
      };

      footer.querySelector("#qa-sup-save").onclick = save;
      modal.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          save();
        }
      };
      setTimeout(() => nameInp.focus(), 60);
    },

    openCustomerModal({ initialValue, triggerSelect }) {
      const modal = createModalShell("Quick Add Customer");
      const body = modal.querySelector(".quickadd-modal-body");

      body.innerHTML = `
        <div class="quickadd-field">
          <label>Customer Name *</label>
          <input type="text" id="qa-cust-name" value="${escapeHtml(initialValue || '')}" required autofocus />
        </div>
        <div class="quickadd-field">
          <label>Mobile Number *</label>
          <input type="text" id="qa-cust-phone" placeholder="03001234567" required />
        </div>
        <div class="quickadd-field">
          <label>CNIC (For Phone/Repair/Udhaar)</label>
          <input type="text" id="qa-cust-cnic" placeholder="35201-xxxxxxx-x" />
        </div>
        <div class="quickadd-field">
          <label>Customer Type</label>
          <select id="qa-cust-type">
            <option value="Walk-in / Retail">Walk-in / Retail</option>
            <option value="Regular Customer">Regular Customer</option>
            <option value="Wholesale / Dealer">Wholesale / Dealer</option>
          </select>
        </div>
      `;

      const footer = modal.querySelector(".quickadd-modal-footer");
      footer.innerHTML = `
        <button type="button" class="quickadd-btn quickadd-btn-secondary" onclick="window.QuickAdd.closeModal()">Cancel</button>
        <button type="button" id="qa-cust-save" class="quickadd-btn quickadd-btn-primary">Save Customer</button>
      `;

      const nameInp = body.querySelector("#qa-cust-name");
      const phoneInp = body.querySelector("#qa-cust-phone");

      const save = async () => {
        const name = nameInp.value.trim();
        const phone = phoneInp.value.trim();
        if (!name) { nameInp.focus(); return; }
        if (!phone) { phoneInp.focus(); return; }

        const resp = await fetch("/api/customers/quick-add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name,
            phone: phone,
            cnic: body.querySelector("#qa-cust-cnic").value.trim(),
            customer_type: body.querySelector("#qa-cust-type").value
          })
        });
        const data = await resp.json();

        if (data.success) {
          const cust = data.customer;
          if (window.posSetCustomer) {
            window.posSetCustomer(cust);
          }
          if (triggerSelect) {
            const opt = document.createElement("option");
            opt.value = cust.id;
            opt.text = `${cust.name} (${cust.phone})`;
            triggerSelect.appendChild(opt);
            triggerSelect.value = cust.id;
            const inst = instances.get(triggerSelect);
            if (inst) inst.selectValue(cust.id, opt.text);
            focusNextField(triggerSelect);
          }
          this.closeModal();
        } else {
          alert(data.error || "Failed to create customer");
        }
      };

      footer.querySelector("#qa-cust-save").onclick = save;
      modal.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          save();
        }
      };
      setTimeout(() => nameInp.focus(), 60);
    },

    openExpenseCategoryModal({ initialValue, triggerSelect }) {
      const modal = createModalShell("New Expense Category");
      const body = modal.querySelector(".quickadd-modal-body");

      body.innerHTML = `
        <div class="quickadd-field">
          <label>Category Name *</label>
          <input type="text" id="qa-exp-cat" value="${escapeHtml(initialValue || '')}" required autofocus />
        </div>
        <div style="margin-top:10px;">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;text-transform:none;">
            <input type="checkbox" id="qa-exp-save-list" checked style="width:auto;margin:0;" />
            Also save permanently to Expense Categories list
          </label>
        </div>
      `;

      const footer = modal.querySelector(".quickadd-modal-footer");
      footer.innerHTML = `
        <button type="button" class="quickadd-btn quickadd-btn-secondary" onclick="window.QuickAdd.closeModal()">Cancel</button>
        <button type="button" id="qa-exp-save" class="quickadd-btn quickadd-btn-primary">Apply Category</button>
      `;

      const catInp = body.querySelector("#qa-exp-cat");
      const saveListChk = body.querySelector("#qa-exp-save-list");

      const save = async () => {
        const cat = catInp.value.trim();
        if (!cat) { catInp.focus(); return; }

        if (saveListChk.checked) {
          await fetch("/api/lookups/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ list_key: "expense_category", label: cat })
          });
          this.broadcastAdded("expense_category", { id: Date.now(), label: cat });
        }

        if (triggerSelect) {
          let found = false;
          for (let i = 0; i < triggerSelect.options.length; i++) {
            if (triggerSelect.options[i].value === cat) {
              found = true;
              break;
            }
          }
          if (!found) {
            const opt = document.createElement("option");
            opt.value = cat;
            opt.text = cat;
            triggerSelect.appendChild(opt);
          }
          triggerSelect.value = cat;
          const inst = instances.get(triggerSelect);
          if (inst) inst.selectValue(cat, cat);
          focusNextField(triggerSelect);
        }
        this.closeModal();
      };

      footer.querySelector("#qa-exp-save").onclick = save;
      modal.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          save();
        }
      };
      setTimeout(() => catInp.focus(), 60);
    },

    openProductModelModal({ initialValue, triggerSelect }) {
      const modal = createModalShell("Quick Add Device / Model");
      const body = modal.querySelector(".quickadd-modal-body");

      body.innerHTML = `
        <div class="quickadd-field">
          <label>Brand *</label>
          <select id="qa-model-brand" class="smart-select" data-list-key="brand">
            <option value="Apple">Apple</option>
            <option value="Samsung">Samsung</option>
            <option value="Xiaomi">Xiaomi</option>
            <option value="Vivo">Vivo</option>
            <option value="Oppo">Oppo</option>
            <option value="Infinix">Infinix</option>
            <option value="Tecno">Tecno</option>
          </select>
        </div>
        <div class="quickadd-field">
          <label>Model Name *</label>
          <input type="text" id="qa-model-name" value="${escapeHtml(initialValue || '')}" placeholder="e.g. Galaxy A15, iPhone 13" required autofocus />
        </div>
        <div class="quickadd-field">
          <label>Item Type</label>
          <select id="qa-model-type">
            <option value="PHONE">Phone / Tablet (IMEI Tracked)</option>
            <option value="ACCESSORY">Accessory (Quantity)</option>
            <option value="SPARE_PART">Spare Part (Repair Stock)</option>
          </select>
        </div>
      `;

      const footer = modal.querySelector(".quickadd-modal-footer");
      footer.innerHTML = `
        <button type="button" class="quickadd-btn quickadd-btn-secondary" onclick="window.QuickAdd.closeModal()">Cancel</button>
        <button type="button" id="qa-model-save" class="quickadd-btn quickadd-btn-primary">Save Model</button>
      `;

      const save = async () => {
        const brand = body.querySelector("#qa-model-brand").value;
        const name = body.querySelector("#qa-model-name").value.trim();
        const itemType = body.querySelector("#qa-model-type").value;
        if (!name) { body.querySelector("#qa-model-name").focus(); return; }

        const resp = await fetch("/api/products/quick-add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brand, name, item_type: itemType })
        });
        const data = await resp.json();

        if (data.success) {
          const prod = data.product;
          if (triggerSelect) {
            const opt = document.createElement("option");
            opt.value = prod.id;
            opt.text = `${prod.brand} ${prod.name}`;
            triggerSelect.appendChild(opt);
            triggerSelect.value = prod.id;
            const inst = instances.get(triggerSelect);
            if (inst) inst.selectValue(prod.id, opt.text);
            focusNextField(triggerSelect);
          }
          this.closeModal();
        } else {
          alert(data.error || "Failed to create model");
        }
      };

      footer.querySelector("#qa-model-save").onclick = save;
      setTimeout(() => body.querySelector("#qa-model-name").focus(), 60);
    },

    closeModal() {
      const el = document.getElementById("quickadd-modal-overlay");
      if (el) el.remove();
    }
  };

  function createModalShell(title) {
    window.QuickAdd.closeModal();
    const overlay = document.createElement("div");
    overlay.id = "quickadd-modal-overlay";
    overlay.className = "quickadd-modal-overlay";

    overlay.innerHTML = `
      <div class="quickadd-modal-box">
        <div class="quickadd-modal-header">
          <h3 class="quickadd-modal-title">${escapeHtml(title)}</h3>
          <button type="button" class="quickadd-modal-close" onclick="window.QuickAdd.closeModal()">✕</button>
        </div>
        <div class="quickadd-modal-body"></div>
        <div class="quickadd-modal-footer"></div>
      </div>
    `;

    document.body.appendChild(overlay);

    overlay.onclick = (e) => {
      if (e.target === overlay) window.QuickAdd.closeModal();
    };

    window.addEventListener("keydown", function escListener(e) {
      if (e.key === "Escape") {
        window.QuickAdd.closeModal();
        window.removeEventListener("keydown", escListener);
      }
    });

    return overlay;
  }

  function focusNextField(currentEl) {
    const focusable = Array.from(document.querySelectorAll("input:not([type=hidden]):not([tabindex='-1']), select:not([tabindex='-1']), textarea, button[type=submit]"))
      .filter(el => !el.disabled && el.offsetParent !== null);
    const idx = focusable.indexOf(currentEl);
    if (idx >= 0 && idx + 1 < focusable.length) {
      focusable[idx + 1].focus();
    }
  }

  // Auto initialize on DOM ready
  function initAllSmartSelects() {
    document.querySelectorAll("select.smart-select, select[data-smart-select]").forEach(sel => {
      if (!instances.has(sel)) {
        new SmartSelect(sel);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAllSmartSelects);
  } else {
    initAllSmartSelects();
  }

  // Export
  window.SmartSelect = {
    init: initAllSmartSelects,
    get: (el) => instances.get(el),
    sync: (el) => {
      const inst = instances.get(el);
      if (inst) inst.syncFromSelect();
    }
  };
})();
