// Decorative flow field with nearest-neighbour connections and pointer ripples.
(()=>{let frame=0,cleanup=()=>{};window.startParticles=(host,subtle=false)=>{
 cleanup();cancelAnimationFrame(frame);if(!host||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 const canvas=document.createElement('canvas');canvas.className='flow-canvas';canvas.setAttribute('aria-hidden','true');host.prepend(canvas);
 const ctx=canvas.getContext('2d');let w=0,h=0,last=0,step=0;const points=Array.from({length:subtle?30:90},()=>({x:Math.random(),y:Math.random(),phase:Math.random()*6.28,r:Math.random()*1.4+.7})),ripples=[];
 const resize=()=>{w=host.clientWidth;h=host.clientHeight;const dpr=Math.min(devicePixelRatio||1,2);canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);};resize();
 const observer=new ResizeObserver(resize);observer.observe(host);
 const move=e=>{if(performance.now()-last<95)return;last=performance.now();const r=host.getBoundingClientRect();ripples.push({x:e.clientX-r.left,y:e.clientY-r.top,t:0});if(ripples.length>12)ripples.shift();};host.addEventListener('pointermove',move);
 function draw(t){if(!canvas.isConnected)return;const delta=Math.min((t-step)||16,40);step=t;ctx.clearRect(0,0,w,h);const time=t*.00015;
  for(const p of points){p.x+=(Math.cos(p.y*7+time+p.phase)*.000018)*delta;p.y+=(Math.sin(p.x*6-time+p.phase)*.000012)*delta;if(p.x<0)p.x=1;if(p.x>1)p.x=0;if(p.y<0)p.y=1;if(p.y>1)p.y=0;ctx.beginPath();ctx.arc(p.x*w,p.y*h,p.r,0,Math.PI*2);ctx.fillStyle=`rgba(105,139,79,${subtle?.16:.3})`;ctx.fill();}
  const used=new Set();for(let i=0;i<points.length;i++){if(used.has(i))continue;let nearest=-1,best=110;for(let j=i+1;j<points.length;j++){if(used.has(j))continue;const d=Math.hypot((points[i].x-points[j].x)*w,(points[i].y-points[j].y)*h);if(d<best){best=d;nearest=j;}}if(nearest>=0){used.add(i);used.add(nearest);const glow=Math.max(0,Math.sin(time*2+points[i].phase));ctx.strokeStyle=`rgba(110,144,85,${(1-best/110)*glow*(subtle?.12:.22)})`;ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(points[i].x*w,points[i].y*h);ctx.lineTo(points[nearest].x*w,points[nearest].y*h);ctx.stroke();}}
  for(let i=ripples.length-1;i>=0;i--){const r=ripples[i];r.t+=delta;if(r.t>1400){ripples.splice(i,1);continue;}ctx.strokeStyle=`rgba(124,157,98,${(1-r.t/1400)*(subtle?.12:.3)})`;ctx.lineWidth=.8;ctx.beginPath();ctx.arc(r.x,r.y,12+r.t*.06,0,Math.PI*2);ctx.stroke();}frame=requestAnimationFrame(draw);
 }frame=requestAnimationFrame(draw);cleanup=()=>{observer.disconnect();host.removeEventListener('pointermove',move);canvas.remove();};
};})();
