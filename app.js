'use strict';

const API = '/api/ai_nav_flat';
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[char]);
let categories = [];
let activeCategory = null; // null means all; a category can itself be named “所有”.
let isEditMode = false;
let editingToolId = null;
let pending = false;
let hasLoaded = false;
let loadVersion = 0;
let modalTrigger = null;

async function requestApi(path = API, { method = 'GET', data, body } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(path, {
            method, signal: controller.signal,
            headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
            body: data === undefined ? body : JSON.stringify(data)
        });
        const result = await response.json().catch(() => null);
        if (!response.ok) throw new Error(result?.error || `请求失败 (${response.status})`);
        if (result === null) throw new Error('服务器返回了无效数据');
        return result;
    } catch (error) {
        if (error.name === 'AbortError') throw new Error('请求超时，请刷新检查结果后重试。');
        if (error instanceof TypeError) throw new Error('无法连接服务器，请检查网络后重试。');
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function filteredPath(filters) {
    return `${API}?${new URLSearchParams(Object.entries(filters).map(([key, value]) => [`eq_${key}`, value]))}`;
}

function showError(error) {
    $('statusMessage').textContent = error.message;
    $('statusBanner').hidden = false;
}

function clearError() {
    $('statusBanner').hidden = true;
}

async function fetchData() {
    const version = ++loadVersion;
    const rows = await requestApi();
    if (version !== loadVersion) return;
    if (!Array.isArray(rows)) throw new Error('服务器返回了无效数据');
    const groups = new Map();
    for (const row of rows) {
        if (!groups.has(row.category)) groups.set(row.category, { name: row.category, tools: [] });
        if (row.name) groups.get(row.category).tools.push(row);
    }
    categories = [...groups.values()];
    if (activeCategory !== null && !groups.has(activeCategory)) activeCategory = null;
    hasLoaded = true;
    render();
}

async function reloadData() {
    clearError();
    try {
        await fetchData();
    } catch (error) {
        showError(error);
        if (!hasLoaded) {
            $('navList').textContent = '暂时无法加载';
            $('mainContent').textContent = '数据加载失败，请点击上方的“重新加载”。';
        }
    }
}

async function mutate(action) {
    if (pending) return;
    pending = true;
    clearError();
    const controls = [...document.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled)')];
    controls.forEach(control => { control.disabled = true; });
    document.body.setAttribute('aria-busy', 'true');
    try {
        await action();
        await fetchData();
    } catch (error) {
        showError(error);
    } finally {
        pending = false;
        controls.forEach(control => { control.disabled = false; });
        document.body.removeAttribute('aria-busy');
    }
}

function safeLink(value) {
    try {
        const url = new URL(value);
        return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch {
        return '';
    }
}

function logoMarkup(value) {
    const logo = String(value || '').trim();
    let source = '';
    if (/^<svg[\s>]/i.test(logo)) {
        // SVG stays in an image context: never insert stored markup into the page.
        const svg = new DOMParser().parseFromString(logo, 'image/svg+xml');
        if (!svg.querySelector('parsererror') && svg.documentElement.localName === 'svg') {
            svg.documentElement.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(svg))}`;
        }
    } else if (safeLink(logo) || /^\/(?!\/)/.test(logo) || /^data:image\/(png|jpeg|gif|webp|svg\+xml|x-icon|vnd.microsoft.icon)[;,]/i.test(logo)) {
        source = logo;
    }
    if (source) {
        return `<img src="${escapeHtml(source)}" alt="" width="42" height="42" loading="lazy" decoding="async"><span class="tool-logo-emoji" hidden>🔧</span>`;
    }
    return `<span class="tool-logo-emoji">${escapeHtml(logo || '🔧')}</span>`;
}

const icons = {
    previous: '<path d="M15 18l-6-6 6-6"/>',
    next: '<path d="M9 18l6-6-6-6"/>',
    edit: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    delete: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
};

function toolButton(action, label, icon, extra = '', disabled = false) {
    return `<button type="button" class="tool-edit-btn ${action === 'move-tool' ? 'move' : action === 'edit-tool' ? 'edit' : 'delete'}" data-action="${action}" ${extra} title="${label}" aria-label="${label}" ${disabled ? 'disabled' : ''}><svg viewBox="0 0 24 24" aria-hidden="true">${icons[icon]}</svg></button>`;
}

function renderNav() {
    $('navList').innerHTML = `
        <div class="nav-item ${activeCategory === null ? 'active' : ''}"><button class="nav-select" data-action="all" ${activeCategory === null ? 'aria-current="true"' : ''}>所有</button></div>
        ${categories.map(cat => `<div class="nav-item ${cat.name === activeCategory ? 'active' : ''}" data-category="${escapeHtml(cat.name)}">
            <button class="nav-select" data-action="category" ${cat.name === activeCategory ? 'aria-current="true"' : ''}>${escapeHtml(cat.name)}</button>
            ${isEditMode ? '<button class="delete-btn" data-action="delete-category" aria-label="删除分类" title="删除分类">✕</button>' : ''}
        </div>`).join('')}
        ${!categories.length && !isEditMode ? '<div class="loading">暂无分类</div>' : ''}
        ${isEditMode ? `<form id="addCategoryForm" class="add-category show">
            <input id="newCategoryName" aria-label="新分类名称" placeholder="新分类名称" maxlength="120" required>
            <button type="submit" aria-label="添加分类">+</button>
        </form>` : ''}`;
}

function renderTools() {
    const visible = activeCategory === null ? categories : categories.filter(cat => cat.name === activeCategory);
    if (!visible.length) {
        $('mainContent').innerHTML = '<div class="loading">暂无分类，请开启编辑模式添加分类和工具。</div>';
        return;
    }
    $('mainContent').innerHTML = `<div class="content-wrapper">${visible.map(cat => {
        const categoryIndex = categories.indexOf(cat);
        return `<section class="category-section" data-category="${escapeHtml(cat.name)}">
            <div class="category-header">
                <div class="category-pill">
                    ${isEditMode && activeCategory === null ? `<div class="sort-actions">
                        <button class="sort-btn" data-action="move-category" data-direction="-1" title="分类上移" aria-label="分类上移" ${categoryIndex === 0 ? 'disabled' : ''}>▲</button>
                        <button class="sort-btn" data-action="move-category" data-direction="1" title="分类下移" aria-label="分类下移" ${categoryIndex === categories.length - 1 ? 'disabled' : ''}>▼</button>
                    </div>` : '<svg class="category-pill-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>'}
                    ${isEditMode ? `<input class="category-rename-input" aria-label="分类名称" maxlength="120" value="${escapeHtml(cat.name)}">` : `<h2>${escapeHtml(cat.name)}</h2>`}
                </div><span class="category-count">${cat.tools.length} 个工具</span>
            </div>
            <div class="tools-grid">
                ${cat.tools.map((tool, index) => {
                    const url = safeLink(tool.url);
                    return `<article class="tool-card" data-id="${Number(tool.id)}">
                        <a class="tool-card-body" aria-describedby="description-${Number(tool.id)}" ${url ? `href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"` : ''}>
                            <div class="tool-logo">${logoMarkup(tool.logo)}</div>
                            <div class="tool-content"><div class="tool-name" title="${escapeHtml(tool.name)}">${escapeHtml(tool.name)}</div>
                                <div class="tool-description" id="description-${Number(tool.id)}">${escapeHtml(tool.description)}</div></div>
                            ${tool.description ? `<span class="tool-tooltip" aria-hidden="true">${escapeHtml(tool.description)}</span>` : ''}
                        </a>
                        ${isEditMode ? `<div class="tool-edit-footer">
                            <div class="edit-group">${toolButton('move-tool', '向前', 'previous', 'data-direction="-1"', index === 0)}${toolButton('move-tool', '向后', 'next', 'data-direction="1"', index === cat.tools.length - 1)}</div>
                            <div class="edit-group">${toolButton('edit-tool', '编辑', 'edit')}${toolButton('delete-tool', '删除', 'delete')}</div>
                        </div>` : ''}
                    </article>`;
                }).join('')}
                ${isEditMode ? `<form class="tool-card add-tool-card show">
                    <input name="logo" placeholder="Logo URL / Emoji / SVG" aria-label="工具 Logo">
                    <input name="name" placeholder="名称" aria-label="工具名称" maxlength="200" required>
                    <textarea name="description" placeholder="描述" aria-label="工具描述" maxlength="10000"></textarea>
                    <input name="url" type="url" placeholder="网址" aria-label="工具网址" maxlength="4096">
                    <div class="add-tool-actions"><button class="save-tool-btn" type="submit">保存</button><button class="cancel-tool-btn" type="reset">清空</button></div>
                </form>` : ''}
            </div>
        </section>`;
    }).join('')}</div>`;
}

function render() {
    renderNav();
    renderTools();
}

function switchCategory(name) {
    activeCategory = name;
    render();
    $('mainContent').scrollTop = 0;
}

async function moveCategory(name, direction) {
    const order = categories.map(cat => cat.name);
    const index = order.indexOf(name);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    await mutate(() => requestApi('/api/reorder', { method: 'POST', data: { kind: 'categories', order } }));
}

async function moveTool(name, id, direction) {
    const cat = categories.find(item => item.name === name);
    const order = cat.tools.map(tool => tool.id);
    const index = order.indexOf(id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    await mutate(() => requestApi('/api/reorder', { method: 'POST', data: { kind: 'tools', category: name, order } }));
}

function editTool(id, trigger) {
    const category = categories.find(cat => cat.tools.some(tool => tool.id === id));
    const tool = category?.tools.find(item => item.id === id);
    if (!tool) return;
    editingToolId = id;
    modalTrigger = trigger;
    $('editCategory').innerHTML = categories.map(cat => `<option value="${escapeHtml(cat.name)}">${escapeHtml(cat.name)}</option>`).join('');
    $('editCategory').value = category.name;
    for (const field of ['logo', 'name', 'description', 'url']) {
        $(`edit${field[0].toUpperCase()}${field.slice(1)}`).value = tool[field] || '';
    }
    $('logoPreview').innerHTML = logoMarkup(tool.logo);
    $('editModal').classList.add('show');
    $('editModal').setAttribute('aria-hidden', 'false');
    document.querySelector('.container').inert = true;
    $('editName').focus();
}

function closeModal() {
    $('editModal').classList.remove('show');
    $('editModal').setAttribute('aria-hidden', 'true');
    document.querySelector('.container').inert = false;
    editingToolId = null;
    if (modalTrigger?.isConnected && !modalTrigger.disabled) modalTrigger.focus();
    else $('editToggle').focus();
}

document.addEventListener('click', async event => {
    const button = event.target.closest('[data-action]');
    if (!button || button.disabled || pending) return;
    const category = button.closest('[data-category]')?.dataset.category;
    const id = Number(button.closest('[data-id]')?.dataset.id);
    switch (button.dataset.action) {
        case 'all': switchCategory(null); break;
        case 'category': switchCategory(category); break;
        case 'move-category': await moveCategory(category, Number(button.dataset.direction)); break;
        case 'move-tool': await moveTool(category, id, Number(button.dataset.direction)); break;
        case 'edit-tool': editTool(id, button); break;
        case 'delete-tool':
            if (confirm('确定要删除这个工具吗？')) await mutate(() => requestApi(filteredPath({ id }), { method: 'DELETE' }));
            break;
        case 'delete-category':
            if (confirm(`确定删除分类“${category}”及其中所有工具吗？`)) {
                await mutate(async () => {
                    await requestApi(filteredPath({ category }), { method: 'DELETE' });
                    if (activeCategory === category) activeCategory = null;
                });
            }
            break;
    }
});

document.addEventListener('submit', async event => {
    const form = event.target;
    event.preventDefault();
    if (pending) return;
    if (form.id === 'addCategoryForm') {
        const name = $('newCategoryName').value.trim();
        if (!name) return;
        await mutate(async () => {
            await requestApi(API, { method: 'POST', data: { category: name, name: null } });
            activeCategory = name;
        });
    } else if (form.matches('.add-tool-card')) {
        const data = Object.fromEntries(new FormData(form));
        data.category = form.closest('[data-category]').dataset.category;
        await mutate(() => requestApi(API, { method: 'POST', data }));
    } else if (form.id === 'editForm') {
        const data = { category: $('editCategory').value };
        for (const field of ['logo', 'name', 'description', 'url']) {
            data[field] = $(`edit${field[0].toUpperCase()}${field.slice(1)}`).value.trim();
        }
        await mutate(async () => {
            await requestApi(filteredPath({ id: editingToolId }), { method: 'PATCH', data });
            closeModal();
        });
    }
});

document.addEventListener('change', async event => {
    const input = event.target;
    if (!input.matches('.category-rename-input') || pending) return;
    const oldName = input.closest('[data-category]').dataset.category;
    const name = input.value.trim();
    if (!name || name === oldName || !confirm(`确定将“${oldName}”重命名为“${name}”吗？`)) {
        input.value = oldName;
        return;
    }
    await mutate(async () => {
        await requestApi(filteredPath({ category: oldName }), { method: 'PATCH', data: { category: name } });
        if (activeCategory === oldName) activeCategory = name;
    });
    if (input.isConnected) input.value = oldName;
});

// Failed images use a local fallback without inline event handlers.
document.addEventListener('error', event => {
    if (event.target.matches?.('.tool-logo img, #logoPreview img')) {
        event.target.hidden = true;
        if (event.target.nextElementSibling) event.target.nextElementSibling.hidden = false;
    }
}, true);

$('editLogo').addEventListener('input', () => { $('logoPreview').innerHTML = logoMarkup($('editLogo').value); });
document.querySelector('.upload-btn').addEventListener('keydown', event => {
    if (['Enter', ' '].includes(event.key)) {
        event.preventDefault();
        if (!pending) $('editLogoFile').click();
    }
});
$('editLogoFile').addEventListener('change', async event => {
    const input = event.target;
    const file = input.files[0];
    if (!file || pending) return;
    if (file.size > 5 * 1024 * 1024 - 1024) {
        showError(new Error('请选择小于 5 MB 的图片。'));
        input.value = '';
        return;
    }
    pending = true;
    clearError();
    const controls = [...$('editForm').querySelectorAll('button, input, textarea, select')];
    controls.forEach(control => { control.disabled = true; });
    $('uploadLabel').textContent = '⏳ 上传中…';
    try {
        const body = new FormData();
        body.append('file', file);
        const result = await requestApi('/api/upload', { method: 'POST', body });
        $('editLogo').value = result.url; // Keep local uploads portable across hostnames.
        $('logoPreview').innerHTML = logoMarkup(result.url);
    } catch (error) {
        showError(error);
    } finally {
        controls.forEach(control => { control.disabled = false; });
        $('uploadLabel').textContent = '📷 上传';
        input.value = '';
        pending = false;
    }
});

$('editToggle').addEventListener('click', () => {
    if (pending) return;
    isEditMode = !isEditMode;
    document.body.classList.toggle('edit-mode', isEditMode);
    $('editToggle').classList.toggle('editing', isEditMode);
    $('editToggle').setAttribute('aria-pressed', String(isEditMode));
    render();
});
$('cancelEdit').addEventListener('click', () => { if (!pending) closeModal(); });
$('editModal').addEventListener('click', event => {
    if (event.target === $('editModal') && !pending) closeModal();
});
document.addEventListener('keydown', event => {
    if (!$('editModal').classList.contains('show')) return;
    if (event.key === 'Escape' && !pending) closeModal();
    if (event.key === 'Tab') {
        const controls = [...$('editForm').querySelectorAll('input:not([type=file]), textarea, select, button, [tabindex="0"]')].filter(item => !item.disabled);
        const first = controls[0], last = controls[controls.length - 1];
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
});

function updateThemeControl() {
    const dark = document.documentElement.dataset.theme === 'dark';
    document.body.classList.toggle('dark-mode', dark);
    $('themeToggle').setAttribute('aria-pressed', String(dark));
    $('themeToggle').title = dark ? '切换到浅色主题' : '切换到深色主题';
    $('themeToggle').innerHTML = dark
        ? '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M1 12h2m18 0h2M4.22 4.22l1.42 1.42m12.72 12.72 1.42 1.42M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
        : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
}
document.addEventListener('themechange', updateThemeControl);
updateThemeControl();
$('themeToggle').addEventListener('click', () => window.navTheme.toggle());
$('retryLoad').addEventListener('click', () => { if (!pending) reloadData(); });
reloadData();
