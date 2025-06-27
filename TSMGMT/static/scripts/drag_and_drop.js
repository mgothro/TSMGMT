window.addEventListener('DOMContentLoaded', () => {
    let draggedEl = null;

    // Map our status keys to Bootstrap color names
    const statusMap = {
        'done': 'success',
        'working_on': 'info',
        'started': 'warning',
        'todays_todos': 'purple',
        'not_started': 'secondary',
		'recurring': 'primary'
    };

    // 1) When drag starts, remember the full card element
    function onDragStart(e) {
        draggedEl = e.currentTarget;
        e.dataTransfer.effectAllowed = 'move';
        // Some browsers require setData to enable dragging
        try { e.dataTransfer.setData('text/plain', ''); } catch (_) { }
    }

    // 2) Attach dragstart to each card wrapper
    document.querySelectorAll('.draggable-item').forEach(card => {
        card.setAttribute('draggable', 'true');
        card.addEventListener('dragstart', onDragStart);
    });

    // 3) Wire up dropzones
    document.querySelectorAll('.dropzone').forEach(zone => {
        zone.addEventListener('dragover', e => {
            e.preventDefault();
            zone.classList.add('drag-over');
            e.dataTransfer.dropEffect = 'move';
        });
        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', async e => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            if (!draggedEl) return;

            const list = zone.querySelector('.todo-list');
            const card = draggedEl;

            // 4) FLIP: capture first positions
            const items = Array.from(list.querySelectorAll('.draggable-item'));
            const firstRects = new Map(items.map(el => [el, el.getBoundingClientRect()]));

            // remove placeholder if any
            const placeholder = list.querySelector('.placeholder');
            if (placeholder) placeholder.remove();

            // 5) DOM move (insert at correct spot)
            card.style.display = 'none';
            const elemBelow = document.elementFromPoint(e.clientX, e.clientY);
            card.style.display = '';
            let ref = elemBelow;
            while (ref && ref.parentNode !== list) ref = ref.parentNode;

            if (ref && ref !== card) {
                const { top, height } = ref.getBoundingClientRect();
                if (e.clientY < top + height / 2) list.insertBefore(card, ref);
                else list.insertBefore(card, ref.nextSibling);
            } else {
                list.appendChild(card);
            }

            // 6) Update header classes for the new status
            const newStatus = zone.dataset.status;
            const header = card.querySelector('.card-header');
            // remove any old bg-* and text-* classes
            header.classList.remove(
                'bg-info', 'bg-warning', 'bg-secondary', 'bg-light',
                'text-white', 'text-dark', 'bg-purple', 'bg-success',
                'bg-primary'
            );
            // add the new ones
            header.classList.add(
                `bg-${statusMap[newStatus]}`,
                newStatus === 'not_started' ? 'text-dark' : 'text-white'
            );

            // 7) FLIP: capture last positions and play animation
            items.forEach(el => {
                const first = firstRects.get(el);
                const last = el.getBoundingClientRect();
                const dx = first.left - last.left;
                const dy = first.top - last.top;
                if (dx || dy) {
                    el.style.transform = `translate(${dx}px,${dy}px)`;
                    el.style.transition = 'transform 0s';
                    requestAnimationFrame(() => {
                        el.style.transition = 'transform 250ms ease';
                        el.style.transform = '';
                    });
                }
            });

            // 8) Persist new order
            const positions = Array.from(list.children)
                .filter(el => el.classList.contains('draggable-item'))
                .map((el, idx) => ({
                    id: el.dataset.id,
                    status: zone.dataset.status,
                    position: idx
                }));

            try {
                await fetch('/work_status/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ positions })
                });
            } catch (err) {
                console.error('Failed to save positions:', err);
            }

            // reset for next drag
            draggedEl = null;
        });
    });
});
