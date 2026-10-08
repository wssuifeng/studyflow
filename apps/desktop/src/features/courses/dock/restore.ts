import {normalizeDock,type DockState} from './state'
/** Layout preference is not permission to obscure a newly opened course. */
export function restoreDockLayout(stored:string|null):DockState {
 try {const value=stored?JSON.parse(stored):{};return normalizeDock({...value,collapsed:true,full:false})}
 catch {return normalizeDock()}
}
