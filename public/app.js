let selectedId = null;
let currentDetail = null;
let selectedUploadFiles = [];
let orderTypes = [];
let xrefs = [];

const statuses = ["Received", "Needs Review", "Booked", "Rejected"];
const headerFields = [
  ["status", "Status", "select"],
  ["order_type_id", "Order Type", "orderType"],
  ["customer_company_name", "Customer Company"],
  ["customer_contact_name", "Customer Contact"],
  ["po_number", "PO Number"],
  ["quote_number", "Quote Number"],
  ["date_received", "Date Received", "date"],
  ["payment_terms", "Payment Terms"],
  ["freight_terms", "Freight Terms"],
  ["total_value", "Total Value", "readonly"],
  ["currency", "Currency"],
  ["bill_to_address", "Bill To Address", "textarea", "wide"],
  ["ship_to_address", "Ship To Address", "textarea", "wide"],
  ["extraction_notes", "Extraction Notes", "textarea", "wide"],
];

const lineFields = [
  ["line_number", "Line"],
  ["customer_part_number", "Customer Part #"],
  ["internal_part_number", "Internal Part #"],
  ["description", "Description"],
  ["quantity", "Qty", "number"],
  ["unit_of_measure", "UOM"],
  ["unit_price", "Unit Price", "number"],
  ["line_total", "Line Total", "lineTotal"],
  ["requested_date", "Requested Date", "date"],
  ["extraction_notes", "Notes"],
];

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function refresh() {
  await Promise.all([loadSummary(), loadPOs(), loadLogs()]);
  if (selectedId) await openDetail(selectedId, false);
}

async function loadSummary() {
  const data = await api("/api/summary");
  const counts = data.status_counts;
  document.querySelector("#summary").innerHTML = `
    ${metric("Emails", data.total_emails)}
    ${metric("POs", data.total_purchase_orders)}
    ${metric("Received", counts.Received)}
    ${metric("Needs Review", counts["Needs Review"])}
    ${metric("Booked", counts.Booked)}
    ${metric("Rejected", counts.Rejected)}
  `;
}

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

async function loadPOs() {
  const status = encodeURIComponent(document.querySelector("#statusFilter").value);
  const search = encodeURIComponent(document.querySelector("#searchInput").value);
  const rows = await api(`/api/purchase-orders?status=${status}&search=${search}`);
  document.querySelector("#poRows").innerHTML = rows
    .map((row) => {
      const active = row.id === selectedId ? "active" : "";
      return `
        <tr class="${active}" onclick="openDetail(${row.id})">
          <td>${badge(row.status)}</td>
          <td>${safe(row.date_received)}</td>
          <td>${safe(row.customer_company_name)}</td>
          <td><strong>${safe(row.po_number)}</strong></td>
          <td>${safe(row.order_type_name)}</td>
          <td>${safe(row.source_sender)}</td>
          <td>${row.line_count}</td>
          <td>${money(row.total_value, row.currency)}</td>
          <td>${pct(row.extraction_confidence)}</td>
          <td>${safe(row.updated_at)}</td>
          <td><button class="danger table-action" onclick="deletePO(event, ${row.id})">Delete</button></td>
        </tr>
      `;
    })
    .join("");
}

async function openDetail(id, mark = true) {
  currentDetail = await api(`/api/purchase-orders/${id}`);
  orderTypes = currentDetail.order_types || orderTypes;
  if (mark) selectedId = id;
  renderDetail();
  await loadPOs();
}

function renderDetail() {
  const po = currentDetail.purchase_order;
  const source = currentDetail.attachment?.extracted_text || currentDetail.email?.body_text || "";
  document.querySelector("#detail").innerHTML = `
    <div class="detail-head">
      <div>
        <h2>${safe(po.po_number) || "Purchase Order"}</h2>
        <p>${safe(po.source_subject)}</p>
      </div>
      ${badge(po.status)}
    </div>
    <div class="grid">${headerFields.map((field) => renderField(po, field, "po")).join("")}</div>
    <div class="line-actions">
      ${renderViewPoButton()}
      <button class="secondary" onclick="savePO()">Save Header</button>
      <button onclick="quickStatus('Booked')">Mark Booked</button>
      <button class="danger" onclick="quickStatus('Rejected')">Reject</button>
    </div>

    <div class="section-title">Line Items</div>
    <div id="lines">${currentDetail.lines.map(renderLine).join("")}</div>
    <button class="secondary" onclick="addLine()">Add Line</button>

    <div class="section-title">Source</div>
    <div class="source">${safe(source)}</div>

    <div class="section-title">Email Metadata</div>
    <div class="source">${safe(JSON.stringify(currentDetail.email, null, 2))}</div>
  `;
}

