/**
 * notifications.js — render the Notifications page with collapsible
 * per-status sections (Awaiting Response, Responded, Applied, Rejected).
 *
 * The number beside "Notifications" in the nav shows only the count of
 * jobs in "Awaiting Response" status. Jobs with status "Awaiting
 * Response" that were set incorrectly (before this change) should have
 * been moved to unsure=1 by the database cleanup migration so the daemon
 * can re-evaluate them.
 */
const STATUS_ORDER = ["Awaiting Response", "Responded", "Applied", "Rejected"];
const STATUS_META = {
  "Awaiting Response": { icon: "🟢", color: "success", label: "Awaiting Response" },
  Responded: { icon: "🟡", color: "warning", label: "Responded" },
  Applied: { icon: "⚪", color: "info", label: "Applied" },
  Rejected: { icon: "🔴", color: "danger", label: "Rejected" },
};

document.addEventListener("DOMContentLoaded", loadNotifications);

async function loadNotifications() {
  try {
    const res = await fetch("/api/notifications");
    if (!res.ok) throw new Error("Failed to load notifications");
    const data = await res.json();
    renderNotifications(data.jobs || [], data.counts || {});
  } catch (error) {
    showToast(error.message, "error");
  }
}

function relativeDate(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (isNaN(then)) return iso;
  const now = new Date();
  const days = Math.round((then - now) / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  if (days > 0 && days < 7) return "in " + days + "d";
  if (days < 0 && days > -7) return (-days) + "d ago";
  return iso;
}

function groupByStatus(jobs) {
  const groups = {};
  for (const status of STATUS_ORDER) { groups[status] = []; }
  for (const job of jobs) { const status = job.status || "Applied"; if (!groups[status]) groups[status] = []; groups[status].push(job); }
  return groups;
}

function renderCard(job) {
  const rawLink = safeUrl(job.link);
  const linkHtml = rawLink ? '<a class="link-button" href="' + escapeHTML(rawLink) + '" target="_blank" rel="noopener noreferrer">Open posting →</a>' : "";
  const interviewParams = new URLSearchParams();
  if (job.company) interviewParams.set("company", job.company);
  if (job.title) interviewParams.set("role", job.title);
  const scheduleHref = "/interviews?" + interviewParams.toString();
  const actions = [];
  if (rawLink) actions.push(linkHtml);
  if (job.email_link) {
    const emailTitle = job.email_subject ? "View email: " + escapeHTML(job.email_subject) : "View matched email";
    actions.push('<a class="link-button btn-email" href="' + escapeHTML(safeUrl(job.email_link) || job.email_link) + '" target="_blank" rel="noopener noreferrer" title="' + emailTitle + '">📧 View email →</a>');
  }
  if (job.email_link || job.status === "Awaiting Response" || job.status === "Responded") { actions.push('<a class="link-button" href="' + escapeHTML(scheduleHref) + '">Schedule interview →</a>'); }
  else if (job.interview_date) { actions.push('<a class="link-button" href="/interviews">View in Interviews →</a>'); }
  else { actions.push('<a class="link-button btn-interview" href="' + escapeHTML(scheduleHref) + '">Schedule interview →</a>'); }
  const status = job.status || "Applied";
  const meta = STATUS_META[status];
  const dateStr = relativeDate(job.email_received_at || job.applied_at || job.updated_at);
  return '<article class="notification-card status-' + meta.color + '"><div class="notification-header"><span class="badge badge-' + meta.color + '">' + meta.icon + ' ' + escapeHTML(status) + '</span>' + (job.email_link ? '<span class="badge badge-email">📧 email reply</span>' : "") + '<span class="text-muted">' + escapeHTML(dateStr) + '</span></div><h3>' + escapeHTML(job.title) + '</h3><p>' + escapeHTML(job.company) + '</p>' + (job.email_subject ? '<p class="email-subject"><strong>Re:</strong> ' + escapeHTML(job.email_subject) + '</p>' : "") + (job.follow_up_sent ? '<p><strong>Follow-up sent:</strong> ' + escapeHTML(relativeDate(job.follow_up_sent)) + '</p>' : "") + (job.interview_date ? '<p><strong>Interview:</strong> ' + escapeHTML(relativeDate(job.interview_date)) + '</p>' : "") + '<div class="notification-actions">' + actions.join("") + '</div></article>';
}



function renderNotifications(jobs, counts) {
  const banner = document.getElementById("notification-banner");
  const awaitingCount = counts["Awaiting Response"] || 0;
  if (awaitingCount > 0) { banner.classList.remove("hidden"); banner.innerHTML = '<span class="banner-icon">🟢</span><div><strong>' + awaitingCount + " job" + (awaitingCount === 1 ? "" : "s") + " awaiting your response.</strong><div class=\"text-muted\">Open the email from the job card and schedule an interview.</div></div>"; }
  else { banner.classList.add("hidden"); }
  // Counts live on the collapsible section headers (rendered below);
  // the old top tab bar was removed, so there is nothing else to update.
  const groups = groupByStatus(jobs);
  const panelsContainer = document.getElementById("notification-panels");
  if (!panelsContainer) return;
  const html = STATUS_ORDER.map(function(status) { const meta = STATUS_META[status]; const statusJobs = groups[status] || []; const panelId = "panel-" + status.toLowerCase().replace(/ /g, "-"); const gridId = "grid-" + status.toLowerCase().replace(/ /g, "-"); const tabId = "tab-" + status.toLowerCase().replace(/ /g, "-"); return '<div class="notification-panel" id="' + panelId + '" data-status="' + status + '"><button type="button" class="notification-panel-header ' + meta.color + '" data-tab="' + tabId + '"><span class="panel-icon">' + meta.icon + '</span><span class="panel-label">' + meta.label + '</span><span class="panel-count">' + statusJobs.length + '</span><span class="panel-toggle" aria-hidden="true">▼</span></button><div class="notification-panel-body ' + (statusJobs.length ? "" : "empty") + '" id="' + gridId + '">' + (statusJobs.length ? statusJobs.map(renderCard).join("") : '<div class="panel-empty-state"><span class="text-muted">No ' + status.toLowerCase() + ' jobs</span></div>') + '</div></div>'; }).join("");
  panelsContainer.innerHTML = html;
  document.querySelectorAll(".notification-panel-header").forEach(function(tab) { tab.addEventListener("click", function() { const panel = tab.closest(".notification-panel"); const toggle = tab.querySelector(".panel-toggle"); const isExpanded = panel.classList.contains("expanded"); panel.classList.toggle("expanded", !isExpanded); toggle.textContent = isExpanded ? "▼" : "▲"; }); });
  document.querySelectorAll(".notification-panel").forEach(function(panel) {
    const body = panel.querySelector(".notification-panel-body");
    const hasJobs = body && !body.classList.contains("empty");
    if (hasJobs) { panel.classList.add("expanded"); const toggle = panel.querySelector(".panel-toggle"); if (toggle) toggle.textContent = "▲"; }
  });
  const empty = document.getElementById("notifications-empty");
  if (jobs.length === 0) { empty.classList.remove("hidden"); }
  else { empty.classList.add("hidden"); }
}

function safeUrl(url) {
  if (!url) return "";
  try { const u = new URL(url, location.href); if (["http:", "https:"].includes(u.protocol)) return u.href; } catch (_) { return ""; }
  return "";
}

function escapeHTML(str) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(str || "").replace(/[&<>"']/g, c => map[c]);
}

function showToast(message, type = "info") {
  let container = document.querySelector(".toast-container");
  if (!container) { container = document.createElement("div"); container.className = "toast-container"; document.body.appendChild(container); }
  const toast = document.createElement("div");
  toast.className = "toast " + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => { toast.classList.add("show"); }, 10);
  setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 250); }, 4000);
}
