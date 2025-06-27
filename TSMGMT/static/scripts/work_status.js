document.addEventListener('click', e => {
    const btn = e.target.closest('.hide-todo');
    if (!btn) return;

    const todoId = btn.dataset.id;
    fetch('/work_status/update', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
            // add CSRF header here if you’re using one
        },
        body: JSON.stringify({ id: todoId, status: 'hidden' })
    })
        .then(resp => {
            if (resp.status === 204) {
                // gently remove the card from the UI
                const card = btn.closest('.card');
                card.classList.add('opacity-0', 'transition-opacity');
                setTimeout(() => card.remove(), 300);
            } else {
                return resp.json().then(j => Promise.reject(j.error));
            }
        })
        .catch(err => {
            console.error('Failed to hide task:', err);
            alert('Could not hide task: ' + err);
        });
});
