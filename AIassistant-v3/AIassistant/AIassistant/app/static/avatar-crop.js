/* Local-only crop preview: no upload occurs until the user confirms the selection. */
(() => {
  const modal=document.createElement('div');modal.id='modal-avatar-crop';modal.className='modal hidden';
  modal.innerHTML=`<div class="modal-card crop-card" role="dialog" aria-modal="true" aria-labelledby="crop-title">
    <h3 id="crop-title">裁剪头像</h3><p class="muted small">拖动图片选取区域，使用滑块放大。圆圈内是头像显示范围。</p>
    <canvas id="crop-preview" width="320" height="320" tabindex="0" aria-label="头像裁剪预览，可用方向键移动图片"></canvas>
    <label class="crop-zoom">缩放 <input id="crop-zoom" type="range" min="1" max="4" step="0.01" value="1" /><output id="crop-value">100%</output></label>
    <p class="muted small">也可聚焦预览后使用方向键移动图片</p>
    <div class="modal-actions"><button id="crop-reset" class="btn">居中重置</button><button id="crop-cancel" class="btn">取消</button><button id="crop-save" class="btn primary">使用选中区域</button></div>
  </div>`;
  document.body.appendChild(modal);
  const canvas=modal.querySelector('canvas'),ctx=canvas.getContext('2d'),zoom=modal.querySelector('#crop-zoom');
  let img=null,base=1,scale=1,x=0,y=0,drag=null,resolve=null,previousFocus=null;
  function clamp(){x=Math.min(0,Math.max(320-img.naturalWidth*scale,x));y=Math.min(0,Math.max(320-img.naturalHeight*scale,y));}
  function draw(){
    if(!img)return;clamp();ctx.clearRect(0,0,320,320);ctx.fillStyle='#fff';ctx.fillRect(0,0,320,320);
    ctx.drawImage(img,x,y,img.naturalWidth*scale,img.naturalHeight*scale);
    ctx.fillStyle='rgba(16,37,65,.38)';ctx.beginPath();ctx.rect(0,0,320,320);ctx.arc(160,160,158,0,Math.PI*2);ctx.fill('evenodd');
    ctx.strokeStyle='rgba(255,255,255,.95)';ctx.lineWidth=2;ctx.beginPath();ctx.arc(160,160,158,0,Math.PI*2);ctx.stroke();
  }
  function reset(){zoom.value='1';scale=base;x=(320-img.naturalWidth*scale)/2;y=(320-img.naturalHeight*scale)/2;modal.querySelector('output').textContent='100%';draw();}
  function finish(blob){const done=resolve;resolve=null;img=null;drag=null;modal.classList.add('hidden');previousFocus?.focus();if(done)done(blob);}
  window.chooseAvatarCrop=async file=>{
    const image=await loadImage(file);
    if(!image.naturalWidth||!image.naturalHeight)throw new Error('无法读取图片尺寸');
    if(image.naturalWidth*image.naturalHeight>80000000)throw new Error('图片尺寸过大，请先缩小图片');
    if(resolve)finish(null);
    img=image;base=Math.max(320/image.naturalWidth,320/image.naturalHeight);
    previousFocus=document.activeElement;modal.classList.remove('hidden');reset();canvas.focus();
    return new Promise(done=>{resolve=done;});
  };
  canvas.addEventListener('pointerdown',e=>{if(!img)return;drag={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const ratio=320/canvas.getBoundingClientRect().width;
    x+=(e.clientX-drag.x)*ratio;y+=(e.clientY-drag.y)*ratio;drag.x=e.clientX;drag.y=e.clientY;draw();});
  canvas.addEventListener('pointerup',()=>{drag=null;});canvas.addEventListener('pointercancel',()=>{drag=null;});
  canvas.addEventListener('keydown',e=>{if(!img)return;const step=e.shiftKey?12:3;
    const dirs={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]};
    if(dirs[e.key]){e.preventDefault();x+=dirs[e.key][0];y+=dirs[e.key][1];draw();}});
  zoom.addEventListener('input',()=>{if(!img)return;const next=base*Number(zoom.value),ratio=next/scale;
    x=160-(160-x)*ratio;y=160-(160-y)*ratio;scale=next;modal.querySelector('output').textContent=Math.round(Number(zoom.value)*100)+'%';draw();});
  modal.querySelector('#crop-reset').onclick=()=>{if(img)reset();};
  modal.querySelector('#crop-cancel').onclick=()=>finish(null);
  modal.addEventListener('click',e=>{if(e.target===modal)finish(null);});
  modal.addEventListener('keydown',e=>{
    if(e.key==='Escape'){e.preventDefault();finish(null);}
    if(e.key==='Tab'){
      const focusable=[...modal.querySelectorAll('button,input,canvas')];
      const first=focusable[0],last=focusable.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
  });
  modal.querySelector('#crop-save').onclick=()=>{
    if(!img)return;
    const output=document.createElement('canvas');output.width=512;output.height=512;
    const out=output.getContext('2d');out.fillStyle='#fff';out.fillRect(0,0,512,512);
    out.drawImage(img,-x/scale,-y/scale,320/scale,320/scale,0,0,512,512);
    output.toBlob(blob=>{if(blob)finish(blob);},'image/png');
  };
})();
