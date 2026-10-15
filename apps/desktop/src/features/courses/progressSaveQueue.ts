/** Every waiter joins the lane before awaiting it; versions are read when its task starts. */
export function createProgressSaveQueue(){
 let tail:Promise<unknown>=Promise.resolve()
 return <T>(task:()=>Promise<T>):Promise<T>=>{
  const result=tail.then(task,task)
  tail=result.then(()=>undefined,()=>undefined)
  return result
 }
}