function renderField(record, field, prefix) {
  const [key, label, type = "text", size = ""] = field;
  const id = `${prefix}_${key}`;
  const confidence = confidenceFor(record, key);
  const review = confidence < 0.7 ? "review" : "";
  const reviewNote = confidence < 0.7 ? '<div class="review-note">Review</div>' : "";
  if (type === "select") {
    return `<div class="field ${size} ${review}"><label>${label}</label><select id="${id}">${statuses
      .map((s) => `<option ${record[key] === s ? "selected" : ""}>${s}</option>`)
      .join("")}</select>${reviewNote}</div>`;
  }
  if (type === "orderType") {
    return `<div class="field ${size} ${review}"><label>${label}</label><select id="${id}">
      <option value="">Select order type</option>
      ${orderTypes.map((orderType) => `<option value="${orderType.id}" ${Number(record[key]) === Number(orderType.id) ? "selected" : ""}>${safe(orderType.name)}</option>`).join("")}
    </select>${reviewNote}</div>`;
  }
  if (type === "readonly") {
    return `<div class="field ${size}"><label>${label}</label><div class="readonly-value">${money(record[key], record.currency)}</div></div>`;
  }
  if (type === "lineTotal") {
    return `<div class="field ${size}"><label>${label}</label><div class="readonly-value">${money(calculatedLineTotal(record), currentDetail?.purchase_order?.currency || "USD")}</div></div>`;
  }
  if (type === "textarea") {
    return `<div class="field ${size} ${review}"><label>${label}</label><textarea id="${id}">${safe(record[key])}</textarea>${reviewNote}</div>`;
  }
  return `<div class="field ${size} ${review}"><label>${label}</label><input id="${id}" type="${type}" value="${safe(inputValue(record[key], type))}" />${reviewNote}</div>`;
}

function inputValue(value, type) {
  if (value == null) return "";
  if (type === "date") return String(value).slice(0, 10);
  return value;
}

function confidenceFor(record, key) {
  try {
    const confidence = JSON.parse(record.field_confidence_json || "{}");
    if (confidence[key] != null) return Number(confidence[key]);
  } catch {
    return 0.5;
  }
  const important = ["customer_company_name", "po_number", "bill_to_address", "ship_to_address", "quote_number", "payment_terms", "freight_terms", "customer_part_number", "quantity", "unit_price", "line_total", "order_type_id"];
  return important.includes(key) && !record[key] ? 0.2 : 0.9;
}

function calculatedLineTotal(line) {
  if (line.quantity != null && line.unit_price != null && line.quantity !== "" && line.unit_price !== "") {
    return Number(line.quantity) * Number(line.unit_price);
  }
  return line.line_total;
}

function renderViewPoButton() {
  const attachment = currentDetail.attachment;
  if (attachment && String(attachment.filename || "").toLowerCase().endsWith(".pdf")) {
    return `<button class="secondary" onclick="window.open('/api/attachments/${attachment.id}/view', '_blank')">View PO</button>`;
  }
  return `<button class="secondary" disabled>No PDF available</button>`;
}

function renderLine(line) {
  return `
    <div class="line-card" data-line-id="${line.id}">
      <div class="grid">
        ${lineFields.map((field) => renderField(line, field, `line_${line.id}`)).join("")}
      </div>
      <div class="line-actions">
        <button class="secondary" onclick="saveLine(${line.id})">Save Line</button>
        <button class="danger" onclick="deleteLine(${line.id})">Delete</button>
      </div>
    </div>
  `;
}

async function savePO() {
  const payload = readFields(headerFields, "po");
  await api(`/api/purchase-orders/${selectedId}`, { method: "PUT", body: JSON.stringify(payload) });
  await refresh();
}

async function quickStatus(status) {
  await api(`/api/purchase-orders/${selectedId}`, { method: "PUT", body: JSON.stringify({ status }) });
  await refresh();
}

