// Job status timeline: renders server-provided initial state, then tails
// the SSE stream until the job reaches a terminal status.
(function () {
  var card = document.querySelector('.job-card');
  if (!card) return;
  var jobId = card.dataset.jobId;
  var steps = { pending: 'step-pending', rendering: 'step-rendering', completed: 'step-completed' };
  var order = ['pending', 'rendering', 'completed'];

  function render(update) {
    var reached = update.status === 'failed' ? 'rendering' : update.status;
    var reachedIdx = order.indexOf(reached);
    order.forEach(function (name, idx) {
      var el = document.getElementById(steps[name]);
      el.classList.toggle('done', reachedIdx >= 0 && idx < reachedIdx);
      el.classList.toggle('active', idx === reachedIdx && update.status !== 'failed');
      if (update.status === 'completed') { el.classList.add('done'); el.classList.remove('active'); }
    });
    var errBox = document.getElementById('error-box');
    if (update.status === 'failed') {
      errBox.hidden = false;
      errBox.textContent = 'Generation failed: ' + (update.error || 'unknown error');
    }
    if (update.status === 'completed' && update.download_url) {
      var btn = document.getElementById('download-btn');
      btn.href = update.download_url;
      btn.hidden = false;
    }
  }

  // Initial state arrives as a data attribute on the job card; the SSE
  // stream re-sends it immediately anyway.
  var initial = JSON.parse(card.dataset.initial);
  render(initial);

  if (initial.status !== 'completed' && initial.status !== 'failed') {
    var es = new EventSource('/jobs/' + jobId + '/events');
    es.addEventListener('status', function (e) {
      var update = JSON.parse(e.data);
      render(update);
      if (update.status === 'completed' || update.status === 'failed') { es.close(); }
    });
    es.onerror = function () { /* EventSource retries automatically */ };
  }
})();
