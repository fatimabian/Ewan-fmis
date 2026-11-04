// Keep long filter menus below their controls, scrolling instead of flipping up.
(() => {
  const selector = '#reportGenerator select,[data-table-toolbar] select,.fmis-pagination select';
  let opened = null, sequence = 0;
  const close = () => {if(!opened)return;opened.menu.hidden=true;opened.button.setAttribute('aria-expanded','false');opened.button.removeAttribute('aria-activedescendant');opened=null;};
  const setup = select => {
    if(select.dataset.downwardReady)return;
    select.dataset.downwardReady='true';
    const height=select.getBoundingClientRect().height || 40;
    const wrapper=document.createElement('span');wrapper.className='fmis-dropdown';
    select.before(wrapper);wrapper.append(select);
    select.classList.add('fmis-dropdown-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    const button=document.createElement('button');button.type='button';button.className='fmis-dropdown-trigger';button.style.minHeight=`${height}px`;button.setAttribute('role','combobox');button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
    const sourceLabel=select.labels?.[0] || select.closest('.report-filter-row,.fmis-filter-field,.fmis-page-size')?.querySelector('label');
    const labelCopy=sourceLabel?.cloneNode(true);labelCopy?.querySelectorAll('select,button,.fmis-dropdown').forEach(node=>node.remove());
    const label=labelCopy?.textContent || select.name;
    button.setAttribute('aria-label',label?.trim() || 'Filter');
    const menu=document.createElement('div');menu.className='fmis-dropdown-menu';menu.id=`fmisDropdown${++sequence}`;menu.hidden=true;menu.setAttribute('role','listbox');menu.setAttribute('aria-label',label?.trim() || 'Filter options');button.setAttribute('aria-controls',menu.id);wrapper.append(button,menu);
    let active=0, search='', searchTimer;
    const options=()=>[...menu.querySelectorAll('[role=option]')];
    const sync=()=>{button.textContent=select.selectedOptions[0]?.textContent.trim() || 'Choose';button.disabled=select.disabled;options().forEach(option=>{const selected=Number(option.dataset.index)===select.selectedIndex;option.setAttribute('aria-selected',String(selected));option.classList.toggle('is-selected',selected);});};
    const position=()=>{const r=button.getBoundingClientRect();menu.style.left=`${Math.max(8,Math.min(r.left,innerWidth-r.width-8))}px`;menu.style.top=`${r.bottom+4}px`;menu.style.width=`${Math.min(Math.max(r.width,180),innerWidth-16)}px`;menu.style.maxHeight=`${Math.max(40,Math.min(300,innerHeight-r.bottom-16))}px`;};
    const activate=index=>{const all=options();if(!all.length)return;active=Math.max(0,Math.min(index,all.length-1));all.forEach((option,i)=>option.classList.toggle('is-active',i===active));button.setAttribute('aria-activedescendant',all[active].id);const row=all[active];if(row.offsetTop<menu.scrollTop)menu.scrollTop=row.offsetTop;else if(row.offsetTop+row.offsetHeight>menu.scrollTop+menu.clientHeight)menu.scrollTop=row.offsetTop+row.offsetHeight-menu.clientHeight;};
    const choose=option=>{if(!option || option.getAttribute('aria-disabled')==='true')return;select.selectedIndex=Number(option.dataset.index);sync();close();button.focus({preventScroll:true});select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));};
    const build=()=>{menu.replaceChildren();[...select.options].forEach((option,index)=>{const row=document.createElement('div');row.id=`${menu.id}Option${index}`;row.dataset.index=index;row.setAttribute('role','option');row.setAttribute('aria-disabled',String(option.disabled || option.parentElement.disabled===true));row.textContent=option.textContent.trim();row.addEventListener('pointerdown',event=>event.preventDefault());row.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();choose(row);});menu.append(row);});sync();};
    const open=()=>{close();build();menu.hidden=false;opened={menu,button,position};button.setAttribute('aria-expanded','true');position();const index=options().findIndex(option=>Number(option.dataset.index)===select.selectedIndex);activate(index);};
    button.addEventListener('click',()=>opened?.button===button?close():open());
    button.addEventListener('keydown',event=>{
      if(event.key==='Escape'){close();event.preventDefault();return;}
      if(event.key==='Tab'){close();return;}
      if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(event.key)){
        event.preventDefault();if(opened?.button!==button){open();return;}
        if(event.key==='Enter'||event.key===' '){choose(options()[active]);return;}
        const direction=['ArrowDown','Home'].includes(event.key)?1:-1;let next=event.key==='Home'?0:event.key==='End'?options().length-1:active+direction;
        while(next>=0 && next<options().length && options()[next].getAttribute('aria-disabled')==='true')next+=direction;
        if(next>=0 && next<options().length)activate(next);return;
      }
      if(event.key.length===1 && !event.ctrlKey && !event.metaKey){if(opened?.button!==button)open();search+=event.key.toLowerCase();clearTimeout(searchTimer);searchTimer=setTimeout(()=>search='',700);const index=options().findIndex(option=>option.getAttribute('aria-disabled')!=='true' && option.textContent.toLowerCase().startsWith(search));if(index>=0)activate(index);}
    });
    select.addEventListener('change',sync);select.addEventListener('focus',()=>button.focus());
    new MutationObserver(sync).observe(select,{attributes:true,subtree:true,childList:true,characterData:true});
    build();
  };
  const init=()=>document.querySelectorAll(selector).forEach(setup);
  document.addEventListener('pointerdown',event=>{if(opened&&!opened.menu.contains(event.target)&&!opened.button.contains(event.target))close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
  const syncButtons=()=>document.querySelectorAll(selector).forEach(select=>{const trigger=select.parentElement.querySelector('.fmis-dropdown-trigger');if(trigger){trigger.textContent=select.selectedOptions[0]?.textContent.trim() || 'Choose';trigger.disabled=select.disabled;}});
  document.addEventListener('change',()=>queueMicrotask(syncButtons));
  document.addEventListener('fmis:filters-synced',syncButtons);
  window.addEventListener('resize',()=>opened?.position());document.addEventListener('scroll',()=>{if(opened?.button.isConnected)opened.position();else close();},true);
  document.addEventListener('fmis:results-updated',()=>{close();init();});
  new MutationObserver(init).observe(document.body,{childList:true,subtree:true});init();
})();
