Chart.register(ChartDataLabels);
 (function() {
 function parseVal(id) {
 const el = document.getElementById(id);
 if (!el) return 0;
 return parseFloat(el.textContent.replace(/[^\d.-]/g, '').replace(/\s/g, '')) || 0;
 }
 function safeLoadJson(id) {
 const el = document.getElementById(id);
 if (!el || !el.textContent.trim()) return null;
 try { return JSON.parse(el.textContent); } catch(e) { return null; }
 }

 const kcFmt = v => v.toLocaleString('cs-CZ') + ' Kč';
 const kcShrt = v => {
 if (Math.abs(v) >= 1000) return (v/1000).toFixed(1).replace('.', ',') + 'k Kč';
 return v.toLocaleString('cs-CZ') + ' Kč';
 };

 const monthlyData = safeLoadJson('monthly-data');
 const debtorsChartData = safeLoadJson('debtors-data');
 const trenerChartData = safeLoadJson('trener-data');
 const activityData = safeLoadJson('activity-data');
 const accData = safeLoadJson('accounting-monthly-data');
 const rawTrainings = safeLoadJson('kpi-trainings-count');
 const rawCharges = safeLoadJson('kpi-charges-count');
 const rawPayments = safeLoadJson('kpi-payments-count');

 // Průměry KPI
 try {
 const mH = parseVal('data-hours'), mT = rawTrainings||0;
 const el1 = document.getElementById('avg-hours-per-training-month');
 if (el1) el1.textContent = mT>0 ? (mH/mT).toFixed(2)+' h' : '0 h';
 const mC = parseVal('data-nauctovano'), mCn = rawCharges||0;
 const el2 = document.getElementById('avg-charge-month');
 if (el2) el2.textContent = mCn>0 ? Math.round(mC/mCn).toLocaleString('cs-CZ')+' Kč' : '0 Kč';
 const mP = parseVal('data-platby'), mPn = rawPayments||0;
 const el3 = document.getElementById('avg-payment-month');
 if (el3) el3.textContent = mPn>0 ? Math.round(mP/mPn).toLocaleString('cs-CZ')+' Kč' : '0 Kč';
 } catch(e) {}

 // Trend badges
 function setTrend(id, val) {
 const el = document.getElementById(id);
 if (!el) return;
 if (val > 0) { el.className='acc-trend up'; el.textContent='+ Kladný'; }
 else if (val < 0) { el.className='acc-trend down'; el.textContent='- Záporný'; }
 else { el.className='acc-trend neutral'; el.textContent='Nulový'; }
 }
 setTimeout(() => {
 setTrend('acc-cashflow-month-trend', parseVal('acc-cashflow-month'));
 setTrend('acc-gross-month-trend', parseVal('acc-gross-month'));
 }, 80);

 const C = { primary:'#3b82f6', success:'#22c55e', danger:'#ef4444',
 warning:'#f59e0b', info:'#06b6d4', purple:'#8b5cf6', orange:'#f97316' };

 /* ── Světlé osy pro chart-card grafy ── */
 const lightAxis = color => ({
 ticks: { color:'#6b7280', font:{size:11} },
 grid: { color:'#f3f4f6' }
 });

 /* ── Sdílená optická nastavení pro acc grafy ── */
 function accChartOptions(yCallback) {
 return {
 responsive: true, maintainAspectRatio: false,
 plugins: { legend:{ display:false }, datalabels:{ display:false } },
 scales: {
 x: { ticks:{ color:'#9ca3af', font:{size:11} }, grid:{ color:'#f3f4f6' } },
 y: { ticks:{ color:'#9ca3af', font:{size:10}, callback: yCallback },
 grid:{ color:'#f3f4f6' }, beginAtZero:true }
 }
 };
 }

 // 1. Bar – měsíc
 const c1 = document.getElementById('comparisonChart');
 if (c1) {
 const n=parseVal('data-nauctovano'), p=parseVal('data-platby'), u=Math.max(0,n-p);
 new Chart(c1, { type:'bar',
 data:{ labels:['Naúčtováno','Zaplaceno','Nezaplaceno'],
 datasets:[{data:[n,p,u], backgroundColor:[C.primary,C.success,C.danger], borderWidth:0, borderRadius:6}]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{ legend:{display:false}, datalabels:{anchor:'end',align:'top',formatter:kcFmt,font:{weight:'bold'}}},
 scales:{ y:{ beginAtZero:true, ticks:{callback:kcFmt}, ...lightAxis() }}}});
 }

 // 2. Bar – celkem
 const c2 = document.getElementById('comparisonChartTotal');
 if (c2) {
 const n=parseVal('data-total-nauctovano'), p=parseVal('data-total-platby'), u=Math.max(0,n-p);
 new Chart(c2, { type:'bar',
 data:{ labels:['Naúčtováno (Celkem)','Zaplaceno (Celkem)','Nezaplaceno'],
 datasets:[{data:[n,p,u], backgroundColor:[C.primary,C.success,C.danger], borderWidth:0, borderRadius:6}]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{ legend:{display:false}, datalabels:{anchor:'end',align:'top',formatter:kcFmt,font:{weight:'bold'}}},
 scales:{ y:{ beginAtZero:true, ticks:{callback:kcFmt}, ...lightAxis() }}}});
 }

 // 3. Bar+Line – 6M  (opraveno: viditelné hodiny na vlastní ose)
 const c3 = document.getElementById('financeChart');
 if (c3 && monthlyData?.length) {
 new Chart(c3, { type:'bar',
 data:{ labels: monthlyData.map(d=>d.label),
 datasets:[
 {label:'Hodiny', data:monthlyData.map(d=>d.hours), type:'line',
 borderColor:C.orange, backgroundColor:'rgba(249,115,22,0.12)',
 borderWidth:3, pointRadius:5, pointBackgroundColor:C.orange,
 fill:true, tension:0.3, yAxisID:'yHours', order:0, z:10},
 {label:'Naúčtováno', data:monthlyData.map(d=>d.charged), backgroundColor:C.primary+'cc', yAxisID:'yMoney', order:1, borderRadius:4},
 {label:'Zaplaceno', data:monthlyData.map(d=>d.paid), backgroundColor:C.success+'cc', yAxisID:'yMoney', order:2, borderRadius:4}
 ]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{
 legend:{position:'bottom', labels:{usePointStyle:true, pointStyleWidth:10}},
 datalabels:{display:false},
 tooltip:{callbacks:{label: ctx => {
 if(ctx.dataset.yAxisID==='yHours') return ' ' + ctx.parsed.y.toFixed(1) + ' h';
 return ' ' + ctx.parsed.y.toLocaleString('cs-CZ') + ' Kč';
 }}}
 },
 scales:{
 yMoney:{ type:'linear', position:'left', beginAtZero:true,
 ticks:{callback:v=>v>=1000?(v/1000).toFixed(0)+'k Kč':v+' Kč', color:'#6b7280', font:{size:11}},
 grid:{color:'#f3f4f6'} },
 yHours:{ type:'linear', position:'right', beginAtZero:true,
 ticks:{callback:v=>v+' h', color:C.orange, font:{size:11, weight:'600'}},
 grid:{drawOnChartArea:false},
 title:{display:true, text:'Hodiny', color:C.orange, font:{size:11}} }
 }}});
 }

 // 4. Line – 7 dní
 const c4 = document.getElementById('activityChart');
 if (c4 && activityData?.length) {
 new Chart(c4, { type:'line',
 data:{ labels: activityData.map(d=>d.day_name),
 datasets:[
 {label:'Hodiny', data:activityData.map(d=>d.hours), borderColor:C.orange, backgroundColor:C.orange+'20', fill:true, tension:0.4, yAxisID:'yHours'},
 {label:'Naúčtováno', data:activityData.map(d=>d.charged), borderColor:C.primary, backgroundColor:C.primary+'20', fill:true, tension:0.4, yAxisID:'yMoney'},
 {label:'Zaplaceno', data:activityData.map(d=>d.paid), borderColor:C.success, backgroundColor:C.success+'20', fill:true, tension:0.4, yAxisID:'yMoney'}
 ]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{ legend:{position:'bottom'}, datalabels:{display:false}},
 scales:{
 yMoney:{ position:'left', beginAtZero:true, ...lightAxis() },
 yHours:{ position:'right', beginAtZero:true, grid:{display:false} }}}});
 }

 /* ─── Účetní grafy (světlá verze) ─── */

 /* Formátuj součet do badgu – pokud záporný, přidej třídu negative */
 function setSumBadge(id, value, positiveClass) {
 const el = document.getElementById(id);
 if (!el) return;
 const fmt = Math.round(value).toLocaleString('cs-CZ') + ' Kč';
 el.textContent = (value >= 0 ? '∑ ' : '∑ −') + (value >= 0 ? fmt : Math.round(Math.abs(value)).toLocaleString('cs-CZ') + ' Kč');
 if (value < 0) {
 el.className = 'acc-sum-badge negative';
 } else {
 el.className = 'acc-sum-badge ' + positiveClass;
 }
 }

 function barChart(canvasId, labels, data, colorFn, yFmt) {
 const ctx = document.getElementById(canvasId);
 if (!ctx || !labels?.length) return;
 new Chart(ctx, { type:'bar',
 data:{ labels, datasets:[{ data, backgroundColor: data.map(colorFn), borderRadius:6, borderWidth:0 }]},
 options: accChartOptions(yFmt) });
 }

 const tealPos = v => v >= 0 ? 'rgba(20,184,166,0.75)' : 'rgba(244,63,94,0.75)';
 const emerPos = v => v >= 0 ? 'rgba(16,185,129,0.75)' : 'rgba(244,63,94,0.75)';
 const limePos = v => v >= 0 ? 'rgba(132,204,22,0.75)' : 'rgba(244,63,94,0.75)';
 const amberClr = () => 'rgba(245,158,11,0.75)';

 if (accData?.length) {
 const labels = accData.map(d => d.label);

 // Cash flow = paid - trener_paid (cash basis)
 const cfVals = accData.map(d => d.cashflow || ((d.paid||0) - (d.trener_paid||0)));
 
 // Hrubý zisk = charged - trener_earned (accrual basis)
 const gpVals = accData.map(d => d.gross_profit);
 
 // Čistý zisk = paid - trener_paid (cash basis) - stejné jako cash flow
 // Použijeme net_profit pokud existuje, jinak počítáme z paid - trener_paid
 const npVals = accData.map(d => d.net_profit !== undefined ? d.net_profit : ((d.paid||0) - (d.trener_paid||0)));
 
 const tpVals = accData.map(d => d.trener_paid||0);

 const sum = arr => arr.reduce((a, b) => a + b, 0);

 // Zapsat součty do badgů
 setSumBadge('sum-cashflow', sum(cfVals), 'teal');
 setSumBadge('sum-gross', sum(gpVals), 'emerald');
 setSumBadge('sum-net', sum(npVals), 'lime');
 setSumBadge('sum-trener', sum(tpVals), 'amber');

 // Vykreslit grafy
 barChart('accCashflowChart', labels, cfVals, tealPos, v => kcShrt(v));
 barChart('accGrossChart', labels, gpVals, emerPos, v => kcShrt(v));
 barChart('accNetProfitChart', labels, npVals, limePos, v => kcShrt(v));
 barChart('accTrenerPaidChart',labels, tpVals, amberClr, v => kcShrt(v));
 }

 // 6. Doughnut – rovnováha
 const c6 = document.getElementById('balanceChart');
 if (c6) {
 const d=Math.abs(parseVal('data-dluhy')), p=parseVal('data-prebytky');
 if (d>0||p>0) new Chart(c6, { type:'doughnut',
 data:{ labels:['Dluhy','Přebytky'], datasets:[{data:[d,p], backgroundColor:[C.danger,C.success]}]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{ legend:{position:'bottom'},
 datalabels:{ color:'#fff', font:{weight:'bold'},
 formatter:(v,ctx)=>{ let s=ctx.dataset.data.reduce((a,b)=>a+b,0); return Math.round((v/s)*100)+'%'; }}}}});
 }

 // 7. Pie – dlužníci
 const c7 = document.getElementById('debtorsChart');
 if (c7 && debtorsChartData?.labels?.length) {
 new Chart(c7, { type:'pie',
 data:{ labels:debtorsChartData.labels,
 datasets:[{data:debtorsChartData.values, backgroundColor:[C.danger,C.warning,C.orange,C.purple,C.info]}]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{ legend:{position:'bottom',labels:{boxWidth:12}},
 datalabels:{ color:'#fff', font:{weight:'bold'},
 formatter:(v,ctx)=>{ let s=ctx.dataset.data.reduce((a,b)=>a+b,0); let r=Math.round((v/s)*100); return r>5?r+'%':''; }}}}});
 }

 // 8. Pie – trenéři
 const c8 = document.getElementById('trenerChart');
 if (c8 && trenerChartData?.labels?.length) {
 new Chart(c8, { type:'pie',
 data:{ labels:trenerChartData.labels,
 datasets:[{data:trenerChartData.values, backgroundColor:[C.success,C.info,C.primary,C.purple,C.orange]}]},
 options:{ responsive:true, maintainAspectRatio:false,
 plugins:{ legend:{position:'bottom',labels:{boxWidth:12}},
 datalabels:{ color:'#fff', font:{weight:'bold'},
 formatter:(v,ctx)=>{ let s=ctx.dataset.data.reduce((a,b)=>a+b,0); let r=Math.round((v/s)*100); return r>5?r+'%':''; }}}}});
 }

 })();
