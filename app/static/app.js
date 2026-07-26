/* ── Drag & Drop ─── */
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileLabel = document.getElementById('file-selected');
const uploadForm = document.getElementById('upload-form');
const submitBtn  = document.getElementById('submit-btn');
const loadingOverlay = document.getElementById('loading-overlay');

if (dropZone) {
  ['dragenter', 'dragover'].forEach(ev => {
    dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  });
  ['dragleave', 'drop'].forEach(ev => {
    dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.remove('dragover'); });
  });
  dropZone.addEventListener('drop', e => {
    const files = e.dataTransfer.files;
    if (files.length) {
      fileInput.files = files;
      updateFileLabel(files[0].name);
    }
  });
}

if (fileInput) {
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) updateFileLabel(fileInput.files[0].name);
  });
}

function updateFileLabel(name) {
  if (fileLabel) { fileLabel.textContent = `📎 ${name}`; fileLabel.style.display = 'block'; }
  if (submitBtn) { submitBtn.disabled = false; }
}

if (uploadForm) {
  uploadForm.addEventListener('submit', () => {
    if (loadingOverlay) loadingOverlay.classList.add('show');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Загрузка…'; }
  });
}

/* ── Table sort ─── */
(function () {
  const table = document.getElementById('results-table');
  if (!table) return;

  let sortCol = 0;   // по умолчанию — колонка «Балл»
  let sortAsc = false;

  const tbody = table.querySelector('tbody');
  const headers = table.querySelectorAll('thead th[data-col]');

  function sortTable(colIdx, asc) {
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {
      const av = a.cells[colIdx]?.dataset.sort ?? a.cells[colIdx]?.textContent.trim() ?? '';
      const bv = b.cells[colIdx]?.dataset.sort ?? b.cells[colIdx]?.textContent.trim() ?? '';
      const an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv, 'ru') : bv.localeCompare(av, 'ru');
    });
    rows.forEach(r => tbody.appendChild(r));
  }

  headers.forEach(th => {
    th.addEventListener('click', () => {
      const col = parseInt(th.dataset.col);
      if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = false; }
      headers.forEach(h => { h.classList.remove('sorted'); h.querySelector('.sort-arrow').textContent = '↕'; });
      th.classList.add('sorted');
      th.querySelector('.sort-arrow').textContent = sortAsc ? '↑' : '↓';
      sortTable(col, sortAsc);
    });
  });

  // Начальная сортировка по баллу (убывание)
  sortTable(0, false);
  headers[0]?.classList.add('sorted');
  if (headers[0]) headers[0].querySelector('.sort-arrow').textContent = '↓';
})();

/* ── Score filter slider ─── */
(function () {
  const slider = document.getElementById('score-slider');
  const scoreVal = document.getElementById('score-val');
  const tbody = document.querySelector('#results-table tbody');

  if (!slider || !tbody) return;

  slider.addEventListener('input', () => {
    const min = parseFloat(slider.value);
    scoreVal.textContent = min.toString();

    tbody.querySelectorAll('tr').forEach(row => {
      const score = parseFloat(row.dataset.score ?? '0');
      row.style.display = score >= min ? '' : 'none';
    });

    // Показываем счётчик
    const shown = tbody.querySelectorAll('tr:not([style*="none"])').length;
    const total = tbody.querySelectorAll('tr').length;
    const counter = document.getElementById('shown-counter');
    if (counter) counter.textContent = `${shown} из ${total}`;
  });
})();

/* ── Feature importance bar animation ─── */
document.querySelectorAll('.feat-bar').forEach(bar => {
  const target = bar.dataset.width || '0';
  bar.style.width = '0';
  setTimeout(() => { bar.style.width = target + '%'; }, 200);
});
