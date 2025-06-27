const syncBtn = document.getElementById('js-sync');
const container = document.getElementById('sync-container');
const progBar = document.getElementById('sync-progress');
const logEl = document.getElementById('sync-log');
const mainRow = document.getElementById('main-row');

syncBtn.addEventListener('click', e => {
    e.preventDefault();
    // Disable main row and show sync UI
    mainRow.classList.add('hidden');
    container.style.display = 'block';
    progBar.value = 0;
    logEl.innerHTML = '';

    let total = 0;
    let current = 0;

    const pstFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Los_Angeles',
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: 'numeric', second: 'numeric', hour12: true
    });

    const es = new EventSource('/work_status/sync_stream');

    es.onmessage = evt => {
        const msg = evt.data;

        // 1) Server-side exception came back
        if (msg.startsWith('SYNC_ERROR:')) {
            const errText = msg.slice('SYNC_ERROR:'.length);
            const now = new Date();
            const stamp = pstFormatter.format(now);
            const errEl = document.createElement('div');
            errEl.style.color = 'red';
            errEl.textContent = `[${stamp}] Sync failed: ${errText}`;
            logEl.appendChild(errEl);
            logEl.scrollTop = logEl.scrollHeight;

            es.close();
            // restore UI immediately
            container.style.display = 'none';
            mainRow.classList.remove('hidden');
            return;
        }

        // 2) Total count
        if (msg.startsWith('PROGRESS_TOTAL:')) {
            total = parseInt(msg.split(':')[1], 10);
            progBar.max = total;
            return;
        }
        // 3) Step increment
        if (msg.startsWith('PROGRESS_STEP:')) {
            current += parseInt(msg.split(':')[1], 10);
            progBar.value = current;
            return;
        }

        // 4) Normal log line
        const now = new Date();
        const stamp = pstFormatter.format(now);
        const line = document.createElement('div');
        line.textContent = `[${stamp}] ${msg}`;
        logEl.appendChild(line);
        logEl.scrollTop = logEl.scrollHeight;

        // 5) All done—reload
        if (msg === 'All done!') {
            es.close();
            setTimeout(() => {
                container.style.display = 'none';
                mainRow.classList.remove('hidden');
                window.location.reload();
            }, 500);
        }
    };

    es.onerror = () => {
        // This only fires on lower-level connection errors
        es.close();
        const now = new Date();
        const stamp = pstFormatter.format(now);
        const err = document.createElement('div');
        err.style.color = 'red';
        err.textContent = `[${stamp}] Network error during sync.`;
        logEl.appendChild(err);
        logEl.scrollTop = logEl.scrollHeight;
        container.style.display = 'none';
        mainRow.classList.remove('hidden');
    };
});
