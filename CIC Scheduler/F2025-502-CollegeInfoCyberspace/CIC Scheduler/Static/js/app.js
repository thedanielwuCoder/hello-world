// app.js — Instructor preferences (supports alphanumeric course IDs)

// Local state
const state = {
  items: [] // { courseId: string, preference: number, label: string }
};

// Helpers
function qs(id) { return document.getElementById(id); }
function enableSubmitIfAny() {
  const btn = qs('submitBtn');
  if (!btn) return;
  btn.disabled = state.items.length === 0;
}

// Render the preferences table
function renderTable() {
  const tbody = qs('prefsBody');
  if (!tbody) return;

  // Clear
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

  if (state.items.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 3;
    td.style.color = '#64748b';
    td.textContent = 'No preferences yet.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // Sort by preference (1 best → 5 worst)
  const rows = [...state.items].sort((a, b) => a.preference - b.preference);

  rows.forEach(item => {
    const tr = document.createElement('tr');

    const tdPref = document.createElement('td');
    tdPref.textContent = item.preference.toString();
    tr.appendChild(tdPref);

    const tdCourse = document.createElement('td');
    tdCourse.textContent = item.label;
    tr.appendChild(tdCourse);

    const tdActions = document.createElement('td');
    const btn = document.createElement('button');
    btn.className = 'logout-btn';
    btn.type = 'button';
    btn.textContent = 'Remove';
    btn.addEventListener('click', () => removeItem(item.courseId));
    tdActions.appendChild(btn);
    tr.appendChild(tdActions);

    tbody.appendChild(tr);
  });
}

// Remove an item
function removeItem(courseId) {
  state.items = state.items.filter(x => String(x.courseId) !== String(courseId));
  renderTable();
  enableSubmitIfAny();
}

// Public: called by onclick in HTML
window.addPrefRow = function addPrefRow() {
  const courseSel = qs('courseSelect');
  const prefSel = qs('prefSelect');
  if (!courseSel || !prefSel) { alert('Missing form controls.'); return; }

  const rawCourseVal = courseSel.value;  // can be alphanumeric like "CIC6173"
  const rawPrefVal = prefSel.value;

  if (!rawCourseVal) { alert('Please choose a course.'); return; }
  if (!rawPrefVal) { alert('Please choose a preference (1–5).'); return; }

  const courseId = String(rawCourseVal).trim();     // allow alphanumeric IDs
  const preference = Number(rawPrefVal);              // keep prefs numeric

  if (!courseId) { alert('Course id is missing.'); return; }
  if (!Number.isInteger(preference) || preference < 1 || preference > 5) {
    alert(`Preference must be 1–5, got: "${rawPrefVal}"`); return;
  }

  const label = courseSel.options[courseSel.selectedIndex].textContent.trim();

  // prevent duplicates (string compare)
  if (state.items.some(x => String(x.courseId) === courseId)) {
    alert('This course is already in your list.');
    return;
  }

  state.items.push({ courseId, preference, label });
  renderTable();
  enableSubmitIfAny();

  // Reset selects to force a fresh valid choice next time
  courseSel.value = '';
  prefSel.value = '1';
};

// Preview modal
window.openPreview = function openPreview() {
  if (state.items.length === 0) return;

  const ul = qs('previewList');
  const modal = qs('previewModal');
  if (!ul || !modal) return;

  // Clear list
  while (ul.firstChild) ul.removeChild(ul.firstChild);

  const items = [...state.items].sort((a, b) => a.preference - b.preference);
  items.forEach(it => {
    const li = document.createElement('li');
    li.textContent = `Preference ${it.preference}: ${it.label}`;
    ul.appendChild(li);
  });

  modal.style.display = 'block';
};

window.closePreview = function closePreview() {
  const modal = qs('previewModal');
  if (modal) modal.style.display = 'none';
};

// Submit to backend
window.confirmSubmit = async function confirmSubmit() {
  // Deep validation before send
  for (let i = 0; i < state.items.length; i++) {
    const it = state.items[i];
    if (it == null || typeof it !== 'object') {
      alert(`Bad item at index ${i}: ${JSON.stringify(it)}`);
      return;
    }
    if (it.courseId == null || String(it.courseId).trim() === '') {
      alert(`items[${i}].courseId is empty.`);
      return;
    }
    if (!Number.isInteger(it.preference) || it.preference < 1 || it.preference > 5) {
      alert(`items[${i}].preference must be 1–5; got: ${JSON.stringify(it.preference)}`);
      return;
    }
  }

  const payload = {
    items: state.items.map(x => ({ courseId: x.courseId, preference: x.preference })), // courseId stays string
    notes: (qs('notes')?.value || '').trim(),
  };
  console.log('DEBUG payload →', payload);

  try {
    const resp = await fetch('/instructor/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'same-origin'
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.ok === false) {
      const msg = data.error || `Submit failed (${resp.status})`;
      alert(msg);
      return;
    }

    if (data.skipped && Array.isArray(data.skipped) && data.skipped.length > 0) {
      alert(`Submitted, but skipped rows at indices: ${data.skipped.join(', ')}`);
    } else {
      alert('Preferences submitted successfully!');
    }
    closePreview();
    window.location.reload();
  } catch (err) {
    console.error(err);
    alert(`There was a problem submitting your preferences.\n${err.message}`);
  }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  renderTable();
  enableSubmitIfAny();
});
