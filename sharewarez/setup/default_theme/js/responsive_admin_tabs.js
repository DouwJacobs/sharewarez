document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.admin-tab-nav, [data-responsive-section-nav]').forEach((tabList, index) => {
        const usesBootstrapTabs = tabList.classList.contains('admin-tab-nav');
        const tabs = usesBootstrapTabs
            ? [...tabList.querySelectorAll('[data-bs-toggle="tab"]')]
            : [...tabList.querySelectorAll('[data-settings-target]')];
        if (tabs.length < 2) return;

        const selectId = `adminTabSelect-${index}`;
        const wrapper = document.createElement('div');
        wrapper.className = 'admin-tab-select-wrap';

        const label = document.createElement('label');
        label.htmlFor = selectId;
        label.textContent = 'Section';

        const select = document.createElement('select');
        select.id = selectId;
        select.className = 'admin-tab-select';
        select.setAttribute('aria-label', tabList.getAttribute('aria-label') || 'Choose section');

        tabs.forEach((tab, tabIndex) => {
            const option = document.createElement('option');
            option.value = String(tabIndex);
            option.textContent = tab.querySelector('strong')?.textContent.trim()
                || tab.textContent.trim();
            option.selected = tab.classList.contains('active')
                || tab.classList.contains('is-active');
            select.appendChild(option);

            tab.addEventListener('shown.bs.tab', () => {
                select.value = String(tabIndex);
            });
            if (!usesBootstrapTabs) {
                tab.addEventListener('click', () => {
                    select.value = String(tabIndex);
                });
            }
        });

        select.addEventListener('change', () => {
            const tab = tabs[Number(select.value)];
            if (!tab) return;
            if (usesBootstrapTabs) {
                bootstrap.Tab.getOrCreateInstance(tab).show();
            } else {
                tab.click();
            }
        });

        wrapper.append(label, select);
        tabList.before(wrapper);
        tabList.dataset.responsiveTabsReady = 'true';
    });
});
