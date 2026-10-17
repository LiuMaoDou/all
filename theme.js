// Runs before the stylesheet so the saved/system theme is applied before paint.
(() => {
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    const valid = value => ['light', 'dark'].includes(value) ? value : null;
    let preference = null;
    try { preference = valid(localStorage.getItem('theme')); } catch { /* Storage is optional. */ }

    function apply() {
        document.documentElement.dataset.theme = preference || (system.matches ? 'dark' : 'light');
        document.dispatchEvent(new Event('themechange'));
    }

    window.navTheme = {
        toggle() {
            preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
            try { localStorage.setItem('theme', preference); } catch { /* Keep this session's choice. */ }
            apply();
        }
    };
    system.addEventListener('change', () => { if (!preference) apply(); });
    window.addEventListener('storage', event => {
        if (event.key === 'theme' || event.key === null) {
            preference = valid(event.newValue);
            apply();
        }
    });
    apply();
})();
