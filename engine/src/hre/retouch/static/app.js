'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const STAGES = [
    ['inputs', '输入与区域', 'SOURCE / REFERENCE', '先确认图像角色与可比区域。', '源图 A 保留内容，参考图 B 只提供所选外观；区域坐标分别定义。'],
    ['diagnose', '诊断与参考分析', 'OBSERVE THE REFERENCE', '理解参考，建立迁移依据。', '分别查看源图状态、参考外观和适合迁移的差异。没有明显退化也可以存在调色目标。'],
    ['evidence', '测量与证据', 'MEASURE / COMPARE', '让外观观察得到证据支持。', '在真实 A/B 与独立区域上测量。直方图和均值受内容比例影响，不能替代语义对应。'],
    ['compose', '目标与编辑提示', 'REFERENCE INTO INTENT', '把参考观察变成明确目标。', '每个目标连接 B 的观察、A 的位置、编辑方向与完成标准。'],
    ['edit', 'GPT Image 2 编辑', 'APPEARANCE TRANSFER', '从原始 A 与 B 开始编辑。', '执行器只接收 A、B 和完整编辑指令；保留实际调用身份与候选结果。'],
    ['verify', '逐目标验证', 'VERIFY THE TRANSFER', '参考接近，也要内容保持。', '独立检查 A/C 的内容、B/C 的外观与自然度。任何必需目标未完成都不能自动通过。'],
    ['refine', '反馈与修订', 'REFINE FROM ORIGINALS', '修正差距，不改变评价目标。', '只处理有证据的残余问题；每轮仍从原始 A/B 编辑，完整保留已达成的要求。'],
    ['report', '全过程记录', 'TRACE / EXPORT', '从参考观察追溯到最终判断。', '分别查看参考属性达成、内容保持、真实调用与候选，不将自动判断当作效果真值。'],
  ];
  const LABELS = {
    inputs:'输入', diagnose:'诊断', evidence:'证据', compose:'提示编译', edit:'图像编辑', verify:'验证', refine:'反馈', report:'报告',
    pending:'待执行', ready:'可执行', completed:'已完成', needs_input:'等待输入', running:'执行中', failed:'失败',
    observed:'已观察', uncertain:'待确认', not_applicable:'不适用', measured:'实际测量', comparable:'可比较', conditional:'条件可比', incomparable:'不可比较', unknown:'未知', targeted:'转为编辑目标', preserve:'保留', excluded:'排除', submission_unknown:'请求结果待核对',
    achieved:'已达成', partial:'部分达成', unmet:'未达成', pass:'通过', fail:'未通过', accept:'外观检查通过', accepted:'通过验收', revise:'需要修订', reject:'拒绝',
    already_satisfied:'原图已满足', ready_to_edit:'目标已冻结', task_not_met:'目标未完成', source_fallback:'原图回退', waiting_for_provider:'等待模型／导入', needs_review:'需复核',
    transfer_supported:'支持参考迁移', already_close:'已接近参考', insufficient_reference:'参考依据不足', needs_evidence:'需要证据',
    source:'源图 A', reference:'参考图 B', appearance_reference:'参考图 B', candidate:'候选 C',
    neutral_balance:'白平衡与中性色', chroma_by_hue:'色相与彩度', skin_rendering:'肤色呈现', shadow_midtone_highlight:'阴影 / 中间调 / 高光',
    highlight_transition:'高光过渡', local_contrast:'局部对比', subject_background_balance:'主体／背景关系', texture_and_noise_observation:'纹理与噪声观察',
    brightness:'亮度', color:'颜色', tone:'影调', saturation:'彩度', white_balance:'白平衡', skin_tone:'肤色',
    manual_agent:'导入 Agent 观察', human:'人工观察', manual_import:'导入结果', api:'实际模型调用', automatic:'实际测量',
    awaiting_verification:'等待验证', stop:'停止修订', skipped:'无需修订', delivery_not_met:'交付条件未满足', not_frozen:'历史未冻结', not_required:'未要求',
  };
  const state = { config:{}, cases:[], current:null, active:'inputs', selections:{source:null,reference:null}, drawRole:null, selectedTarget:null, focusRegion:null, importStage:null, busy:false };
  let noticeTimer;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const arr = (value) => Array.isArray(value) ? value : value == null ? [] : typeof value === 'object' ? Object.entries(value).map(([key,val]) => typeof val === 'object' && val !== null ? {attribute:key,...val} : {attribute:key,observation:val}) : [value];
  const text = (value) => value == null ? '' : typeof value === 'string' ? value : typeof value === 'number' ? String(value) : value.observation ?? value.description ?? value.instruction ?? value.summary ?? value.item ?? value.reason ?? JSON.stringify(value);
  const label = (value) => LABELS[value] || value || '—';
  const originValue = (value) => typeof value==='string'?value:value?.provenance||value?.provider||value?.model||'';
  const safeUrl = (value) => {
    if (!value) return '';
    try { const url = new URL(String(value), location.href); return url.origin === location.origin && ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
  };
  const number = (n, digits=1) => Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : '—';
  const percentage = (n) => Number.isFinite(Number(n)) ? `${(Number(n)*100).toFixed(1)}%` : '—';
  const apiPath = (suffix='') => `/api/cases/${encodeURIComponent(state.current.id)}${suffix}`;
  const tagClass = (status) => ['achieved','pass','accept','accepted','completed','observed','comparable','already_satisfied','ready_to_edit','transfer_supported'].includes(status) ? 'good' : ['fail','reject','failed','unmet','incomparable','task_not_met','delivery_not_met'].includes(status) ? 'bad' : ['partial','uncertain','needs_input','conditional','unknown','revise','needs_review','insufficient_reference','needs_evidence','not_frozen'].includes(status) ? 'warn' : '';
  const tag = (status) => `<span class="tag ${tagClass(status)}">${esc(label(status))}</span>`;
  const blank = (title,detail='尚无实际结果；执行或导入本阶段后会显示。') => `<div class="blank-content"><strong>${esc(title)}</strong>${esc(detail)}</div>`;
  const factList = (items,empty='暂无记录') => arr(items).length ? `<ul class="fact-list">${arr(items).map(x=>`<li>${esc(text(x))}</li>`).join('')}</ul>` : `<p class="muted">${esc(empty)}</p>`;
  const jsonDetails = (value,title='查看原始记录') => value ? `<details class="code-details"><summary>${esc(title)}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>` : '';
  const evidenceLinks = (refs) => arr(refs).length ? `<div class="evidence-links">${arr(refs).map(ref=>`<button class="evidence-link" data-evidence="${esc(typeof ref==='string'?ref:text(ref))}" title="定位证据 ${esc(typeof ref==='string'?ref:text(ref))}">${esc(typeof ref==='string'?ref:text(ref))}</button>`).join('')}</div>` : '';

  async function api(url, options={}) {
    const response = await fetch(url, {headers:{'Content-Type':'application/json'},...options});
    let data;
    try { data = await response.json(); } catch { throw new Error(`服务返回无效响应（${response.status}）`); }
    if (!response.ok) throw new Error(data.message || data.error || `请求失败（${response.status}）`);
    return data;
  }
  const post = (url,body) => api(url,{method:'POST',body:JSON.stringify(body)});
  function notify(message,error=false) {
    clearTimeout(noticeTimer); $('notice').textContent=message; $('notice').className=`notice${error?' error':''}`;
    const dialog=document.querySelector('dialog[open]');
    if(error&&dialog){let warning=dialog.querySelector('.dialog-error');if(!warning){warning=document.createElement('p');warning.className='notice error dialog-error';warning.setAttribute('role','alert');dialog.querySelector('.dialog-header').after(warning);}warning.textContent=message;}
    noticeTimer=setTimeout(()=>$('notice').classList.add('hidden'),error?14000:7000);
  }
  async function task(message,fn) {
    if(state.busy) return;
    state.busy=true; $('busy-message').textContent=message; $('busy-overlay').classList.remove('hidden');
    try { await fn(); } catch(error) { notify(error.message || String(error),true); }
    finally { state.busy=false; $('busy-overlay').classList.add('hidden'); }
  }
  function acceptCase(data,{stage=null}={}) {
    const next=data.case || data;
    if(state.current?.id!==next?.id){
      state.selectedTarget=null;state.focusRegion=null;state.selections={source:null,reference:null};state.drawRole=null;
      $('trace-panel').classList.add('hidden');
      $('region-editor').classList.add('hidden');
      document.querySelectorAll('.photo-card').forEach(card=>card.classList.remove('highlighted'));
      document.querySelectorAll('.draw-toggle').forEach(button=>button.setAttribute('aria-pressed','false'));
      document.querySelectorAll('.photo-canvas').forEach(canvas=>{canvas.classList.remove('drawing');canvas.querySelector('.draw-hint').classList.add('hidden');});
    }
    state.current=next;
    if (!state.current || !state.current.id) throw new Error('案例响应缺少 id');
    if(stage) state.active=stage;
    render();
  }
  async function refreshCases() {
    const data=await api('/api/cases'); state.cases=data.cases || [];
    const select=$('case-select');
    select.innerHTML=state.cases.length ? state.cases.map(c=>`<option value="${esc(c.id)}">${esc(c.source_name || c.id)} → ${esc(c.reference_name || '参考')}</option>`).join('') : '<option value="">尚无案例</option>';
    if(state.current) select.value=state.current.id;
  }
  async function loadCase(id) {
    if(!id) return;
    await task('正在读取案例与真实阶段记录',async()=>{const data=await api(`/api/cases/${encodeURIComponent(id)}`); state.selectedTarget=null;state.focusRegion=null;state.selections={source:null,reference:null}; acceptCase(data,{stage:data.phase&&STAGES.some(s=>s[0]===data.phase)?data.phase:'inputs'});});
  }
  function renderNav() {
    $('stage-nav').innerHTML=STAGES.map(([id,title,en],index)=>{
      const record=state.current?.stages?.find(s=>s.id===id); const status=id==='refine'&&['accepted','already_satisfied','delivery_not_met'].includes(state.current?.status)&&!state.current?.refinement?'skipped':record?.status || 'pending';
      return `<button class="stage-nav-item ${state.active===id?'active':''} ${esc(status)}" data-stage="${id}" aria-current="${state.active===id?'step':'false'}"><span class="step-number">${status==='completed'?'✓':status==='skipped'?'—':String(index+1).padStart(2,'0')}</span><span><strong>${title}${status==='skipped'?' · 无需修订':''}</strong><small>${en}</small></span><span class="status-dot" title="${esc(label(status))}"></span></button>`;
    }).join('');
  }
  function render() {
    renderNav();
    const c=state.current;
    $('empty-state').classList.toggle('hidden',!!c); $('photo-section').classList.toggle('hidden',!c); $('download-report').disabled=!c;
    $('stage-content').innerHTML='';
    const spec=STAGES.find(s=>s[0]===state.active)||STAGES[0];
    if(!c){$('stage-heading').innerHTML='把参考看清楚，<br><em>再让外观发生改变。</em>';$('stage-intro').textContent='载入源图与参考图，逐步查看分析、证据与迁移的全过程。';$('case-summary').innerHTML='';return;}
    $('stage-heading').textContent=spec[3]; $('stage-intro').textContent=spec[4]; $('case-id').textContent=`${spec[2]} / ${c.id}`;
    $('case-summary').innerHTML=`<p class="brief">${esc(c.brief)}</p>${tag(c.status)} <span class="tag">分析接口 ${Number(c.calls?.analysis||0)} 次 · 图像预算 ${Number(c.calls?.images||0)}/${Number(state.config.max_generations||3)}</span>`;
    ['source','reference'].forEach(role=>{
      const asset=c.images?.[role]; const img=$(`${role}-image`); const url=safeUrl(asset?.url);
      if(img.getAttribute('src')!==url) { if(url) img.src=url; else img.removeAttribute('src'); }
      $(`${role}-meta`).innerHTML=`<span>${esc(asset?.name || label(role))}</span><span>${Number(asset?.width||0)} × ${Number(asset?.height||0)}</span>`;
    });
    renderRegions();
    const renderers={inputs:renderInputs,diagnose:renderDiagnosis,evidence:renderEvidence,compose:renderCompose,edit:renderEdit,verify:renderVerify,refine:renderRefine,report:renderReport};
    $('stage-content').innerHTML=`<div class="stage-reveal">${originBanner(state.active)}${['inputs','compose','edit'].includes(state.active)?renderAcceptance():''}${renderers[state.active]()}</div>`;
    $('footer-status').textContent=`${label(c.status)} · ${arr(c.events).length} 条真实记录 · B 为外观参考，不是像素真值`;
    requestAnimationFrame(updateOverlays);
    bindComparison();
  }
  function originBanner(stage) {
    const c=state.current;
    const hasResult={diagnose:!!c.analysis,evidence:!!c.evidence,compose:!!c.contract,edit:!!c.images?.candidate,verify:!!c.verification,refine:arr(c.events).some(e=>e.stage==='refine')}[stage];
    if(!hasResult)return '';
    const event=arr(c.events).slice().reverse().find(e=>e.stage===stage&&(e.kind==='measured'||e.kind==='observed_import'||e.provenance));
    const origin=originValue(event?.provenance);
    let title='来源未记录',detail='请在原始记录中核对观察与执行来源。',kind='warn';
    if(event?.kind==='measured'){title='像素实测';detail='由本地程序测量真实 A/B 和独立 ROI，不包含自动语义推断。';kind='good';}
    else if(origin==='manual_agent'){title='Agent 观察导入';detail='来自实际读图的 Agent 观察，已校验并记录导入；未计为分析接口调用。';kind='good';}
    else if(origin==='human'){title='人工观察';detail='来自实际人工检查并导入；不冒充模型接口结果。';kind='good';}
    else if(origin==='manual_import'){title='编辑结果导入';detail='已记录实际可见执行身份；导入不代表候选通过验收。';kind='good';}
    else if(origin){title='实际接口结果';detail=`${label(origin)} · 详细模型身份与回执见全过程记录。`;kind='good';}
    return `<div class="origin-banner"><span class="tag ${kind}">${esc(title)}</span><span>${esc(detail)}</span>${event?.time?`<time>${esc(formatTime(event.time))}</time>`:''}</div>`;
  }
  function actionBar(stage,{run=true,importResult=true,extra=''}={}) {
    const conf=stage==='edit'?state.config.image_configured:state.config.analysis_configured;
    const local=stage==='evidence'; const c=state.current;
    const outOfOrder=(['edit','verify','refine'].includes(stage)&&c.phase!==stage)||(['diagnose','compose'].includes(stage)&&!!c.contract)||(['accepted','already_satisfied','delivery_not_met','submission_unknown'].includes(c.status)&&!local);
    const disabled=run&&((!local&&!conf)||outOfOrder);
    const next=STAGES[STAGES.findIndex(s=>s[0]===stage)+1];
    return `<div class="stage-actionbar"><p>${local?'测量真实图像与已保存 ROI，不调用图像模型。':conf?'执行会调用当前配置的真实模型，并保存原始结果。':'当前未配置本阶段模型；可导出请求并导入实际 Agent／人工结果。'}</p><div class="actions">${run?`<button class="button primary" data-run="${stage}" ${disabled?'disabled':''}>${local?'测量 A/B 与区域':stage==='edit'?'运行 GPT Image 2 编辑':'执行'+label(stage)}</button>`:''}${stage!=='evidence'?`<button class="button" data-export="${stage}">导出请求</button>`:''}${importResult?`<button class="button quiet" data-import="${stage}">导入结果</button>`:''}${extra}${next?`<button class="button quiet" data-stage="${next[0]}">查看${next[1]} →</button>`:''}</div></div>`;
  }
  function renderInputs() {
    const c=state.current;
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">01 / INPUT ROLES</p><h2>内容锚点与外观参考分别保留</h2></div>${tag('ready')}</div><div class="three-column"><div><h3><span class="role-badge source">A</span> 内容来源</h3><p class="muted">身份、表情、对象、文字、构图、几何和可见真实纹理。</p></div><div><h3><span class="role-badge reference">B</span> 外观来源</h3><p class="muted">经确认的亮度、白平衡、色彩、影调、局部对比与区域关系。</p></div><div><h3>区域独立对应</h3><p class="muted">每张图分别选区；同坐标不代表同对象，材质和光照差异需要确认。</p></div></div><div class="callout">${esc(c.brief)}</div><div class="stage-actionbar"><p>已保存 ${arr(c.regions).length} 对独立区域。区域可以先粗选，分析后再确认可比属性。</p><div class="actions"><button class="button" data-region-open>设置区域对应</button><button class="button quiet" data-stage="evidence">先查看真实测量</button><button class="button primary" data-stage="diagnose">进入诊断与参考分析 →</button></div></div></div>`;
  }
  function renderDiagnosis() {
    const a=state.current.analysis;
    if(!a) return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">02 / OBSERVATION</p><h2>等待对真实 A/B 的诊断</h2></div></div>${blank('参考外观尚未分析','先执行视觉分析，或导出包含 A/B 角色的请求，再导入实际观察。')}${actionBar('diagnose')}</div>`;
    const src=a.source_diagnosis||{};
    const profiles=arr(a.reference_profile);
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">02 / SOURCE DIAGNOSIS</p><h2>A 的状态，与 B 的风格分开分析</h2></div>${tag(a.analysis_status)}</div><div class="two-column"><div><h3>源图技术问题</h3>${factList(src.source_degradation,'未记录技术退化；这不代表没有参考外观目标。')}<h3 style="margin-top:20px">源图摄影外观</h3>${factList(src.source_appearance)}</div><div><h3>必须保留的源图事实</h3>${factList(src.protected_facts)}<h3 style="margin-top:20px">不可辨文字／细节</h3>${factList(src.unreadable_text_regions,'暂无不可辨区域记录')}</div></div></div><div class="panel"><div class="section-heading"><div><p class="eyebrow">REFERENCE APPEARANCE PROFILE</p><h2>B 提供了哪些可迁移外观</h2></div><span class="tag">观察与不确定项分别显示</span></div>${profiles.length?`<div class="observation-grid">${profiles.map(p=>`<article class="observation-card"><header><h3>${esc(label(p.attribute||p.dimension||p.id))}</h3>${tag(p.status||'uncertain')}</header><p>${esc(text(p))}</p><span class="region-label">${esc(text(p.region)||'全图／区域未指定')}</span>${evidenceLinks(p.evidence_refs)}</article>`).join('')}</div>`:blank('尚无参考属性记录')}${renderCoverage(a.coverage)}${jsonDetails(a,'查看完整诊断 JSON')}</div><div class="panel"><div class="section-heading"><div><p class="eyebrow">TRANSFERABLE DIFFERENCES</p><h2>哪些差异适合迁移到 A</h2></div></div>${arr(a.candidate_deltas).length?`<div class="observation-grid">${arr(a.candidate_deltas).map(d=>`<article class="observation-card"><h3>${esc(label(d.attribute))}</h3><p>${esc(d.desired_change||d.instruction||text(d))}</p><div class="target-flow"><div><small>A 当前</small>${esc(text(d.source_state||d.source_observation))}</div><span class="arrow">→</span><div><small>B 依据</small>${esc(text(d.reference_state||d.reference_observation))}</div></div>${evidenceLinks(d.evidence_refs)}${d.uncertainty?`<p class="dim">${esc(text(d.uncertainty))}</p>`:''}</article>`).join('')}</div>`:blank('未形成可支持的差异目标')}${renderCorrespondence(a.correspondence)}${actionBar('diagnose')}</div>`;
  }
  function renderCoverage(coverage) {
    const items=arr(coverage); if(!items.length)return '';
    if(items.some(x=>Array.isArray(x.target_ids)))return `<div style="margin-top:22px"><h3>参考外观如何转成编辑目标</h3><div class="coverage-grid">${items.map(x=>`<article class="coverage-item"><strong>${esc(label(x.attribute))}</strong>${tag(x.status)}<p>${esc(x.reason||'')}</p><div class="evidence-links">${arr(x.target_ids).map(id=>`<button class="button mini quiet" data-target="${esc(id)}">${esc(id)} ↗</button>`).join('')||'<span class="dim">此属性不作为新增编辑目标</span>'}</div></article>`).join('')}</div></div>`;
    return `<div style="margin-top:22px"><h3>参考维度覆盖</h3><div class="evidence-links">${items.map(x=>`<span class="tag ${tagClass(x.status)}" title="${esc(text(x))}">${esc(label(x.attribute||x.dimension||x.id||typeof x==='string'&&x))}${x.status?' · '+esc(label(x.status)):''}</span>`).join('')}</div></div>`;
  }
  function renderCorrespondence(items) {
    const rows=arr(items);if(!rows.length)return '';
    return `<div style="margin-top:22px"><h3>语义与材质对应</h3>${rows.map(x=>`<div class="observation-card" style="margin-bottom:8px"><header><h3>${esc(x.description||x.material||x.semantic||x.id||'区域对应')}</h3>${tag(typeof x.comparability==='string'?x.comparability:'unknown')}</header><p>A：${esc(text(x.source_region))}<br>B：${esc(text(x.reference_region))}</p>${x.reason||x.observation?`<p>${esc(x.reason||x.observation)}</p>`:''}${evidenceLinks(x.evidence_refs)}</div>`).join('')}</div>`;
  }
  function legend() {return '<div class="chart-legend"><span><i style="background:var(--blue)"></i>源图 A</span><span><i style="background:var(--amber)"></i>参考图 B</span></div>';}
  function seriesPath(values,max=1) {
    if(!Array.isArray(values)||!values.length)return '';
    return values.map((v,i)=>`${i?'L':'M'}${(34+i*(516/Math.max(1,values.length-1))).toFixed(2)},${(118-Math.max(0,Math.min(1,Number(v)/max))*98).toFixed(2)}`).join(' ');
  }
  function chart(a,b,kind='histogram') {
    const va=arr(a?.[kind]).map(Number),vb=arr(b?.[kind]).map(Number); if(!va.length&&!vb.length)return blank('暂无可显示的测量');
    const max=kind==='histogram'?Math.max(...va,...vb,1):1;
    const ticks=kind==='histogram'?['暗部','中间调','亮部']:['P01','P10','P50','P90','P99'];
    return `<svg class="chart" viewBox="0 0 580 145" role="img" aria-label="${kind==='histogram'?'A/B 亮度直方图':'A/B 亮度分位数'}"><line class="grid-line" x1="34" y1="118" x2="550" y2="118"/><line class="grid-line" x1="34" y1="69" x2="550" y2="69"/><line class="grid-line" x1="34" y1="20" x2="550" y2="20"/>${va.length?`<path class="line-a" d="${seriesPath(va,max)}"/>`:''}${vb.length?`<path class="line-b" d="${seriesPath(vb,max)}"/>`:''}${ticks.map((s,i)=>`<text x="${34+i*(516/(ticks.length-1))}" y="139" text-anchor="${i===0?'start':i===ticks.length-1?'end':'middle'}">${s}</text>`).join('')}</svg>`;
  }
  function palette(stats,role) {
    return `<div class="palette-label"><span class="role-badge ${role==='source'?'source':'reference'}">${role==='source'?'A':'B'}</span>${esc(label(role))} 的像素色板</div><div class="palette">${arr(stats?.palette).map(s=>{const hex=/^#[0-9a-fA-F]{6}$/.test(s.hex)?s.hex:'#444444';return `<span style="background:${hex};flex:${Math.max(.005,Number(s.weight)||0)}" title="${hex} · ${percentage(s.weight)}"></span>`;}).join('')}</div>`;
  }
  function statsTable(a,b) {
    const values=[['Lab 平均 L*',a?.lab_mean?.[0],b?.lab_mean?.[0]],['Lab 平均 a*',a?.lab_mean?.[1],b?.lab_mean?.[1]],['Lab 平均 b*',a?.lab_mean?.[2],b?.lab_mean?.[2]],['平均彩度',a?.saturation,b?.saturation],['局部对比描述量',a?.local_contrast,b?.local_contrast]];
    return `<table class="stat-table"><thead><tr><th>显示域属性</th><th>A</th><th>B</th></tr></thead><tbody>${values.map(([t,x,y])=>`<tr><td>${t}</td><td class="mono">${number(x,t.includes('彩度')||t.includes('对比')?3:1)}</td><td class="mono">${number(y,t.includes('彩度')||t.includes('对比')?3:1)}</td></tr>`).join('')}<tr><td>暗端／亮端比例</td><td class="mono">${percentage(a?.clipping?.black)} / ${percentage(a?.clipping?.white)}</td><td class="mono">${percentage(b?.clipping?.black)} / ${percentage(b?.clipping?.white)}</td></tr></tbody></table>`;
  }
  function renderEvidence() {
    const e=state.current.evidence;
    if(!e)return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">03 / REAL IMAGE MEASUREMENTS</p><h2>用真实像素核查外观观察</h2></div></div>${blank('尚未执行测量','可先保存独立区域，再测量全图与每一对 ROI。')}${actionBar('evidence',{importResult:false})}</div>`;
    return `<div class="two-column"><div class="panel"><p class="eyebrow">DISPLAY LUMA</p><h2>全图亮度分布</h2>${legend()}${chart(e.source,e.reference)}<p class="muted">各自的像素分布；内容面积不同会影响形状。</p></div><div class="panel"><p class="eyebrow">TONAL RELATIONSHIPS</p><h2>阴影到高光的分位数</h2>${legend()}${chart(e.source,e.reference,'luma_quantiles')}<p class="muted">用于描述层次，不能唯一恢复摄影影调曲线。</p></div></div><div class="panel"><div class="section-heading"><div><p class="eyebrow">COLOUR EVIDENCE</p><h2>色彩与显示域属性</h2></div><span class="tag good">实际测量</span></div><div class="two-column"><div>${palette(e.source,'source')}${palette(e.reference,'reference')}<p class="muted" style="margin-top:16px">色板反映图像内容，不自动成为全图调色目标。</p></div><div>${statsTable(e.source,e.reference)}</div></div><div class="callout">${esc(e.domain||'显示域统计；不是线性辐射或精确物理曝光。')}</div></div><div class="panel"><div class="section-heading"><div><p class="eyebrow">REGION EVIDENCE</p><h2>独立区域上的参考依据</h2></div><button class="button mini quiet" data-region-open>编辑区域</button></div>${arr(e.regions).length?arr(e.regions).map(r=>`<article class="observation-card" style="margin-bottom:12px"><header><h3><button class="text-button" data-evidence="${esc(r.id)}">${esc(r.id)} · ${esc(r.description)}</button></h3>${tag(r.comparability)}</header><div class="two-column"><div>${legend()}${chart(r.source,r.reference,'luma_quantiles')}</div><div>${statsTable(r.source,r.reference)}</div></div><p class="muted">声明可比属性：${arr(r.attributes).map(x=>esc(label(x))).join(' / ')||'尚未确认'}</p></article>`).join(''):blank('尚无独立 ROI 测量','先分别在 A/B 框选可比较区域，再重新执行测量。')}${jsonDetails(e)}${actionBar('evidence',{importResult:false})}</div>`;
  }
  function renderTargets() {
    const c=state.current.contract;
    return arr(c?.targets).length?`<div class="target-list">${arr(c.targets).map((t,i)=>`<article class="target-card ${state.selectedTarget===t.target_id?'selected':''}" data-target="${esc(t.target_id)}" tabindex="0" role="button" aria-label="查看目标 ${esc(t.target_id)} 的参考证据链"><span class="target-id"><b>${String(i+1).padStart(2,'0')}</b><small>${esc(t.target_id)}</small></span><div><h3>${esc(label(t.attribute))} · ${esc(t.desired_change)}</h3><div class="target-flow"><div><small>B 的参考依据</small>${esc(t.reference_observation)}</div><span class="arrow">→</span><div><small>A 的当前状态</small>${esc(t.source_observation)}</div></div><p class="target-criterion">完成标准：${esc(t.acceptance_criterion)}</p>${evidenceLinks(t.evidence_refs)}</div><div class="target-aside"><span class="tag ${t.mandatory?'warn':''}">${t.mandatory?'必需目标':'可选目标'}</span>${tag(t.comparability)}<small class="dim">查看使用链 ↗</small></div></article>`).join('')}</div>`:blank('尚无冻结目标');
  }
  function renderCompose() {
    const c=state.current.contract;
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">04 / FROZEN APPEARANCE TARGETS</p><h2>参考观察如何成为编辑目标</h2></div>${c?tag(c.overall_status):'<span class="tag">尚未编译</span>'}</div>${c?renderTargets():blank('先完成诊断与证据','目标必须说明 B 的依据、A 的现状和完成标准。')}${c?`<div class="two-column" style="margin-top:22px"><div><h3>源图保护项</h3>${factList(c.protected_facts)}</div><div><h3>明确排除的参考特征</h3>${factList(c.excluded_reference_traits)}</div></div>${renderCoverage(c.coverage)}<div class="callout">${esc(c.acceptance_rule||'所有必需目标达成，内容与自然度检查通过。')}</div>`:''}${actionBar('compose')}${jsonDetails(c,'查看冻结目标合同')}</div>${renderPrompt()}`;
  }
  function renderPrompt() {
    const prompt=state.current.prompt;
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">COMPILED EDIT PROMPT</p><h2>系统编译的编辑指令</h2></div><div class="actions"><button class="button mini quiet" data-copy-prompt ${prompt?'':'disabled'}>复制提示词</button><button class="button mini quiet" data-export="edit" ${prompt?'':'disabled'}>导出编辑请求</button></div></div>${prompt?`<div class="prompt-view" id="prompt-view">${esc(prompt)}</div><p class="muted" style="margin-top:12px">A/B 直接进入编辑器；分析图、统计图和 JSON 不是编辑附件。外部候选实际使用的提示词单独保存在本轮结果来源记录中。</p>`:blank('提示词尚未生成','这里会显示真实编译结果，不预填统一美化风格。')}</div>`;
  }
  function renderCandidateProvenance() {
    const round=arr(state.current.rounds).slice(-1)[0];if(!round)return '';
    const geometry=round.candidate_geometry;
    const unknown=round.model==='unknown';
    const nativeUrl=safeUrl(round.native_url);
    const size=value=>Array.isArray(value)&&value.length===2?value.map(Number).join(' × '):'未记录';
    return `<div class="panel candidate-provenance"><div class="section-heading"><div><p class="eyebrow">ACTUAL RESULT / PROVENANCE</p><h2>本轮结果的实际来源</h2></div><span class="tag ${unknown?'warn':''}">${unknown?'后端型号未确认':esc(round.model||'型号未记录')}</span></div><p class="muted">${esc(round.observation?.note||'实际执行与来源详见本轮记录。')}</p>${geometry?`<p class="muted">原生结果 ${esc(size(geometry.native_size))}；对比图 ${esc(size(geometry.delivered_size))}。${geometry.policy==='full_frame_resize'?'已按完整画幅缩放用于对比，原生结果保留；缩放不增加真实细节。':'画布变换详见本轮几何记录。'}</p>`:''}<div class="actions">${nativeUrl?`<a class="button mini quiet" href="${esc(nativeUrl)}" download>下载原生结果</a>`:''}</div><details class="code-details"><summary>${round.prompt_source==='external_submitted'?'查看本轮实际提交的提示词':round.prompt_source==='case_compiled_unconfirmed'?'查看案例提示词（外部执行未核对）':'查看本轮提示词记录'}</summary><pre>${esc(round.prompt||'未记录')}</pre></details></div>`;
  }
  function renderComparison() {
    const images=state.current.images||{}; if(!images.candidate)return '';
    return `${renderCandidateProvenance()}<div class="panel"><div class="section-heading"><div><p class="eyebrow">SOURCE / CANDIDATE</p><h2>A 的内容，C 的外观变化</h2></div><button class="button mini quiet" data-inspect>放大检查 A/B/C</button></div><div class="comparison"><img src="${esc(safeUrl(images.source?.url))}" alt="原始源图 A"><div class="candidate-layer"><img src="${esc(safeUrl(images.candidate?.url))}" alt="编辑候选 C"></div><div class="compare-line"></div><span class="compare-label left-label">C · 编辑候选</span><span class="compare-label right-label">A · 原始源图</span><input type="range" min="0" max="100" value="50" aria-label="拖动比较源图 A 与候选 C"></div><p class="compare-description">拖动检查变化；B 保持在上方独立画幅中。并列展示不代表已通过验收。</p></div>`;
  }
  function renderEdit() {
    return `${renderComparison()}<div class="panel"><div class="section-heading"><div><p class="eyebrow">05 / GPT IMAGE 2</p><h2>固定两图角色，一次请求一张结果</h2></div><span class="tag">${esc(state.config.image_model||'gpt-image-2')}</span></div><div class="three-column"><div><h3>01 · 原始输入</h3><p class="muted">A 与 B 按固定顺序送入，每次修订都重新读取原始两图。</p></div><div><h3>02 · 完整目标</h3><p class="muted">目标、局部关系、保护项和参考排除项共同构成编辑指令。</p></div><div><h3>03 · 真实输出</h3><p class="muted">保留候选与实际模型身份，独立验证前不标记成功。</p></div></div><div class="provider-note"><span class="dot"></span><span>${state.config.image_configured?'已配置图像接口；点击运行会实际提交图像编辑。':'尚未配置图像接口。可导出请求，完成真实编辑后导入 C；请填写实际观察到的模型身份。'}</span></div>${actionBar('edit',{importResult:false,extra:'<button class="button quiet" data-candidate-import>导入编辑结果 C</button>'})}</div>${renderPrompt()}${renderRounds()}`;
  }
  function renderChecks(checks,title) {
    return `<div class="panel"><h3>${title}</h3>${arr(checks).length?arr(checks).map(check=>`<div class="check-row"><div><h3>${esc(check.item||check.name||check.region||'检查项')}</h3><p>${esc(check.observation||check.reason||'')}</p></div>${tag(check.status)}</div>`).join(''):blank('尚无检查结果')}</div>`;
  }
  function renderCandidateEvidence() {
    const rows=arr(state.current.candidate_attribute_deltas);if(!rows.length)return '';
    const units={brightness:'L*',color:'Lab a/b 距离',tone:'L* 分位差',saturation:'彩度差'};
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">A / B / C MEASUREMENTS</p><h2>编辑前后，与参考的属性差距</h2></div><span class="tag good">实际像素测量</span></div><p class="muted">在已声明的区域上比较 A/B 与 C/B 的属性差距。数值变小仅支持该属性更接近参考，不能代替人物、文字、几何和自然度核查。</p><table class="stat-table"><thead><tr><th>区域 / 属性</th><th>A 与 B</th><th>C 与 B</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.region_id)} · ${esc(label(row.attribute))}<small class="dim"> ${esc(units[row.attribute]||'')}</small></td><td class="mono">${number(row.before,3)}</td><td class="mono">${number(row.after,3)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function renderVerify() {
    const v=state.current.verification;
    return `${renderComparison()}${renderAcceptance()}<div class="panel"><div class="section-heading"><div><p class="eyebrow">06 / TARGET-BY-TARGET VERIFICATION</p><h2>每个参考目标都要单独回答</h2></div>${v?tag(v.global_status):'<span class="tag">等待验证</span>'}</div><div class="callout">内容保持、参考属性达成、自然度分别判断。任何必需目标未达成、未知或缺失，都不能用其他项的改善抵消。</div>${v?`<div>${arr(v.target_results).map(r=>`<article class="result-row" data-target="${esc(r.target_id)}" tabindex="0" role="button"><strong>${esc(r.target_id)} · ${esc(label(state.current.contract?.targets?.find(t=>t.target_id===r.target_id)?.attribute))}</strong>${tag(r.status)}<p>${esc(r.observation)}</p>${r.remaining_gap?`<p class="remaining">剩余差距：${esc(text(r.remaining_gap))}</p>`:''}${evidenceLinks(r.evidence_refs)}</article>`).join('')}</div>`:blank('候选尚未完成逐目标验证',state.current.images?.candidate?'真实候选已导入，下一步执行或导入独立的 A/B/C 验证。':'没有候选时不生成虚构的达成状态。')}${actionBar('verify')}${jsonDetails(v)}</div>${renderCandidateEvidence()}${v?`<div class="two-column">${renderChecks(v.preservation_checks,'A → C 内容保持')}${renderChecks(v.artifact_checks,'自然度与参考污染')}</div><div class="panel"><h3>无法确认的覆盖范围</h3>${factList(v.evaluator_coverage,'未记录额外不可评范围')}</div>`:''}`;
  }
  function renderAcceptance() {
    const c=state.current;const d=c.delivery_assessment||{};const legacy=d.status==='not_frozen';
    const size=value=>Array.isArray(value)&&value.length===2?value.join(' × '):'未记录';
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">APPEARANCE / NATIVE DELIVERY</p><h2>外观与交付分别验收</h2></div>${tag(c.status)}</div><div class="two-column"><div><h3>参考外观与可见内容</h3>${tag(c.appearance_status||'pending')}<p class="muted">逐目标及保护项的判断；不能替代原生尺寸与细节交付检查。</p></div><div><h3>原生交付条件</h3>${tag(d.status||'pending')}<p class="muted">原生文件 ${esc(size(d.native_size))}；交付／对比图 ${esc(size(d.delivered_size))}。</p><p class="muted">${legacy?'历史案例未冻结独立交付门槛；原验收结论按当时合同保留。':`冻结原生尺寸下限 ${esc(size(d.required_native_size))}；细节保真 ${esc(label(d.detail_preservation||'not_required'))}。`}</p></div></div>${factList(d.reasons,'交付要求在创建案例时冻结；尚无实际结果。')}${jsonDetails(c.delivery_requirements,'查看本案例冻结的交付要求')}</div>`;
  }
  function renderRefine() {
    if(state.current.status==='delivery_not_met')return `${renderAcceptance()}<div class="panel"><h2>本案例已停止</h2><p class="muted">外观结果与交付限制均已保留。尺寸或细节能力需要先核对；没有支持的改法时不追加重绘。</p><button class="button primary" data-stage="report">查看全过程记录 →</button></div>${renderRounds()}`;
    if(['accepted','already_satisfied'].includes(state.current.status))return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">07 / FEEDBACK DECISION</p><h2>本轮无需修订</h2></div>${tag('skipped')}</div><p class="muted">${state.current.status==='accepted'?'已根据独立验证结果通过当前冻结目标的验收，流程进入全过程记录。':'输入已经满足目标，已进入全过程记录。'}</p><div class="stage-actionbar"><p>参考达成、内容保持和结果来源分别保留在记录中。</p><div class="actions"><button class="button" data-stage="verify">查看逐目标验证</button><button class="button primary" data-stage="report">查看全过程记录 →</button></div></div></div>${renderRounds()}`;
    const issues=arr(state.current.verification?.actionable_issues);
    const decision=state.current.refinement;
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">07 / BOUNDED FEEDBACK</p><h2>围绕具体差距修订编辑计划</h2></div><span class="tag">原始 A+B → 新候选</span></div>${decision?`<div class="observation-card"><header><h3>本轮反馈结论</h3>${tag(decision.action)}</header><p>${esc(decision.reason||'')}</p>${arr(decision.review_requests).length?factList(decision.review_requests):''}</div>`:''}${issues.length?issues.map(x=>`<article class="observation-card" style="margin-bottom:10px"><h3>${esc(x.target_id||x.id||x.kind||'可处理问题')}</h3><p>${esc(x.observation||text(x))}</p>${x.suggested_correction||x.suggested_change?`<p>修正方向：${esc(x.suggested_correction||x.suggested_change)}</p>`:''}${evidenceLinks(x.evidence_refs)}</article>`).join(''):blank('暂无可支持的修正问题',state.current.verification?'按验证结果确认是否需要复核或修订；未发现明确问题时不增加采样。':'先验证 C；不能为了多采样而虚构反馈理由。')}<div class="callout">冻结的目标与完成标准保持不变。新提示保留完整期望状态；上一轮 C 仅供检查，不作为新的源图。</div>${actionBar('refine')}</div>${renderRounds()}${renderPrompt()}`;
  }
  function renderRounds() {
    const rounds=arr(state.current.rounds);if(!rounds.length)return '';
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">CANDIDATE HISTORY</p><h2>所有真实候选与判断</h2></div><span class="tag">${rounds.length} 轮</span></div><div class="round-grid">${rounds.map((r,i)=>`<article class="round-card"><header><strong>ROUND ${String((r.index??i)+1).padStart(2,'0')}</strong>${tag(r.status||r.verification?.global_status||'pending')}</header>${r.candidate_url?`<img src="${esc(safeUrl(r.candidate_url))}" alt="第 ${i+1} 轮候选">`:blank('暂无候选图')}<small>${r.model==='unknown'?'外部导入 · 后端型号未确认':esc(r.model||r.provenance||'查看原始记录确认调用来源')}</small><p class="muted">外观 ${esc(label(r.appearance_status||'pending'))} · 交付 ${esc(label(r.delivery_assessment?.status||'pending'))}</p>${safeUrl(r.native_url)?`<a class="button mini quiet" href="${esc(safeUrl(r.native_url))}" download>下载原生结果</a>`:''}${jsonDetails(r,'查看本轮提示与验证')}</article>`).join('')}</div></div>`;
  }
  function renderReport() {
    const c=state.current;const targets=arr(c.contract?.targets);const results=arr(c.verification?.target_results);
    return `<div class="panel"><div class="section-heading"><div><p class="eyebrow">08 / REFERENCE USE REPORT</p><h2>参考的影响，有迹可循</h2></div><button class="button primary" data-report>导出全部案例记录 ↓</button></div><div class="three-column"><div><p class="eyebrow">APPEARANCE</p><h2>${results.filter(x=>x.status==='achieved').length} / ${targets.length}</h2><p class="muted">已达成的目标；未验证不计为完成</p></div><div><p class="eyebrow">RECORDED BUDGET</p><h2>${Number(c.calls?.analysis||0)} + ${Number(c.calls?.images||0)}</h2><p class="muted">分析接口调用 + 图像预算次数（含导入候选）；来源见事件记录</p></div><div><p class="eyebrow">OVERALL STATUS</p>${tag(c.status)}<p class="muted" style="margin-top:8px">自动验收观察仍需独立效果评价</p></div></div></div>${renderAcceptance()}<div class="panel"><h2 style="margin-bottom:16px">参考观察 → 目标 → 验证</h2>${renderTargets()}</div>${renderRounds()}<div class="panel"><div class="section-heading"><div><p class="eyebrow">OBSERVED EVENTS</p><h2>真实阶段记录</h2></div></div><div class="timeline">${arr(c.events).slice().reverse().map(e=>`<div class="timeline-item"><time>${esc(formatTime(e.time))}</time><div><p><span style="color:var(--amber)">${esc(label(e.stage))}</span> · ${esc(e.message)}</p><small>${esc(label(originValue(e.provenance)||e.kind))}</small></div></div>`).join('')||blank('尚无事件')}</div>${jsonDetails(c,'查看完整案例 JSON')}</div>`;
  }
  function formatTime(value){if(!value)return '—';const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleTimeString('zh-CN',{hour12:false});}

  function imageRect(role) {
    const img=$(`${role}-image`);const canvas=img.parentElement;const box=canvas.getBoundingClientRect();
    if(!img.naturalWidth||!img.naturalHeight)return null;
    const width=box.width,height=img.getBoundingClientRect().height,ratio=Math.min(width/img.naturalWidth,height/img.naturalHeight);
    const rw=img.naturalWidth*ratio,rh=img.naturalHeight*ratio;
    return {left:box.left+(width-rw)/2,top:box.top+(height-rh)/2,width:rw,height:rh,x:(width-rw)/2,y:(height-rh)/2};
  }
  function updateOverlays() {
    ['source','reference'].forEach(role=>{
      const rect=imageRect(role);const overlay=$(`${role}-overlay`);if(!rect)return;
      Object.assign(overlay.style,{left:`${rect.x}px`,top:`${rect.y}px`,width:`${rect.width}px`,height:`${rect.height}px`});
      const regions=arr(state.current?.regions);const selection=state.selections[role];
      const boxMarkup=(box,cls,id)=>box?`<rect x="${box[0]*1000}" y="${box[1]*1000}" width="${(box[2]-box[0])*1000}" height="${(box[3]-box[1])*1000}" class="${cls}"/>${id?`<text x="${box[0]*1000+8}" y="${box[1]*1000+37}">${esc(id)}</text>`:''}`:'';
      overlay.innerHTML=regions.map(r=>boxMarkup(r[role==='source'?'source_box':'reference_box'],`saved${state.focusRegion===r.id?' focused':''}`,r.id)).join('')+boxMarkup(selection,'selection','新选区');
    });
  }
  function renderRegions() {
    const regions=arr(state.current?.regions);
    const frozen=!!state.current?.contract;
    document.querySelectorAll('.draw-toggle').forEach(button=>{button.disabled=frozen;button.title=frozen?'目标已冻结，区域仅供查看；修改对应请建立新案例。':'在本图独立拖动框选';});
    ['save-region','clear-selection','region-description','region-comparability'].forEach(id=>$(id).disabled=frozen);
    document.querySelectorAll('#region-attributes input').forEach(input=>input.disabled=frozen);
    $('toggle-regions').textContent=frozen?'查看独立区域对应（已冻结）':'查看／编辑独立区域对应';
    $('region-list').innerHTML=regions.map(r=>`<div class="region-row"><button class="text-button" data-evidence="${esc(r.id)}">${esc(r.id)}</button><div class="region-details"><strong>${esc(r.description)}</strong><small>A ${esc(arr(r.source_box).map(x=>number(x,3)).join(', '))} · B ${esc(arr(r.reference_box).map(x=>number(x,3)).join(', '))}</small></div>${tag(r.comparability)}${!frozen?`<button class="button mini quiet" data-remove-region="${esc(r.id)}" aria-label="删除区域 ${esc(r.id)}">删除</button>`:''}</div>`).join('');
    $('selection-readout').textContent=frozen?'目标已冻结，区域仅供查看；修改对应请建立新案例。':['source','reference'].map(role=>`${role==='source'?'A':'B'}：${state.selections[role]?state.selections[role].map(x=>number(x,3)).join(', '):'未选择'}`).join(' · ');
    updateOverlays();
  }
  function setDrawRole(role) {
    state.drawRole=role===state.drawRole?null:role;
    document.querySelectorAll('.draw-toggle').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.role===state.drawRole)));
    document.querySelectorAll('.photo-canvas').forEach(canvas=>{const on=canvas.dataset.role===state.drawRole;canvas.classList.toggle('drawing',on);canvas.querySelector('.draw-hint').classList.toggle('hidden',!on);});
    $('region-editor').classList.remove('hidden');
  }
  function setupDrawing() {
    document.querySelectorAll('.photo-canvas').forEach(canvas=>{
      let start=null;
      const point=(event)=>{const r=imageRect(canvas.dataset.role);if(!r)return null;return [Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))];};
      canvas.addEventListener('pointerdown',event=>{
        if(state.drawRole!==canvas.dataset.role||!state.current)return;
        const r=imageRect(canvas.dataset.role);if(!r||event.clientX<r.left||event.clientX>r.left+r.width||event.clientY<r.top||event.clientY>r.top+r.height)return;
        event.preventDefault();start=point(event);canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener('pointermove',event=>{if(!start)return;const p=point(event);if(!p)return;state.selections[canvas.dataset.role]=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];renderRegions();});
      const finish=()=>{if(!start)return;start=null;const box=state.selections[canvas.dataset.role];if(box&&(box[2]-box[0]<.005||box[3]-box[1]<.005))state.selections[canvas.dataset.role]=null;renderRegions();};
      canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);
    });
  }
  function focusEvidence(ref) {
    if(['c','candidate'].includes(String(ref).toLowerCase())&&state.current?.images?.candidate){state.active='verify';$('trace-panel').classList.add('hidden');render();requestAnimationFrame(()=>document.querySelector('.comparison')?.scrollIntoView({behavior:'smooth',block:'center'}));return;}
    const r=arr(state.current?.regions).find(region=>ref===region.id||String(ref).endsWith(`:${region.id}`)||String(ref).includes(`:${region.id}:`));
    state.focusRegion=r?.id||null;
    const lower=String(ref).toLowerCase();
    $('source-card').classList.toggle('highlighted',!!r||lower==='a'||lower.includes('source'));
    $('reference-card').classList.toggle('highlighted',!!r||lower==='b'||lower.includes('reference'));
    updateOverlays();
    $('photo-section').scrollIntoView({behavior:'smooth',block:'start'});
    if(!r&&!(lower==='a'||lower==='b'||lower.includes('source')||lower.includes('reference')))notify(`证据 ${ref} 已保留；当前没有对应的可视区域。`);
  }
  function openTarget(id) {
    const target=arr(state.current?.contract?.targets).find(t=>t.target_id===id);
    if(!target){notify(`目标 ${id} 尚无可追溯合同。`,true);return;}
    state.selectedTarget=id;
    const result=arr(state.current.verification?.target_results).find(r=>r.target_id===id);
    const profile=arr(state.current.analysis?.reference_profile).find(p=>p.attribute===target.attribute);
    const region=arr(state.current.regions).find(r=>r.id===target.source_region||r.id===target.reference_region||arr(target.evidence_refs).some(ref=>String(ref).includes(r.id)));
    state.focusRegion=region?.id||null;updateOverlays();
    $('trace-title').textContent=`${id} · ${label(target.attribute)}`;
    $('trace-content').innerHTML=`<div class="trace-node"><p class="eyebrow">01 / REFERENCE B</p><h3>B 的观察与依据</h3><p>${esc(target.reference_observation||profile?.observation||'未记录参考观察')}</p>${evidenceLinks(target.evidence_refs)}${region?`<canvas class="trace-crop" data-crop-role="reference" data-crop-region="${esc(region.id)}" width="640" height="300" aria-label="参考区域裁切"></canvas>`:''}</div><div class="trace-node"><p class="eyebrow">02 / SOURCE A</p><h3>应用到 A 的什么位置</h3><p>${esc(target.source_observation)}<br>${esc(text(target.source_region))}</p>${region?`<canvas class="trace-crop" data-crop-role="source" data-crop-region="${esc(region.id)}" width="640" height="300" aria-label="源图区域裁切"></canvas>`:''}</div><div class="trace-node"><p class="eyebrow">03 / EDIT TARGET</p><h3>${esc(target.desired_change)}</h3><p>完成标准：${esc(target.acceptance_criterion)}</p><span class="tag ${target.mandatory?'warn':''}">${target.mandatory?'必需目标':'可选目标'}</span>${target.uncertainty?`<p style="margin-top:8px">不确定性：${esc(target.uncertainty)}</p>`:''}</div><div class="trace-node"><p class="eyebrow">04 / ACTUAL PROMPT</p><h3>进入完整编辑指令</h3><p>${state.current.prompt?'查看主面板的实际编译提示；目标与保护项一同送入编辑器。':'尚未生成实际提示词。'}</p><button class="text-button" data-stage="compose">定位编辑提示 →</button></div><div class="trace-node"><p class="eyebrow">05 / VERIFICATION</p><h3>${result?label(result.status):'等待对候选验证'}</h3><p>${esc(result?.observation||'没有实际验证时不显示达成判断。')}</p>${result?tag(result.status):''}</div>`;
    $('trace-panel').classList.remove('hidden');
    $('trace-panel').querySelector('.close-trace').focus();
    document.querySelectorAll('.target-card').forEach(card=>card.classList.toggle('selected',card.dataset.target===id));
    drawTraceCrops();
  }
  function drawTraceCrops(){document.querySelectorAll('[data-crop-role]').forEach(canvas=>{const role=canvas.dataset.cropRole;const region=arr(state.current.regions).find(r=>r.id===canvas.dataset.cropRegion);const box=region?.[`${role}_box`];const img=$(`${role}-image`);if(!box||!img.complete||!img.naturalWidth)return;const ctx=canvas.getContext('2d');const sw=(box[2]-box[0])*img.naturalWidth,sh=(box[3]-box[1])*img.naturalHeight;const scale=Math.min(canvas.width/sw,canvas.height/sh);ctx.fillStyle='#0d1810';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,box[0]*img.naturalWidth,box[1]*img.naturalHeight,sw,sh,(canvas.width-sw*scale)/2,(canvas.height-sh*scale)/2,sw*scale,sh*scale);});}
  function bindComparison(){document.querySelectorAll('.comparison input').forEach(input=>input.addEventListener('input',()=>{const box=input.closest('.comparison');box.querySelector('.candidate-layer').style.clipPath=`inset(0 ${100-Number(input.value)}% 0 0)`;box.querySelector('.compare-line').style.left=`${input.value}%`;}));}
  function showInspect(){if(!state.current)return;$('inspect-content').innerHTML=['source','reference','candidate'].filter(role=>state.current.images?.[role]).map(role=>`<figure><figcaption>${esc(label(role))}</figcaption><img src="${esc(safeUrl(state.current.images[role].url))}" alt="放大检查 ${esc(label(role))}"></figure>`).join('');$('inspect-dialog').showModal();}
  function download(name,value,type='application/json'){const blob=new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type});const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function exportStage(stage){await task('正在导出真实阶段请求',async()=>{const data=await api(apiPath(`/export?stage=${encodeURIComponent(stage)}`));download(`${state.current.id}-${stage}-request.json`,data);notify(`已导出 ${label(stage)} 请求，包含真实输入角色与上下文。`);});}
  async function report(){if(!state.current)return;await task('正在导出完整案例记录',async()=>{const data=await api(apiPath('/report'));download(`${state.current.id}-report.json`,data);});}
  function fileData(file){return new Promise((resolve,reject)=>{if(!file)return reject(new Error('请选择图片文件'));const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('无法读取文件'));reader.readAsDataURL(file);});}

  document.addEventListener('click',async event=>{
    const button=event.target.closest('button');
    const target=event.target.closest('[data-target]');
    if(button?.dataset.stage){state.active=button.dataset.stage;render();return;}
    if(button?.dataset.evidence){focusEvidence(button.dataset.evidence);return;}
    if(button?.dataset.run){const stage=button.dataset.run;await task(`正在执行${label(stage)}`,async()=>{acceptCase(await post(apiPath('/step'),{stage}),{stage});await refreshCases();notify(`${label(stage)}状态已更新，请查看实际结果。`);});return;}
    if(button?.dataset.export){await exportStage(button.dataset.export);return;}
    if(button?.dataset.import){state.importStage=button.dataset.import;$('import-title').textContent=`导入${label(state.importStage)}的实际结果`;$('import-json').value='';$('import-json-file').value='';$('import-dialog').showModal();return;}
    if(button?.hasAttribute('data-copy-prompt')){try{await navigator.clipboard.writeText(state.current.prompt);notify('已复制系统编译的编辑提示词。');}catch{download(`${state.current.id}-prompt.txt`,state.current.prompt,'text/plain');}return;}
    if(button?.hasAttribute('data-candidate-import')){
      let resolve=$('pending-reconcile');
      if(!resolve){resolve=document.createElement('label');resolve.id='pending-reconcile';resolve.innerHTML='<input id="pending-confirm" type="checkbox"> 此图就是上一条结果未知请求的返回结果，关联原请求且不重复计数。';$('candidate-note').closest('label').after(resolve);}
      resolve.hidden=!state.current?.pending_image;$('pending-confirm').checked=false;
      $('candidate-model').placeholder='gpt-image-2 或其日期快照；无法确认时填写 unknown';
      $('candidate-prompt').value='';$('candidate-full-frame').checked=false;
      $('candidate-dialog').showModal();return;
    }
    if(button?.hasAttribute('data-region-open')){$('region-editor').classList.remove('hidden');$('region-description').focus();return;}
    if(button?.hasAttribute('data-inspect')){showInspect();return;}
    if(button?.hasAttribute('data-report')){await report();return;}
    if(button?.dataset.removeRegion){await task('正在保存区域对应',async()=>{acceptCase(await post(apiPath('/regions'),{regions:arr(state.current.regions).filter(r=>r.id!==button.dataset.removeRegion)}));});return;}
    if(button?.classList.contains('draw-toggle')){setDrawRole(button.dataset.role);return;}
    if(button?.classList.contains('dialog-close')){button.closest('dialog').close();return;}
    if(button?.classList.contains('close-trace')){$('trace-panel').classList.add('hidden');return;}
    if(target){openTarget(target.dataset.target);}
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape')$('trace-panel').classList.add('hidden');if((event.key==='Enter'||event.key===' ')&&event.target.matches('[data-target]')){event.preventDefault();openTarget(event.target.dataset.target);}});
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>dialog.querySelector('.dialog-error')?.remove()));
  $('new-case').addEventListener('click',()=>$('new-dialog').showModal());$('empty-new-case').addEventListener('click',()=>$('new-dialog').showModal());
  $('case-select').addEventListener('change',event=>loadCase(event.target.value));
  ['source','reference'].forEach(role=>{$(`${role}-file`).addEventListener('change',event=>{$(`${role}-file-name`).textContent=event.target.files[0]?.name||'PNG / JPEG / WebP';});$(`${role}-image`).addEventListener('load',()=>{updateOverlays();drawTraceCrops();});});
  $('new-form').addEventListener('submit',event=>{event.preventDefault();task('正在保存原始图像与案例',async()=>{const source=$('source-file').files[0],reference=$('reference-file').files[0];const [source_data,reference_data]=await Promise.all([fileData(source),fileData(reference)]);const data=await post('/api/cases',{source_data,reference_data,source_name:source.name,reference_name:reference.name,brief:$('brief').value.trim()});state.selections={source:null,reference:null};acceptCase(data,{stage:'inputs'});await refreshCases();$('new-dialog').close();notify('真实 A/B 已保存，可以逐步分析。');});});
  $('import-form').addEventListener('submit',event=>{event.preventDefault();task('正在校验并导入阶段观察',async()=>{let payload;try{payload=JSON.parse($('import-json').value);}catch{throw new Error('JSON 格式不正确，请检查括号与引号。');}if(payload.payload&&Object.keys(payload).length===1)payload=payload.payload;acceptCase(await post(apiPath('/import'),{stage:state.importStage,payload,provenance:$('import-provenance').value}),{stage:state.importStage});$('import-dialog').close();await refreshCases();notify('实际结果已导入；来源会显示在全过程记录中。');});});
  $('import-json-file').addEventListener('change',async event=>{const file=event.target.files[0];if(file)$('import-json').value=await file.text();});
  $('candidate-form').addEventListener('submit',event=>{event.preventDefault();task('正在导入实际编辑候选',async()=>{
    if(state.current?.pending_image&&!$('pending-confirm')?.checked)throw new Error('请先核对这是否为上一条未知请求的结果，避免重复计数。');
    const image_data=await fileData($('candidate-file').files[0]);
    acceptCase(await post(apiPath('/candidate'),{image_data,model:$('candidate-model').value.trim(),provenance:'manual_import',note:$('candidate-note').value.trim(),submitted_prompt:$('candidate-prompt').value.trim()||null,external_geometry:$('candidate-full-frame').checked?{policy:'full_frame_resize',source_frame_confirmed:true}:null,pending_attempt_id:state.current?.pending_image?.attempt_id||null}),{stage:'verify'});$('candidate-dialog').close();notify('已导入候选 C 并进入逐目标验证；实际型号、原生尺寸与本轮提示词已分别记录。');
  });});
  $('toggle-regions').addEventListener('click',()=>$('region-editor').classList.toggle('hidden'));
  $('clear-selection').addEventListener('click',()=>{state.selections={source:null,reference:null};renderRegions();});
  $('save-region').addEventListener('click',()=>task('正在保存独立区域对',async()=>{if(!state.selections.source||!state.selections.reference)throw new Error('请在 A 和 B 中分别框选区域；坐标不会自动复制。');const description=$('region-description').value.trim();if(!description)throw new Error('请填写区域的语义／材质说明。');const attributes=[...$('region-attributes').querySelectorAll('input:checked')].map(input=>input.value);if(!attributes.length)throw new Error('请至少选择一项待核查属性。');const regions=arr(state.current.regions).slice();let index=regions.length+1;while(regions.some(r=>r.id===`roi_${String(index).padStart(2,'0')}`))index++;regions.push({id:`roi_${String(index).padStart(2,'0')}`,description,source_box:state.selections.source,reference_box:state.selections.reference,comparability:$('region-comparability').value,attributes});acceptCase(await post(apiPath('/regions'),{regions}));state.selections={source:null,reference:null};state.drawRole=null;$('region-description').value='';renderRegions();setDrawRole(null);notify('已保存独立区域；重新测量可查看该区域的实际属性。');}));
  $('inspect-images').addEventListener('click',showInspect);
  $('inspect-content').addEventListener('click',event=>{if(event.target.tagName==='IMG')event.target.classList.toggle('zoomed');});
  $('download-report').addEventListener('click',report);
  window.addEventListener('resize',updateOverlays);
  setupDrawing();renderNav();
  (async()=>{try{state.config=await api('/api/config');$('provider-label').textContent=`${state.config.image_model||'gpt-image-2'} · 分析${state.config.analysis_configured?'已配置':'待配置／导入'} · 编辑${state.config.image_configured?'已配置':'待配置／导入'}`;await refreshCases();if(state.cases.length){const requested=new URLSearchParams(location.search).get('case');await loadCase(state.cases.some(c=>c.id===requested)?requested:state.cases[0].id);}else render();}catch(error){$('case-select').innerHTML='<option value="">服务未连接</option>';$('provider-label').textContent='本地服务未连接';notify(error.message,true);render();}})();
})();
