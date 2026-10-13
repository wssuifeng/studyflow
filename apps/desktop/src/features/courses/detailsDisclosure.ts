export function detailsPreferenceKey(scope:string,lessonId:string,blockId:string){return 'studyflow:details:'+JSON.stringify([scope,lessonId,blockId])}
export function readDetailsPreference(storage:Pick<Storage,'getItem'>|null,key:string){try{return storage?.getItem(key)==='open'}catch{return false}}
export function saveDetailsPreference(storage:Pick<Storage,'setItem'>|null,key:string,open:boolean){try{storage?.setItem(key,open?'open':'closed')}catch{/* Presentation preferences never block reading. */}}
export function revealTeachingTarget(node:HTMLElement|null,wholeBlock=false){
 if(!node)return
 for(let parent:HTMLElement|null=node;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')(parent as HTMLDetailsElement).open=true}
 if(wholeBlock)node.querySelectorAll<HTMLDetailsElement>('details').forEach(details=>details.open=true)
}
