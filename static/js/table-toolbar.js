(() => {
    const closeToolbar = toolbar => {
        const button = toolbar.querySelector('[data-filter-toggle]');
        const panel = toolbar.querySelector('[data-filter-popover]');
        if (!button || !panel) return;
        panel.hidden = true;
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
            if (opening) panel.querySelector('select,input,button,a')?.focus();
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
})();
