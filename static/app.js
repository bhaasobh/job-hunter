const $ = (id) => document.getElementById(id);
const PROFILE_KEY = "job-hunter-profile";
const SETTINGS_KEY = "job-hunter-settings";
const ONBOARDING_KEY = "job-hunter-onboarding-complete";
const LAST_SCAN_KEY = "job-hunter-last-scan";
const DEFAULT_EXCLUDED_KEYWORDS = ["senior", "manager", "staff", "student", "lead", "principal", "head", "director", "vp", "vice", "chief", "architect", "unpaid", "internship"];
const state = { jobs: [], cv: null, currentPage: "dashboard", sortKey: "newest", sortDirection: "desc" };

const pageInfo = {
  dashboard: ["Dashboard", "Your job search at a glance"],
  jobs: ["Jobs", "Browse and manage matching opportunities"],
  companies: ["Companies", "Companies represented in your job results"],
  "cv-profile": ["CV & Profile", "Keep your profile ready for better matches"],
  settings: ["Settings", "Manage your job search preferences"],
};

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}



function toast(message, isError = false) {
  const element = $("notificationToast");
  element.textContent = message;
  element.style.background = isError ? "#b91c1c" : "#172033";
  element.hidden = false;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { element.hidden = true; }, 4000);
}

function showPage(name) {
  if (!pageInfo[name]) return;
  state.currentPage = name;
  document.querySelectorAll(".page").forEach((page) => {
    const active = page.dataset.page === name;
    page.classList.toggle("active", active);
    page.hidden = !active;
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === name);
  });
  const [title, subtitle] = pageInfo[name];
  $("pageTitle").textContent = title;
  $("pageSubtitle").textContent = subtitle;
  $("searchButton").hidden = name !== "jobs";
  if (name === "jobs") renderJobs();
  if (name === "companies") renderCompanies();
  if (name === "add-company") loadCustomCompanies();
}

