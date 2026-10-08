export const toolTabs = [{id:'exercises',label:'练习',icon:'✎'},{id:'notes',label:'笔记',icon:'≡'}] as const
export type ToolTab = typeof toolTabs[number]['id']
export interface DockState {open:ToolTab[]; panes:ToolTab[]; order:ToolTab[]; width:number; split:number; collapsed:boolean; full:boolean}
export const isTool = (value:unknown):value is ToolTab => toolTabs.some(t => t.id===value)
export function normalizeDock(value:Partial<DockState>={}):DockState {
 const unique=(items:unknown[]) => [...new Set(items.filter(isTool))]
 const order=unique([...(Array.isArray(value.order)?value.order:[]),...toolTabs.map(t=>t.id)])
 const open=unique(Array.isArray(value.open)?value.open:order)
 const panes=unique(Array.isArray(value.panes)?value.panes:open.slice(0,1)).filter(t=>open.includes(t)).slice(0,2)
 if (!panes.length && open.length) panes.push(open[0]!)
 return {order,open,panes,width:Math.min(820,Math.max(280,Number(value.width)||420)),split:Math.min(.8,Math.max(.2,Number(value.split)||.5)),collapsed:!open.length||(value.collapsed ?? true),full:!!value.full}
}
export function activateTool(state:DockState,tool:ToolTab,pane=0):DockState {
 const next=normalizeDock(state); if (!next.open.includes(tool)) next.open.push(tool)
 next.collapsed=false; const old=next.panes.indexOf(tool)
 if (old>=0) return next
 next.panes[Math.min(pane,Math.max(0,next.panes.length-1),1)]=tool; return normalizeDock(next)
}
export function closeTool(state:DockState,tool:ToolTab):DockState {
 return normalizeDock({...state,open:state.open.filter(t=>t!==tool),panes:state.panes.filter(t=>t!==tool)})
}
export function splitTools(state:DockState,tool:ToolTab,available:number):DockState {
 if (available<560 || state.panes.includes(tool)) return state
 const next=normalizeDock(state);if(!next.open.includes(tool))next.open.push(tool)
 next.panes=[...next.panes.slice(0,1),tool];next.collapsed=false;return normalizeDock(next)
}
export function reorderTools(state:DockState,from:ToolTab,to:ToolTab):DockState {
 const current=normalizeDock(state)
 if(from===to)return current
 const order=current.order.filter(t=>t!==from),target=order.indexOf(to)
 if(target<0)return current
 order.splice(target,0,from)
 return normalizeDock({...current,order})
}
