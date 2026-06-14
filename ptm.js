(function(){
  let soundOn = localStorage.getItem('ptmSound') !== 'off';
  let ctx;
  function beep(freq=620, duration=0.07, gain=0.075){
    if(!soundOn) return;
    try{
      ctx = ctx || new (window.AudioContext||window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      g.gain.value = gain;
      osc.connect(g); g.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + duration);
    }catch(e){}
  }
  window.ptmBeep = beep;
  window.toggleHelp = function(show){
    const m=document.getElementById('shortcutHelp');
    if(m) m.style.display = show ? 'flex' : 'none';
    beep(500);
  }

  let inlineTarget=null;
  function fieldHtml(kind, opts){
    if(kind==='ledger'){
      const groups=(opts.groups||['Sundry Debtors','Sundry Creditors','Cash-in-Hand','Bank Accounts']).map(x=>`<option>${x}</option>`).join('');
      return `<input name="name" placeholder="Ledger Name" required autofocus><select name="group_name">${groups}</select><input name="gstin" placeholder="GSTIN"><input name="mobile" placeholder="Mobile"><input name="opening" type="number" step=".01" placeholder="Opening Balance"><select name="drcr"><option>Dr</option><option>Cr</option></select>`;
    }
    if(kind==='item'){
      const units=(opts.units||['Nos']).map(x=>`<option>${x}</option>`).join('');
      return `<input name="name" placeholder="Stock Item Name" required autofocus><select name="unit" data-create="unit" title="Alt+C = Unit Create">${units}</select><input name="hsn" placeholder="HSN"><input name="gst_rate" type="number" step=".01" placeholder="GST %"><input name="opening_qty" type="number" step=".01" placeholder="Opening Qty"><input name="opening_rate" type="number" step=".01" placeholder="Opening Rate"><input name="reorder" type="number" step=".01" placeholder="Reorder Level">`;
    }
    if(kind==='unit'){
      return `<input name="symbol" placeholder="Unit Symbol e.g. Nos" required autofocus><input name="formal_name" placeholder="Formal Name">`;
    }
    return '';
  }
  window.closeInlineMaster=function(){ const m=document.getElementById('inlineMasterModal'); if(m) m.style.display='none'; inlineTarget=null; beep(500); }
  window.openInlineMaster=async function(target){
    inlineTarget=target;
    const kind=target.dataset.create;
    if(!kind) return false;
    beep(760);
    let opts={};
    try{ const r=await fetch('/api/master_options/'+kind); opts=await r.json(); }catch(e){}
    const title={ledger:'Create Ledger',item:'Create Stock Item',unit:'Create Unit'}[kind]||'Create Master';
    document.getElementById('inlineMasterTitle').textContent=title;
    document.getElementById('inlineMasterFields').innerHTML=fieldHtml(kind, opts||{});
    document.getElementById('inlineMasterModal').style.display='flex';
    setTimeout(()=>{ const f=document.querySelector('#inlineMasterFields input, #inlineMasterFields select'); if(f) f.focus(); },80);
    return true;
  }
  document.addEventListener('submit', async function(e){
    if(e.target && e.target.id==='inlineMasterForm'){
      e.preventDefault();
      const form=e.target; const fd=new FormData(form);
      let kind=inlineTarget && inlineTarget.dataset.create;
      if(!kind) return;
      const data={}; fd.forEach((v,k)=>data[k]=v);
      try{
        const r=await fetch('/api/create_master/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        const j=await r.json();
        if(!j.ok){ alert(j.error||'Create failed'); return; }
        if(inlineTarget){
          let opt=[...inlineTarget.options].find(o=>o.value.toLowerCase()===j.value.toLowerCase() || o.text.toLowerCase()===j.label.toLowerCase());
          if(!opt){ opt=new Option(j.label,j.value,true,true); if(j.gst_rate!==undefined) opt.dataset.gst=j.gst_rate; inlineTarget.add(opt); }
          inlineTarget.value=j.value; inlineTarget.dispatchEvent(new Event('change',{bubbles:true}));
        }
        closeInlineMaster(); beep(900);
      }catch(err){ alert('Create error: '+err); }
    }
  }, true);

  document.addEventListener('click', function(e){
    const t=e.target.closest('a,button,input,select,textarea');
    if(t) beep(t.tagName==='A'?650:520);
  }, true);
  const go = (url)=>{ beep(740); setTimeout(()=>{ location=url; }, 60); };
  document.addEventListener('keydown', e=>{
    const k=e.key.toLowerCase();
    if(e.key==='?' || (e.shiftKey && e.key==='/')){e.preventDefault(); toggleHelp(true); return;}
    if(e.key==='Escape'){
      const modal=[...document.querySelectorAll('.modal')].find(m=>getComputedStyle(m).display!=='none');
      if(modal){ e.preventDefault(); modal.style.display='none'; beep(520); return; }
      e.preventDefault(); beep(480); setTimeout(()=>{ if(history.length>1) history.back(); else location='/dashboard'; }, 60); return;
    }
    if(['ArrowDown','ArrowUp','ArrowLeft','ArrowRight'].includes(e.key)){
      const active=document.activeElement;
      const isForm=active && ['INPUT','TEXTAREA','SELECT'].includes(active.tagName);
      if(!isForm){
        const selector='.gateway a,.menugrid a,.tally-right a,.tally-topbar a,button.btn,a.btn,button';
        const items=[...document.querySelectorAll(selector)].filter(x=>x.offsetParent!==null && !x.disabled);
        if(items.length){
          e.preventDefault();
          let i=items.indexOf(active);
          if(i<0) i=-1;
          const next = (e.key==='ArrowDown' || e.key==='ArrowRight');
          i = next ? (i+1)%items.length : (i-1+items.length)%items.length;
          items[i].focus({preventScroll:true});
          beep(430,0.035,0.04);
          return;
        }
      }
    }
    if(e.key==='Enter'){
      const active=document.activeElement;
      if(active && active.matches && active.matches('a,button.btn,a.btn')){
        e.preventDefault(); beep(740); active.click(); return;
      }
    }
    if(e.ctrlKey && k==='m'){ e.preventDefault(); soundOn=!soundOn; localStorage.setItem('ptmSound', soundOn?'on':'off'); beep(800); alert('Sound '+(soundOn?'ON':'OFF')); return; }
    if(e.ctrlKey && k==='a'){let f=document.querySelector('form'); if(f){e.preventDefault(); beep(850); f.submit();} return;}
    if(e.key==='F4'){e.preventDefault();go('/voucher/Contra')}
    if(e.key==='F5'){e.preventDefault();go('/voucher/Payment')}
    if(e.key==='F6'){e.preventDefault();go('/voucher/Receipt')}
    if(e.key==='F7'){e.preventDefault();go('/voucher/Journal')}
    if(e.key==='F8' && e.ctrlKey){e.preventDefault();go('/invoice/Credit%20Note')}
    else if(e.key==='F8'){e.preventDefault();go('/invoice/Sales')}
    if(e.key==='F9' && e.ctrlKey){e.preventDefault();go('/invoice/Debit%20Note')}
    else if(e.key==='F9'){e.preventDefault();go('/invoice/Purchase')}
    if(e.altKey && k==='c'){
      const active=document.activeElement;
      if(active && active.dataset && active.dataset.create){ e.preventDefault(); openInlineMaster(active); return; }
    }
    // Tally style top-line shortcuts without Alt. Works only outside form fields.
    const activeEl=document.activeElement;
    const inForm=activeEl && ['INPUT','TEXTAREA','SELECT'].includes(activeEl.tagName);
    if(!e.ctrlKey && !e.altKey && !e.metaKey && !inForm){
      const topKeyMap={k:'/companies',d:'/backup',x:'/utilities/tally',g:'/dashboard',i:'/utilities/tally',e:'/utilities/tally',p:'print',q:'/logout'};
      if(topKeyMap[k]){
        e.preventDefault();
        if(topKeyMap[k]==='print'){ beep(760); window.print(); }
        else { go(topKeyMap[k]); }
        return;
      }
    }
    if(e.altKey){
      const map={
        o:'/companies',g:'/dashboard','1':'/masters/group','2':'/masters/ledger','3':'/masters/unit','4':'/masters/item','5':'/gst_rates',
        p:'/invoice_payment',d:'/reports/daybook',t:'/reports/trial',l:'/reports/pl',b:'/reports/balance',c:'/reports/cashbook',k:'/reports/bankbook',s:'/reports/stock',r:'/reports/gst',x:'/reports/sales_register',y:'/reports/purchase_register',u:'/reports/outstanding',
        n:'/clients',j:'/status/gst',i:'/status/itr',w:'/status/task',z:'/backup',e:'/restore',h:'/checkup',a:'/reports/audit'
      };
      if(map[k]){e.preventDefault();go(map[k]);}
    }
  });
})();

try{const d=new Date();const el=document.getElementById('todayText');if(el){el.textContent=d.toLocaleDateString('en-IN',{weekday:'long',day:'2-digit',month:'short',year:'numeric'});}}catch(e){}
