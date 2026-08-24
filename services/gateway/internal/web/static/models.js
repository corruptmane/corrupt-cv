// Model picker: one delegated listener covers buttons rendered by the
// /models/search partial, including nodes swapped in by HTMX later.
document.addEventListener('click', function (e) {
  var btn = e.target.closest('.model-option');
  if (!btn) return;
  var keyInput = document.getElementById('model_key');
  if (!keyInput) return;
  var key = btn.dataset.key;
  var name = btn.dataset.name;
  keyInput.value = key;
  document.getElementById('model_search').value = name;
  document.getElementById('model-results').innerHTML = '';
  document.getElementById('model-selected').textContent = 'Selected: ' + name + ' (' + key + ')';
});
