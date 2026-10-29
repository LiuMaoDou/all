'use strict';

window.createFavorites = ({ api, icon, escape, target, isActive }) => {
    const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });
    const dateFormatter = new Intl.DateTimeFormat('sv-SE', { year: 'numeric', month: '2-digit', day: '2-digit' });
    const state = { folders: [], bookmarks: [], folder: 'all', sortBy: 'name', sort: 'asc', query: '', loaded: false, busy: false, error: '' };
    try {
        state.sort = localStorage.getItem('favorites-sort') === 'desc' ? 'desc' : 'asc';
        state.sortBy = localStorage.getItem('favorites-sort-by') === 'date' ? 'date' : 'name';
        const saved = localStorage.getItem('favorites-folder');
        if (saved === 'unfiled' || /^\d+$/.test(saved || '')) state.folder = saved;
    } catch { /* Preferences are optional. */ }

    const page = document.createElement('section');
    page.className = 'favorites-page';
    page.setAttribute('aria-label', '我的收藏');
    page.innerHTML = `
        <header class="favorites-page-header">
            <h1>我的收藏</h1>
        </header>
        <div class="favorites-status" role="alert" hidden><span></span><button data-favorite-action="retry">重新加载</button></div>
        <div class="favorites-body">
            <button class="folders-backdrop" data-favorite-action="close-folders" aria-label="关闭文件夹列表" hidden></button>
            <nav class="favorites-folders" aria-label="收藏文件夹"></nav>
            <section class="favorites-workspace" aria-label="收藏链接">
                <div class="favorites-content-header">
                    <button class="favorites-mobile-folders favorite-secondary" data-favorite-action="toggle-folders" aria-expanded="false"></button>
                    <div class="favorites-breadcrumb"></div>
                    <div class="favorites-toolbar">
                        <div class="favorites-folder-heading"></div>
                        <div class="favorites-filters">
                            <label class="favorite-search"><span></span><input type="search" aria-label="搜索收藏名称或链接" placeholder="搜索收藏名称或链接"></label>
                        </div>
                    </div>
                </div>
                <div class="favorite-list-stage">
                    <div class="favorite-list-scroll"><div class="favorite-list-legend" role="group" aria-label="收藏排序"><button class="favorite-column-sort" data-favorite-action="sort-name"></button><button class="favorite-column-sort" data-favorite-action="sort-date"></button><span></span></div><div class="favorite-list"></div></div>
                </div>
            </section>
        </div>`;

    const dialog = document.createElement('dialog');
    dialog.className = 'favorites-dialog';
    dialog.setAttribute('aria-labelledby', 'favoriteDialogTitle');
    document.body.append(dialog);
    const menu = document.createElement('div');
    menu.className = 'favorite-menu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    document.body.append(menu);
    let menuTrigger = null;
    let dialogTrigger = null;
    let dialogKind = null;
    let dialogId = null;
    let loadPromise = null;

    const field = selector => page.querySelector(selector);
    const folderName = () => state.folder === 'all' ? '全部收藏' : state.folder === 'unfiled' ? '未分类' : state.folders.find(f => String(f.id) === state.folder)?.name || '全部收藏';
    const savePreference = (key, value) => { try { localStorage.setItem(key, value); } catch { /* Optional. */ } };
    const friendlyError = error => ({
        'Folder already exists': '已有同名文件夹，请换一个名称。',
        'This folder name is reserved': '“全部收藏”和“未分类”是系统文件夹，请使用其他名称。',
        'Folder no longer exists': '文件夹已被删除，请重新选择。',
        'Record no longer exists': '这条记录已被删除，请重新加载。'
    })[error.message] || error.message;

    function hideMenu(restoreFocus = false) {
        const wasOpen = !menu.hidden;
        menu.hidden = true;
        menuTrigger?.setAttribute('aria-expanded', 'false');
        if (restoreFocus && wasOpen && menuTrigger?.isConnected) menuTrigger.focus();
    }

    function drawFolders() {
        const count = id => state.bookmarks.filter(b => b.folder_id === id).length;
        const folderRow = (id, name, count, symbol, editable = false) => `<div class="favorite-folder-row ${state.folder === String(id) ? 'active' : ''}">
            <button class="favorite-folder-select" data-favorite-action="folder" data-folder="${id}" ${state.folder === String(id) ? 'aria-current="true"' : ''}>${icon(symbol)}<span class="favorite-folder-name">${escape(name)}</span><span class="favorite-folder-count">${count}</span></button>
            ${editable ? `<button class="favorite-folder-more" data-favorite-action="folder-menu" data-id="${id}" aria-label="管理文件夹 ${escape(name)}" aria-haspopup="menu" aria-expanded="false">${icon('ellipsis')}</button>` : ''}
        </div>`;
        field('.favorites-folders').innerHTML = `<div class="favorites-folders-heading"><span>文件夹</span><button class="favorite-icon-button" data-favorite-action="new-folder" aria-label="新建文件夹">${icon('plus')}</button></div>
            ${folderRow('all', '全部收藏', state.bookmarks.length, 'folder')}
            ${folderRow('unfiled', '未分类', count(null), 'inbox')}
            ${[...state.folders].sort((a, b) => collator.compare(a.name, b.name)).map(f => folderRow(f.id, f.name, count(f.id), 'folder', true)).join('')}`;
    }

    function drawRows() {
        for (const [key, label] of [['name', '收藏名称'], ['date', '添加日期']]) {
            const active = state.sortBy === key;
            const button = field(`[data-favorite-action="sort-${key}"]`);
            button.innerHTML = `<span>${label}</span>${icon(active ? 'chevron-down' : 'arrow-up-down')}`;
            button.classList.toggle('ascending', active && state.sort === 'asc');
            button.setAttribute('aria-pressed', String(active));
            button.setAttribute('aria-label', `${label}，${active ? (state.sort === 'asc' ? '当前升序，点击降序' : '当前降序，点击升序') : '点击排序'}`);
        }
        const query = state.query.trim().toLocaleLowerCase();
        const inFolder = state.bookmarks.filter(b => state.folder === 'all' || (state.folder === 'unfiled' ? b.folder_id === null : String(b.folder_id) === state.folder));
        const visible = inFolder.filter(b => !query || `${b.name}\n${b.url}`.toLocaleLowerCase().includes(query))
            .sort((a, b) => (state.sort === 'desc' ? -1 : 1) * ((state.sortBy === 'date' ? Date.parse(a.created_at) - Date.parse(b.created_at) : collator.compare(a.name, b.name)) || a.id - b.id));
        const name = folderName();
        field('.favorites-breadcrumb').innerHTML = `<span>我的收藏</span><span aria-hidden="true">/</span><span>${escape(name)}</span>`;
        field('.favorites-folder-heading').innerHTML = `${icon('folder-open')}<h2>${escape(name)}</h2><span class="favorite-visible-count" aria-live="polite">${visible.length} 个链接</span>`;
        if (!state.loaded) {
            field('.favorite-list').innerHTML = `<div class="favorite-empty" role="status">${state.error ? '暂时无法加载收藏，请重新加载。' : '正在加载收藏…'}</div>`;
            return;
        }
        const addButton = `<button class="favorite-icon-button favorite-add-link" data-favorite-action="new-bookmark" aria-label="收藏链接">${icon('plus')}</button>`;
        if (!visible.length) {
            field('.favorite-list').innerHTML = `<div class="favorite-empty">${icon(query ? 'search' : 'bookmark')}<h3>${query ? '没有找到相关收藏' : '这里还没有收藏'}</h3><p>${query ? '试试其他名称或网址。' : '收藏网站、文章、文档和视频，让好内容随时可达。'}</p>${addButton}</div>`;
            return;
        }
        field('.favorite-list').innerHTML = visible.map(bookmark => {
            const date = new Date(bookmark.created_at);
            const label = dateFormatter.format(date);
            return `<div class="favorite-row" data-bookmark-id="${bookmark.id}">
                <a class="favorite-link" href="${escape(bookmark.url)}" target="_blank" rel="noopener noreferrer"><span class="favorite-symbol tone-${bookmark.id % 4}">${icon(bookmark.icon)}</span><span class="favorite-name">${escape(bookmark.name)}</span></a>
                <time class="favorite-date" datetime="${escape(bookmark.created_at)}">${label}</time>
                <button class="favorite-more" data-favorite-action="bookmark-menu" data-id="${bookmark.id}" aria-label="管理收藏 ${escape(bookmark.name)}" aria-haspopup="menu" aria-expanded="false">${icon('ellipsis')}</button>
            </div>`;
        }).join('') + `<div class="favorite-add-row">${addButton}</div>`;
    }

    function draw() {
        if (!isActive()) return;
        hideMenu();
        const banner = field('.favorites-status');
        banner.hidden = !state.error;
        banner.querySelector('span').textContent = state.error;
        field('.favorites-mobile-folders').innerHTML = `${icon('folder')}<span>文件夹</span>`;
        field('.favorite-search > span').innerHTML = icon('search');
        field('.favorite-search input').value = state.query;
        drawFolders();
        drawRows();
    }

    async function refresh() {
        if (loadPromise) return loadPromise;
        loadPromise = (async () => {
            state.error = '';
            try {
                const data = await api('/api/favorites');
                if (!Array.isArray(data.folders) || !Array.isArray(data.bookmarks)) throw new Error('服务器返回了无效的收藏数据。');
                state.folders = data.folders;
                state.bookmarks = data.bookmarks;
                state.loaded = true;
                if (!['all', 'unfiled'].includes(state.folder) && !state.folders.some(f => String(f.id) === state.folder)) state.folder = 'all';
            } catch (error) { state.error = friendlyError(error); }
            finally { loadPromise = null; draw(); }
        })();
        return loadPromise;
    }

    function showDialog(kind, id = null, trigger = null) {
        if (state.busy) return;
        dialogTrigger = trigger || menuTrigger || field('[data-favorite-action="new-bookmark"]');
        hideMenu();
        dialogKind = kind;
        dialogId = id;
        const bookmark = state.bookmarks.find(b => b.id === id);
        const folder = state.folders.find(f => f.id === id);
        const deleting = kind.startsWith('delete-');
        const isFolder = kind.includes('folder');
        const title = { 'new-folder': '新建文件夹', 'rename-folder': '重命名文件夹', 'delete-folder': '删除文件夹', 'new-bookmark': '收藏链接', 'edit-bookmark': '编辑收藏', 'move-bookmark': '移动收藏', 'delete-bookmark': '删除收藏' }[kind];
        const defaultFolder = bookmark ? bookmark.folder_id : /^\d+$/.test(state.folder) ? Number(state.folder) : null;
        const folderOptions = `<option value="">未分类</option>${state.folders.map(f => `<option value="${f.id}">${escape(f.name)}</option>`).join('')}`;
        dialog.innerHTML = `<form id="favoriteForm">
            <div class="favorite-dialog-heading"><h2 id="favoriteDialogTitle">${title}</h2><button type="button" class="favorite-icon-button" data-dismiss aria-label="关闭">${icon('x')}</button></div>
            ${deleting ? `<p class="favorite-confirm">${kind === 'delete-folder' ? `确定删除“${escape(folder?.name)}”？其中的收藏会保留并移到“未分类”。` : `确定删除“${escape(bookmark?.name)}”？`}</p>` : isFolder ? `<label for="favoriteFolderName">文件夹名称</label><input id="favoriteFolderName" name="name" maxlength="120" required value="${escape(folder?.name || '')}" placeholder="例如：开发资源">` : `
                <label for="favoriteName">名称</label><input id="favoriteName" name="name" maxlength="200" required value="${escape(bookmark?.name || '')}" placeholder="给这个链接起个名字">
                <label for="favoriteUrl">网址</label><input id="favoriteUrl" name="url" type="url" maxlength="4096" required value="${escape(bookmark?.url || '')}" placeholder="https://example.com">
                <label for="favoriteFolder">文件夹</label><select id="favoriteFolder" name="folder_id">${folderOptions}</select>`}
            <p class="favorite-form-error" role="alert" hidden></p>
            <div class="favorite-dialog-actions"><button type="button" class="favorite-secondary" data-dismiss>取消</button><button type="submit" class="${deleting ? 'favorite-danger' : 'favorite-primary'}">${deleting ? '确认删除' : '保存'}</button></div>
        </form>`;
        if (!isFolder && !deleting) dialog.querySelector('[name=folder_id]').value = defaultFolder ?? '';
        dialog.showModal();
        (dialog.querySelector(kind === 'move-bookmark' ? '[name=folder_id]' : 'input') || dialog.querySelector('[data-dismiss]')).focus();
    }

    function openMenu(button, type, id) {
        const wasOpen = !menu.hidden && menuTrigger === button;
        hideMenu();
        if (wasOpen) return;
        menuTrigger = button;
        button.setAttribute('aria-expanded', 'true');
        const actions = type === 'folder' ? [['rename-folder', 'pencil', '重命名'], ['delete-folder', 'trash-2', '删除文件夹']] : [['edit-bookmark', 'pencil', '编辑收藏'], ['move-bookmark', 'folder', '移动到文件夹'], ['delete-bookmark', 'trash-2', '删除收藏']];
        menu.innerHTML = actions.map(([action, symbol, label]) => `<button role="menuitem" data-menu-action="${action}" data-id="${id}">${icon(symbol)}${label}</button>`).join('');
        menu.hidden = false;
        const bounds = button.getBoundingClientRect();
        menu.style.left = `${Math.max(12, Math.min(bounds.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 12))}px`;
        menu.style.top = `${bounds.bottom + menu.offsetHeight + 6 < innerHeight - 12 ? bounds.bottom + 6 : Math.max(12, bounds.top - menu.offsetHeight - 6)}px`;
        menu.querySelector('button').focus();
    }

    page.addEventListener('click', event => {
        const button = event.target.closest('[data-favorite-action]');
        if (!button || state.busy) return;
        const action = button.dataset.favoriteAction;
        if (action === 'sort-name' || action === 'sort-date') {
            const key = action === 'sort-name' ? 'name' : 'date';
            state.sort = state.sortBy === key ? (state.sort === 'asc' ? 'desc' : 'asc') : key === 'date' ? 'desc' : 'asc';
            state.sortBy = key;
            savePreference('favorites-sort', state.sort);
            savePreference('favorites-sort-by', key);
            hideMenu();
            drawRows();
            field('.favorite-list-scroll').scrollTop = 0;
        } else if (action === 'folder') {
            state.folder = button.dataset.folder;
            savePreference('favorites-folder', state.folder);
            field('.favorites-body').classList.remove('folders-open');
            field('.folders-backdrop').hidden = true;
            field('.favorites-mobile-folders').setAttribute('aria-expanded', 'false');
            draw();
            field('.favorite-list-scroll').scrollTop = 0;
        } else if (action === 'toggle-folders' || action === 'close-folders') {
            const open = action !== 'close-folders' && !field('.favorites-body').classList.contains('folders-open');
            field('.favorites-body').classList.toggle('folders-open', open);
            field('.folders-backdrop').hidden = !open;
            field('.favorites-mobile-folders').setAttribute('aria-expanded', String(open));
        } else if (action.endsWith('-menu')) openMenu(button, action === 'folder-menu' ? 'folder' : 'bookmark', Number(button.dataset.id));
        else if (action === 'retry') refresh();
        else showDialog(action, null, button);
    });
    field('.favorite-search input').addEventListener('input', event => { state.query = event.target.value; hideMenu(); drawRows(); field('.favorite-list-scroll').scrollTop = 0; });
    menu.addEventListener('click', event => {
        const button = event.target.closest('[data-menu-action]');
        if (button) showDialog(button.dataset.menuAction, Number(button.dataset.id), menuTrigger);
    });
    document.addEventListener('click', event => { if (!menu.contains(event.target) && !event.target.closest('[data-favorite-action$="-menu"]')) hideMenu(); });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            hideMenu(true);
            field('.favorites-body').classList.remove('folders-open');
            field('.folders-backdrop').hidden = true;
            field('.favorites-mobile-folders').setAttribute('aria-expanded', 'false');
        }
        if (!menu.hidden && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            const buttons = [...menu.querySelectorAll('button')];
            const current = buttons.indexOf(document.activeElement);
            buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
        }
    });
    document.addEventListener('scroll', event => { if (!menu.contains(event.target)) hideMenu(); }, true);
    window.addEventListener('resize', () => hideMenu());
    dialog.addEventListener('click', event => { if (!state.busy && (event.target === dialog || event.target.closest('[data-dismiss]'))) dialog.close(); });
    dialog.addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
    dialog.addEventListener('close', () => { if (dialogTrigger?.isConnected) dialogTrigger.focus(); });
    dialog.addEventListener('submit', async event => {
        event.preventDefault();
        event.stopPropagation();
        if (state.busy) return;
        const form = event.target;
        const data = Object.fromEntries(new FormData(form));
        if ('folder_id' in data) data.folder_id = data.folder_id ? Number(data.folder_id) : null;
        state.busy = true;
        form.setAttribute('aria-busy', 'true');
        const controls = [...form.querySelectorAll('button,input,select')];
        controls.forEach(control => { control.disabled = true; });
        const errorBox = form.querySelector('.favorite-form-error');
        errorBox.hidden = true;
        try {
            const isFolder = dialogKind.includes('folder');
            const base = isFolder ? '/api/favorite-folders' : '/api/favorites';
            const creating = dialogKind.startsWith('new-');
            const deleting = dialogKind.startsWith('delete-');
            const result = await api(creating ? base : `${base}/${dialogId}`, { method: creating ? 'POST' : deleting ? 'DELETE' : 'PATCH', ...(deleting ? {} : { data }) });
            if (dialogKind === 'new-folder') { state.folder = String(result.id); savePreference('favorites-folder', state.folder); }
            dialog.close();
            await refresh();
            if (isActive()) {
                const savedRow = !isFolder && !deleting && page.querySelector(`.favorite-row[data-bookmark-id="${result.id}"] .favorite-more`);
                (savedRow || field('[data-favorite-action="sort-name"]')).focus();
            }
        } catch (error) { errorBox.textContent = friendlyError(error); errorBox.hidden = false; }
        finally { state.busy = false; form.removeAttribute('aria-busy'); controls.forEach(control => { control.disabled = false; }); }
    });

    return {
        mount() { target.replaceChildren(page); draw(); if (!state.loaded) refresh(); },
        unmount() { hideMenu(); if (dialog.open && !state.busy) dialog.close(); },
        openBookmark() { showDialog('new-bookmark'); },
        reload: refresh,
    };
};
