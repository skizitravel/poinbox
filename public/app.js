let selectedId = null;
let currentDetail = null;
let selectedUploadFiles = [];
let orderTypes = [];
let xrefs = [];
let products = [];
let users = [];
let customers = [];
let departments = [];
let paymentTerms = [];
let testDocuments = [];
let evaluationData = { run: null, results: [] };
let inboxAccounts = [];
let inboxSyncRuns = [];
let inboxDetectionResults = [];
let inboxMessageRecords = [];
let gmailConfig = {};
let outlookConfig = {};
let openaiConfig = {};
let exportDestinations = [];
let currentInboxConfig = null;
let configuringInboxId = null;
let extractionLearning = { summary: {}, recent_feedback: [], recent_failures: [], corrected_fields: [], corrections_by_customer: [] };
let reviewTasks = [];
let reviewTaskUsers = [];
let operationsMetrics = {};
let canonicalMasterData = { counts: [], bridge_counts: {}, samples: {} };
let oracleEbsConfig = { manifest: null, profile: null, mapping_summary: {} };
let oraclePayloadPreview = null;
let currentUser = null;
let activeAdminTab = "users";
let editingUserId = null;
let editingCustomerId = null;
let currentCustomerDetail = null;
let editingAddressId = null;
let editingContactId = null;
let pendingReviewAction = null;
let editingGoldenDocumentId = null;
let currentGoldenAnswer = null;
let manualSyncInboxId = null;
let poEntryOpen = false;

const statuses = ["Received", "Needs Review", "Booked", "Rejected"];
const headerFields = [
  ["status", "Status", "select"],
  ["order_type_id", "Order Type", "orderType"],
  ["customer_company_name", "Customer Company"],
  ["customer_contact_name", "Customer Contact"],
  ["po_number", "PO Number"],
  ["po_revision", "PO Revision"],
  ["quote_number", "Quote Number"],
  ["date_received", "Date Received", "date"],
  ["payment_terms", "Payment Terms"],
  ["freight_terms", "Freight Terms"],
  ["total_value", "Total Value", "readonly"],
  ["currency", "Currency"],
  ["extraction_notes", "Extraction Notes", "textarea", "wide"],
];

const lineFields = [
  ["line_number", "Line"],
  ["customer_part_number", "Customer Part #"],
  ["customer_part_revision", "Customer Part Rev"],
  ["internal_part_number", "Internal Part #"],
  ["internal_part_revision", "Internal Part Rev"],
  ["description", "Description"],
  ["quantity", "Qty", "number"],
  ["unit_of_measure", "UOM"],
  ["unit_price", "Unit Price", "number"],
  ["line_total", "Line Total", "lineTotal"],
  ["product_match_status", "Product Match", "readonly"],
  ["requested_date", "Requested Date", "date"],
  ["extraction_notes", "Notes"],
];

const openAIModelOptions = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"];
const addressKeys = ["address_line_1", "address_line_2", "address_line_3", "city", "state", "country", "zip_code"];
const addressLabels = {
  address_line_1: "Line 1",
  address_line_2: "Line 2",
  address_line_3: "Line 3",
  city: "City",
  state: "State",
  country: "Country",
  zip_code: "Zip Code",
};
const adminTabs = ["users", "master", "setup", "testing", "analytics", "erp"];
const adminTabLabels = {
  users: "Users & Access",
  master: "Master Data",
  setup: "Setup",
  testing: "Testing",
  analytics: "Analytics",
  erp: "ERP",
};
const adminPermissionSelectIds = {
  users: "adminPermUsers",
  master: "adminPermMaster",
  setup: "adminPermSetup",
  testing: "adminPermTesting",
  analytics: "adminPermAnalytics",
  erp: "adminPermErp",
};

async function api(path, options = {}) {
  const { skipAuthRedirect = false, ...fetchOptions } = options;
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...fetchOptions,
  });
  if (res.status === 401 && !skipAuthRedirect) {
    showLogin("Please log in to continue.");
    throw new Error("Please log in to continue.");
  }
  if (res.status === 403) {
    throw new Error("You do not have permission for that action.");
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function safeApi(path, fallback) {
  try {
    return await api(path);
  } catch (error) {
    console.warn(`Admin data load skipped ${path}:`, error);
    return fallback;
  }
}

function canonicalFallbackData() {
  return { counts: [], groups: { master_bridge: [], setup_reference: [], erp_diagnostics: [] }, bridge_counts: {}, samples: {} };
}

function hasPermission(permission) {
  return Boolean(currentUser?.permissions?.includes(permission));
}

function canViewDashboard() {
  return hasPermission("po_dashboard:view");
}

function canEditDashboard() {
  return hasPermission("po_dashboard:edit");
}

function canViewAdmin() {
  return hasPermission("admin:view");
}

function adminTabAccess(tab) {
  const explicit = currentUser?.admin_tab_permissions?.[tab];
  if (explicit) return explicit;
  if (!currentUser) return "no_access";
  if (currentUser.is_admin) return "full_access";
  if (hasPermission(`admin:${tab}:edit`)) return "full_access";
  if (hasPermission(`admin:${tab}:view`)) return "view_only";
  if (tab === "users") return hasPermission("users:manage") ? "full_access" : "no_access";
  if (currentUser.can_access_admin || hasPermission("admin:view")) return "full_access";
  return "no_access";
}

function canViewAdminTab(tab) {
  return ["view_only", "full_access"].includes(adminTabAccess(tab));
}

function canEditAdminTab(tab) {
  return adminTabAccess(tab) === "full_access";
}

function firstAvailableAdminTab() {
  return adminTabs.find((tab) => canViewAdminTab(tab)) || "";
}

function canViewUsers() {
  return hasPermission("users:view") || hasPermission("users:manage");
}

function canManageUsers() {
  return hasPermission("users:manage");
}

function canViewIntegrations() {
  return hasPermission("integrations:view");
}

function canManageIntegrations() {
  return hasPermission("integrations:manage");
}

function setMessage(selector, message, kind = "") {
  const el = document.querySelector(selector);
  el.className = `upload-message ${kind}`;
  el.textContent = message;
}

async function refresh() {
  if (!canViewDashboard()) return;
  await Promise.all([loadSummary(), loadPOs(), loadLogs(), loadReviewTasks()]);
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
          <td><strong>${safe(row.po_number)}</strong> ${row.open_exception_count ? `<span class="mini-badge">${row.open_exception_count} exceptions</span>` : ""}</td>
          <td>${safe(row.po_revision)}</td>
          <td>${safe(row.order_type_name)}</td>
          <td>${safe(row.source_display || sourceLabel(row))}</td>
          <td>${safe(row.source_sender)}</td>
          <td>${row.line_count}</td>
          <td>${money(row.total_value, row.currency)}</td>
          <td>${pct(row.extraction_confidence)}</td>
          <td>${safe(row.updated_at)}</td>
          <td>
            <button class="secondary table-action" onclick="openPoEntryView(event, ${row.id})">PO Entry View</button>
            ${canEditDashboard() ? `<button class="danger table-action" onclick="deletePO(event, ${row.id})">Delete</button>` : ""}
          </td>
        </tr>
      `;
    })
    .join("");
}

async function openDetail(id, mark = true) {
  if (Number(selectedId || 0) !== Number(id)) oraclePayloadPreview = null;
  currentDetail = await api(`/api/purchase-orders/${id}`);
  orderTypes = currentDetail.order_types || orderTypes;
  if (mark) selectedId = id;
  renderDetail();
  if (poEntryOpen) renderPoEntryModal();
  await loadPOs();
}

function renderDetail() {
  document.querySelector("#detail").innerHTML = renderDetailHtml();
}

function renderDetailHtml(context = "") {
  const po = currentDetail.purchase_order;
  const source = sourceTextForCurrentDetail();
  const editActions = canEditDashboard()
    ? `<button class="secondary" onclick="savePO('${context}')">Save Header</button>
      <button class="secondary" onclick="markExtractionReviewed()">Mark Extraction Reviewed</button>
      <button onclick="quickStatus('Booked')">Mark Booked</button>
      <button class="danger" onclick="quickStatus('Rejected')">Reject</button>`
    : '<span class="view-only-note">View Only</span>';
  return `
    <div class="detail-head">
      <div>
        <h2>${safe(po.po_number) || "Purchase Order"}</h2>
        <p>${safe(po.source_subject)}</p>
        <p class="muted-line">Source: ${safe(po.source_display || sourceLabel(po))}</p>
      </div>
      <div class="detail-status">
        ${!canEditDashboard() ? '<span class="badge ViewOnly">View Only</span>' : ""}${badge(po.status)}
        <div class="detail-top-actions">${renderDetailTopActions(context)}</div>
      </div>
    </div>
    <div class="grid">${headerFields.map((field) => renderField(po, field, "po", context)).join("")}</div>
    ${renderStructuredAddressSection("bill_to", "Bill-To Address", "bill_to_address_structured_json", "bill_to_address", context)}
    ${renderStructuredAddressSection("ship_to", "Ship-To Address", "ship_to_address_structured_json", "ship_to_address", context)}
    <div class="muted-panel">Corrections captured for learning: ${po.extraction_feedback_count || 0}. Reviewed: ${po.extraction_reviewed_at ? safe(po.extraction_reviewed_at) : "Not reviewed"}.</div>
    <div class="line-actions">
      <button class="secondary" onclick="openAcknowledgmentDraft()">Draft Acknowledgment</button>
      ${editActions}
    </div>

    <div class="section-title">Line Items</div>
    <div id="${scopedId("lines", context)}">${currentDetail.lines.map((line) => renderLine(line, context)).join("")}</div>
    ${canEditDashboard() ? '<button class="secondary" onclick="addLine()">Add Line</button>' : ""}

    ${renderMasterDataReviews()}
    ${renderDetailExceptions()}
    ${renderDuplicateCandidates()}
    ${renderOraclePreviewPanel()}
    ${renderSourceEvidencePanel()}
    ${renderAuditTrail()}

    <div class="section-title">Source</div>
    <div class="source">${safe(source)}</div>

    <div class="section-title">Email Metadata</div>
    <div class="source">${safe(JSON.stringify(currentDetail.email, null, 2))}</div>
  `;
}

function scopedId(id, context = "") {
  return context ? `${context}_${id}` : id;
}

function sourceTextForCurrentDetail() {
  return currentDetail?.attachment?.extracted_text || currentDetail?.email?.body_text || "";
}

function renderField(record, field, prefix, context = "") {
  const [key, label, type = "text", size = ""] = field;
  const id = scopedId(`${prefix}_${key}`, context);
  const confidence = confidenceFor(record, key);
  const review = confidence < 0.7 ? "review" : "";
  const reviewNote = confidence < 0.7 ? '<div class="review-note">Review</div>' : "";
  const action = renderFieldAction(key);
  const contextualAction = renderFieldContextualAction(key);
  const lineId = prefix.startsWith("line_") ? Number(prefix.replace("line_", "")) : null;
  const evidence = renderEvidenceHint(key, lineId);
  if (!canEditDashboard() && !["readonly", "lineTotal"].includes(type)) {
    return renderReadonlyField(record, key, label, size, review, reviewNote);
  }
  if (type === "select") {
    return `<div class="field ${size} ${review}" data-field-name="${safe(key)}"><label>${label}</label><select id="${id}">${statuses
      .map((s) => `<option ${record[key] === s ? "selected" : ""}>${s}</option>`)
      .join("")}</select>${reviewNote}${evidence}${action}${contextualAction}</div>`;
  }
  if (type === "orderType") {
    return `<div class="field ${size} ${review}" data-field-name="${safe(key)}"><label>${label}</label><select id="${id}">
      <option value="">Select order type</option>
      ${orderTypes.map((orderType) => `<option value="${orderType.id}" ${Number(record[key]) === Number(orderType.id) ? "selected" : ""}>${safe(orderType.name)}</option>`).join("")}
    </select>${reviewNote}${evidence}${action}${contextualAction}</div>`;
  }
  if (type === "readonly") {
    const value = key === "total_value" ? money(record[key], record.currency) : safe(record[key]);
    return `<div class="field ${size}"><label>${label}</label><div class="readonly-value">${value}</div></div>`;
  }
  if (type === "lineTotal") {
    return `<div class="field ${size}"><label>${label}</label><div class="readonly-value">${money(calculatedLineTotal(record), currentDetail?.purchase_order?.currency || "USD")}</div></div>`;
  }
  if (type === "textarea") {
    return `<div class="field ${size} ${review}" data-field-name="${safe(key)}"><label>${label}</label><textarea id="${id}">${safe(record[key])}</textarea>${reviewNote}${evidence}${action}${contextualAction}</div>`;
  }
  return `<div class="field ${size} ${review}" data-field-name="${safe(key)}"><label>${label}</label><input id="${id}" type="${type}" value="${safe(inputValue(record[key], type))}" />${reviewNote}${evidence}${action}${contextualAction}</div>`;
}

function evidenceForField(fieldName, lineId = null) {
  return (currentDetail?.source_evidence || []).find((item) => item.field_name === fieldName && Number(item.purchase_order_line_id || 0) === Number(lineId || 0));
}

function renderEvidenceHint(fieldName, lineId = null) {
  const item = evidenceForField(fieldName, lineId);
  if (!item || !item.source_snippet) return "";
  const auto = item.confidence != null && Number(item.confidence) < 0.7;
  return `<details class="evidence-hint" ${auto ? "open" : ""}>
    <summary>Source Evidence</summary>
    <div>${safe(item.source_snippet)}</div>
    <span>${safe(item.source_attachment_filename)} ${item.sheet_name ? `Sheet: ${safe(item.sheet_name)}` : ""} ${item.row_number ? `Row ${safe(item.row_number)}` : ""} ${item.page_number ? `Page ${safe(item.page_number)}` : ""}</span>
  </details>`;
}

function renderDetailExceptions() {
  const tasks = currentDetail.review_tasks || [];
  const openTasks = tasks.filter((task) => task.status === "open");
  return `
    <div class="section-title">Exceptions</div>
    <div class="review-list">
      ${
        openTasks.length
          ? openTasks
              .map(
                (task) => `
          <div class="review-item ${safe(task.severity)}">
            <div><strong>${safe(task.reason_code)}</strong> ${safe(task.message)}</div>
            <div class="muted-line">${safe(task.field_name)} ${task.confidence != null ? `- ${pct(task.confidence)}` : ""}</div>
            <div class="muted-line">Current: ${safe(task.current_value)} ${task.extracted_value ? `| Extracted: ${safe(task.extracted_value)}` : ""}</div>
            ${
              canEditDashboard()
                ? `<button class="secondary table-action" onclick="resolveReviewTask(${task.id})">Resolve</button>
                   <button class="secondary table-action" onclick="ignoreReviewTask(${task.id})">Ignore</button>`
                : ""
            }
          </div>
        `,
              )
              .join("")
          : '<div class="muted-panel">No open exceptions.</div>'
      }
    </div>
  `;
}

function renderSourceEvidencePanel() {
  const evidence = currentDetail.source_evidence || [];
  return `
    <div class="section-title">Source Evidence</div>
    <div class="evidence-list">
      ${
        evidence.length
          ? evidence
              .slice(0, 40)
              .map(
                (item) => `<div class="evidence-row">
                  <strong>${safe(item.field_name)}</strong>
                  <span>${safe(item.extracted_value)}</span>
                  <p>${safe(item.source_snippet)}</p>
                  <small>${safe(item.source_attachment_filename)} ${item.sheet_name ? `Sheet: ${safe(item.sheet_name)}` : ""} ${item.row_number ? `Row ${safe(item.row_number)}` : ""} ${item.paragraph_index ? `Paragraph ${safe(item.paragraph_index)}` : ""} ${item.confidence != null ? `Confidence ${pct(item.confidence)}` : ""}</small>
                </div>`,
              )
              .join("")
          : '<div class="muted-panel">No field-level source evidence captured yet.</div>'
      }
    </div>
  `;
}

function renderDuplicateCandidates() {
  const candidates = (currentDetail.duplicate_candidates || []).filter((item) => item.status === "open");
  if (!candidates.length) return "";
  const po = currentDetail.purchase_order || {};
  return `
    <div class="section-title">Possible Duplicates</div>
    <div class="review-list">
      ${candidates
        .map(
          (item) => `
        <div class="review-item warning">
          <div><strong>${safe(item.match_type)}</strong> ${safe(item.reason)}</div>
          <div class="duplicate-grid">
            <div><strong>Current</strong><br />PO ${safe(po.po_number)} Rev ${safe(po.po_revision)}<br />${safe(po.customer_company_name)}<br />${money(po.total_value, po.currency)}<br />${safe(po.source_sender)}</div>
            <div><strong>Candidate</strong><br />PO ${safe(item.candidate_po_number)} Rev ${safe(item.candidate_po_revision)}<br />${safe(item.candidate_customer)}<br />${money(item.candidate_total, po.currency)}<br />${safe(item.candidate_source_sender)}<br />${safe(item.candidate_attachment_filename)}</div>
          </div>
          <div class="line-actions">
            <button class="secondary table-action" onclick="openDetail(${item.candidate_purchase_order_id})">Open Existing PO</button>
            ${canEditDashboard() ? `<button class="secondary table-action" onclick="duplicateCandidateAction(${item.id}, 'mark_duplicate')">Mark Duplicate</button>
              <button class="secondary table-action" onclick="duplicateCandidateAction(${item.id}, 'keep_both')">Keep Both</button>
              <button class="secondary table-action" onclick="duplicateCandidateAction(${item.id}, 'link_revision')">Link Revision</button>
              <button class="secondary table-action" onclick="duplicateCandidateAction(${item.id}, 'ignore')">Ignore</button>` : ""}
          </div>
        </div>`,
        )
        .join("")}
    </div>
  `;
}

function renderAuditTrail() {
  const events = currentDetail.audit_events || [];
  return `
    <div class="section-title">Audit Trail</div>
    <div class="mini-list">
      ${
        events.length
          ? events.map((event) => `<div class="log-row"><strong>${safe(event.event_type)}</strong> ${safe(event.message)} <span>${safe(event.created_at)} ${safe(event.user_display || event.user_email || "")}</span></div>`).join("")
          : '<div class="muted-panel">No audit events yet.</div>'
      }
    </div>
  `;
}

function renderReadonlyField(record, key, label, size, review, reviewNote) {
  let value = record[key];
  if (key === "status") value = badge(value);
  else if (key === "order_type_id") value = safe(record.order_type_name || "");
  else value = safe(inputValue(value, "text"));
  return `<div class="field ${size} ${review}"><label>${label}</label><div class="readonly-value">${value}</div>${reviewNote}${renderFieldAction(key)}${renderFieldContextualAction(key)}</div>`;
}

function renderFieldAction(key) {
  if (key === "customer_company_name") return renderInlineMasterDataAction("customer");
  if (key === "customer_contact_name") return renderInlineMasterDataAction("contact");
  return "";
}

function renderFieldContextualAction(key) {
  if (key !== "extraction_notes") return "";
  return `<div class="field-inline-action"><button class="secondary table-action" onclick="openConfirmedOrderView()">Confirmed Order View</button></div>`;
}

function renderStructuredAddressSection(prefix, title, jsonKey, textKey, context = "") {
  const po = currentDetail.purchase_order;
  const structured = structuredAddressFor(po, jsonKey, textKey);
  return `
    <div class="section-title">${title}</div>
    <div class="address-grid">
      ${addressKeys
        .map((key) => {
          const id = scopedId(`po_${prefix}_${key}`, context);
          if (!canEditDashboard()) {
            return `<div class="field"><label>${addressLabels[key]}</label><div class="readonly-value">${safe(structured[key])}</div></div>`;
          }
          return `<div class="field"><label>${addressLabels[key]}</label><input id="${id}" value="${safe(structured[key])}" /></div>`;
        })
        .join("")}
    </div>
    ${renderInlineMasterDataAction(`${prefix}_address`)}
  `;
}

function structuredAddressFor(po, jsonKey, textKey) {
  const parsed = parseJson(po[jsonKey]);
  const structured = {};
  for (const key of addressKeys) structured[key] = parsed[key] || "";
  if (!Object.values(structured).some(Boolean) && po[textKey]) {
    structured.address_line_1 = po[textKey] || "";
  }
  return structured;
}

function readStructuredAddress(prefix, context = "") {
  const output = {};
  for (const key of addressKeys) {
    output[key] = document.querySelector(`#${scopedId(`po_${prefix}_${key}`, context)}`)?.value.trim() || "";
  }
  return output;
}