function populateSelect(id, values, placeholder) {
  const select = $(id);
  const selected = select.value;
  const unique = [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  select.replaceChildren(new Option(placeholder, ""));
  unique.forEach((value) => select.add(new Option(value, value)));
  select.value = unique.includes(selected) ? selected : "";
}

function normalizedStatus(job) {
  if (["saved", "applied"].includes(job?.status)) return job.status;
  const count = Number(job?.appearance_count) || 1;
  if (count > 3) return "old";
  return "new";
}

function filteredJobs() {
  const keyword = $("keywordFilter").value.trim().toLowerCase();
  const status = $("statusFilter").value;
  const company = $("companyJobFilter").value;
  const location = $("locationJobFilter").value;
  const remote = $("remoteFilter").checked;
  const excluded = excludedKeywords();
  const jobs = state.jobs.filter((job) => {
    const haystack = [job.title, job.company, job.location, job.tags, job.description].join(" ").toLowerCase();
    
    let matchesStatus = true;
    const count = Number(job?.appearance_count) || 1;
    if (status === "new") {
      // In the New filter, show only new jobs until 3x seen (x1, x2, x3)
      matchesStatus = count <= 3 && job.status !== "saved" && job.status !== "applied";
    } else if (status === "old") {
      // More than 3x seen is an old job
      matchesStatus = (count > 3 || job.status === "old") && job.status !== "saved" && job.status !== "applied";
    } else if (status === "saved") {
      matchesStatus = job.status === "saved";
    } else if (status === "applied") {
      matchesStatus = job.status === "applied";
    }

    return (!keyword || haystack.includes(keyword))
      && matchesStatus
      && (!company || job.company === company)
      && (!location || job.location === location)
      && (!remote || job.remote === true || /remote/i.test(job.location || ""))
      && !excluded.some((word) => haystack.includes(word));
  });
  const sort = state.sortKey;
  const direction = state.sortDirection === "asc" ? 1 : -1;
  const alpha = (left, right, field) => String(left[field] || "").localeCompare(String(right[field] || ""));
  return jobs.sort((left, right) => {
    if (sort === "match") return (Number(left.match_score || -1) - Number(right.match_score || -1)) * direction;
    if (sort === "seen") return (Number(left.appearance_count || 1) - Number(right.appearance_count || 1)) * direction;
    if (sort === "title" || sort === "company" || sort === "location") return alpha(left, right, sort) * direction;
    if (sort === "status") return normalizedStatus(left).localeCompare(normalizedStatus(right)) * direction;
    return (new Date(left.created_at || left.posted || 0) - new Date(right.created_at || right.posted || 0)) * direction;
  });
}

function sortHeader(label, key) {
  const active = state.sortKey === key;
  const arrow = active ? (state.sortDirection === "asc" ? " ▲" : " ▼") : "";
  const direction = active ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none";
  return `<th aria-sort="${direction}"><button class="column-sort" type="button" data-sort="${key}">${label}${arrow}</button></th>`;
}

function setSort(key) {
  if (state.sortKey === key) state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  else {
    state.sortKey = key;
    state.sortDirection = ["newest", "match", "seen"].includes(key) ? "desc" : "asc";
  }
  $("jobSort").value = key;
  renderJobs();
}

function jobCard(job) {
  const score = Number.isFinite(Number(job.match_score)) ? `<span class="job-score">${escapeHtml(job.match_score)}% match</span>` : "—";
  const count = Math.max(1, Number(job.appearance_count) || 1);
  const isNew = count <= 1;
  const indicator = `<span class="seen-indicator ${isNew ? "is-new" : "is-seen"}">${isNew ? "New" : `Seen x${count}`}</span>`;
  return `<tr class="job-row" data-job-id="${escapeHtml(job.job_id)}">
    <td class="job-title-cell" data-label="Role"><strong>${escapeHtml(job.title || "Untitled role")}</strong><span>${escapeHtml(job.job_type || job.source || "Job opening")}</span></td>
    <td data-label="Company"><strong>${escapeHtml(job.company || "Unknown company")}</strong></td>
    <td data-label="Location">${escapeHtml(job.location || "Location not specified")}</td>
    <td data-label="Match">${score}</td>
    <td data-label="Seen">${indicator}</td>
    <td data-label="Status"><select class="job-status" aria-label="Application status"><option value="new">New</option><option value="old">Old</option><option value="saved">Saved</option><option value="applied">Applied</option></select></td>
    <td class="job-actions" data-label="Actions"><button class="secondary-btn details-job" type="button">Details</button><a class="primary-btn job-link" target="_blank" rel="noopener" href="${escapeHtml(job.url || "#")}">View</a></td>
  </tr>`;
}

function renderJobs() {
  const jobs = filteredJobs();
  $("jobsContainer").innerHTML = jobs.length ? `<table class="jobs-table"><thead><tr>${sortHeader("Role", "title")}${sortHeader("Company", "company")}${sortHeader("Location", "location")}${sortHeader("Match", "match")}${sortHeader("Seen", "seen")}${sortHeader("Status", "status")}<th><span class="sr-only">Actions</span></th></tr></thead><tbody>${jobs.map(jobCard).join("")}</tbody></table>` : "";
  $("noJobsState").hidden = jobs.length !== 0;
  document.querySelectorAll(".column-sort").forEach((button) => button.addEventListener("click", () => setSort(button.dataset.sort)));
  document.querySelectorAll(".job-row").forEach((row) => {
    const job = state.jobs.find((item) => String(item.job_id) === row.dataset.jobId);
    const select = row.querySelector(".job-status");
    select.value = normalizedStatus(job);
    select.addEventListener("change", () => updateJobStatus(job, select.value));
    row.querySelector(".details-job").addEventListener("click", () => showJobDetails(job));
  });
}

async function updateJobStatus(job, status) {
  job.status = status;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(job.job_id)}/status`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not update job status");
    Object.assign(job, data.job);
    updateDashboard();
  } catch (error) {
    toast(error.message, true);
    await loadJobs();
  }
}

function showJobDetails(job) {
  $("jobDetailsContainer").innerHTML = `<h2>${escapeHtml(job.title || "Untitled role")}</h2>
    <p><strong>${escapeHtml(job.company || "Unknown company")}</strong></p>
    <p>📍 ${escapeHtml(job.location || "Location not specified")}</p>
    <p>${escapeHtml(job.description || job.match_reason || "No additional description is available.")}</p>
    ${job.match_reason ? `<p><strong>Match insight:</strong> ${escapeHtml(job.match_reason)}</p>` : ""}
    ${job.url ? `<a class="primary-btn job-link" target="_blank" rel="noopener" href="${escapeHtml(job.url)}">Open job listing</a>` : ""}`;
  $("jobDetailsModal").hidden = false;
}

function updateDashboard() {
  const today = new Date().toDateString();
  const total = state.jobs.length;
  $("totalJobs").textContent = total;
  $("newJobsToday").textContent = state.jobs.filter((job) => new Date(job.created_at || job.posted || 0).toDateString() === today).length;
  $("matchingJobs").textContent = state.jobs.filter((job) => Number(job.match_score) >= 70).length;
  $("savedJobs").textContent = state.jobs.filter((job) => normalizedStatus(job) === "saved").length;
  $("monitoredCompanies").textContent = new Set(state.jobs.map((job) => job.company).filter(Boolean)).size;
  $("appliedJobs").textContent = state.jobs.filter((job) => normalizedStatus(job) === "applied").length;
  $("emptyState").hidden = total > 0 || Boolean(state.cv);
}

function renderCompanies() {
  const query = $("companySearch").value.trim().toLowerCase();
  const companies = [...new Map(state.jobs.filter((job) => job.company).map((job) => [job.company, 0])).keys()]
    .map((name) => ({ name, count: state.jobs.filter((job) => job.company === name).length }))
    .filter((company) => company.name.toLowerCase().includes(query))
    .sort((a, b) => a.name.localeCompare(b.name));
  $("companiesContainer").innerHTML = companies.map((company) => `<div class="company-row"><div><strong>${escapeHtml(company.name)}</strong><span>${company.count} job${company.count === 1 ? "" : "s"} found</span></div><button class="secondary-btn company-jobs" data-company="${escapeHtml(company.name)}">View jobs</button></div>`).join("");
  $("noCompaniesState").hidden = companies.length !== 0;
  document.querySelectorAll(".company-jobs").forEach((button) => button.addEventListener("click", () => {
    $("companyJobFilter").value = button.dataset.company;
    showPage("jobs");
  }));
}

async function loadJobs() {
  try {
    const response = await fetch("/api/jobs");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load jobs");
    state.jobs = data.jobs || [];
    populateSelect("companyJobFilter", state.jobs.map((job) => job.company), "All companies");
    populateSelect("locationJobFilter", state.jobs.map((job) => job.location), "All locations");
    updateDashboard();
    renderJobs();
    renderCompanies();
  } catch (error) {
    $("jobsContainer").innerHTML = "";
    toast(error.message, true);
  }
}

function updateScanStatusDisplay(statusMessage, lastScanTime) {
  if (statusMessage) {
    ["scanStatusMessage", "jobsScanStatusMessage"].forEach((id) => {
      const el = $(id);
      if (el) {
        const p = el.querySelector("p");
        if (p) p.textContent = statusMessage;
      }
    });
  }
  if (lastScanTime) {
    ["lastScanInfo", "jobsLastScanInfo"].forEach((id) => {
      const el = $(id);
      if (el) {
        const val = el.querySelector(".value");
        if (val) val.textContent = lastScanTime;
      }
    });
  }
}

function setScanning(active, message = "") {
  const scanButtons = ["startScanBtn", "searchButton", "scanAllBtn"];
  scanButtons.forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.disabled = active;
    if (id === "searchButton") {
      btn.innerHTML = active ? '<span class="btn-spinner"></span> Searching…' : "Search Jobs Now";
    } else if (id === "scanAllBtn") {
      btn.innerHTML = active ? '<span class="btn-spinner"></span> Scanning…' : "Scan All";
    } else {
      btn.innerHTML = active ? '<span class="btn-spinner"></span> Scanning…' : "Start Scan Now";
    }
  });

  const jobsScanningBtn = $("jobsScanningBtn");
  if (jobsScanningBtn) {
    jobsScanningBtn.hidden = !active;
  }
  const jobsScanningBtnText = $("jobsScanningBtnText");
  if (jobsScanningBtnText && message) {
    jobsScanningBtnText.textContent = message;
  }

  ["scanProgress", "jobsScanProgress"].forEach((id) => {
    const el = $(id);
    if (el) el.hidden = !active;
  });

  ["scanStatusMessage", "jobsScanStatusMessage"].forEach((id) => {
    const el = $(id);
    if (el) el.hidden = active;
  });

  if (message) {
    ["scanPhase", "jobsScanPhase"].forEach((id) => {
      const el = $(id);
      if (el) el.textContent = message;
    });
  }
}

function excludedKeywords() {
  return [...new Set($("excludedKeywords").value
    .split(/[\n,]/)
    .map((word) => word.trim().toLowerCase())
    .filter(Boolean))];
}

async function startScan() {
  showPage("jobs");
  setScanning(true, "Searching for new jobs…");
  try {
    const response = await fetch("/api/search/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ use_ai_analysis: Boolean(state.cv?.cv_id), cv_id: state.cv?.cv_id || "", excluded_keywords: excludedKeywords() }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not start the search");
    while (true) {
      await new Promise((resolve) => window.setTimeout(resolve, 800));
      const progressResponse = await fetch(`/api/search/status/${encodeURIComponent(data.task_id)}`);
      const task = await progressResponse.json();
      if (!progressResponse.ok) throw new Error(task.error || "Could not read search progress");
      const progressPercent = `${task.progress || 0}%`;
      const countText = task.total_sources ? `${task.completed_sources}/${task.total_sources}` : "Preparing";
      const phaseText = task.current_source || "Scanning companies…";

      ["scanProgressBar", "jobsScanProgressBar"].forEach((id) => {
        const el = $(id);
        if (el) el.style.width = progressPercent;
      });
      ["scanCount", "jobsScanCount"].forEach((id) => {
        const el = $(id);
        if (el) el.textContent = countText;
      });
      ["scanPhase", "jobsScanPhase"].forEach((id) => {
        const el = $(id);
        if (el) el.textContent = phaseText;
      });

      const jobsScanningBtnText = $("jobsScanningBtnText");
      if (jobsScanningBtnText) {
        jobsScanningBtnText.textContent = task.current_source
          ? `Searching ${task.current_source}… (${countText})`
          : `Searching for new jobs… (${countText})`;
      }

      await loadJobs();

      if (task.state === "error") throw new Error(task.error || "Search failed");
      if (task.state === "complete") break;
    }
    await loadJobs();
    const now = new Date().toLocaleString();
    const message = `Scan complete. Found ${state.jobs.length} jobs.`;
    // Backend now handles last scan storage
    updateScanStatusDisplay(message, now);
    toast(`Search complete: ${state.jobs.length} jobs available.`);
  } catch (error) {
    updateScanStatusDisplay(error.message);
    toast(error.message, true);
  } finally {
    setScanning(false);
  }
}

function loadLocalState() {
  try { state.cv = JSON.parse(localStorage.getItem(PROFILE_KEY) || "null"); } catch { state.cv = null; }
  try {
    const settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    Object.entries(settings).forEach(([id, value]) => {
      const element = $(id);
      if (!element) return;
      if (element.type === "checkbox") element.checked = Boolean(value);
      else element.value = value;
    });
  } catch { /* No saved settings yet. */ }
  try {
    const lastScan = JSON.parse(localStorage.getItem(LAST_SCAN_KEY) || "null");
    if (lastScan) {
      updateScanStatusDisplay(lastScan.message, lastScan.time);
    }
  } catch { /* No saved last scan yet. */ }
  if (!$("excludedKeywords").value.trim()) $("excludedKeywords").value = DEFAULT_EXCLUDED_KEYWORDS.join(", ");
  renderCvStatus();
}

function renderCvStatus() {
  $("cvStatus").hidden = !state.cv;
  if (!state.cv) return;
  $("cvKeywords").innerHTML = (state.cv.keywords || []).slice(0, 20).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("");
}

async function uploadCv() {
  const file = $("cvFileInput").files[0];
  if (!file) return;
  const data = new FormData();
  data.append("cv", file);
  $("loadingOverlay").hidden = false;
  $("loadingText").textContent = "Analyzing your CV…";
  try {
    const response = await fetch("/api/cv/analyze", { method: "POST", body: data });
    const profile = await response.json();
    if (!response.ok) throw new Error(profile.error || "Could not analyze CV");
    state.cv = profile;
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
    renderCvStatus();
    toast("CV uploaded and analyzed.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("loadingOverlay").hidden = true;
  }
}

function addSkill(input, list) {
  const value = input.value.trim();
  if (!value) return;
  const tag = document.createElement("span");
  tag.className = "skill-tag";
  tag.append(document.createTextNode(value));
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `Remove ${value}`);
  remove.addEventListener("click", () => tag.remove());
  tag.append(remove);
  list.append(tag);
  input.value = "";
}

function saveProfile() {
  const fields = ["fullName", "jobTitles", "preferredLocations", "workArrangement", "yearsExperience", "currentRole", "aboutYou"];
  localStorage.setItem(PROFILE_KEY + "-details", JSON.stringify(Object.fromEntries(fields.map((id) => [id, $(id).value]))));
  toast("Profile saved.");
}

function saveSettings() {
  const ids = ["autoScanToggle", "scanFrequency", "companiesScope", "minMatchPercentage", "preferredTechs", "preferredPositions", "excludedKeywords", "telegramToggle", "telegramFrequency", "telegramMinMatch"];
  const settings = Object.fromEntries(ids.map((id) => [id, $(id).type === "checkbox" ? $(id).checked : $(id).value]));
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  $("telegramSettings").hidden = !$("telegramToggle").checked;
  renderJobs();
  toast("Settings saved.");
}

function clearLocalData() {
  if (!window.confirm("Clear saved profile and settings from this browser? Job results will not be deleted.")) return;
  localStorage.removeItem(PROFILE_KEY);
  localStorage.removeItem(PROFILE_KEY + "-details");
  localStorage.removeItem(SETTINGS_KEY);
  state.cv = null;
  renderCvStatus();
  toast("Local profile and settings cleared.");
}

function emailJobs() {
  const jobs = filteredJobs();
  if (!jobs.length) {
    toast("No jobs currently matching your filters to email.");
    return;
  }
  
  $("emailModalDesc").textContent = `You are about to email ${jobs.length} jobs.`;
  const savedEmail = localStorage.getItem("job-hunter-email") || "";
  $("emailInput").value = savedEmail;
  $("saveEmailToggle").checked = Boolean(savedEmail);
  $("emailModal").hidden = false;
}

async function sendEmailFromModal() {
  const recipient = $("emailInput").value.trim();
  if (!recipient) {
    toast("Please enter a valid email address.", true);
    return;
  }

  if ($("saveEmailToggle").checked) {
    localStorage.setItem("job-hunter-email", recipient);
  } else {
    localStorage.removeItem("job-hunter-email");
  }

  const jobs = filteredJobs();
  
  const btn = $("sendEmailBtn");
  const originalText = btn.innerHTML;
  btn.innerHTML = `<span class="btn-spinner"></span> Sending…`;
  btn.disabled = true;
  
  try {
    const response = await fetch("/api/email/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipient_email: recipient, jobs: jobs })
    });
    
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Failed to email jobs");
    
    toast(`Sent ${jobs.length} jobs to ${recipient}`);
    $("emailModal").hidden = true;
  } catch (error) {
    toast(error.message, true);
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

function openOnboarding() {
  const steps = [
    ["Welcome to Job Hunter AI", "Upload your CV to get more useful job matches."],
    ["Find opportunities", "Start a scan from the dashboard whenever you are ready."],
    ["Keep track", "Save roles and mark applications as you progress."],
  ];
  let index = 0;
  const overlay = $("onboardingOverlay");
  const draw = () => {
    $("onboardingContent").innerHTML = `<h2>${steps[index][0]}</h2><p>${steps[index][1]}</p>`;
    $("onboardingProgressBar").style.width = `${((index + 1) / steps.length) * 100}%`;
    $("onboardingProgressText").textContent = `${index + 1} of ${steps.length}`;
    $("onboardingBack").hidden = index === 0;
    $("onboardingNext").textContent = index === steps.length - 1 ? "Finish" : "Next";
  };
  const close = () => { overlay.hidden = true; localStorage.setItem(ONBOARDING_KEY, "true"); };
  $("onboardingBack").onclick = () => { index -= 1; draw(); };
  $("onboardingNext").onclick = () => { if (index === steps.length - 1) close(); else { index += 1; draw(); } };
  $("onboardingSkip").onclick = close;
  overlay.hidden = false;
  draw();
}



document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
["keywordFilter", "statusFilter", "companyJobFilter", "locationJobFilter", "remoteFilter"].forEach((id) => $(id).addEventListener(id === "keywordFilter" ? "input" : "change", renderJobs));
$("jobSort").addEventListener("change", () => { state.sortKey = $("jobSort").value; state.sortDirection = ["newest", "match", "seen"].includes(state.sortKey) ? "desc" : "asc"; renderJobs(); });
$("searchButton").addEventListener("click", startScan);
$("startScanBtn").addEventListener("click", startScan);
document.querySelectorAll(".action-card").forEach((button) => button.addEventListener("click", () => showPage({ "view-jobs": "jobs", "upload-cv": "cv-profile", "manage-companies": "companies", "view-settings": "settings" }[button.dataset.action])));
$("companySearch").addEventListener("input", renderCompanies);
$("scanAllBtn").addEventListener("click", startScan);

$("uploadArea").addEventListener("click", () => $("cvFileInput").click());
$("cvFileInput").addEventListener("change", uploadCv);
$("replaceCvBtn").addEventListener("click", () => $("cvFileInput").click());
["addLanguage", "addFramework", "addTool"].forEach((id) => $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); addSkill($(id), $({ addLanguage: "languageSkills", addFramework: "frameworkSkills", addTool: "toolSkills" }[id])); } }));
$("saveProfileBtn").addEventListener("click", saveProfile);
$("telegramToggle").addEventListener("change", () => { $("telegramSettings").hidden = !$("telegramToggle").checked; });
$("saveSettingsBtn").addEventListener("click", saveSettings);
$("clearDataBtn").addEventListener("click", clearLocalData);
$("showTutorialBtn").addEventListener("click", openOnboarding);
$("closeJobModal").addEventListener("click", () => { $("jobDetailsModal").hidden = true; });
$("jobDetailsModal").addEventListener("click", (event) => { if (event.target === $("jobDetailsModal")) $("jobDetailsModal").hidden = true; });
if ($("closeEmailModal")) {
  $("closeEmailModal").addEventListener("click", () => { $("emailModal").hidden = true; });
  $("emailModal").addEventListener("click", (event) => { if (event.target === $("emailModal")) $("emailModal").hidden = true; });
  $("sendEmailBtn").addEventListener("click", sendEmailFromModal);
}
$("getStartedBtn").addEventListener("click", () => showPage("cv-profile"));
$("skipSetupBtn").addEventListener("click", () => { $("emptyState").hidden = true; });
if ($("emailJobsBtn")) {
  $("emailJobsBtn").addEventListener("click", emailJobs);
}

loadLocalState();
showPage("dashboard");
loadJobs();
if (!localStorage.getItem(ONBOARDING_KEY)) openOnboarding();

