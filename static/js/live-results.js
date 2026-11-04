// Update only result regions. Forms and their in-progress values stay mounted.
(() => {
  let controller = null, generation = 0;
  const status = document.createElement('p');
  status.className = 'fmis-live-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  status.hidden = true; document.body.append(status);
  const targetFor = element => element.closest('#filteredReport') || element.closest('[data-live-page]')?.querySelector('[data-live-results]');
  const selectorFor = target => target.id === 'filteredReport' ? '#filteredReport' : `[data-live-results="${target.dataset.liveResults}"]`;
  const error = message => { status.textContent = message; status.hidden = false; status.classList.add('is-error'); };
  const unsavedInside = target => [...target.querySelectorAll('input:not([type=hidden]),textarea,select')].some(field => {
    if (field.closest('.fmis-pagination,[data-trend-chart]')) return false;
    if (field.type === 'checkbox' || field.type === 'radio') return field.checked !== field.defaultChecked;
    if (field.tagName === 'SELECT') return [...field.options].some(option=>option.selected !== option.defaultSelected);
    return field.value !== field.defaultValue;
  });
  async function update(url, target, historyMode = 'push', sourceForm = null, reset = false) {
    if (unsavedInside(target)) { error('Your edits are still open. Save or close them before changing this list.'); return; }
    document.dispatchEvent(new Event('fmis:results-loading'));
    controller?.abort(); controller = new AbortController(); const ticket = ++generation;
    target.setAttribute('aria-busy','true'); status.classList.remove('is-error'); status.textContent='Updating results…'; status.hidden=false;
    const focused = target.contains(document.activeElement) ? document.activeElement : null;
    const focusName = focused?.name || focused?.closest('.fmis-dropdown')?.querySelector('select')?.name;
    const scrolls = [...target.querySelectorAll('*')].filter(el=>el.scrollTop || el.scrollLeft).map(el=>({className:el.className,chart:el.closest('[data-trend-chart]')?.dataset.trendSource,top:el.scrollTop,left:el.scrollLeft}));
    try {
      const response = await fetch(url, {signal:controller.signal,credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest','X-FMIS-Live-Update':'1'}});
      if (!response.ok || response.redirected) throw new Error('The results could not be updated. Your entries have been kept. Try again or sign in in another tab.');
      const doc = new DOMParser().parseFromString(await response.text(),'text/html');
      if (ticket !== generation) return;
      const next = doc.querySelector(selectorFor(target));
      if (!next) throw new Error('The results could not be updated. Your entries have been kept. Please try again.');
      // Preserve view choices, independently of server-side record filters.
      const chartChoices = [...target.querySelectorAll('[data-trend-chart]')].map(chart=>({id:chart.dataset.trendSource,view:chart.querySelector('[data-trend-view]')?.value,months:chart.querySelector('[data-trend-window]')?.value}));
      if (unsavedInside(target)) throw new Error('Your edits are still open. Save or close them before changing this list.');
      target.replaceWith(next);
      document.dispatchEvent(new CustomEvent('fmis:results-updated',{detail:{root:next}}));
      chartChoices.forEach(choice=>{const chart=[...next.querySelectorAll('[data-trend-chart]')].find(el=>el.dataset.trendSource===choice.id); if(!chart)return; [['[data-trend-view]',choice.view],['[data-trend-window]',choice.months]].forEach(([selector,value])=>{const field=chart.querySelector(selector);if(field&&value){field.value=value;field.dispatchEvent(new Event('change'));}});});
      scrolls.forEach(saved=>{const el=[...next.querySelectorAll('*')].find(node=>node.className===saved.className && node.closest('[data-trend-chart]')?.dataset.trendSource===saved.chart);if(el){el.scrollTop=saved.top;el.scrollLeft=saved.left;}});
      if (sourceForm) {
        if (reset) {const fresh=doc.querySelector('form[data-table-toolbar]'); if(fresh){[...sourceForm.elements].forEach(field=>{const replacement=fresh.elements.namedItem(field.name);if(replacement && field.name && !['submit','button'].includes(field.type)){field.value=replacement.value;}});}}
        sourceForm.querySelectorAll('[data-filter-popover]').forEach(panel=>{panel.hidden=true;});
        sourceForm.querySelector('[data-filter-toggle]')?.setAttribute('aria-expanded','false');
        const fresh=doc.querySelector('form[data-table-toolbar]');
        sourceForm.querySelector('[data-filter-toggle]')?.classList.toggle('has-active-filters',Boolean(fresh?.querySelector('.has-active-filters')));
        sourceForm.querySelectorAll('.fmis-filter-error,.analytics-filter-error').forEach(el=>el.remove());
        fresh?.querySelectorAll('.fmis-filter-error,.analytics-filter-error').forEach(el=>{const container=sourceForm.querySelector('.fmis-filter-grid');container?.append(el.cloneNode(true)); const panel=sourceForm.querySelector('[data-filter-popover]');if(panel)panel.hidden=false;});
      }
      if(focusName){const field=[...next.querySelectorAll('input,select,textarea')].find(el=>el.name===focusName);(field?.closest('.fmis-dropdown')?.querySelector('button') || field)?.focus({preventScroll:true});}
      document.dispatchEvent(new Event('fmis:filters-synced'));
      if(historyMode==='push') history.pushState({fmisLive:true},'',url);
      status.textContent='Results updated.'; window.setTimeout(()=>{if(ticket===generation)status.hidden=true;},1500);
    } catch (err) { if(err.name!=='AbortError' && ticket===generation)error(err.message || 'Could not update results. Your entries have been kept.'); }
    finally { if(ticket===generation)document.querySelectorAll('[data-live-results][aria-busy],#filteredReport[aria-busy]').forEach(el=>el.removeAttribute('aria-busy')); }
  }
  window.fmisCancelResultsUpdate = () => { controller?.abort(); generation++; document.querySelectorAll('[aria-busy="true"][data-live-results]').forEach(el=>el.removeAttribute('aria-busy')); status.hidden=true; };
  window.fmisRefreshResults = (element=document.querySelector('[data-live-page]')) => {const target=element?.matches?.('[data-live-results]')?element:element?.querySelector('[data-live-results]');if(target)return update(location.href,target,'none');};
  document.addEventListener('click', event=>{
    if(event.defaultPrevented || event.button!==0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)return;
    const link=event.target.closest('.fmis-pagination a,.fmis-filter-reset'); if(!link)return;
    const target=targetFor(link);if(!target)return;
    const url=new URL(link.href,location.href);if(url.origin!==location.origin || url.pathname!==location.pathname)return;
    event.preventDefault();update(url.href,target,'push',link.closest('form[data-table-toolbar]'),link.classList.contains('fmis-filter-reset'));
  },true);
  document.addEventListener('submit',event=>{
    const form=event.target;if(!form.matches('form[data-table-toolbar],.fmis-pagination form') || form.method.toLowerCase()!=='get')return;
    const target=targetFor(form);if(!target)return;
    event.preventDefault();const params=new URLSearchParams(new FormData(form));
    const url=new URL(form.getAttribute('action') || location.pathname,location.href);url.search=params.toString();
    update(url.href,target,'push',form.matches('[data-table-toolbar]')?form:null);
  },true);
  if(document.querySelector('[data-live-results],#filteredReport'))history.replaceState({...history.state,fmisLive:true},'',location.href);
  window.addEventListener('popstate',event=>{if(!event.state?.fmisLive)return;const target=document.querySelector('[data-live-results],#filteredReport');if(target)update(location.href,target,'none');});
})();