function renderInlineMasterDataAction(type) {
  const reviewType = type === "bill_to_address" ? "bill_to_address" : type === "ship_to_address" ? "ship_to_address" : type;
  const review = (currentDetail.master_data_reviews || []).find((item) => item.review_type === reviewType && item.status === "open");
  if (!review) return "";
  const action = reviewActionLabel(review.review_type);
  const blocked = actionBlockedByMissingCustomer(review);
  const canAct = canEditAdminTab("master") && !blocked;
  return `
    <div class="inline-master-action">
      <span>${safe(review.message)}</span>
      ${canAct ? `<button class="secondary table-action" onclick="startMasterDataReviewAction(${review.id})">${action}</button>` : ""}
      ${!canViewAdminTab("master") ? '<span class="view-only-note">Master data review needed</span>' : ""}
      ${blocked ? '<span class="review-note">Add Customer first</span>' : ""}
    </div>
  `;
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
  const important = ["customer_company_name", "po_number", "po_revision", "bill_to_address", "ship_to_address", "quote_number", "payment_terms", "freight_terms", "customer_part_number", "customer_part_revision", "internal_part_revision", "quantity", "unit_price", "line_total", "order_type_id"];
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

function renderDetailTopActions(context = "") {
  const entryButton = context ? "" : `<button class="secondary" onclick="openPoEntryView(event, ${currentDetail.purchase_order.id})">PO Entry View</button>`;
  const oracleButton = !context && canEditAdminTab("erp") ? `<button class="secondary" onclick="previewOracleEbsPayload(event)">Oracle Preview</button>` : "";
  return `${renderViewPoButton()}${entryButton}${oracleButton}`;
}

async function previewOracleEbsPayload(event) {
  if (event) event.stopPropagation();
  if (!selectedId || !canEditAdminTab("erp")) return;
  oraclePayloadPreview = { loading: true };
  renderDetail();
  try {
    oraclePayloadPreview = await api(`/api/purchase-orders/${selectedId}/erp/oracle-ebs/preview`, { method: "POST", body: JSON.stringify({}) });
  } catch (error) {
    oraclePayloadPreview = { error: error.message || "Oracle EBS preview failed." };
  }
  renderDetail();
}

function renderOraclePreviewPanel() {
  if (!oraclePayloadPreview) return "";
  if (oraclePayloadPreview.loading) {
    return `<div class="section-title">Oracle EBS Payload Preview</div><div class="muted-panel">Generating Oracle EBS preview...</div>`;
  }
  if (oraclePayloadPreview.error) {
    return `<div class="section-title">Oracle EBS Payload Preview</div><div class="muted-panel error">${safe(oraclePayloadPreview.error)}</div>`;
  }
  const messages = oraclePayloadPreview.validation?.messages || [];
  const payload = oraclePayloadPreview.payload || {};
  return `
    <div class="section-title">Oracle EBS Payload Preview</div>
    <div class="review-list">
      ${
        messages.length
          ? messages
              .map((item) => `<div class="review-item ${item.severity === "error" ? "critical" : "warning"}"><strong>${safe(item.severity)}</strong> ${safe(item.message)} <span class="muted-line">${safe(item.field)}</span></div>`)
              .join("")
          : '<div class="muted-panel">Canonical draft validated for Oracle EBS preview.</div>'
      }
    </div>
    <div class="muted-panel">Preview only. No Oracle order was created, booked, exported, or changed.</div>
    <div class="source">${safe(JSON.stringify(payload, null, 2))}</div>
  `;
}

function renderLine(line, context = "") {
  return `
    <div class="line-card" data-line-id="${line.id}">
      <div class="grid">
        ${lineFields.map((field) => renderField(line, field, `line_${line.id}`, context)).join("")}
      </div>
      ${canEditDashboard() ? `<div class="line-actions">
        <button class="secondary" onclick="saveLine(${line.id}, '${context}')">Save Line</button>
        <button class="danger" onclick="deleteLine(${line.id})">Delete</button>
      </div>` : ""}
    </div>
  `;
}

async function openPoEntryView(event, id = selectedId) {
  if (event) event.stopPropagation();
  if (!id) return;
  if (!currentDetail || Number(currentDetail.purchase_order?.id) !== Number(id)) {
    await openDetail(id);
  } else {
    selectedId = id;
  }
  poEntryOpen = true;
  renderPoEntryModal();
  document.querySelector("#poEntryModal").classList.remove("hidden");
  document.querySelector("#poEntryModal").setAttribute("aria-hidden", "false");
}

function closePoEntryView() {
  poEntryOpen = false;
  document.querySelector("#poEntryModal").classList.add("hidden");
  document.querySelector("#poEntryModal").setAttribute("aria-hidden", "true");
}

function renderPoEntryModal() {
  if (!currentDetail) return;
  const po = currentDetail.purchase_order || {};
  document.querySelector("#poEntryTitle").textContent = `PO Entry View${po.po_number ? ` - ${po.po_number}` : ""}`;
  document.querySelector("#savePoEntryBtn").classList.toggle("hidden", !canEditDashboard());
  document.querySelector("#poEntrySource").innerHTML = renderPoEntrySource();
  document.querySelector("#poEntryDetail").innerHTML = renderDetailHtml("entry");
}

function renderPoEntrySource() {
  const attachment = currentDetail.attachment || {};
  const filename = attachment.original_filename || attachment.filename || "Source document";
  if (attachment.id && String(filename).toLowerCase().endsWith(".pdf")) {
    return `
      <div class="section-title">${safe(filename)}</div>
      <iframe class="po-entry-pdf" title="PO source file" src="/api/attachments/${attachment.id}/view"></iframe>
    `;
  }
  const source = sourceTextForCurrentDetail();
  return `
    <div class="section-title">${safe(filename)}</div>
    <pre class="source po-entry-source-text">${safe(source || "No PDF or source text available for this purchase order.")}</pre>
  `;
}

async function savePoEntry() {
  if (!canEditDashboard() || !selectedId || !currentDetail) return;
  document.querySelector("#savePoEntryBtn").disabled = true;
  try {
    await savePO("entry", false);
    for (const line of currentDetail.lines || []) {
      await saveLine(line.id, "entry", false);
    }
    currentDetail = await api(`/api/purchase-orders/${selectedId}`);
    orderTypes = currentDetail.order_types || orderTypes;
    renderDetail();
    renderPoEntryModal();
    await Promise.all([loadPOs(), loadSummary(), loadLogs(), loadReviewTasks()]);
  } finally {
    document.querySelector("#savePoEntryBtn").disabled = false;
  }
}

function renderMasterDataReviews() {
  const reviews = currentDetail.master_data_reviews || [];
  const openReviews = reviews.filter((review) => review.status === "open");
  if (!reviews.length) {
    return `
      <div class="section-title">Master Data Review</div>
      <div class="review-panel muted-panel">No master data review items.</div>
    `;
  }
  return `
    <div class="section-title">Master Data Review</div>
    <div class="review-panel">
      ${openReviews.length ? "" : '<div class="muted-panel">All master data review items are resolved.</div>'}
      ${reviews.map(renderMasterDataReview).join("")}
    </div>
  `;
}

function renderMasterDataReview(review) {
  const suggested = review.suggested_value || parseJson(review.suggested_value_json);
  const disabled = !canEditAdminTab("master") || review.status !== "open" || actionBlockedByMissingCustomer(review);
  const action = reviewActionLabel(review.review_type);
  return `
    <div class="master-review-item ${review.status}">
      <div>
        <strong>${reviewTypeLabel(review.review_type)}</strong>
        <p>${safe(review.message)}</p>
        <pre class="inline-pre">${safe(reviewSuggestedText(review, suggested))}</pre>
        ${actionBlockedByMissingCustomer(review) ? '<div class="review-note">Add or match the customer before adding this record.</div>' : ""}
      </div>
      <div class="review-actions">
        <span class="badge ${review.status === "open" ? "NeedsReview" : "Booked"}">${safe(review.status)}</span>
        ${action && canEditAdminTab("master") && review.status === "open" ? `<button class="secondary" ${disabled ? "disabled" : ""} onclick="startMasterDataReviewAction(${review.id})">${action}</button>` : ""}
      </div>
    </div>
  `;
}

function actionBlockedByMissingCustomer(review) {
  return ["bill_to_address", "ship_to_address", "contact"].includes(review.review_type) && !review.matched_customer_id;
}

function reviewActionLabel(type) {
  return {
    customer: "Add Customer",
    bill_to_address: "Add Bill-To Address",
    ship_to_address: "Add Ship-To Address",
    contact: "Add Contact",
  }[type];
}

function reviewTypeLabel(type) {
  return {
    customer: "Customer",
    bill_to_address: "Bill-To Address",
    ship_to_address: "Ship-To Address",
    contact: "Customer Contact",
  }[type] || type;
}

function reviewSuggestedText(review, suggested) {
  if (review.review_type === "customer") return suggested.customer_name || "";
  if (review.review_type === "contact") return [suggested.first_name, suggested.last_name].filter(Boolean).join(" ");
  return suggested.address_text || formatSuggestedAddress(suggested);
}

function formatSuggestedAddress(suggested) {
  const locality = [suggested.city, suggested.state, suggested.zip_code].filter(Boolean).join(" ");
  return [suggested.address_line_1, suggested.address_line_2, suggested.address_line_3, locality, suggested.country].filter(Boolean).join("\n");
}

function parseJson(text) {
  try {
    return JSON.parse(text || "{}");
  } catch {
    return {};
  }
}

async function startMasterDataReviewAction(reviewId) {
  const review = (currentDetail.master_data_reviews || []).find((item) => Number(item.id) === Number(reviewId));
  if (!review || !canEditAdminTab("master")) return;
  const suggested = review.suggested_value || parseJson(review.suggested_value_json);
  pendingReviewAction = { reviewId, type: review.review_type };
  if (review.review_type === "customer") {
    await openCustomerModal();
    document.querySelector("#customerName").value = suggested.customer_name || currentDetail.purchase_order.customer_company_name || "";
    document.querySelector("#customerPaymentTerms").value = suggested.payment_terms || currentDetail.purchase_order.payment_terms || "";
    return;
  }
  if (!review.matched_customer_id) return;
  await openCustomerModal(review.matched_customer_id);
  if (review.review_type === "contact") {
    openContactModal(null, suggested);
    return;
  }
  const addressType = review.review_type === "ship_to_address" ? "ship_to" : "bill_to";
  pendingReviewAction.type = addressType;
  openAddressModal(null, addressPrefillFromReview(addressType, suggested));
}

function addressPrefillFromReview(addressType, suggested) {
  const addressText = typeof suggested === "string" ? suggested : suggested.address_text || "";
  return {
    address_type: addressType,
    label: addressType === "ship_to" ? "PO Ship To" : "PO Bill To",
    address_line_1: suggested.address_line_1 || addressText,
    address_line_2: suggested.address_line_2 || "",
    address_line_3: suggested.address_line_3 || "",
    city: suggested.city || "",
    state: suggested.state || "",
    country: suggested.country || "",
    zip_code: suggested.zip_code || "",
  };
}

async function resolveMasterDataReview(reviewId, payload = {}) {
  const data = await api(`/api/master-data-reviews/${reviewId}/resolve`, { method: "POST", body: JSON.stringify(payload) });
  currentDetail = data;
  if (selectedId) renderDetail();
}

async function savePO(context = "", shouldRefresh = true) {
  if (!canEditDashboard()) return;
  const payload = readFields(headerFields, "po", context);
  payload.bill_to_address_structured_json = readStructuredAddress("bill_to", context);
  payload.ship_to_address_structured_json = readStructuredAddress("ship_to", context);
  await api(`/api/purchase-orders/${selectedId}`, { method: "PUT", body: JSON.stringify(payload) });
  if (shouldRefresh) await refresh();
}

async function markExtractionReviewed() {
  if (!canEditDashboard()) return;
  await api(`/api/purchase-orders/${selectedId}/mark-reviewed`, { method: "PUT", body: "{}" });
  await refresh();
}

async function quickStatus(status) {
  if (!canEditDashboard()) return;
  await api(`/api/purchase-orders/${selectedId}`, { method: "PUT", body: JSON.stringify({ status }) });
  await refresh();
}

async function saveLine(id, context = "", shouldRefresh = true) {
  if (!canEditDashboard()) return;
  const payload = readFields(lineFields, `line_${id}`, context);
  await api(`/api/purchase-orders/${selectedId}/lines/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  if (shouldRefresh) await refresh();
}

async function deleteLine(id) {
  if (!canEditDashboard()) return;
  await api(`/api/purchase-orders/${selectedId}/lines/${id}`, { method: "DELETE" });
  await refresh();
}

async function addLine() {
  if (!canEditDashboard()) return;
  await api(`/api/purchase-orders/${selectedId}/lines`, {
    method: "POST",
    body: JSON.stringify({ line_number: String(currentDetail.lines.length + 1), unit_of_measure: "EA" }),
  });
  await refresh();
}

async function deletePO(event, id) {
  event.stopPropagation();
  if (!canEditDashboard()) return;
  if (!confirm("Are you sure? Deleting PO cannot be reversed.")) {
    return;
  }
  await api(`/api/purchase-orders/${id}`, { method: "DELETE" });
  if (selectedId === id) {
    selectedId = null;
    currentDetail = null;
    document.querySelector("#detail").innerHTML =
      '<div class="empty-state branded-empty"><img src="/assets/brand/mascot-mountain-goat-default-240.png" alt="" aria-hidden="true" /><strong>Here&rsquo;s the smartest route.</strong><span>Select a purchase order to review extracted fields and source text.</span></div>';
  }
  await Promise.all([loadSummary(), loadPOs(), loadLogs()]);
}

function readFields(fields, prefix, context = "") {
  const payload = {};
  for (const [key, , type = "text"] of fields) {
    if (type === "readonly" || type === "lineTotal") continue;
    const value = document.querySelector(`#${scopedId(`${prefix}_${key}`, context)}`).value;
    payload[key] = type === "number" && value !== "" ? Number(value) : normalizeFieldValue(type, value);
  }
  return payload;
}

function normalizeFieldValue(type, value) {
  if (value === "") return null;
  if (type === "date" && value) return value.slice(0, 10);
  return value;
}

async function loadLogs() {
  const rows = await api("/api/logs");
  document.querySelector("#logs").innerHTML = rows
    .map((row) => `<div class="log-row"><strong>${row.level}</strong> ${safe(row.message)} <span>${safe(row.created_at)}</span></div>`)
    .join("");
}

async function switchView(view) {
  if (view === "admin" && !canViewAdmin()) {
    alert("You do not have access to Admin.");
    view = canViewDashboard() ? "dashboard" : "none";
  }
  if (view === "dashboard" && !canViewDashboard()) {
    alert("You do not have access to the PO Dashboard.");
    view = canViewAdmin() ? "admin" : "none";
  }
  const dashboard = document.querySelector("#dashboardView");
  const admin = document.querySelector("#adminView");
  document.querySelector("#dashboardViewBtn").classList.toggle("active-view", view === "dashboard");
  document.querySelector("#adminViewBtn").classList.toggle("active-view", view === "admin");
  dashboard.classList.toggle("hidden", view !== "dashboard");
  admin.classList.toggle("hidden", view !== "admin");
  if (view === "admin") {
    await loadAdminData();
    switchAdminTab(canViewAdminTab(activeAdminTab) ? activeAdminTab : firstAvailableAdminTab());
  } else if (view === "dashboard") {
    await refresh();
  }
}

async function loadAdminData() {
  if (!canViewAdmin()) return;
  const canViewCanonicalDiagnostics = canViewAdminTab("master") || canViewAdminTab("setup") || canViewAdminTab("erp");
  const [
    orderTypeData,
    departmentData,
    paymentTermData,
    inboxData,
    exportDestinationData,
    xrefData,
    customerData,
    productData,
    canonicalData,
    userData,
    reportingData,
    oracleEbsData,
  ] = await Promise.all([
    canViewAdminTab("setup") ? safeApi("/api/order-types", []) : Promise.resolve([]),
    canViewAdminTab("setup") ? safeApi("/api/departments", []) : Promise.resolve([]),
    canViewAdminTab("setup") ? safeApi("/api/payment-terms", []) : Promise.resolve([]),
    canViewAdminTab("setup") ? safeApi("/api/inbox-accounts", { accounts: [], sync_runs: [] }) : Promise.resolve({ accounts: [], sync_runs: [] }),
    canViewAdminTab("setup") ? safeApi("/api/export-destinations", { destinations: [] }) : Promise.resolve({ destinations: [] }),
    canViewAdminTab("master") ? safeApi("/api/customer-part-xrefs", []) : Promise.resolve([]),
    canViewAdminTab("master") ? safeApi("/api/customers", []) : Promise.resolve([]),
    canViewAdminTab("master") ? safeApi("/api/products", { products: [] }) : Promise.resolve({ products: [] }),
    canViewCanonicalDiagnostics ? safeApi("/api/canonical-master-data", canonicalFallbackData()) : Promise.resolve(canonicalFallbackData()),
    canViewUsers() ? safeApi("/api/users", []) : Promise.resolve([]),
    canViewAdminTab("analytics") ? safeApi("/api/reporting/operations", {}) : Promise.resolve({}),
    canViewAdminTab("erp") ? safeApi("/api/erp/oracle-ebs", { manifest: null, profile: null, mapping_summary: {} }) : Promise.resolve({ manifest: null, profile: null, mapping_summary: {} }),
  ]);
  orderTypes = orderTypeData;
  departments = departmentData;
  paymentTerms = paymentTermData;
  inboxAccounts = inboxData.accounts || [];
  inboxSyncRuns = inboxData.sync_runs || [];
  exportDestinations = exportDestinationData.destinations || [];
  xrefs = xrefData;
  customers = customerData;
  products = productData.products || [];
  canonicalMasterData = canonicalData || canonicalFallbackData();
  users = userData;
  operationsMetrics = reportingData || {};
  oracleEbsConfig = oracleEbsData || { manifest: null, profile: null, mapping_summary: {} };
  configureAdminAccessUi();
  renderOrderTypes();
  renderXrefs();
  renderUsers();
  renderCustomers();
  renderProducts();
  renderCanonicalMasterData();
  renderSetupReferenceData();
  renderDepartments();
  renderPaymentTerms();
  renderInboxAccounts(inboxData.gmail_configured, inboxData.outlook_configured);
  renderSyncRuns();
  renderExportDestinations();
  renderOperationsMetrics();
  renderOracleEbsProfile();
  renderErpDiagnostics();
  if (canViewAdminTab("testing")) {
    await loadTestingData();
  } else {
    testDocuments = [];
    evaluationData = { run: null, results: [] };
    inboxDetectionResults = [];
    inboxMessageRecords = [];
  }
  applyAdminPaneReadonlyStates();
}

function switchAdminTab(tab) {
  if (!tab || !canViewAdminTab(tab)) tab = firstAvailableAdminTab();
  if (!tab) return;
  activeAdminTab = tab;
  for (const name of adminTabs) {
    document.querySelector(`#adminTab${capitalize(name)}`).classList.toggle("hidden", name !== tab);
    document.querySelector(`#adminTab${capitalize(name)}Btn`).classList.toggle("active-admin-tab", name === tab);
  }
  applyAdminPaneReadonlyStates();
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function configureAdminAccessUi() {
  for (const tab of adminTabs) {
    const canView = canViewAdminTab(tab);
    document.querySelector(`#adminTab${capitalize(tab)}Btn`).classList.toggle("hidden", !canView);
    if (!canView) document.querySelector(`#adminTab${capitalize(tab)}`).classList.add("hidden");
  }
  document.querySelector("#usersPanel").classList.toggle("hidden", !canViewUsers());
}

function applyAdminPaneReadonlyStates() {
  for (const tab of adminTabs) {
    const pane = document.querySelector(`#adminTab${capitalize(tab)}`);
    if (!pane || !canViewAdminTab(tab)) continue;
    const readonly = !canEditAdminTab(tab);
    pane.classList.toggle("admin-view-only-pane", readonly);
    if (!readonly) continue;
    for (const control of pane.querySelectorAll("input, textarea, select, button")) {
      if (control.type === "hidden") continue;
      const label = (control.textContent || control.value || control.id || "").trim().toLowerCase();
      const id = control.id || "";
      const isReadAction = label.startsWith("download") || id.toLowerCase().includes("download");
      control.disabled = !isReadAction;
    }
  }
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

function renderDepartments() {
  document.querySelector("#departmentRows").innerHTML = departments
    .map(
      (row) => `
      <tr>
        <td><input id="department_name_${row.id}" value="${safe(row.name)}" /></td>
        <td>${row.is_active ? "Active" : "Inactive"}</td>
        <td>
          <button class="secondary" onclick="saveDepartment(${row.id})">Save</button>
          <button class="danger" onclick="deleteDepartment(${row.id})">Delete</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

async function loadTestingData() {
  if (!canViewAdminTab("testing")) return;
  const [documentsData, evaluationsData, gmailData, outlookData, openaiData, detectionData, learningData] = await Promise.all([
    api("/api/testing/documents"),
    api("/api/testing/evaluations"),
    api("/api/gmail-oauth-config"),
    api("/api/outlook-oauth-config"),
    api("/api/openai-extraction-config"),
    api("/api/inbox-detection-results"),
    api("/api/extraction-learning"),
  ]);
  testDocuments = documentsData.documents || [];
  evaluationData = evaluationsData.latest || { run: null, results: [] };
  gmailConfig = gmailData || {};
  outlookConfig = outlookData || {};
  openaiConfig = openaiData || {};
  inboxDetectionResults = detectionData.results || [];
  inboxMessageRecords = detectionData.messages || [];
  extractionLearning = learningData || extractionLearning;
  renderTestDocuments();
  renderEvaluation();
  renderOpenAIConfig();
  renderGmailConfig();
  renderOutlookConfig();
  renderDetectionResults();
  renderExtractionLearning();
  applyAdminPaneReadonlyStates();
}

function renderTestDocuments() {
  document.querySelector("#testDocumentRows").innerHTML = testDocuments
    .map(
      (row) => `
      <tr>
        <td>${safe(row.original_filename || row.filename)}</td>
        <td><select id="test_doc_type_${row.id}">${testDocumentTypes().map((type) => `<option value="${type}" ${row.document_type === type ? "selected" : ""}>${type}</option>`).join("")}</select></td>
        <td><select id="test_expected_${row.id}">${testClassifications().map((type) => `<option value="${type}" ${row.expected_classification === type ? "selected" : ""}>${type}</option>`).join("")}</select></td>
        <td>${row.has_golden_answer ? "Yes" : "No"}</td>
        <td>${row.last_detected_classification ? `${safe(row.last_detected_classification)} ${row.last_detection_correct ? "OK" : "Review"}` : ""}</td>
        <td><input id="test_notes_${row.id}" value="${safe(row.notes)}" /></td>
        <td>
          <button class="secondary table-action" onclick="saveTestDocument(${row.id})">Save</button>
          <button class="secondary table-action" onclick="openGoldenModal(${row.id})">Golden</button>
          <button class="danger table-action" onclick="deleteTestDocument(${row.id})">Delete</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

function testDocumentTypes() {
  return ["po_pdf", "po_email_body", "scanned_po_pdf", "quote", "order_confirmation", "invoice", "rfq", "random_email", "other"];
}

function testClassifications() {
  return ["purchase_order", "possible_po", "not_po"];
}

async function uploadTestDocuments(fileList) {
  if (!canEditAdminTab("testing") || !fileList?.length) return;
  const form = new FormData();
  Array.from(fileList).forEach((file) => form.append("files", file));
  setMessage("#testingMessage", "Uploading test documents...");
  const res = await fetch("/api/testing/documents/upload", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok || data.error) {
    setMessage("#testingMessage", data.error || "Upload failed.", "error");
    return;
  }
  testDocuments = data.documents || [];
  const rejected = data.rejected_files?.length ? ` Rejected: ${data.rejected_files.map((file) => file.filename).join(", ")}.` : "";
  setMessage("#testingMessage", `Uploaded ${data.imported}.${rejected}`, data.rejected_files?.length ? "error" : "success");
  renderTestDocuments();
}

async function saveTestDocument(id) {
  if (!canEditAdminTab("testing")) return;
  const payload = {
    document_type: document.querySelector(`#test_doc_type_${id}`).value,
    expected_classification: document.querySelector(`#test_expected_${id}`).value,
    notes: document.querySelector(`#test_notes_${id}`).value.trim(),
  };
  const data = await api(`/api/testing/documents/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  testDocuments = data.documents || [];
  renderTestDocuments();
}

async function deleteTestDocument(id) {
  if (!canEditAdminTab("testing")) return;
  if (!confirm("Delete this test document?")) return;
  const data = await api(`/api/testing/documents/${id}`, { method: "DELETE" });
  testDocuments = data.documents || [];
  renderTestDocuments();
}

function renderEvaluation() {
  const run = evaluationData.run;
  document.querySelector("#evaluationSummary").innerHTML = run
    ? `
      ${metric("Docs", run.document_count)}
      ${metric("Mode", safe(run.extraction_mode || "rule_based"))}
      ${metric("TP", run.true_positives)}
      ${metric("FP", run.false_positives)}
      ${metric("TN", run.true_negatives)}
      ${metric("FN", run.false_negatives)}
      ${metric("Fields", pct(run.field_match_rate))}
      ${metric("Lines", pct(run.line_match_rate))}
      ${metric("Confidence", pct(run.average_confidence))}
    `
    : '<div class="muted-panel">No evaluation run yet.</div>';
  document.querySelector("#evaluationRows").innerHTML = (evaluationData.results || [])
    .map((row) => {
      const fields = parseJson(row.field_results_json);
      const lines = parseJson(row.line_results_json);
      return `
      <tr title="${safe(JSON.stringify({ fields, lines }, null, 2))}">
        <td>${safe(row.original_filename || row.filename)}</td>
        <td>${safe(row.expected_classification)}</td>
        <td>${safe(row.detected_classification)}</td>
        <td>${row.detection_correct ? "Yes" : "No"}</td>
        <td>${pct(matchRateFromFieldResults(fields))}</td>
        <td>${lineRateText(lines)}</td>
        <td>${row.processing_latency_ms} ms</td>
      </tr>
    `;
    })
    .join("");
}

function matchRateFromFieldResults(fields) {
  const values = Object.values(fields || {});
  const compared = values.filter((item) => item.expected || item.actual);
  if (!compared.length) return null;
  return compared.filter((item) => item.match).length / compared.length;
}

function lineRateText(lines) {
  if (!lines || !lines.lines) return "";
  let compared = 0;
  let matched = 0;
  for (const line of lines.lines) {
    for (const item of Object.values(line)) {
      compared += 1;
      if (item.match) matched += 1;
    }
  }
  return compared ? pct(matched / compared) : "";
}

async function runEvaluation() {
  if (!canEditAdminTab("testing")) return;
  setMessage("#testingMessage", "Running extraction evaluation...");
  const data = await api("/api/testing/evaluations/run", { method: "POST", body: JSON.stringify({ extraction_mode: document.querySelector("#evaluationMode").value }) });
  if (data.error) {
    setMessage("#testingMessage", data.error, "error");
    return;
  }
  evaluationData = data;
  setMessage("#testingMessage", "Evaluation complete.", "success");
  renderEvaluation();
  await loadTestingData();
}

function renderOpenAIConfig() {
  const savedModel = openaiConfig.model || "gpt-4.1-mini";
  const options = openAIModelOptions.includes(savedModel) ? openAIModelOptions : [savedModel, ...openAIModelOptions];
  document.querySelector("#openaiConfigStatus").innerHTML = `
    ${metric("API Key", openaiConfig.api_key_configured ? "Configured" : "Not configured")}
    ${metric("Model", safe(savedModel))}
    ${metric("AI Extraction", openaiConfig.use_ai_extraction ? "On" : "Off")}
    ${metric("Secret Storage", safe(openaiConfig.encrypted_storage || ""))}
  `;
  document.querySelector("#openaiModel").innerHTML = options
    .map((model) => `<option value="${safe(model)}" ${model === savedModel ? "selected" : ""}>${openAIModelOptions.includes(model) ? safe(model) : `Current: ${safe(model)}`}</option>`)
    .join("");
  document.querySelector("#useAiExtraction").checked = Boolean(openaiConfig.use_ai_extraction);
  document.querySelector("#openaiApiKey").placeholder = openaiConfig.api_key_configured ? "API key configured - leave blank to keep it" : "Paste OpenAI API key";
}

async function loadExtractionLearning() {
  if (!canViewAdminTab("testing")) return;
  const customer = encodeURIComponent(document.querySelector("#learningCustomerFilter").value.trim());
  const field = encodeURIComponent(document.querySelector("#learningFieldFilter").value.trim());
  extractionLearning = await api(`/api/extraction-learning?customer=${customer}&field=${field}`);
  renderExtractionLearning();
}

function renderExtractionLearning() {
  const summary = extractionLearning.summary || {};
  document.querySelector("#learningSummary").innerHTML = `
    ${metric("Runs", summary.total_runs || 0)}
    ${metric("Successful", summary.successful_runs || 0)}
    ${metric("Failed", summary.failed_runs || 0)}
    ${metric("Corrections", summary.total_feedback || 0)}
  `;
  document.querySelector("#learningFieldRows").innerHTML = miniList(extractionLearning.corrected_fields || [], "field_name");
  document.querySelector("#learningCustomerRows").innerHTML = miniList(extractionLearning.corrections_by_customer || [], "customer_company_name");
  document.querySelector("#learningFeedbackRows").innerHTML = (extractionLearning.recent_feedback || [])
    .map(
      (row) => `
      <tr>
        <td>${safe(row.created_at)}</td>
        <td>${safe(row.customer_company_name)}</td>
        <td>${safe(row.po_number)}</td>
        <td>${safe(row.field_name)}</td>
        <td>${safe(row.extracted_value)}</td>
        <td>${safe(row.corrected_value)}</td>
        <td>${safe(row.user_email)}</td>
        <td>${safe(row.source_attachment_filename)}</td>
      </tr>
    `,
    )
    .join("");
  document.querySelector("#learningFailureRows").innerHTML = (extractionLearning.recent_failures || [])
    .map(
      (row) => `
      <tr>
        <td>${safe(row.created_at)}</td>
        <td>${safe(row.extraction_method)}</td>
        <td>${safe(row.model_name)}</td>
        <td>${safe(row.error_message)}</td>
      </tr>
    `,
    )
    .join("");
}

function renderPaymentTerms() {
  document.querySelector("#paymentTermRows").innerHTML = paymentTerms
    .map(
      (row) => `
      <tr>
        <td><input id="payment_term_name_${row.id}" value="${safe(row.name)}" /></td>
        <td>${row.is_active ? "Active" : "Inactive"}</td>
        <td>
          <button class="secondary" onclick="savePaymentTerm(${row.id})">Save</button>
          <button class="danger" onclick="deletePaymentTerm(${row.id})">Delete</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

function renderExportDestinations() {
  const target = document.querySelector("#exportDestinationRows");
  if (!target) return;
  target.innerHTML = (exportDestinations || [])
    .map(
      (row) => `
      <tr>
        <td>${safe(row.name)}</td>
        <td>${safe(row.destination_type)}</td>
        <td>${safe(row.endpoint_url)}</td>
        <td>${row.secret_configured ? "Configured" : "Not set"}</td>
        <td>${row.is_active ? "Active" : "Inactive"}</td>
        <td>
          <button class="danger table-action" onclick="deactivateExportDestination(${row.id})">Deactivate</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

function renderProducts() {
  const target = document.querySelector("#productRows");
  if (!target) return;
  target.innerHTML = products
    .map(
      (row) => `
      <tr>
        <td><input id="product_part_${row.id}" value="${safe(row.internal_part_number)}" /></td>
        <td><input id="product_rev_${row.id}" value="${safe(row.internal_part_revision)}" /></td>
        <td><input id="product_desc_${row.id}" value="${safe(row.description)}" /></td>
        <td><input id="product_uom_${row.id}" value="${safe(row.unit_of_measure)}" /></td>
        <td>${row.is_active ? "Active" : "Inactive"}</td>
        <td>
          <button class="secondary table-action" onclick="saveProduct(${row.id})">Save</button>
          <button class="danger table-action" onclick="deleteProduct(${row.id})">Delete</button>
        </td>
      </tr>
    `,
    )
    .join("");
}

function renderCanonicalMasterData() {
  const rows = document.querySelector("#canonicalMasterDataRows");
  if (!rows) return;
  const counts = canonicalGroupRows("master_bridge", [
    "trading_partner",
    "trading_partner_account",
    "trading_partner_site",
    "partner_role_assignment",
    "product",
    "product_org_attributes",
    "customer_product_alias",
  ]);
  rows.innerHTML = counts.length
    ? counts
        .map(
          (row) => `
      <tr>
        <td>${safe(row.label || row.table)}</td>
        <td>${row.count || 0}</td>
      </tr>
    `,
        )
        .join("")
    : '<tr><td colspan="2">Master data bridge records are not available yet.</td></tr>';
  const bridge = canonicalMasterData.bridge_counts || {};
  const bridgeLabels = {
    customers_to_accounts: "Customers to accounts",
    addresses_to_sites: "Addresses to sites",
    xrefs_to_aliases: "Xrefs to aliases",
    products_to_canonical: "Products to canonical products",
  };
  document.querySelector("#canonicalBridgeRows").innerHTML = Object.keys(bridgeLabels)
    .map((key) => `<span class="mini-pill">${bridgeLabels[key]}: ${bridge[key] || 0}</span>`)
    .join("");
  const aliases = canonicalMasterData.samples?.aliases || [];
  document.querySelector("#canonicalAliasRows").innerHTML = aliases.length
    ? aliases
        .map((row) => `<span class="mini-pill">${safe(row.account_name)}: ${safe(row.customer_product_number)} -> ${safe(row.product_number)}</span>`)
        .join("")
    : '<div class="muted-panel">No canonical aliases yet.</div>';
}

function canonicalGroupRows(groupName, fallbackTables = []) {
  const grouped = canonicalMasterData.groups?.[groupName];
  if (Array.isArray(grouped) && grouped.length) return grouped;
  const fallbackSet = new Set(fallbackTables);
  return (canonicalMasterData.counts || []).filter((row) => fallbackSet.has(row.table));
}

function renderSetupReferenceData() {
  const rows = document.querySelector("#setupReferenceRows");
  if (!rows) return;
  const counts = canonicalGroupRows("setup_reference", [
    "organization_unit",
    "selling_context",
    "fulfillment_location",
    "unit_of_measure",
    "uom_alias",
    "uom_conversion",
    "currency",
    "payment_terms",
    "shipping_terms",
    "freight_terms",
    "delivery_method",
    "price_reference",
    "order_document_type",
    "line_document_type",
  ]);
  rows.innerHTML = counts.length
    ? counts
        .map(
          (row) => `
      <tr>
        <td>${safe(row.label || row.table)}</td>
        <td>${row.count || 0}</td>
      </tr>
    `,
        )
        .join("")
    : '<tr><td colspan="2">ERP reference data is not available yet.</td></tr>';
  const samples = canonicalMasterData.samples?.setup_references || [];
  const setupBridgeCount = canonicalMasterData.bridge_counts?.order_types_to_document_types || 0;
  const sampleTarget = document.querySelector("#setupReferenceSamples");
  if (!sampleTarget) return;
  const sampleHtml = samples
    .map((row) => `<span class="mini-pill">${safe(row.surface)}: ${safe(row.display_name)}${row.detail ? ` (${safe(row.detail)})` : ""}</span>`)
    .join("");
  const bridgeHtml = `<span class="mini-pill">Order types to document types: ${setupBridgeCount}</span>`;
  sampleTarget.innerHTML = samples.length || setupBridgeCount
    ? `${bridgeHtml}${sampleHtml}`
    : '<div class="muted-panel">No ERP reference values have been synced or backfilled yet.</div>';
}

function renderErpDiagnostics() {
  const rows = document.querySelector("#erpDiagnosticRows");
  if (!rows) return;
  const counts = canonicalGroupRows("erp_diagnostics", [
    "erp_system",
    "erp_profile",
    "custom_field_definition",
    "custom_field_value",
    "external_id_map",
    "validation_rule",
  ]);
  rows.innerHTML = counts.length
    ? counts
        .map(
          (row) => `
      <tr>
        <td>${safe(row.label || row.table)}</td>
        <td>${row.count || 0}</td>
      </tr>
    `,
        )
        .join("")
    : '<tr><td colspan="2">ERP diagnostics are not available yet.</td></tr>';
  const maps = canonicalMasterData.samples?.external_id_maps || [];
  const mapTarget = document.querySelector("#erpExternalMapSamples");
  if (!mapTarget) return;
  mapTarget.innerHTML = maps.length
    ? maps
        .map((row) => `<span class="mini-pill">${safe(row.canonical_entity_type)} ${safe(row.canonical_entity_id)} -> ${safe(row.external_entity_type)} ${safe(row.external_id || row.external_code)}</span>`)
        .join("")
    : '<div class="muted-panel">No external ID maps yet.</div>';
}

async function refreshCanonicalBackfill() {
  if (!canEditAdminTab("master")) return;
  const button = document.querySelector("#canonicalBackfillBtn");
  button.disabled = true;
  setMessage("#canonicalMasterDataMessage", "Refreshing canonical backfill...");
  try {
    canonicalMasterData = await api("/api/canonical-master-data/backfill", { method: "POST", body: JSON.stringify({}) });
    const created = Object.values(canonicalMasterData.backfill || {}).reduce((total, value) => total + Number(value || 0), 0);
    renderCanonicalMasterData();
    renderSetupReferenceData();
    renderErpDiagnostics();
    setMessage("#canonicalMasterDataMessage", `Canonical backfill refreshed. ${created} new bridge records created.`, "success");
  } catch (error) {
    setMessage("#canonicalMasterDataMessage", error.message || "Canonical backfill failed.", "error");
  } finally {
    button.disabled = false;
  }
}

function setControlValue(id, value) {
  const el = document.querySelector(`#${id}`);
  if (el) el.value = value ?? "";
}

function renderOracleEbsProfile() {
  const status = document.querySelector("#oracleEbsStatus");
  if (!status) return;
  const profile = oracleEbsConfig.profile || {};
  const settings = profile.settings || {};
  const system = profile.system || {};
  setControlValue("oracleSystemName", system.system_name || "Oracle EBS");
  setControlValue("oracleEnvironment", system.environment || "sandbox");
  setControlValue("oracleConnectionMode", system.connection_mode || "api");
  setControlValue("oracleWriteMode", profile.write_mode || "preview");
  document.querySelector("#oracleActiveFlag").checked = profile.active_flag !== false;
  setControlValue("oracleUserId", settings.user_id);
  setControlValue("oracleResponsibilityId", settings.responsibility_id);
  setControlValue("oracleRespApplicationId", settings.resp_application_id);
  setControlValue("oracleSecurityGroupId", settings.security_group_id);
  setControlValue("oracleOrgId", settings.org_id);
  setControlValue("oracleNlsLanguage", settings.nls_language || "AMERICAN");
  setControlValue("oracleOrderSourceId", settings.order_source_id);
  setControlValue("oracleOrderTypeId", settings.order_type_id);
  setControlValue("oracleLineTypeId", settings.line_type_id);
  setControlValue("oraclePriceReferenceId", settings.price_reference_id);
  setControlValue("oracleFulfillmentOrgId", settings.fulfillment_org_id);
  setControlValue("oracleEndpointUrl", settings.endpoint_url);
  setControlValue("oracleCredentialReference", settings.credential_reference);
  setControlValue("oracleApiUsername", settings.api_username);
  setControlValue("oracleApiPassword", "");
  const manifest = oracleEbsConfig.manifest || {};
  status.innerHTML = `
    ${metric("Adapter", manifest.adapter_code || "oracle_ebs_order_entry")}
    ${metric("Profile", profile.id ? "Configured" : "Not Configured")}
    ${metric("Mode", profile.write_mode || "preview")}
    ${metric("Secret", profile.secret_configured ? "Configured" : "Not Set")}
  `;
  document.querySelector("#oracleManifestSummary").innerHTML = `
    ${metric("ERP Family", manifest.erp_family || "oracle_ebs")}
    ${metric("Transaction", manifest.supported_transaction || "entered_sales_order")}
    ${metric("Context Fields", (manifest.required_context_fields || []).length)}
    ${metric("Capabilities", (manifest.capabilities || []).length)}
  `;
  const mappings = oracleEbsConfig.mapping_summary || {};
  document.querySelector("#oracleMappingSummary").innerHTML = Object.keys(mappings).length
    ? Object.keys(mappings)
        .sort()
        .map((key) => `<span class="mini-pill">${safe(key)}: ${mappings[key]}</span>`)
        .join("")
    : '<div class="muted-panel">No Oracle external ID mappings yet.</div>';
}

async function saveOracleEbsProfile() {
  if (!canEditAdminTab("erp")) return;
  const payload = {
    system_name: document.querySelector("#oracleSystemName").value.trim(),
    environment: document.querySelector("#oracleEnvironment").value,
    connection_mode: document.querySelector("#oracleConnectionMode").value,
    write_mode: document.querySelector("#oracleWriteMode").value,
    active_flag: document.querySelector("#oracleActiveFlag").checked,
    user_id: document.querySelector("#oracleUserId").value.trim(),
    responsibility_id: document.querySelector("#oracleResponsibilityId").value.trim(),
    resp_application_id: document.querySelector("#oracleRespApplicationId").value.trim(),
    security_group_id: document.querySelector("#oracleSecurityGroupId").value.trim(),
    org_id: document.querySelector("#oracleOrgId").value.trim(),
    nls_language: document.querySelector("#oracleNlsLanguage").value.trim(),
    order_source_id: document.querySelector("#oracleOrderSourceId").value.trim(),
    order_type_id: document.querySelector("#oracleOrderTypeId").value.trim(),
    line_type_id: document.querySelector("#oracleLineTypeId").value.trim(),
    price_reference_id: document.querySelector("#oraclePriceReferenceId").value.trim(),
    fulfillment_org_id: document.querySelector("#oracleFulfillmentOrgId").value.trim(),
    endpoint_url: document.querySelector("#oracleEndpointUrl").value.trim(),
    credential_reference: document.querySelector("#oracleCredentialReference").value.trim(),
    api_username: document.querySelector("#oracleApiUsername").value.trim(),
    api_password: document.querySelector("#oracleApiPassword").value,
  };
  const data = await api("/api/erp/oracle-ebs", { method: "POST", body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#oracleEbsMessage", data.error, "error");
    return;
  }
  oracleEbsConfig = data;
  renderOracleEbsProfile();
  setMessage("#oracleEbsMessage", data.profile?.secret_configured ? "Oracle EBS profile saved. Secret is configured." : "Oracle EBS profile saved. No password secret is configured.", data.profile?.secret_configured ? "success" : "");
}

async function loadReviewTasks() {
  if (!canViewDashboard()) return;
  const params = new URLSearchParams({
    status: document.querySelector("#exceptionStatusFilter")?.value || "open",
    severity: document.querySelector("#exceptionSeverityFilter")?.value || "",
    customer: document.querySelector("#exceptionCustomerFilter")?.value || "",
    sort: document.querySelector("#exceptionSortFilter")?.value || "severity",
  });
  const data = await api(`/api/review-tasks?${params.toString()}`);
  reviewTasks = data.tasks || [];
  reviewTaskUsers = data.users || [];
  renderReviewTasks();
}

function renderReviewTasks() {
  const tbody = document.querySelector("#exceptionRows");
  if (!tbody) return;
  tbody.innerHTML = reviewTasks.length
    ? reviewTasks
        .map(
      (task) => `
        <tr>
          <td><input type="checkbox" class="exception-check" value="${task.id}" /></td>
          <td>${safe(task.severity)}</td>
          <td>${safe(task.priority || "")}</td>
          <td>${safe(task.po_number)}</td>
          <td>${safe(task.customer_company_name)}</td>
          <td>${safe(task.message)}</td>
          <td>${safe(task.field_name)}</td>
          <td>${safe(task.current_value)}</td>
          <td>${pct(task.confidence)}</td>
          <td>${task.age_hours != null ? `${safe(task.age_hours)}h` : ""}</td>
          <td>${safe(task.assigned_to_display)}</td>
          <td>${safe(task.created_at)}</td>
          <td>
            ${task.purchase_order_id ? `<button class="secondary table-action" onclick="openDetail(${task.purchase_order_id})">Open PO</button>` : ""}
            ${canEditDashboard() ? `<button class="secondary table-action" onclick="assignSingleException(${task.id})">Assign</button>` : ""}
            ${canEditDashboard() ? `<button class="secondary table-action" onclick="resolveReviewTask(${task.id})">Resolve</button><button class="secondary table-action" onclick="ignoreReviewTask(${task.id})">Ignore</button>` : ""}
          </td>
        </tr>
      `,
        )
        .join("")
    : '<tr><td colspan="12">No matching exceptions.</td></tr>';
}

function selectedExceptionIds() {
  return Array.from(document.querySelectorAll(".exception-check:checked")).map((input) => Number(input.value));
}

async function bulkExceptionAction(action) {
  if (!canEditDashboard()) return;
  const taskIds = selectedExceptionIds();
  if (!taskIds.length) {
    alert("Select at least one exception.");
    return;
  }
  const data = await api("/api/review-tasks/bulk", { method: "POST", body: JSON.stringify({ action, task_ids: taskIds }) });
  reviewTasks = data.tasks || [];
  reviewTaskUsers = data.users || [];
  renderReviewTasks();
}

async function assignSingleException(taskId) {
  if (!canEditDashboard()) return;
  const options = reviewTaskUsers.map((user) => `${user.id}: ${user.display_name || user.email}`).join("\n");
  const value = prompt(`Assign to user id:\n${options}`);
  if (value == null) return;
  const assignedTo = value.trim() ? Number(value.trim().split(":", 1)[0]) : null;
  const data = await api(`/api/review-tasks/${taskId}/assign`, { method: "POST", body: JSON.stringify({ assigned_to_user_id: assignedTo }) });
  reviewTasks = data.tasks || [];
  renderReviewTasks();
}

function openNextException() {
  const task = reviewTasks.find((item) => item.status === "open" && item.purchase_order_id);
  if (task) openDetail(task.purchase_order_id);
}

function miniList(rows, labelKey) {
  if (!rows.length) return '<div class="muted-panel">No data yet.</div>';
  return rows.map((row) => `<span class="mini-pill">${safe(row[labelKey])}: ${row.count}</span>`).join("");
}

function renderOperationsMetrics() {
  const inbox = operationsMetrics.inbox || {};
  const statusCounts = operationsMetrics.status_counts || {};
  document.querySelector("#operationsSummary").innerHTML = `
    ${metric("POs", operationsMetrics.total_purchase_orders || 0)}
    ${metric("Received", statusCounts.Received || 0)}
    ${metric("Booked", statusCounts.Booked || 0)}
    ${metric("Open Exceptions", operationsMetrics.open_exceptions || 0)}
    ${metric("Exception Rate", pct(operationsMetrics.exception_rate || 0))}
    ${metric("Avg Confidence", pct(operationsMetrics.average_extraction_confidence || 0))}
    ${metric("Corrections", operationsMetrics.manual_correction_count || 0)}
    ${metric("Inbox Seen", inbox.messages_seen || 0)}
    ${metric("Inbox POs", inbox.purchase_orders_created || 0)}
  `;
  document.querySelector("#receivedTrendRows").innerHTML = miniList(operationsMetrics.received_by_day || [], "day");
  document.querySelector("#bookedTrendRows").innerHTML = miniList(operationsMetrics.booked_by_day || [], "day");
  document.querySelector("#topCustomerRows").innerHTML = miniList(operationsMetrics.top_customers || [], "customer");
  document.querySelector("#topExceptionRows").innerHTML = miniList(operationsMetrics.top_exception_reasons || [], "reason_code");
  document.querySelector("#inboxReliabilityRows").innerHTML = (operationsMetrics.inbox_by_account || []).length
    ? operationsMetrics.inbox_by_account.map((row) => `<span class="mini-pill">${safe(row.display_name || row.provider)}: seen ${row.messages_seen || 0}, POs ${row.purchase_orders_created || 0}, errors ${row.error_count || 0}</span>`).join("")
    : '<div class="muted-panel">No inbox sync data yet.</div>';
}

async function refreshOperationsMetrics() {
  if (!canViewAdminTab("analytics")) return;
  const button = document.querySelector("#refreshOperationsBtn");
  button.disabled = true;
  button.textContent = "Refreshing...";
  setMessage("#operationsMessage", "Refreshing operations metrics...");
  try {
    operationsMetrics = await api("/api/reporting/operations");
    renderOperationsMetrics();
    setMessage("#operationsMessage", "Metrics refreshed.", "success");
  } catch (error) {
    setMessage("#operationsMessage", error.message || "Metrics refresh failed.", "error");
  } finally {
    button.disabled = false;
    button.textContent = "Refresh Metrics";
  }
}

function renderInboxAccounts(gmailConfigured = false, outlookConfigured = false) {
  document.querySelector("#connectGmailBtn").title = gmailConfigured ? "Start Gmail OAuth" : "Set Gmail config first";
  document.querySelector("#connectOutlookBtn").title = outlookConfigured ? "Start Outlook OAuth" : "Set Outlook config first";
  const canEditSetup = canEditAdminTab("setup");
  document.querySelector("#inboxAccountRows").innerHTML = inboxAccounts
    .map(
      (row) => `
      <tr>
        <td>${safe(row.provider)}</td>
        <td><input id="inbox_name_${row.id}" value="${safe(row.display_name)}" /></td>
        <td><input id="inbox_monitored_${row.id}" value="${safe(row.monitored_email)}" /></td>
        <td><input id="inbox_folder_${row.id}" value="${safe(row.folder || "INBOX")}" /></td>
        <td>${row.is_enabled ? "Enabled" : "Disabled"}</td>
        <td>${inboxHealthBadge(row)}</td>
        <td>${safe(row.last_sync_at)}</td>
        <td>
          ${
            canEditSetup
              ? `
            <button class="secondary table-action" onclick="openInboxConfig(${row.id})">Configure</button>
            <button class="secondary table-action" onclick="saveInboxAccount(${row.id})">Save</button>
            <button class="secondary table-action" onclick="toggleInboxAccount(${row.id}, ${row.is_enabled ? "false" : "true"})">${row.is_enabled ? "Deactivate" : "Activate"}</button>
            <button class="secondary table-action" onclick="syncInboxAccount(${row.id})" ${row.is_enabled ? "" : "disabled"}>Sync Now</button>
            <button class="danger table-action" onclick="deleteInboxAccount(${row.id})">Delete</button>
          `
              : '<span class="view-only-note">View Only</span>'
          }
        </td>
      </tr>
    `,
    )
    .join("");
}

function renderGmailConfig() {
  document.querySelector("#gmailClientId").value = gmailConfig.client_id || "";
  document.querySelector("#gmailRedirectUri").value = gmailConfig.redirect_uri || "http://127.0.0.1:8000/api/oauth/gmail/callback";
  document.querySelector("#gmailScopes").value = gmailConfig.scopes || "https://www.googleapis.com/auth/gmail.readonly";
  document.querySelector("#gmailClientSecret").placeholder = gmailConfig.client_secret_configured ? "Secret configured - leave blank to keep it" : "Google OAuth client secret";
}

function inboxHealthBadge(row) {
  const status = !row.is_enabled ? "Disabled" : row.sync_status === "auth_failed" ? "Auth failed" : row.sync_status === "failed" ? "Last sync failed" : row.connected_email ? "Connected" : "Needs configuration";
  return `<span class="badge ${status.replace(/\s/g, "")}">${safe(status)}</span>`;
}

function renderOutlookConfig() {
  document.querySelector("#outlookClientId").value = outlookConfig.client_id || "";
  document.querySelector("#outlookTenant").value = outlookConfig.tenant || "common";
  document.querySelector("#outlookRedirectUri").value = outlookConfig.redirect_uri || "http://127.0.0.1:8000/api/oauth/outlook/callback";
  document.querySelector("#outlookScopes").value = outlookConfig.scopes || "offline_access User.Read Mail.Read";
  document.querySelector("#outlookClientSecret").placeholder = outlookConfig.client_secret_configured ? "Secret configured - leave blank to keep it" : "Microsoft Graph client secret";
}

function renderSyncRuns() {
  document.querySelector("#syncRunRows").innerHTML = inboxSyncRuns
    .map((row) => {
      const errors = parseJson(row.errors_json);
      return `
      <tr>
        <td>${safe(row.started_at || row.created_at)}</td>
        <td>${safe(row.provider)}</td>
        <td>${safe(row.start_at || "")}${row.end_at ? ` to ${safe(row.end_at)}` : ""}</td>
        <td>${safe(row.status)}</td>
        <td>${row.messages_seen}</td>
        <td>${row.messages_imported}</td>
        <td>${row.messages_skipped}</td>
        <td>${row.purchase_orders_created}</td>
        <td>${safe(Array.isArray(errors) ? errors.join(" ") : "")}</td>
      </tr>
    `;
    })
    .join("");
}

function renderDetectionResults() {
  document.querySelector("#detectionResultRows").innerHTML = inboxDetectionResults
    .map(
      (row) => `
      <tr>
        <td>${safe(row.created_at)}</td>
        <td>${safe(row.provider_message_id)}</td>
        <td>${safe(row.processing_status || row.detected_classification)}</td>
        <td>${pct(row.detection_confidence)}</td>
        <td>${row.attachment_count || 0}</td>
        <td>${row.duplicate_skipped ? "Yes" : "No"}</td>
        <td>${row.purchase_order_id ? safe(row.purchase_order_id) : ""}</td>
        <td>${row.processing_latency_ms || ""} ms</td>
        <td>${safe(row.error_message)} ${row.inbox_message_record_id && canEditAdminTab("testing") ? `<button class="secondary table-action" onclick="retryInboxMessage(${row.inbox_message_record_id})">Retry</button>` : ""}</td>
      </tr>
    `,
    )
    .join("");
}

async function retryInboxMessage(recordId) {
  if (!canEditAdminTab("testing")) return;
  setMessage("#testingMessage", "Retrying inbox message...");
  const data = await api(`/api/inbox-message-records/${recordId}/retry`, { method: "POST", body: "{}" });
  inboxAccounts = data.accounts || [];
  inboxSyncRuns = data.sync_runs || [];
  const detection = await api("/api/inbox-detection-results");
  inboxDetectionResults = detection.results || [];
  inboxMessageRecords = detection.messages || [];
  renderInboxAccounts(data.gmail_configured, data.outlook_configured);
  renderSyncRuns();
  renderDetectionResults();
  setMessage("#testingMessage", data.error || "Retry complete.", data.error ? "error" : "success");
}

async function addInboxAccount() {
  if (!canEditAdminTab("setup")) return;
  const payload = {
    provider: "gmail",
    display_name: document.querySelector("#inboxDisplayName").value.trim() || "Gmail Test Inbox",
    monitored_email: document.querySelector("#inboxMonitoredEmail").value.trim(),
    folder: document.querySelector("#inboxFolder").value.trim() || "INBOX",
    is_enabled: true,
  };
  const data = await api("/api/inbox-accounts", { method: "POST", body: JSON.stringify(payload) });
  inboxAccounts = data.accounts || [];
  inboxSyncRuns = data.sync_runs || [];
  setMessage("#inboxSetupMessage", "Inbox account added.", "success");
  renderInboxAccounts(data.gmail_configured, data.outlook_configured);
  renderSyncRuns();
}

async function connectGmail() {
  if (!canEditAdminTab("setup")) return;
  const data = await api("/api/inbox-accounts/gmail/connect", { method: "POST", body: "{}" });
  if (data.error) {
    setMessage("#inboxSetupMessage", data.error, "error");
    return;
  }
  if (data.auth_url) window.open(data.auth_url, "_blank");
}

async function connectOutlook() {
  if (!canEditAdminTab("setup")) return;
  const data = await api("/api/inbox-accounts/outlook/connect", { method: "POST", body: "{}" });
  if (data.error) {
    setMessage("#inboxSetupMessage", data.error, "error");
    return;
  }
  if (data.auth_url) window.open(data.auth_url, "_blank");
}

async function saveInboxAccount(id) {
  if (!canEditAdminTab("setup")) return;
  const existing = inboxAccounts.find((row) => Number(row.id) === Number(id)) || {};
  const payload = {
    display_name: document.querySelector(`#inbox_name_${id}`).value.trim(),
    monitored_email: document.querySelector(`#inbox_monitored_${id}`).value.trim(),
    folder: document.querySelector(`#inbox_folder_${id}`).value.trim(),
    is_enabled: existing.is_enabled ?? true,
    evaluate_without_attachments: existing.evaluate_without_attachments ?? false,
    sync_interval_hours: existing.sync_interval_hours || 24,
    sync_start_time: existing.sync_start_time || "02:00",
  };
  const data = await api(`/api/inbox-accounts/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  inboxAccounts = data.accounts || [];
  setMessage("#inboxSetupMessage", "Inbox account saved.", "success");
  renderInboxAccounts(data.gmail_configured, data.outlook_configured);
}

async function toggleInboxAccount(id, enabled) {
  if (!canEditAdminTab("setup")) return;
  const row = inboxAccounts.find((item) => Number(item.id) === Number(id));
  if (!row) return;
  const payload = {
    display_name: row.display_name || "",
    monitored_email: row.monitored_email || "",
    folder: row.folder || "INBOX",
    is_enabled: enabled,
    evaluate_without_attachments: row.evaluate_without_attachments ?? false,
    sync_interval_hours: row.sync_interval_hours || 24,
    sync_start_time: row.sync_start_time || "02:00",
  };
  const data = await api(`/api/inbox-accounts/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  inboxAccounts = data.accounts || [];
  setMessage("#inboxSetupMessage", "Inbox account updated.", "success");
  renderInboxAccounts(data.gmail_configured, data.outlook_configured);
}

async function openInboxConfig(id) {
  if (!canViewAdminTab("setup")) return;
  configuringInboxId = id;
  setMessage("#inboxConfigMessage", "");
  const data = await api(`/api/inbox-accounts/${id}/config`);
  if (data.error) {
    setMessage("#inboxSetupMessage", data.error, "error");
    return;
  }
  currentInboxConfig = data;
  renderInboxConfig();
  document.querySelector("#inboxConfigModal").classList.remove("hidden");
  document.querySelector("#inboxConfigModal").setAttribute("aria-hidden", "false");
}

function closeInboxConfig() {
  configuringInboxId = null;
  currentInboxConfig = null;
  document.querySelector("#inboxConfigModal").classList.add("hidden");
  document.querySelector("#inboxConfigModal").setAttribute("aria-hidden", "true");
}

function renderInboxConfig() {
  const account = currentInboxConfig?.account || {};
  const labels = currentInboxConfig?.labels || [];
  const isOutlook = account.provider === "outlook";
  document.querySelector("#configInboxName").value = account.display_name || "";
  document.querySelector("#configConnectedEmail").value = account.connected_email || "";
  document.querySelector("#configMonitoredEmail").value = account.monitored_email || "";
  document.querySelector("#configFolder").value = account.folder || "INBOX";
  document.querySelector("#configInboxEnabled").checked = Boolean(account.is_enabled);
  document.querySelector("#configEvalNoAttachments").checked = Boolean(account.evaluate_without_attachments);
  document.querySelector("#configSyncInterval").value = account.sync_interval_hours || 24;
  document.querySelector("#configSyncStart").value = account.sync_start_time || "02:00";
  document.querySelector("#configNextSync").textContent = account.next_sync_at || "Not scheduled";
  document.querySelector("#inboxLabelTitle").textContent = isOutlook ? "Outlook Folders" : "Gmail Labels";
  document.querySelector("#refreshInboxLabelsBtn").textContent = isOutlook ? "Refresh Folders" : "Refresh Labels";
  const labelList = document.querySelector("#inboxLabelList");
  if (!labels.length) {
    labelList.innerHTML = `<div class="muted-panel">No ${isOutlook ? "folders" : "labels"} cached yet. Use ${isOutlook ? "Refresh Folders" : "Refresh Labels"} after the inbox is connected.</div>`;
    return;
  }
  labelList.innerHTML = labels
    .map(
      (label) => `
      <label class="label-row">
        <input type="checkbox" data-label-id="${safe(label.label_id)}" ${label.is_selected ? "checked" : ""} />
        <span class="label-main">${safe(label.label_name || label.label_id)}</span>
        <span class="label-meta">${safe(label.label_id)}${label.label_type ? ` - ${safe(label.label_type)}` : ""}</span>
      </label>
    `,
    )
    .join("");
}

async function refreshInboxLabels() {
  if (!canEditAdminTab("setup")) return;
  if (!configuringInboxId) return;
  const account = currentInboxConfig?.account || {};
  const noun = account.provider === "outlook" ? "folders" : "labels";
  setMessage("#inboxConfigMessage", `Refreshing ${noun}...`);
  const data = await api(`/api/inbox-accounts/${configuringInboxId}/labels/refresh`, { method: "POST", body: "{}" });
  currentInboxConfig = data;
  renderInboxConfig();
  if (data.error) {
    setMessage("#inboxConfigMessage", data.error, "error");
    return;
  }
  setMessage("#inboxConfigMessage", `${account.provider === "outlook" ? "Folders" : "Labels"} refreshed.`, "success");
}

async function saveInboxConfig() {
  if (!canEditAdminTab("setup")) return;
  if (!configuringInboxId) return;
  const interval = Number(document.querySelector("#configSyncInterval").value || 24);
  if (!Number.isFinite(interval) || interval < 1) {
    setMessage("#inboxConfigMessage", "Sync interval must be at least 1 hour.", "error");
    return;
  }
  const selectedLabelIds = Array.from(document.querySelectorAll("#inboxLabelList input[type='checkbox']:checked")).map((input) => input.dataset.labelId);
  const payload = {
    display_name: document.querySelector("#configInboxName").value.trim(),
    monitored_email: document.querySelector("#configMonitoredEmail").value.trim(),
    folder: document.querySelector("#configFolder").value.trim() || "INBOX",
    is_enabled: document.querySelector("#configInboxEnabled").checked,
    evaluate_without_attachments: document.querySelector("#configEvalNoAttachments").checked,
    sync_interval_hours: interval,
    sync_start_time: document.querySelector("#configSyncStart").value || "02:00",
    selected_label_ids: selectedLabelIds,
  };
  const data = await api(`/api/inbox-accounts/${configuringInboxId}/config`, { method: "PUT", body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#inboxConfigMessage", data.error, "error");
    return;
  }
  currentInboxConfig = data;
  setMessage("#inboxConfigMessage", "Configuration saved.", "success");
  renderInboxConfig();
  await loadAdminData();
}

async function saveGmailConfig() {
  if (!canEditAdminTab("testing")) return;
  const payload = {
    client_id: document.querySelector("#gmailClientId").value.trim(),
    client_secret: document.querySelector("#gmailClientSecret").value.trim(),
    redirect_uri: document.querySelector("#gmailRedirectUri").value.trim(),
    scopes: document.querySelector("#gmailScopes").value.trim(),
  };
  const data = await api("/api/gmail-oauth-config", { method: "POST", body: JSON.stringify(payload) });
  gmailConfig = data;
  document.querySelector("#gmailClientSecret").value = "";
  setMessage("#gmailConfigMessage", data.client_secret_configured ? "Gmail config saved. Secret is configured." : "Gmail config saved. Client secret is not configured.", data.client_secret_configured ? "success" : "error");
  renderGmailConfig();
  await loadTestingData();
}

async function saveOutlookConfig() {
  if (!canEditAdminTab("testing")) return;
  const payload = {
    client_id: document.querySelector("#outlookClientId").value.trim(),
    client_secret: document.querySelector("#outlookClientSecret").value.trim(),
    tenant: document.querySelector("#outlookTenant").value.trim(),
    redirect_uri: document.querySelector("#outlookRedirectUri").value.trim(),
    scopes: document.querySelector("#outlookScopes").value.trim(),
  };
  const data = await api("/api/outlook-oauth-config", { method: "POST", body: JSON.stringify(payload) });
  outlookConfig = data;
  document.querySelector("#outlookClientSecret").value = "";
  setMessage("#outlookConfigMessage", data.client_secret_configured ? "Outlook config saved. Secret is configured." : "Outlook config saved. Client secret is not configured.", data.client_secret_configured ? "success" : "error");
  renderOutlookConfig();
  await loadTestingData();
}

async function saveOpenAIConfig() {
  if (!canEditAdminTab("testing")) return;
  const payload = {
    api_key: document.querySelector("#openaiApiKey").value.trim(),
    model: document.querySelector("#openaiModel").value.trim(),
    use_ai_extraction: document.querySelector("#useAiExtraction").checked,
  };
  const data = await api("/api/openai-extraction-config", { method: "POST", body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#openaiConfigMessage", data.error, "error");
    return;
  }
  openaiConfig = data;
  document.querySelector("#openaiApiKey").value = "";
  renderOpenAIConfig();
  setMessage("#openaiConfigMessage", data.api_key_configured ? "OpenAI config saved. API key is configured." : "OpenAI config saved. No API key configured.", data.api_key_configured ? "success" : "error");
}

async function syncInboxAccount(id) {
  openManualSyncModal(id);
}

function openManualSyncModal(id) {
  if (!canEditAdminTab("setup")) return;
  manualSyncInboxId = id;
  const account = inboxAccounts.find((row) => Number(row.id) === Number(id)) || {};
  const end = new Date();
  const start = account.last_sync_at ? new Date(account.last_sync_at) : new Date(end.getTime() - 24 * 60 * 60 * 1000);
  document.querySelector("#manualSyncStart").value = datetimeLocalValue(start);
  document.querySelector("#manualSyncEnd").value = datetimeLocalValue(end);
  setMessage("#manualSyncMessage", "");
  document.querySelector("#manualSyncModal").classList.remove("hidden");
  document.querySelector("#manualSyncModal").setAttribute("aria-hidden", "false");
}

function closeManualSyncModal() {
  manualSyncInboxId = null;
  document.querySelector("#manualSyncModal").classList.add("hidden");
  document.querySelector("#manualSyncModal").setAttribute("aria-hidden", "true");
}

function datetimeLocalValue(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

async function runManualSync() {
  if (!manualSyncInboxId) return;
  const startAtLocal = document.querySelector("#manualSyncStart").value;
  const endAtLocal = document.querySelector("#manualSyncEnd").value;
  const startDate = new Date(startAtLocal);
  const endDate = new Date(endAtLocal);
  if (!startAtLocal || !endAtLocal || Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime()) || endDate < startDate) {
    setMessage("#manualSyncMessage", "Enter a valid date/time range.", "error");
    return;
  }
  const startAt = startDate.toISOString();
  const endAt = endDate.toISOString();
  const button = document.querySelector("#runManualSyncBtn");
  button.disabled = true;
  const account = inboxAccounts.find((row) => Number(row.id) === Number(manualSyncInboxId)) || {};
  setMessage("#manualSyncMessage", `Syncing ${(account.provider || "inbox").toUpperCase()} from ${startAtLocal} to ${endAtLocal}...`);
  const data = await api(`/api/inbox-accounts/${manualSyncInboxId}/sync`, { method: "POST", body: JSON.stringify({ start_at: startAt, end_at: endAt }) });
  inboxAccounts = data.accounts || [];
  inboxSyncRuns = data.sync_runs || [];
  if (data.error) {
    setMessage("#manualSyncMessage", data.error, "error");
    button.disabled = false;
    renderInboxAccounts(data.gmail_configured, data.outlook_configured);
    renderSyncRuns();
    return;
  }
  const detection = await api("/api/inbox-detection-results");
  inboxDetectionResults = detection.results || [];
  inboxMessageRecords = detection.messages || [];
  const run = data.sync_run || {};
  const summary = `Seen ${run.messages_seen || 0}, imported ${run.messages_imported || 0}, skipped ${run.messages_skipped || 0}, POs created ${run.purchase_orders_created || 0}.`;
  setMessage("#manualSyncMessage", (run.messages_seen || 0) === 0 ? `No messages found in selected range. ${summary}` : `${run.status === "failed" ? "Sync failed." : "Sync complete."} ${summary}`, run.status === "failed" ? "error" : "success");
  button.disabled = false;
  renderInboxAccounts(data.gmail_configured, data.outlook_configured);
  renderSyncRuns();
  renderDetectionResults();
  await refresh();
}

async function deleteInboxAccount(id) {
  if (!confirm("Delete this inbox connection?")) return;
  const data = await api(`/api/inbox-accounts/${id}`, { method: "DELETE" });
  inboxAccounts = data.accounts || [];
  inboxSyncRuns = data.sync_runs || [];
  renderInboxAccounts(data.gmail_configured, data.outlook_configured);
  renderSyncRuns();
}

function renderXrefs() {
  renderXrefCustomerOptions();
  document.querySelector("#xrefRows").innerHTML = xrefs
    .map(
      (row) => `
      <tr>
        <td><input id="xref_customer_${row.id}" list="xrefCustomerOptions" value="${safe(row.customer_name)}" /></td>
        <td><input id="xref_customer_part_${row.id}" value="${safe(row.customer_part_number)}" /></td>
        <td><input id="xref_customer_rev_${row.id}" value="${safe(row.customer_part_revision)}" /></td>
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

function renderXrefCustomerOptions() {
  document.querySelector("#xrefCustomerOptions").innerHTML = customers
    .map((customer) => customer.customer_name)
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))
    .map((name) => `<option value="${safe(name)}"></option>`)
    .join("");
}

function renderCustomers() {
  document.querySelector("#customerRows").innerHTML = customers
    .map(
      (row) => `
      <tr>
        <td>${safe(row.customer_name)}</td>
        <td>${safe(row.customer_number)}</td>
        <td>${safe(row.payment_terms_display || row.payment_terms)}</td>
        <td>${row.bill_to_count || 0}</td>
        <td>${row.ship_to_count || 0}</td>
        <td>${row.contact_count || 0}</td>
        <td><button class="secondary" onclick="openCustomerModal(${row.id})">Edit</button></td>
      </tr>
    `,
    )
    .join("");
}

async function openCustomerModal(id = null) {
  editingCustomerId = id;
  editingAddressId = null;
  currentCustomerDetail = null;
  setMessage("#customerModalMessage", "");
  document.querySelector("#customerName").value = "";
  document.querySelector("#customerNumber").value = "";
  document.querySelector("#customerPaymentTerms").value = "";
  renderCustomerPaymentTermOptions();
  document.querySelector("#addressRows").innerHTML = "";
  document.querySelector("#contactRows").innerHTML = "";
  document.querySelector("#customerChildEditors").classList.toggle("hidden", !id);
  document.querySelector("#deleteCustomerBtn").classList.toggle("hidden", !id);
  if (id) {
    currentCustomerDetail = await api(`/api/customers/${id}`);
    const customer = currentCustomerDetail.customer;
    document.querySelector("#customerName").value = customer.customer_name || "";
    document.querySelector("#customerNumber").value = customer.customer_number || "";
    document.querySelector("#customerPaymentTerms").value = customer.payment_terms || "";
    renderCustomerPaymentTermOptions(customer.payment_terms_id, customer.payment_terms);
    renderCustomerChildren();
  }
  document.querySelector("#customerModal").classList.remove("hidden");
}

function closeCustomerModal() {
  editingCustomerId = null;
  editingAddressId = null;
  currentCustomerDetail = null;
  pendingReviewAction = null;
  document.querySelector("#customerModal").classList.add("hidden");
  closeAddressModal();
}

function renderCustomerPaymentTermOptions(selectedId = null, fallbackText = "") {
  const select = document.querySelector("#customerPaymentTermsId");
  const activeTerms = paymentTerms.filter((term) => term.is_active || Number(term.id) === Number(selectedId));
  const hasSelected = activeTerms.some((term) => Number(term.id) === Number(selectedId));
  select.innerHTML = `
    <option value="">${fallbackText ? "Use text value" : "Select payment terms"}</option>
    ${!hasSelected && selectedId ? `<option value="${selectedId}" selected>Current: ${safe(fallbackText || selectedId)}</option>` : ""}
    ${activeTerms.map((term) => `<option value="${term.id}" ${Number(term.id) === Number(selectedId) ? "selected" : ""}>${safe(term.name)}</option>`).join("")}
  `;
}

async function saveCustomer() {
  if (!canEditAdminTab("master")) return;
  const payload = {
    customer_name: document.querySelector("#customerName").value.trim(),
    customer_number: document.querySelector("#customerNumber").value.trim(),
    payment_terms_id: document.querySelector("#customerPaymentTermsId").value,
    payment_terms: document.querySelector("#customerPaymentTerms").value.trim(),
  };
  const path = editingCustomerId ? `/api/customers/${editingCustomerId}` : "/api/customers";
  const method = editingCustomerId ? "PUT" : "POST";
  const data = await api(path, { method, body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#customerModalMessage", data.error, "error");
    return;
  }
  editingCustomerId = data.customer.id;
  currentCustomerDetail = data;
  document.querySelector("#customerChildEditors").classList.remove("hidden");
  document.querySelector("#deleteCustomerBtn").classList.remove("hidden");
  setMessage("#customerModalMessage", "Customer saved.", "success");
  if (pendingReviewAction?.type === "customer") {
    await resolveMasterDataReview(pendingReviewAction.reviewId, { matched_customer_id: editingCustomerId, matched_record_id: editingCustomerId });
    pendingReviewAction = null;
  }
  await reloadCustomers();
  renderCustomerChildren();
}

async function deleteCustomer() {
  if (!canEditAdminTab("master")) return;
  if (!editingCustomerId) return;
  if (!confirm("Delete this customer profile?")) return;
  await api(`/api/customers/${editingCustomerId}`, { method: "DELETE" });
  closeCustomerModal();
  await reloadCustomers();
}

async function reloadCustomers() {
  customers = await api("/api/customers");
  renderCustomers();
}

function renderCustomerChildren() {
  if (!currentCustomerDetail) return;
  document.querySelector("#addressRows").innerHTML = currentCustomerDetail.addresses
    .map(
      (row) => `
      <tr>
        <td>${row.address_type === "ship_to" ? "Ship To" : "Bill To"}</td>
        <td>${safe(row.label)}</td>
        <td><pre class="inline-pre">${safe(formatAddress(row))}</pre></td>
        <td>${row.is_default ? "Default" : ""}</td>
        <td><button class="secondary table-action" onclick="editAddress(${row.id})">Edit</button></td>
      </tr>
    `,
    )
    .join("");
  document.querySelector("#contactRows").innerHTML = currentCustomerDetail.contacts
    .map(
      (row) => `
      <tr>
        <td>${safe(row.first_name)}</td>
        <td>${safe(row.last_name)}</td>
        <td>${safe(row.job_title)}</td>
        <td>${safe(row.phone_number)}</td>
        <td>${safe(row.email)}</td>
        <td><button class="secondary table-action" onclick="openContactModal(${row.id})">Edit</button></td>
      </tr>
    `,
    )
    .join("");
}

async function addAddress() {
  if (!canEditAdminTab("master")) return;
  openAddressModal();
}

function openAddressModal(id = null, prefill = {}) {
  if (!canEditAdminTab("master")) return;
  if (!editingCustomerId) {
    setMessage("#customerModalMessage", "Save the customer before adding addresses.", "error");
    return;
  }
  editingAddressId = id;
  const row = id ? currentCustomerDetail.addresses.find((address) => Number(address.id) === Number(id)) || {} : prefill;
  document.querySelector("#addressModalTitle").textContent = id ? "Edit Address" : "Add Address";
  document.querySelector("#addressType").value = row.address_type || "bill_to";
  document.querySelector("#addressLabel").value = row.label || "";
  document.querySelector("#addressLine1").value = row.address_line_1 || "";
  document.querySelector("#addressLine2").value = row.address_line_2 || "";
  document.querySelector("#addressLine3").value = row.address_line_3 || "";
  document.querySelector("#addressCity").value = row.city || "";
  document.querySelector("#addressState").value = row.state || "";
  document.querySelector("#addressCountry").value = row.country || "";
  document.querySelector("#addressZip").value = row.zip_code || "";
  document.querySelector("#addressDefault").checked = Boolean(row.is_default);
  document.querySelector("#deleteAddressModalBtn").classList.toggle("hidden", !id);
  setMessage("#addressModalMessage", "");
  document.querySelector("#addressModal").classList.remove("hidden");
}

function closeAddressModal() {
  editingAddressId = null;
  document.querySelector("#addressModal").classList.add("hidden");
}

async function saveAddressModal() {
  if (!canEditAdminTab("master")) return;
  if (!editingCustomerId) {
    setMessage("#addressModalMessage", "Save the customer before adding addresses.", "error");
    return;
  }
  const payload = addressPayloadFromForm();
  const path = editingAddressId ? `/api/customer-addresses/${editingAddressId}` : `/api/customers/${editingCustomerId}/addresses`;
  const method = editingAddressId ? "PUT" : "POST";
  currentCustomerDetail = await api(path, { method, body: JSON.stringify(payload) });
  const savedAddressId = editingAddressId || newestId(currentCustomerDetail.addresses);
  if (pendingReviewAction?.type === payload.address_type) {
    await resolveMasterDataReview(pendingReviewAction.reviewId, { matched_customer_id: editingCustomerId, matched_record_id: savedAddressId });
    pendingReviewAction = null;
  }
  closeAddressModal();
  renderCustomerChildren();
  await reloadCustomers();
}

async function deleteAddress(id) {
  if (!canEditAdminTab("master")) return;
  if (!confirm("Delete this address?")) return;
  currentCustomerDetail = await api(`/api/customer-addresses/${id}`, { method: "DELETE" });
  renderCustomerChildren();
  await reloadCustomers();
}

function editAddress(id) {
  openAddressModal(id);
}

async function deleteAddressModal() {
  if (!editingAddressId) return;
  await deleteAddress(editingAddressId);
  closeAddressModal();
}

function addressPayloadFromForm() {
  return {
    address_type: document.querySelector("#addressType").value,
    label: document.querySelector("#addressLabel").value.trim(),
    address_line_1: document.querySelector("#addressLine1").value.trim(),
    address_line_2: document.querySelector("#addressLine2").value.trim(),
    address_line_3: document.querySelector("#addressLine3").value.trim(),
    city: document.querySelector("#addressCity").value.trim(),
    state: document.querySelector("#addressState").value.trim(),
    country: document.querySelector("#addressCountry").value.trim(),
    zip_code: document.querySelector("#addressZip").value.trim(),
    is_default: document.querySelector("#addressDefault").checked,
  };
}

function clearAddressForm() {
  editingAddressId = null;
  for (const selector of ["#addressLabel", "#addressLine1", "#addressLine2", "#addressLine3", "#addressCity", "#addressState", "#addressCountry", "#addressZip"]) {
    document.querySelector(selector).value = "";
  }
  document.querySelector("#addressType").value = "bill_to";
  document.querySelector("#addressDefault").checked = false;
}

function formatAddress(row) {
  const locality = [row.city, row.state, row.zip_code].filter(Boolean).join(" ");
  const parts = [row.address_line_1, row.address_line_2, row.address_line_3, locality, row.country].filter(Boolean);
  return parts.join("\n") || row.address_text || "";
}

function newestId(rows) {
  return Math.max(...(rows || []).map((row) => Number(row.id || 0)), 0) || null;
}

function openContactModal(id = null, prefill = {}) {
  if (!canEditAdminTab("master")) return;
  if (!editingCustomerId) {
    setMessage("#customerModalMessage", "Save the customer before adding contacts.", "error");
    return;
  }
  editingContactId = id;
  const row = id ? currentCustomerDetail.contacts.find((contact) => Number(contact.id) === Number(id)) || {} : prefill;
  document.querySelector("#contactModalTitle").textContent = id ? "Edit Contact" : "Add Contact";
  document.querySelector("#modalContactFirstName").value = row.first_name || "";
  document.querySelector("#modalContactLastName").value = row.last_name || "";
  document.querySelector("#modalContactJobTitle").value = row.job_title || "";
  document.querySelector("#modalContactPhone").value = row.phone_number || "";
  document.querySelector("#modalContactEmail").value = row.email || "";
  document.querySelector("#deleteContactModalBtn").classList.toggle("hidden", !id);
  setMessage("#contactModalMessage", "");
  document.querySelector("#contactModal").classList.remove("hidden");
}

function closeContactModal() {
  editingContactId = null;
  document.querySelector("#contactModal").classList.add("hidden");
}

async function saveContactModal() {
  if (!canEditAdminTab("master")) return;
  const payload = {
    first_name: document.querySelector("#modalContactFirstName").value.trim(),
    last_name: document.querySelector("#modalContactLastName").value.trim(),
    job_title: document.querySelector("#modalContactJobTitle").value.trim(),
    phone_number: document.querySelector("#modalContactPhone").value.trim(),
    email: document.querySelector("#modalContactEmail").value.trim(),
  };
  const path = editingContactId ? `/api/customer-contacts/${editingContactId}` : `/api/customers/${editingCustomerId}/contacts`;
  const method = editingContactId ? "PUT" : "POST";
  currentCustomerDetail = await api(path, { method, body: JSON.stringify(payload) });
  const savedContactId = editingContactId || newestId(currentCustomerDetail.contacts);
  if (pendingReviewAction?.type === "contact") {
    await resolveMasterDataReview(pendingReviewAction.reviewId, { matched_customer_id: editingCustomerId, matched_record_id: savedContactId });
    pendingReviewAction = null;
  }
  closeContactModal();
  renderCustomerChildren();
  await reloadCustomers();
}

async function deleteContactModal() {
  if (!canEditAdminTab("master")) return;
  if (!editingContactId) return;
  currentCustomerDetail = await api(`/api/customer-contacts/${editingContactId}`, { method: "DELETE" });
  closeContactModal();
  renderCustomerChildren();
  await reloadCustomers();
}

async function openGoldenModal(documentId) {
  editingGoldenDocumentId = documentId;
  currentGoldenAnswer = await api(`/api/testing/documents/${documentId}/golden-answer`);
  const header = currentGoldenAnswer.header || {};
  document.querySelector("#goldenExpectedIsPo").checked = header.expected_is_po !== 0;
  document.querySelector("#goldenCustomer").value = header.customer_company_name || "";
  document.querySelector("#goldenContact").value = header.customer_contact_name || "";
  document.querySelector("#goldenPoNumber").value = header.po_number || "";
  document.querySelector("#goldenQuoteNumber").value = header.quote_number || "";
  document.querySelector("#goldenDateReceived").value = inputValue(header.date_received, "date");
  document.querySelector("#goldenTotalValue").value = header.total_value || "";
  document.querySelector("#goldenCurrency").value = header.currency || "USD";
  document.querySelector("#goldenPaymentTerms").value = header.payment_terms || "";
  document.querySelector("#goldenFreightTerms").value = header.freight_terms || "";
  document.querySelector("#goldenBillTo").value = header.bill_to_address || "";
  document.querySelector("#goldenShipTo").value = header.ship_to_address || "";
  document.querySelector("#goldenNotes").value = header.notes || "";
  clearGoldenLineForm();
  renderGoldenLines();
  document.querySelector("#goldenModal").classList.remove("hidden");
}

function closeGoldenModal() {
  editingGoldenDocumentId = null;
  currentGoldenAnswer = null;
  document.querySelector("#goldenModal").classList.add("hidden");
}

async function saveGoldenHeader() {
  if (!canEditAdminTab("testing")) return;
  if (!editingGoldenDocumentId) return;
  const payload = {
    expected_is_po: document.querySelector("#goldenExpectedIsPo").checked,
    customer_company_name: document.querySelector("#goldenCustomer").value.trim(),
    customer_contact_name: document.querySelector("#goldenContact").value.trim(),
    po_number: document.querySelector("#goldenPoNumber").value.trim(),
    quote_number: document.querySelector("#goldenQuoteNumber").value.trim(),
    date_received: document.querySelector("#goldenDateReceived").value,
    total_value: document.querySelector("#goldenTotalValue").value,
    currency: document.querySelector("#goldenCurrency").value.trim(),
    payment_terms: document.querySelector("#goldenPaymentTerms").value.trim(),
    freight_terms: document.querySelector("#goldenFreightTerms").value.trim(),
    bill_to_address: document.querySelector("#goldenBillTo").value.trim(),
    ship_to_address: document.querySelector("#goldenShipTo").value.trim(),
    notes: document.querySelector("#goldenNotes").value.trim(),
  };
  const data = await api(`/api/testing/documents/${editingGoldenDocumentId}/golden-answer`, { method: "PUT", body: JSON.stringify(payload) });
  currentGoldenAnswer = data.golden_answer;
  await loadTestingData();
  renderGoldenLines();
}

function renderGoldenLines() {
  const lines = currentGoldenAnswer?.lines || [];
  document.querySelector("#goldenLineRows").innerHTML = lines
    .map(
      (line) => `
      <tr>
        <td>${safe(line.line_number)}</td>
        <td>${safe(line.customer_part_number)}</td>
        <td>${safe(line.internal_part_number)}</td>
        <td>${safe(line.description)}</td>
        <td>${safe(line.quantity)}</td>
        <td>${safe(line.unit_price)}</td>
        <td>${safe(line.line_total)}</td>
        <td>${safe(line.requested_date)}</td>
        <td><button class="danger table-action" onclick="deleteGoldenLine(${line.id})">Delete</button></td>
      </tr>
    `,
    )
    .join("");
}

async function addGoldenLine() {
  if (!canEditAdminTab("testing")) return;
  if (!currentGoldenAnswer?.header?.id) {
    await saveGoldenHeader();
  }
  const headerId = currentGoldenAnswer?.header?.id;
  if (!headerId) return;
  const payload = {
    line_number: document.querySelector("#goldenLineNumber").value.trim(),
    customer_part_number: document.querySelector("#goldenCustomerPart").value.trim(),
    internal_part_number: document.querySelector("#goldenInternalPart").value.trim(),
    description: document.querySelector("#goldenDescription").value.trim(),
    quantity: document.querySelector("#goldenQuantity").value,
    unit_of_measure: document.querySelector("#goldenUom").value.trim(),
    unit_price: document.querySelector("#goldenUnitPrice").value,
    requested_date: document.querySelector("#goldenRequestedDate").value,
  };
  currentGoldenAnswer = await api(`/api/testing/golden-answers/${headerId}/lines`, { method: "POST", body: JSON.stringify(payload) });
  clearGoldenLineForm();
  renderGoldenLines();
  await loadTestingData();
}

async function deleteGoldenLine(id) {
  if (!canEditAdminTab("testing")) return;
  currentGoldenAnswer = await api(`/api/testing/golden-lines/${id}`, { method: "DELETE" });
  renderGoldenLines();
}

function clearGoldenLineForm() {
  for (const selector of ["#goldenLineNumber", "#goldenCustomerPart", "#goldenInternalPart", "#goldenDescription", "#goldenQuantity", "#goldenUom", "#goldenUnitPrice", "#goldenRequestedDate"]) {
    document.querySelector(selector).value = "";
  }
}

function renderUsers() {
  if (!canViewUsers()) {
    document.querySelector("#userRows").innerHTML = "";
    return;
  }
  document.querySelector("#userRows").innerHTML = users
    .map(
      (row) => `
      <tr>
        <td>${safe(row.first_name)}</td>
        <td>${safe(row.last_name)}</td>
        <td>${safe(row.job_title)}</td>
        <td>${safe(row.email)}</td>
        <td>${row.is_active ? "Active" : "Inactive"}</td>
        <td>${userAdminAccessLabel(row)}</td>
        <td>${row.can_access_po_dashboard ? "Yes" : "No"}</td>
        <td>${accessLabel(row.po_dashboard_access_level)}</td>
        <td>${safe(row.created_at)}</td>
        <td>
          ${canManageUsers() ? `<button class="secondary" onclick="openUserModal(${row.id})">Edit</button>` : '<span class="view-only-note">View Only</span>'}
        </td>
      </tr>
    `,
    )
    .join("");
}

async function inviteUser() {
  if (!canManageUsers()) return;
  const payload = {
    first_name: document.querySelector("#inviteFirstName").value.trim(),
    last_name: document.querySelector("#inviteLastName").value.trim(),
    job_title: document.querySelector("#inviteJobTitle").value.trim(),
    email: document.querySelector("#inviteEmail").value.trim(),
    password: document.querySelector("#invitePassword").value.trim(),
    can_access_po_dashboard: true,
    po_dashboard_access_level: "view_only",
  };
  if (!payload.first_name || !payload.last_name || !payload.email) {
    setMessage("#usersMessage", "First name, last name, and email are required.", "error");
    return;
  }
  const data = await api("/api/users", { method: "POST", body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#usersMessage", data.error, "error");
    return;
  }
  users = data.users;
  document.querySelector("#inviteFirstName").value = "";
  document.querySelector("#inviteLastName").value = "";
  document.querySelector("#inviteJobTitle").value = "";
  document.querySelector("#inviteEmail").value = "";
  document.querySelector("#invitePassword").value = "";
  setMessage("#usersMessage", data.temporary_password ? `User invited. Temporary password: ${data.temporary_password}` : "User invited.", "success");
  renderUsers();
}

function accessLabel(value) {
  return value === "view_only" ? "View Only" : value === "edit" ? "Edit" : "None";
}

function userAdminAccessLabel(user) {
  if (user.is_admin) return "Full Admin";
  if (!user.can_access_admin) return "No";
  const permissions = user.admin_tab_permissions || {};
  const active = adminTabs.filter((tab) => permissions[tab] && permissions[tab] !== "no_access");
  return active.length ? `Selected (${active.length})` : "Selected";
}

function defaultAdminPermissionValue(user, tab) {
  if (user?.is_admin) return "full_access";
  const permissions = user?.admin_tab_permissions || {};
  if (permissions[tab]) return permissions[tab];
  return user?.can_access_admin && tab !== "users" ? "full_access" : "no_access";
}

function setAdminPermissionForm(user) {
  for (const tab of adminTabs) {
    const select = document.querySelector(`#${adminPermissionSelectIds[tab]}`);
    select.value = defaultAdminPermissionValue(user, tab);
  }
  updateAdminPermissionMenu();
}

function readAdminPermissionForm() {
  const permissions = {};
  for (const tab of adminTabs) {
    permissions[tab] = document.querySelector(`#${adminPermissionSelectIds[tab]}`).value;
  }
  return permissions;
}

function updateAdminPermissionMenu() {
  const fullAdmin = document.querySelector("#editUserAdmin").checked;
  const selectAdmin = document.querySelector("#editUserAdminAccess");
  if (fullAdmin) selectAdmin.checked = true;
  selectAdmin.disabled = fullAdmin;
  const showMenu = selectAdmin.checked && !fullAdmin;
  document.querySelector("#adminPermissionMenu").classList.toggle("hidden", !showMenu);
  for (const tab of adminTabs) {
    const select = document.querySelector(`#${adminPermissionSelectIds[tab]}`);
    if (fullAdmin) select.value = "full_access";
    select.disabled = fullAdmin || !selectAdmin.checked;
  }
}

function openUserModal(id) {
  if (!canManageUsers()) return;
  const user = users.find((row) => Number(row.id) === Number(id));
  if (!user) return;
  editingUserId = id;
  document.querySelector("#editUserFirstName").value = user.first_name || "";
  document.querySelector("#editUserLastName").value = user.last_name || "";
  document.querySelector("#editUserJobTitle").value = user.job_title || "";
  document.querySelector("#editUserEmail").value = user.email || "";
  document.querySelector("#editUserActive").checked = Boolean(user.is_active);
  document.querySelector("#editUserAdmin").checked = Boolean(user.is_admin);
  document.querySelector("#editUserAdminAccess").checked = Boolean(user.can_access_admin);
  document.querySelector("#editUserDashboardAccess").checked = Boolean(user.can_access_po_dashboard);
  document.querySelector("#editUserPoLevel").value = user.po_dashboard_access_level || "none";
  document.querySelector("#editUserPassword").value = "";
  setAdminPermissionForm(user);
  setMessage("#userModalMessage", "");
  document.querySelector("#userModal").classList.remove("hidden");
}

function closeUserModal() {
  editingUserId = null;
  document.querySelector("#userModal").classList.add("hidden");
}

async function saveUser(id = editingUserId) {
  if (!canManageUsers()) return;
  const payload = {
    first_name: document.querySelector("#editUserFirstName").value.trim(),
    last_name: document.querySelector("#editUserLastName").value.trim(),
    job_title: document.querySelector("#editUserJobTitle").value.trim(),
    email: document.querySelector("#editUserEmail").value.trim(),
    is_active: document.querySelector("#editUserActive").checked,
    is_admin: document.querySelector("#editUserAdmin").checked,
    can_access_admin: document.querySelector("#editUserAdminAccess").checked,
    can_access_po_dashboard: document.querySelector("#editUserDashboardAccess").checked,
    po_dashboard_access_level: document.querySelector("#editUserPoLevel").value,
    admin_tab_permissions: readAdminPermissionForm(),
    new_password: document.querySelector("#editUserPassword").value.trim(),
  };
  const data = await api(`/api/users/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#userModalMessage", data.error, "error");
    users = data.users || users;
    renderUsers();
    return;
  }
  users = data.users;
  setMessage("#usersMessage", "User updated.", "success");
  closeUserModal();
  renderUsers();
}

async function deactivateUser(id = editingUserId) {
  if (!canManageUsers()) return;
  const data = await api(`/api/users/${id}`, { method: "DELETE" });
  if (data.error) {
    setMessage("#userModalMessage", data.error, "error");
    users = data.users || users;
    renderUsers();
    return;
  }
  users = data.users;
  setMessage("#usersMessage", "User deactivated.", "success");
  closeUserModal();
  renderUsers();
}

async function addOrderType() {
  if (!canEditAdminTab("setup")) return;
  const input = document.querySelector("#orderTypeName");
  if (!input.value.trim()) return;
  const data = await api("/api/order-types", { method: "POST", body: JSON.stringify({ name: input.value.trim() }) });
  orderTypes = data.order_types;
  input.value = "";
  renderOrderTypes();
}

async function saveOrderType(id) {
  if (!canEditAdminTab("setup")) return;
  const name = document.querySelector(`#order_type_name_${id}`).value.trim();
  const data = await api(`/api/order-types/${id}`, { method: "PUT", body: JSON.stringify({ name, is_active: true }) });
  orderTypes = data.order_types;
  renderOrderTypes();
}

async function deleteOrderType(id) {
  if (!canEditAdminTab("setup")) return;
  const data = await api(`/api/order-types/${id}`, { method: "DELETE" });
  orderTypes = data.order_types;
  if (data.message) {
    alert(data.message);
  }
  renderOrderTypes();
}

async function addDepartment() {
  if (!canEditAdminTab("setup")) return;
  const input = document.querySelector("#departmentName");
  if (!input.value.trim()) return;
  const data = await api("/api/departments", { method: "POST", body: JSON.stringify({ name: input.value.trim() }) });
  departments = data.departments;
  input.value = "";
  renderDepartments();
}

async function saveDepartment(id) {
  if (!canEditAdminTab("setup")) return;
  const name = document.querySelector(`#department_name_${id}`).value.trim();
  const data = await api(`/api/departments/${id}`, { method: "PUT", body: JSON.stringify({ name, is_active: true }) });
  departments = data.departments;
  renderDepartments();
}

async function deleteDepartment(id) {
  if (!canEditAdminTab("setup")) return;
  const data = await api(`/api/departments/${id}`, { method: "DELETE" });
  departments = data.departments;
  renderDepartments();
}

async function addPaymentTerm() {
  if (!canEditAdminTab("setup")) return;
  const input = document.querySelector("#paymentTermName");
  if (!input.value.trim()) return;
  const data = await api("/api/payment-terms", { method: "POST", body: JSON.stringify({ name: input.value.trim() }) });
  paymentTerms = data.payment_terms || [];
  input.value = "";
  renderPaymentTerms();
}

async function savePaymentTerm(id) {
  if (!canEditAdminTab("setup")) return;
  const name = document.querySelector(`#payment_term_name_${id}`).value.trim();
  const data = await api(`/api/payment-terms/${id}`, { method: "PUT", body: JSON.stringify({ name, is_active: true }) });
  paymentTerms = data.payment_terms || [];
  renderPaymentTerms();
}

async function deletePaymentTerm(id) {
  if (!canEditAdminTab("setup")) return;
  const data = await api(`/api/payment-terms/${id}`, { method: "DELETE" });
  paymentTerms = data.payment_terms || [];
  if (data.message) alert(data.message);
  renderPaymentTerms();
}

async function saveExportDestination() {
  if (!canEditAdminTab("setup")) return;
  const payload = {
    name: document.querySelector("#exportDestinationName").value.trim(),
    destination_type: document.querySelector("#exportDestinationType").value,
    endpoint_url: document.querySelector("#exportDestinationUrl").value.trim(),
    secret: document.querySelector("#exportDestinationSecret").value.trim(),
    config: { mode: "scaffold_only" },
    is_active: true,
  };
  if (!payload.name) {
    setMessage("#exportDestinationMessage", "Destination name is required.", "error");
    return;
  }
  const data = await api("/api/export-destinations", { method: "POST", body: JSON.stringify(payload) });
  if (data.error) {
    setMessage("#exportDestinationMessage", data.error, "error");
    return;
  }
  exportDestinations = data.destinations || [];
  document.querySelector("#exportDestinationName").value = "";
  document.querySelector("#exportDestinationUrl").value = "";
  document.querySelector("#exportDestinationSecret").value = "";
  setMessage("#exportDestinationMessage", "Export destination saved.", "success");
  renderExportDestinations();
}

async function deactivateExportDestination(id) {
  if (!canEditAdminTab("setup")) return;
  const data = await api(`/api/export-destinations/${id}`, { method: "DELETE" });
  exportDestinations = data.destinations || [];
  renderExportDestinations();
}

async function addXref() {
  if (!canEditAdminTab("master")) return;
  const payload = {
    customer_name: document.querySelector("#xrefCustomer").value.trim(),
    customer_part_number: document.querySelector("#xrefCustomerPart").value.trim(),
    customer_part_revision: document.querySelector("#xrefCustomerRev").value.trim(),
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
  document.querySelector("#xrefCustomerRev").value = "";
  document.querySelector("#xrefInternalPart").value = "";
  setXrefMessage("Cross reference saved.", "success");
  renderXrefs();
}

async function saveXref(id) {
  if (!canEditAdminTab("master")) return;
  const payload = {
    customer_name: document.querySelector(`#xref_customer_${id}`).value.trim(),
    customer_part_number: document.querySelector(`#xref_customer_part_${id}`).value.trim(),
    customer_part_revision: document.querySelector(`#xref_customer_rev_${id}`).value.trim(),
    internal_part_number: document.querySelector(`#xref_internal_part_${id}`).value.trim(),
  };
  const data = await api(`/api/customer-part-xrefs/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  xrefs = data.xrefs;
  setXrefMessage("Cross reference updated.", "success");
  renderXrefs();
}

async function deleteXref(id) {
  if (!canEditAdminTab("master")) return;
  const data = await api(`/api/customer-part-xrefs/${id}`, { method: "DELETE" });
  xrefs = data.xrefs;
  renderXrefs();
}

async function uploadXrefCsv(file) {
  if (!canEditAdminTab("master")) return;
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

async function uploadCustomerCsv(file, contacts = false) {
  if (!canEditAdminTab("master")) return;
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    setCustomersMessage("Only CSV files are allowed.", "error");
    return;
  }
  const form = new FormData();
  form.append("files", file);
  setCustomersMessage("Uploading customer CSV...");
  const path = contacts ? "/api/customer-contacts/upload-csv" : "/api/customers/upload-csv";
  const res = await fetch(path, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok || data.error) {
    setCustomersMessage(data.error || "Customer CSV upload failed.", "error");
    return;
  }
  customers = data.customers || customers;
  const errorText = data.errors?.length ? ` Errors: ${data.errors.join(" ")}` : "";
  setCustomersMessage(`Imported ${data.imported}, skipped ${data.skipped}.${errorText}`, data.errors?.length ? "error" : "success");
  renderCustomers();
}

async function addProduct() {
  if (!canEditAdminTab("master")) return;
  const payload = {
    internal_part_number: document.querySelector("#productPart").value.trim(),
    internal_part_revision: document.querySelector("#productRevision").value.trim(),
    description: document.querySelector("#productDescription").value.trim(),
    unit_of_measure: document.querySelector("#productUom").value.trim(),
    is_active: true,
  };
  if (!payload.internal_part_number) {
    setProductsMessage("Internal part number is required.", "error");
    return;
  }
  const data = await api("/api/products", { method: "POST", body: JSON.stringify(payload) });
  products = data.products || [];
  document.querySelector("#productPart").value = "";
  document.querySelector("#productRevision").value = "";
  document.querySelector("#productDescription").value = "";
  document.querySelector("#productUom").value = "";
  setProductsMessage("Product saved.", "success");
  renderProducts();
}

async function saveProduct(id) {
  if (!canEditAdminTab("master")) return;
  const payload = {
    internal_part_number: document.querySelector(`#product_part_${id}`).value.trim(),
    internal_part_revision: document.querySelector(`#product_rev_${id}`).value.trim(),
    description: document.querySelector(`#product_desc_${id}`).value.trim(),
    unit_of_measure: document.querySelector(`#product_uom_${id}`).value.trim(),
    is_active: true,
  };
  const data = await api(`/api/products/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  products = data.products || [];
  setProductsMessage("Product updated.", "success");
  renderProducts();
}

async function deleteProduct(id) {
  if (!canEditAdminTab("master")) return;
  const data = await api(`/api/products/${id}`, { method: "DELETE" });
  products = data.products || [];
  renderProducts();
}

async function uploadProductCsv(file) {
  if (!canEditAdminTab("master") || !file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    setProductsMessage("Only CSV files are allowed.", "error");
    return;
  }
  const form = new FormData();
  form.append("files", file);
  setProductsMessage("Uploading product CSV...");
  const res = await fetch("/api/products/upload-csv", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok || data.error) {
    setProductsMessage(data.error || "Product CSV upload failed.", "error");
    return;
  }
  products = data.products || [];
  const errorText = data.errors?.length ? ` Errors: ${data.errors.join(" ")}` : "";
  setProductsMessage(`Imported ${data.imported}, skipped ${data.skipped}.${errorText}`, data.errors?.length ? "error" : "success");
  renderProducts();
}

function setProductsMessage(message, kind = "") {
  const el = document.querySelector("#productsMessage");
  if (!el) return;
  el.className = `upload-message ${kind}`;
  el.textContent = message;
}

function setCustomersMessage(message, kind = "") {
  const el = document.querySelector("#customersMessage");
  el.className = `upload-message ${kind}`;
  el.textContent = message;
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

async function resolveReviewTask(id) {
  if (!canEditDashboard()) return;
  const data = await api(`/api/review-tasks/${id}/resolve`, { method: "POST", body: JSON.stringify({ resolved_reason: "manual" }) });
  if (selectedId && data.purchase_order) currentDetail = data;
  if (selectedId && data.purchase_order) renderDetail();
  await loadReviewTasks();
}

async function ignoreReviewTask(id) {
  if (!canEditDashboard()) return;
  const data = await api(`/api/review-tasks/${id}/ignore`, { method: "POST", body: "{}" });
  if (selectedId && data.purchase_order) currentDetail = data;
  if (selectedId && data.purchase_order) renderDetail();
  await loadReviewTasks();
}

async function duplicateCandidateAction(id, action) {
  if (!canEditDashboard()) return;
  const data = await api(`/api/duplicate-candidates/${id}/action`, { method: "POST", body: JSON.stringify({ action }) });
  currentDetail = data;
  renderDetail();
  await loadReviewTasks();
}

function toggleExceptionsPanel() {
  document.querySelector("#exceptionsPanel").classList.toggle("hidden");
  loadReviewTasks();
}

function openCustomerCsvModal() {
  document.querySelector("#customerCsvModal").classList.remove("hidden");
  document.querySelector("#customerCsvModal").setAttribute("aria-hidden", "false");
}

function closeCustomerCsvModal() {
  document.querySelector("#customerCsvModal").classList.add("hidden");
  document.querySelector("#customerCsvModal").setAttribute("aria-hidden", "true");
}

function downloadCustomerCsv(mode) {
  if (mode === "contacts") {
    window.location.href = "/api/customer-contacts.csv";
  } else {
    window.location.href = `/api/customers.csv?mode=${mode}`;
  }
  closeCustomerCsvModal();
}

function badge(status) {
  const klass = String(status || "").replace(/\s/g, "");
  return `<span class="badge ${klass}">${safe(status)}</span>`;
}

function sourceLabel(row) {
  if (row.source_type === "email" || ["gmail", "outlook"].includes(row.email_provider)) return row.source_sender || "Email";
  if (row.source_type === "sample_import" || row.email_provider === "sample") return "Sample Import";
  if (row.source_type === "manual") return "Manually Entered";
  return "Unknown";
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
  if (!canEditDashboard()) return;
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
  const allowed = [".pdf", ".txt", ".eml", ".xlsx", ".docx"];
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
    container.textContent = "No files selected yet.";
    return;
  }
  container.innerHTML = `<ul>${selectedUploadFiles.map((file) => `<li>${safe(file.name)} (${Math.ceil(file.size / 1024)} KB)</li>`).join("")}</ul>`;
}

async function openConfirmedOrderView() {
  if (!selectedId) return;
  const data = await api(`/api/purchase-orders/${selectedId}/confirmed-order`);
  const win = window.open("", "_blank");
  if (!win) {
    alert(data.summary || "Confirmed order view could not be opened.");
    return;
  }
  win.document.write(`
    <html><head><title>Confirmed Order ${safe(data.purchase_order?.po_number)}</title><style>
      body{font-family:"Source Sans 3",Segoe UI,Arial,sans-serif;padding:24px;color:#0f172a}
      table{width:100%;border-collapse:collapse;margin-top:16px}
      th,td{border:1px solid #e2e8f0;padding:8px;text-align:left}
      button{padding:8px 12px;border:1px solid #2563eb;border-radius:10px;background:#2563eb;color:#fff;font:inherit;font-weight:600}
    </style></head><body>
      <button onclick="window.print()">Print</button>
      <pre>${safe(data.summary)}</pre>
    </body></html>
  `);
  win.document.close();
}

async function openAcknowledgmentDraft() {
  if (!selectedId) return;
  const data = await api(`/api/purchase-orders/${selectedId}/acknowledgment-draft`);
  const text = `To: ${data.to}\nSubject: ${data.subject}\n\n${data.body}`;
  try {
    await navigator.clipboard.writeText(text);
    alert("Acknowledgment draft copied to clipboard.");
  } catch {
    prompt("Copy acknowledgment draft:", text);
  }
}

function setUploadMessage(message, kind = "") {
  const el = document.querySelector("#uploadMessage");
  el.className = `upload-message ${kind}`;
  el.textContent = message;
}

function showLogin(message = "") {
  currentUser = null;
  document.querySelector("#loginView").classList.remove("hidden");
  document.querySelector("#appShell").classList.add("hidden");
  setMessage("#loginMessage", message);
}

function showApp() {
  document.querySelector("#loginView").classList.add("hidden");
  document.querySelector("#appShell").classList.remove("hidden");
  configureAccessUI();
}

function configureAccessUI() {
  document.querySelector("#currentUserPill").innerHTML = `${safe(currentUser?.name)} ${!canEditDashboard() && canViewDashboard() ? '<span class="badge ViewOnly">View Only</span>' : ""}`;
  document.querySelector("#dashboardViewBtn").classList.toggle("hidden", !canViewDashboard());
  document.querySelector("#adminViewBtn").classList.toggle("hidden", !canViewAdmin());
  document.querySelector("#syncBtn").classList.toggle("hidden", !canEditDashboard());
  document.querySelector("#importBtn").classList.toggle("hidden", !canEditDashboard());
  configureAdminAccessUi();
}

async function loadMe() {
  const data = await api("/api/me");
  currentUser = data.user;
  if (!currentUser) {
    showLogin();
    return false;
  }
  showApp();
  return true;
}

async function login() {
  const email = document.querySelector("#loginEmail").value.trim();
  const password = document.querySelector("#loginPassword").value;
  if (!email || !password) {
    setMessage("#loginMessage", "Email and password are required.", "error");
    return;
  }
  try {
    const data = await api("/api/login", { method: "POST", body: JSON.stringify({ email, password }), skipAuthRedirect: true });
    currentUser = data.user;
    document.querySelector("#loginPassword").value = "";
    showApp();
    await switchView(canViewDashboard() ? "dashboard" : "admin");
  } catch (error) {
    setMessage("#loginMessage", error.message || "Login failed.", "error");
  }
}

async function logout() {
  await api("/api/logout", { method: "POST", body: "{}" });
  selectedId = null;
  currentDetail = null;
  showLogin("Logged out.");
}

async function uploadSelectedFiles() {
  if (!canEditDashboard()) return;
  if (!selectedUploadFiles.length) {
    setUploadMessage("Select or drop at least one PDF, TXT, EML, XLSX, or DOCX file.", "error");
    return;
  }
  const btn = document.querySelector("#uploadProcessBtn");
  btn.disabled = true;
  btn.textContent = "Uploading...";
  setUploadMessage("Finding the clean route through these files...");
  try {
    const form = new FormData();
    selectedUploadFiles.forEach((file) => form.append("files", file));
    const res = await fetch("/api/upload-samples", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || "Upload failed");
    }
    const rejected = data.rejected_files?.length ? ` Rejected: ${data.rejected_files.map((f) => f.filename).join(", ")}.` : "";
    setUploadMessage(`The clean list is ready. Imported ${data.imported}, skipped ${data.skipped}, created ${data.purchase_orders} PO records.${rejected}`, data.rejected_files?.length ? "error" : "success");
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
  if (!canEditDashboard()) return;
  const btn = document.querySelector("#folderImportBtn");
  btn.disabled = true;
  btn.textContent = "Importing...";
  setUploadMessage("Finding the clean route through the sample folder...");
  try {
    const data = await api("/api/import-samples", { method: "POST" });
    setUploadMessage(`The clean list is ready. Imported ${data.imported}, skipped ${data.skipped}, created ${data.purchase_orders} PO records.`, "success");
    await refresh();
  } catch (error) {
    setUploadMessage(error.message || "Import failed.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Import Existing Sample Folder";
  }
}

document.querySelector("#importBtn").addEventListener("click", openUploadModal);
document.querySelector("#loginBtn").addEventListener("click", login);
document.querySelector("#loginEmail").addEventListener("keydown", (event) => {
  if (event.key === "Enter") login();
});
document.querySelector("#loginPassword").addEventListener("keydown", (event) => {
  if (event.key === "Enter") login();
});
document.querySelector("#logoutBtn").addEventListener("click", logout);

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

document.querySelector("#customerCsvModal").addEventListener("click", (event) => {
  if (event.target.id === "customerCsvModal") {
    closeCustomerCsvModal();
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
  alert("Gmail/Outlook sync is stubbed for the MVP. Use Import POs to test the pipeline.");
});

document.querySelector("#exportBtn").addEventListener("click", openExportModal);
document.querySelector("#exceptionsBtn").addEventListener("click", toggleExceptionsPanel);
document.querySelector("#exportHeaderBtn").addEventListener("click", () => exportPOs("header"));
document.querySelector("#exportLinesBtn").addEventListener("click", () => exportPOs("lines"));
document.querySelector("#cancelExportBtn").addEventListener("click", closeExportModal);
document.querySelector("#closeExportBtn").addEventListener("click", closeExportModal);
document.querySelector("#dashboardViewBtn").addEventListener("click", () => switchView("dashboard"));
document.querySelector("#adminViewBtn").addEventListener("click", () => switchView("admin"));
document.querySelector("#adminTabUsersBtn").addEventListener("click", () => switchAdminTab("users"));
document.querySelector("#adminTabMasterBtn").addEventListener("click", () => switchAdminTab("master"));
document.querySelector("#adminTabSetupBtn").addEventListener("click", () => switchAdminTab("setup"));
document.querySelector("#adminTabTestingBtn").addEventListener("click", () => switchAdminTab("testing"));
document.querySelector("#adminTabAnalyticsBtn").addEventListener("click", () => switchAdminTab("analytics"));
document.querySelector("#adminTabErpBtn").addEventListener("click", () => switchAdminTab("erp"));
document.querySelector("#addOrderTypeBtn").addEventListener("click", addOrderType);
document.querySelector("#addDepartmentBtn").addEventListener("click", addDepartment);
document.querySelector("#addPaymentTermBtn").addEventListener("click", addPaymentTerm);
document.querySelector("#saveExportDestinationBtn").addEventListener("click", saveExportDestination);
document.querySelector("#saveOracleEbsProfileBtn").addEventListener("click", saveOracleEbsProfile);
document.querySelector("#addXrefBtn").addEventListener("click", addXref);
document.querySelector("#addProductBtn").addEventListener("click", addProduct);
document.querySelector("#canonicalBackfillBtn").addEventListener("click", refreshCanonicalBackfill);
document.querySelector("#inviteUserBtn").addEventListener("click", inviteUser);
document.querySelector("#closeUserModalBtn").addEventListener("click", closeUserModal);
document.querySelector("#cancelUserModalBtn").addEventListener("click", closeUserModal);
document.querySelector("#saveUserModalBtn").addEventListener("click", () => saveUser());
document.querySelector("#deactivateUserModalBtn").addEventListener("click", () => deactivateUser());
document.querySelector("#editUserAdmin").addEventListener("change", updateAdminPermissionMenu);
document.querySelector("#editUserAdminAccess").addEventListener("change", updateAdminPermissionMenu);
document.querySelector("#addCustomerBtn").addEventListener("click", () => openCustomerModal());
document.querySelector("#uploadCustomersCsvBtn").addEventListener("click", () => document.querySelector("#customerCsvInput").click());
document.querySelector("#uploadCustomerContactsCsvBtn").addEventListener("click", () => document.querySelector("#customerContactCsvInput").click());
document.querySelector("#downloadCustomersCsvBtn").addEventListener("click", openCustomerCsvModal);
document.querySelector("#customerCsvInput").addEventListener("change", (event) => uploadCustomerCsv(event.target.files[0], false));
document.querySelector("#customerContactCsvInput").addEventListener("change", (event) => uploadCustomerCsv(event.target.files[0], true));
document.querySelector("#uploadProductsCsvBtn").addEventListener("click", () => document.querySelector("#productCsvInput").click());
document.querySelector("#downloadProductsCsvBtn").addEventListener("click", () => {
  window.location.href = "/api/products.csv";
});
document.querySelector("#productCsvInput").addEventListener("change", (event) => uploadProductCsv(event.target.files[0]));
document.querySelector("#downloadCustomersOnlyBtn").addEventListener("click", () => downloadCustomerCsv("customers"));
document.querySelector("#downloadCustomersAddressesBtn").addEventListener("click", () => downloadCustomerCsv("addresses"));
document.querySelector("#downloadCustomerContactsBtn").addEventListener("click", () => downloadCustomerCsv("contacts"));
document.querySelector("#cancelCustomerCsvBtn").addEventListener("click", closeCustomerCsvModal);
document.querySelector("#closeCustomerCsvBtn").addEventListener("click", closeCustomerCsvModal);
document.querySelector("#closeCustomerModalBtn").addEventListener("click", closeCustomerModal);
document.querySelector("#cancelCustomerModalBtn").addEventListener("click", closeCustomerModal);
document.querySelector("#saveCustomerBtn").addEventListener("click", saveCustomer);
document.querySelector("#deleteCustomerBtn").addEventListener("click", deleteCustomer);
document.querySelector("#addAddressBtn").addEventListener("click", addAddress);
document.querySelector("#closeAddressModalBtn").addEventListener("click", closeAddressModal);
document.querySelector("#cancelAddressModalBtn").addEventListener("click", closeAddressModal);
document.querySelector("#saveAddressModalBtn").addEventListener("click", saveAddressModal);
document.querySelector("#deleteAddressModalBtn").addEventListener("click", deleteAddressModal);
document.querySelector("#addContactBtn").addEventListener("click", () => openContactModal());
document.querySelector("#closeContactModalBtn").addEventListener("click", closeContactModal);
document.querySelector("#cancelContactModalBtn").addEventListener("click", closeContactModal);
document.querySelector("#saveContactModalBtn").addEventListener("click", saveContactModal);
document.querySelector("#deleteContactModalBtn").addEventListener("click", deleteContactModal);
document.querySelector("#testDocUploadBtn").addEventListener("click", () => document.querySelector("#testDocInput").click());
document.querySelector("#testDocInput").addEventListener("change", (event) => uploadTestDocuments(event.target.files));
document.querySelector("#runEvaluationBtn").addEventListener("click", runEvaluation);
document.querySelector("#refreshLearningBtn").addEventListener("click", loadExtractionLearning);
document.querySelector("#refreshOperationsBtn").addEventListener("click", refreshOperationsMetrics);
document.querySelector("#downloadSummaryReportBtn").addEventListener("click", () => {
  window.location.href = "/api/reporting/summary.csv";
});
document.querySelector("#downloadExceptionsReportBtn").addEventListener("click", () => {
  window.location.href = "/api/reporting/exceptions.csv";
});
document.querySelector("#downloadCorrectionsReportBtn").addEventListener("click", () => {
  window.location.href = "/api/reporting/corrections.csv";
});
document.querySelector("#exceptionStatusFilter").addEventListener("change", loadReviewTasks);
document.querySelector("#exceptionSeverityFilter").addEventListener("change", loadReviewTasks);
document.querySelector("#exceptionSortFilter").addEventListener("change", loadReviewTasks);
document.querySelector("#exceptionCustomerFilter").addEventListener("input", () => loadReviewTasks());
document.querySelector("#openNextExceptionBtn").addEventListener("click", openNextException);
document.querySelector("#bulkResolveExceptionsBtn").addEventListener("click", () => bulkExceptionAction("resolve"));
document.querySelector("#bulkIgnoreExceptionsBtn").addEventListener("click", () => bulkExceptionAction("ignore"));
document.querySelector("#addInboxAccountBtn").addEventListener("click", addInboxAccount);
document.querySelector("#connectGmailBtn").addEventListener("click", connectGmail);
document.querySelector("#connectOutlookBtn").addEventListener("click", connectOutlook);
document.querySelector("#saveGmailConfigBtn").addEventListener("click", saveGmailConfig);
document.querySelector("#saveOutlookConfigBtn").addEventListener("click", saveOutlookConfig);
document.querySelector("#saveOpenAIConfigBtn").addEventListener("click", saveOpenAIConfig);
document.querySelector("#closeInboxConfigBtn").addEventListener("click", closeInboxConfig);
document.querySelector("#cancelInboxConfigBtn").addEventListener("click", closeInboxConfig);
document.querySelector("#refreshInboxLabelsBtn").addEventListener("click", refreshInboxLabels);
document.querySelector("#saveInboxConfigBtn").addEventListener("click", saveInboxConfig);
document.querySelector("#closeManualSyncBtn").addEventListener("click", closeManualSyncModal);
document.querySelector("#cancelManualSyncBtn").addEventListener("click", closeManualSyncModal);
document.querySelector("#runManualSyncBtn").addEventListener("click", runManualSync);
document.querySelector("#savePoEntryBtn").addEventListener("click", savePoEntry);
document.querySelector("#closePoEntryBtn").addEventListener("click", closePoEntryView);
document.querySelector("#poEntryModal").addEventListener("click", (event) => {
  if (event.target.id === "poEntryModal") closePoEntryView();
});
document.querySelector("#closeGoldenModalBtn").addEventListener("click", closeGoldenModal);
document.querySelector("#cancelGoldenModalBtn").addEventListener("click", closeGoldenModal);
document.querySelector("#saveGoldenHeaderBtn").addEventListener("click", saveGoldenHeader);
document.querySelector("#addGoldenLineBtn").addEventListener("click", addGoldenLine);
document.querySelector("#xrefCsvBtn").addEventListener("click", () => document.querySelector("#xrefCsvInput").click());
document.querySelector("#xrefCsvDownloadBtn").addEventListener("click", () => {
  window.location.href = "/api/customer-part-xrefs.csv";
});
document.querySelector("#xrefCsvInput").addEventListener("change", (event) => uploadXrefCsv(event.target.files[0]));

document.querySelector("#statusFilter").addEventListener("change", loadPOs);
document.querySelector("#searchInput").addEventListener("input", () => loadPOs());

loadMe().then((ok) => {
  if (!ok) return;
  switchView(canViewDashboard() ? "dashboard" : "admin");
});


