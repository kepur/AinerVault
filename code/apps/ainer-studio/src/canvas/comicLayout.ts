import type {CNode,CEdge} from './model';

/** Arrange references and production steps without changing recipes or links. */
export function comicLayout(nodes:CNode[]):Map<string,{x:number;y:number}> {
  const steps=['story','material','blocking','dialogue','frame','video','tail','assemble'];
  const width=(n:CNode)=>Math.max(300,n.measured?.width||n.width||360);
  const height=(n:CNode)=>Math.max(120,n.measured?.height||n.height||(n.type==='text'?360:300))+34;
  const movable=nodes.filter(n=>!n.parentId&&!n.data.pinned),occupied=nodes.filter(n=>!n.parentId&&n.data.pinned).map(n=>({x:n.position.x,y:n.position.y,w:width(n),h:height(n)}));
  const result=new Map<string,{x:number;y:number}>(),cols=new Map<string,number>();let x=0;
  for(const step of steps){cols.set(step,x);x+=Math.max(360,...nodes.filter(n=>n.data.comic?.step===step).map(width))+100;}
  const segmentIds=[...new Set(nodes.filter(n=>['blocking','dialogue','frame','video'].includes(n.data.comic?.step||'')).map(n=>n.data.comic!.source_id))];
  const rowHeight=Math.max(420,...nodes.filter(n=>['blocking','dialogue','frame','video','tail'].includes(n.data.comic?.step||'')).map(height))+100;
  const stacks=new Map<string,number>();
  for(const n of movable){
    const step=n.data.comic?.step||'extra',idx=segmentIds.indexOf(n.data.comic?.source_id||'');
    const px=cols.get(step)??x;let py=idx>=0&&!['material','story','assemble'].includes(step)?80+idx*rowHeight:stacks.get(step)||80;
    let collisions;
    do{collisions=occupied.filter(r=>px<r.x+r.w+50&&px+width(n)+50>r.x&&py<r.y+r.h+60&&py+height(n)+60>r.y);if(collisions.length)py=Math.max(...collisions.map(r=>r.y+r.h+80));}while(collisions.length);
    result.set(n.id,{x:px,y:py});occupied.push({x:px,y:py,w:width(n),h:height(n)});stacks.set(step,py+height(n)+80);
  }
  return result;
}

export function freeGraphLayout(nodes:CNode[],edges:CEdge[]) {
  const movable=nodes.filter(n=>!n.parentId&&!n.data.pinned),ids=new Set(movable.map(n=>n.id)),ranks=new Map(movable.map(n=>[n.id,0]));
  const incoming=new Map(movable.map(n=>[n.id,edges.filter(e=>e.target===n.id&&ids.has(e.source))]));
  const done=new Set<string>();
  for(let pass=0;pass<=movable.length;pass++){
    const ready=movable.filter(n=>!done.has(n.id)&&incoming.get(n.id)!.every(e=>done.has(e.source)));
    if(!ready.length)break;
    for(const n of ready){ranks.set(n.id,Math.max(0,...incoming.get(n.id)!.map(e=>(ranks.get(e.source)||0)+1)));done.add(n.id);}
  }
  const max=Math.max(0,...ranks.values());let extra=max+1;
  for(const n of movable)if(!done.has(n.id))ranks.set(n.id,extra++);
  const result=new Map<string,{x:number;y:number}>(),widths=new Map<number,number>();
  for(const n of movable){const rank=ranks.get(n.id)!;widths.set(rank,Math.max(widths.get(rank)||360,n.measured?.width||n.width||360));}
  const xs=new Map<number,number>();let x=0;for(const rank of [...widths.keys()].sort((a,b)=>a-b)){xs.set(rank,x);x+=widths.get(rank)!+120;}
  const bottoms=new Map<number,number>();
  for(const n of movable){const rank=ranks.get(n.id)!,px=xs.get(rank)!;let y=bottoms.get(rank)||80;
    const h=(n.measured?.height||n.height||360)+50,w=n.measured?.width||n.width||360;
    for(const pin of nodes.filter(p=>p.data.pinned&&!p.parentId))if(px<pin.position.x+(pin.measured?.width||pin.width||360)+60&&px+w+60>pin.position.x&&y<pin.position.y+(pin.measured?.height||pin.height||360)+60&&y+h+60>pin.position.y)y=pin.position.y+(pin.measured?.height||pin.height||360)+120;
    result.set(n.id,{x:px,y});bottoms.set(rank,y+h+80);
  }
  return result;
}
