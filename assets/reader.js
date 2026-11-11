const mode=document.getElementById('mode'),notes=document.getElementById('notes');
mode.addEventListener('click',()=>{
  const yes=document.body.classList.toggle('chinese-only');
  mode.textContent=yes?'显示原文':'仅看中文';
  mode.setAttribute('aria-pressed',String(yes));
});
notes.addEventListener('click',()=>{
  const hide=document.body.classList.toggle('hide-notes');
  notes.classList.toggle('active',!hide);
  notes.setAttribute('aria-pressed',String(!hide));
});
document.getElementById('topbtn').addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));
document.getElementById('search').addEventListener('input',e=>{
  const q=e.target.value.toLocaleLowerCase().trim();
  let matches=0;
  document.querySelectorAll('.paragraph').forEach(p=>{
    p.hidden=!!q&&!p.textContent.toLocaleLowerCase().includes(q);
    if(!p.hidden)matches++;
  });
  document.querySelectorAll('.article-part').forEach(s=>{
    s.hidden=!!q&&![...s.querySelectorAll('.paragraph')].some(p=>!p.hidden);
  });
  const status=document.getElementById('search-status');
  status.hidden=!q;
  status.textContent=matches?`找到 ${matches} 个相关自然段`:'未找到相关自然段';
});
const toc=[...document.querySelectorAll('.toc a')];
if('IntersectionObserver' in window){
  const observer=new IntersectionObserver(entries=>{
    for(const e of entries)if(e.isIntersecting)
      toc.forEach(a=>a.classList.toggle('current',a.hash==='#'+e.target.id));
  },{rootMargin:'-80px 0px -70% 0px'});
  document.querySelectorAll('.article-part').forEach(e=>observer.observe(e));
}
