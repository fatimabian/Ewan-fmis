// Shared filter popovers open beneath their trigger and stay inside the viewport.
(() => {
    const positionPanel = (button, panel) => {
        const buttonRect = button.getBoundingClientRect();
        const gap = 8;
        panel.classList.add('is-viewport-positioned');
        panel.style.visibility = 'hidden';
        panel.hidden = false;
        const panelRect = panel.getBoundingClientRect();
        const left = Math.max(12, Math.min(buttonRect.right - panelRect.width, window.innerWidth - panelRect.width - 12));
        const below = buttonRect.bottom + gap;
        panel.style.left = `${left}px`;
        panel.style.top = `${Math.max(8, below)}px`;
        panel.style.maxHeight = `${Math.max(100, window.innerHeight - below - 12)}px`;
        panel.style.overflowY = 'auto';
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
    const repositionOpenPanels = () => {
        document.querySelectorAll('[data-table-toolbar]').forEach(toolbar => {
            const button = toolbar.querySelector('[data-filter-toggle]');
            const panel = toolbar.querySelector('[data-filter-popover]');
            if (button && panel && !panel.hidden) positionPanel(button, panel);
        });
    };
    window.addEventListener('resize', repositionOpenPanels);
    document.addEventListener('scroll', repositionOpenPanels, true);
})();
