(() => {
    const positionPanel = (button, panel) => {
        if (window.matchMedia('(max-width:600px)').matches) {
            panel.classList.remove('is-viewport-positioned');
            panel.style.removeProperty('top');
            panel.style.removeProperty('left');
            return;
        }
        const buttonRect = button.getBoundingClientRect();
        const gap = 8;
        panel.classList.add('is-viewport-positioned');
        panel.style.visibility = 'hidden';
        panel.hidden = false;
        const panelRect = panel.getBoundingClientRect();
        const left = Math.max(12, Math.min(buttonRect.right - panelRect.width, window.innerWidth - panelRect.width - 12));
        const below = buttonRect.bottom + gap;
        const above = buttonRect.top - panelRect.height - gap;
        const top = below + panelRect.height <= window.innerHeight - 12 || above < 12 ? below : above;
        panel.style.left = `${left}px`;
        panel.style.top = `${Math.max(12, top)}px`;
        panel.style.visibility = '';
    };

    const closeToolbar = toolbar => {
        const button = toolbar.querySelector('[data-filter-toggle]');
        const panel = toolbar.querySelector('[data-filter-popover]');
        if (!button || !panel) return;
        panel.hidden = true;
        panel.classList.remove('is-viewport-positioned');
        panel.style.removeProperty('top');
        panel.style.removeProperty('left');
        button.setAttribute('aria-expanded', 'false');
    };

    document.querySelectorAll('[data-table-toolbar]').forEach(toolbar => {
        const button = toolbar.querySelector('[data-filter-toggle]');
        const panel = toolbar.querySelector('[data-filter-popover]');
        if (!button || !panel) return;
        button.addEventListener('click', () => {
            const opening = panel.hidden;
            document.querySelectorAll('[data-table-toolbar]').forEach(other => {
                if (other !== toolbar) closeToolbar(other);
            });
            panel.hidden = !opening;
            button.setAttribute('aria-expanded', String(opening));
            if (opening) {
                positionPanel(button, panel);
                panel.querySelector('select,input,button,a')?.focus();
            }
        });
        toolbar.querySelector('[data-filter-close]')?.addEventListener('click', () => {
            closeToolbar(toolbar);
            button.focus();
        });
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        document.querySelectorAll('[data-table-toolbar]').forEach(toolbar => {
            const button = toolbar.querySelector('[data-filter-toggle]');
            const panel = toolbar.querySelector('[data-filter-popover]');
            if (panel && !panel.hidden) {
                closeToolbar(toolbar);
                button?.focus();
            }
        });
    });
    window.addEventListener('resize', () => {
        document.querySelectorAll('[data-table-toolbar]').forEach(toolbar => {
            const button = toolbar.querySelector('[data-filter-toggle]');
            const panel = toolbar.querySelector('[data-filter-popover]');
            if (button && panel && !panel.hidden) positionPanel(button, panel);
        });
    });
})();