async function saveLine(id) {
  const payload = readFields(lineFields, `line_${id}`);
  await api(`/api/purchase-orders/${selectedId}/lines/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  await refresh();
}

async function deleteLine(id) {
  await api(`/api/purchase-orders/${selectedId}/lines/${id}`, { method: "DELETE" });
  await refresh();
}

async function addLine() {
  await api(`/api/purchase-orders/${selectedId}/lines`, {
    method: "POST",
    body: JSON.stringify({ line_number: String(currentDetail.lines.length + 1), unit_of_measure: "EA" }),
  });
  await refresh();
}

async function deletePO(event, id) {
  event.stopPropagation();
  if (!confirm("Are you sure? Deleting PO cannot be reversed.")) {
    return;
  }
  await api(`/api/purchase-orders/${id}`, { method: "DELETE" });
  if (selectedId === id) {
    selectedId = null;
    currentDetail = null;
    document.querySelector("#detail").innerHTML = '<div class="empty-state">Select a purchase order to review extracted fields and source text.</div>';
  }
  await Promise.all([loadSummary(), loadPOs(), loadLogs()]);
}

function readFields(fields, prefix) {
  const payload = {};
  for (const [key, , type = "text"] of fields) {
    if (type === "readonly" || type === "lineTotal") continue;
    const value = document.querySelector(`#${prefix}_${key}`).value;
    payload[key] = type === "number" && value !== "" ? Number(value) : normalizeFieldValue(type, value);
  }
  return payload;
}

function normalizeFieldValue(type, value) {
  if (value === "") return null;
  if (type === "date" && value) return value.slice(0, 10);
  return value;
}\n
async function loadLogs() {
  const rows = await api("/api/logs");
  document.querySelector("#logs").innerHTML = rows
    .map((row) => `<div class="log-row"><strong>${row.level}</strong> ${safe(row.message)} <span>${safe(row.created_at)}</span></div>`)
    .join("");
}

async function switchView(view) {
  const dashboard = document.querySelector("#dashboardView");
  const admin = document.querySelector("#adminView");
  document.querySelector("#dashboardViewBtn").classList.toggle("active-view", view === "dashboard");
  document.querySelector("#adminViewBtn").classList.toggle("active-view", view === "admin");
  dashboard.classList.toggle("hidden", view !== "dashboard");
  admin.classList.toggle("hidden", view !== "admin");
  if (view === "admin") {
    await loadAdminData();
  }
}

async function loadAdminData() {
  const [orderTypeData, xrefData] = await Promise.all([api("/api/order-types"), api("/api/customer-part-xrefs")]);
  orderTypes = orderTypeData;
  xrefs = xrefData;
  renderOrderTypes();
  renderXrefs();
}

