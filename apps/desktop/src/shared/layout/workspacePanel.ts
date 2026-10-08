import type {InjectionKey, Ref} from 'vue'

export interface PanelPresentation { visible:boolean; width:number; full:boolean }
export interface PanelGeometry { navigation:number; width:number; maxWidth:number; compact:boolean }
export function panelGeometry(viewport:number,preferred=420,full=false,focus=false,navigationWidth?:number):PanelGeometry {
  const compact=viewport<900
  const navigation=focus?0:navigationWidth??(viewport<1280?72:184)
  const available=Math.max(0,viewport-navigation)
  const maxWidth=full||compact?available:Math.max(280,Math.min(820,available-360))
  return {navigation,width:full||compact?available:Math.min(maxWidth,Math.max(280,preferred)),maxWidth,compact}
}
export interface WorkspacePanel {
  navigationVisible?:Readonly<Ref<boolean>>
  geometry:Readonly<Ref<PanelGeometry>>
  publish:(owner:symbol,state:PanelPresentation)=>void
  release:(owner:symbol)=>void
}
export const workspacePanelKey:InjectionKey<WorkspacePanel>=Symbol('workspace-panel')