function renderOrderTypes() {
  document.querySelector("#orderTypeRows").innerHTML = orderTypes
    .map(
      (row) => `
      <tr>
        <td><input id="order_type_name_${row.id}" value="${safe(row.name)}" /></td>
        <td>${row.is_active ? "Active" : "Inactive"}</td>
        <td>
          <button class="secondary" onclick="saveOrderType(${row.id})">Save</button>
          <button class="danger" onclick="deleteOrderType(${row.id})">Delete</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

function renderXrefs() {
  document.querySelector("#xrefRows").innerHTML = xrefs
    .map(
      (row) => `
      <tr>
        <td><input id="xref_customer_${row.id}" value="${safe(row.customer_name)}" /></td>
        <td><input id="xref_customer_part_${row.id}" value="${safe(row.customer_part_number)}" /></td>
        <td><input id="xref_internal_part_${row.id}" value="${safe(row.internal_part_number)}" /></td>
        <td>
          <button class="secondary" onclick="saveXref(${row.id})">Save</button>
          <button class="danger" onclick="deleteXref(${row.id})">Delete</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

async function addOrderType() {
  const input = document.querySelector("#orderTypeName");
  if (!input.value.trim()) return;
  const data = await api("/api/order-types", { method: "POST", body: JSON.stringify({ name: input.value.trim() }) });
  orderTypes = data.order_types;
  input.value = "";
  renderOrderTypes();
}

async function saveOrderType(id) {
  const name = document.querySelector(`#order_type_name_${id}`).value.trim();
  const data = await api(`/api/order-types/${id}`, { method: "PUT", body: JSON.stringify({ name, is_active: true }) });
  orderTypes = data.order_types;
  renderOrderTypes();
}

async function deleteOrderType(id) {
  const data = await api(`/api/order-types/${id}`, { method: "DELETE" });
  orderTypes = data.order_types;
  if (data.message) {
    alert(data.message);
  }
  renderOrderTypes();
}

async function addXref() {
  const payload = {
    customer_name: document.querySelector("#xrefCustomer").value.trim(),
    customer_part_number: document.querySelector("#xrefCustomerPart").value.trim(),
    internal_part_number: document.querySelector("#xrefInternalPart").value.trim(),
  };
  if (!payload.customer_name || !payload.customer_part_number || !payload.internal_part_number) {
    setXrefMessage("Customer, customer part number, and internal part number are required.", "error");
    return;
  }
  const data = await api("/api/customer-part-xrefs", { method: "POST", body: JSON.stringify(payload) });
  xrefs = data.xrefs;
  document.querySelector("#xrefCustomer").value = "";
  document.querySelector("#xrefCustomerPart").value = "";
  document.querySelector("#xrefInternalPart").value = "";
  setXrefMessage("Cross reference saved.", "success");
  renderXrefs();
}

async function saveXref(id) {
  const payload = {
    customer_name: document.querySelector(`#xref_customer_${id}`).value.trim(),
    customer_part_number: document.querySelector(`#xref_customer_part_${id}`).value.trim(),
    internal_part_number: document.querySelector(`#xref_internal_part_${id}`).value.trim(),
  };
  const data = await api(`/api/customer-part-xrefs/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  xrefs = data.xrefs;
  setXrefMessage("Cross reference updated.", "success");
  renderXrefs();
}

async function deleteXref(id) {
  const data = await api(`/api/customer-part-xrefs/${id}`, { method: "DELETE" });
  xrefs = data.xrefs;
  renderXrefs();
}

async function uploadXrefCsv(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    setXrefMessage("Only CSV files are allowed.", "error");
    return;
  }
  const form = new FormData();
  form.append("files", file);
  setXrefMessage("Uploading cross reference CSV...");
  const res = await fetch("/api/customer-part-xrefs/upload", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok || data.error) {
    setXrefMessage(data.error || "CSV upload failed.", "error");
    return;
  }
  xrefs = data.xrefs;
  const errorText = data.errors?.length ? ` Errors: ${data.errors.join(" ")}` : "";
  setXrefMessage(`Imported ${data.imported}, skipped ${data.skipped}.${errorText}`, data.errors?.length ? "error" : "success");
  renderXrefs();
}

function setXrefMessage(message, kind = "") {
  const el = document.querySelector("#xrefMessage");
  el.className = `upload-message ${kind}`;
  el.textContent = message;
}

function openExportModal() {
  document.querySelector("#exportModal").classList.remove("hidden");
  document.querySelector("#exportModal").setAttribute("aria-hidden", "false");
}

function closeExportModal() {
  document.querySelector("#exportModal").classList.add("hidden");
  document.querySelector("#exportModal").setAttribute("aria-hidden", "true");
}

function exportPOs(mode) {
  const status = encodeURIComponent(document.querySelector("#statusFilter").value);
  const search = encodeURIComponent(document.querySelector("#searchInput").value);
  window.location.href = `/api/export/purchase-orders.csv?mode=${mode}&status=${status}&search=${search}`;
  closeExportModal();
}

function badge(status) {
  const klass = String(status || "").replace(/\s/g, "");
  return `<span class="badge ${klass}">${safe(status)}</span>`;
}

function pct(value) {
  return value == null ? "" : `${Math.round(Number(value) * 100)}%`;
}

function money(value, currency = "USD") {
  if (value == null || value === "") return "";
  return `${currency || "USD"} ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function safe(value) {
  if (value == null) return "";
  return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function openUploadModal() {
  selectedUploadFiles = [];
  renderSelectedFiles();
  setUploadMessage("");
  document.querySelector("#fileInput").value = "";
  document.querySelector("#uploadModal").classList.remove("hidden");
  document.querySelector("#uploadModal").setAttribute("aria-hidden", "false");
}

function closeUploadModal() {
  document.querySelector("#uploadModal").classList.add("hidden");
  document.querySelector("#uploadModal").setAttribute("aria-hidden", "true");
}

function setFiles(files) {
  const allowed = [".pdf", ".txt", ".eml"];
  const incoming = Array.from(files || []);
  const rejected = incoming.filter((file) => !allowed.some((ext) => file.name.toLowerCase().endsWith(ext)));
  selectedUploadFiles = incoming.filter((file) => allowed.some((ext) => file.name.toLowerCase().endsWith(ext)));
  renderSelectedFiles();
  if (rejected.length) {
    setUploadMessage(`Ignored unsupported file type: ${rejected.map((file) => file.name).join(", ")}`, "error");
  } else {
    setUploadMessage("");
  }
}

function renderSelectedFiles() {
  const container = document.querySelector("#selectedFiles");
  if (!selectedUploadFiles.length) {
    container.textContent = "No files selected.";
    return;
  }
  container.innerHTML = `<ul>${selectedUploadFiles.map((file) => `<li>${safe(file.name)} (${Math.ceil(file.size / 1024)} KB)</li>`).join("")}</ul>`;
}

function setUploadMessage(message, kind = "") {
  const el = document.querySelector("#uploadMessage");
  el.className = `upload-message ${kind}`;
  el.textContent = message;
}

async function uploadSelectedFiles() {
  if (!selectedUploadFiles.length) {
    setUploadMessage("Select or drop at least one PDF, TXT, or EML file.", "error");
    return;
  }
  const btn = document.querySelector("#uploadProcessBtn");
  btn.disabled = true;
  btn.textContent = "Uploading...";
  setUploadMessage("Uploading and processing files...");
  try {
    const form = new FormData();
    selectedUploadFiles.forEach((file) => form.append("files", file));
    const res = await fetch("/api/upload-samples", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || "Upload failed");
    }
    const rejected = data.rejected_files?.length ? ` Rejected: ${data.rejected_files.map((f) => f.filename).join(", ")}.` : "";
    setUploadMessage(`Imported ${data.imported}, skipped ${data.skipped}, created ${data.purchase_orders} PO records.${rejected}`, data.rejected_files?.length ? "error" : "success");
    await refresh();
    if (!data.rejected_files?.length) {
      closeUploadModal();
    }
  } catch (error) {
    setUploadMessage(error.message || "Upload failed.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload & Process";
  }
}

async function importExistingSampleFolder() {
  const btn = document.querySelector("#folderImportBtn");
  btn.disabled = true;
  btn.textContent = "Importing...";
  setUploadMessage("Importing existing sample folder...");
  try {
    const data = await api("/api/import-samples", { method: "POST" });
    setUploadMessage(`Imported ${data.imported}, skipped ${data.skipped}, created ${data.purchase_orders} PO records.`, "success");
    await refresh();
  } catch (error) {
    setUploadMessage(error.message || "Import failed.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Import Existing Sample Folder";
  }
}

document.querySelector("#importBtn").addEventListener("click", openUploadModal);

document.querySelector("#selectFileBtn").addEventListener("click", () => {
  document.querySelector("#fileInput").click();
});

document.querySelector("#fileInput").addEventListener("change", (event) => {
  setFiles(event.target.files);
});

document.querySelector("#uploadProcessBtn").addEventListener("click", uploadSelectedFiles);
document.querySelector("#folderImportBtn").addEventListener("click", importExistingSampleFolder);
document.querySelector("#cancelUploadBtn").addEventListener("click", closeUploadModal);
document.querySelector("#closeUploadBtn").addEventListener("click", closeUploadModal);

document.querySelector("#uploadModal").addEventListener("click", (event) => {
  if (event.target.id === "uploadModal") {
    closeUploadModal();
  }
});

document.querySelector("#exportModal").addEventListener("click", (event) => {
  if (event.target.id === "exportModal") {
    closeExportModal();
  }
});

const dropZone = document.querySelector("#dropZone");
["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragover");
  });
});
dropZone.addEventListener("drop", (event) => {
  setFiles(event.dataTransfer.files);
});

document.querySelector("#syncBtn").addEventListener("click", () => {
  alert("Gmail/Outlook sync is stubbed for the MVP. Use Import Samples to test the pipeline.");
});

document.querySelector("#exportBtn").addEventListener("click", openExportModal);
document.querySelector("#exportHeaderBtn").addEventListener("click", () => exportPOs("header"));
document.querySelector("#exportLinesBtn").addEventListener("click", () => exportPOs("lines"));
document.querySelector("#cancelExportBtn").addEventListener("click", closeExportModal);
document.querySelector("#closeExportBtn").addEventListener("click", closeExportModal);
document.querySelector("#dashboardViewBtn").addEventListener("click", () => switchView("dashboard"));
document.querySelector("#adminViewBtn").addEventListener("click", () => switchView("admin"));
document.querySelector("#addOrderTypeBtn").addEventListener("click", addOrderType);
document.querySelector("#addXrefBtn").addEventListener("click", addXref);
document.querySelector("#xrefCsvBtn").addEventListener("click", () => document.querySelector("#xrefCsvInput").click());
document.querySelector("#xrefCsvDownloadBtn").addEventListener("click", () => {
  window.location.href = "/api/customer-part-xrefs.csv";
});
document.querySelector("#xrefCsvInput").addEventListener("change", (event) => uploadXrefCsv(event.target.files[0]));

document.querySelector("#statusFilter").addEventListener("change", loadPOs);
document.querySelector("#searchInput").addEventListener("input", () => loadPOs());

loadAdminData().then(refresh);
