"""Safe public database errors; never expose SQL or bound answers."""
from __future__ import annotations
from sqlalchemy.exc import SQLAlchemyError, IntegrityError


def database_error_payload(error):
    original=getattr(error,"orig",error)
    code=getattr(original,"sqlite_errorcode",None)
    base=code & 255 if isinstance(code,int) else None
    if base == 13 or isinstance(error, OSError) and (error.errno == 28 or getattr(error, "winerror", None) in {39, 112}):
        return {"code": "DATABASE_DISK_FULL" if isinstance(error, SQLAlchemyError) else "WORKSPACE_DISK_FULL", "message": "工作区所在磁盘空间不足，本次保存未完成。", "next_action": "保留当前输入并检查磁盘剩余空间；释放空间后可用原幂等键重试。也可确认不保存退出，不必强制结束进程。"}
    readonly=base==8 or "readonly" in str(original).lower() or "read-only" in str(original).lower()
    if isinstance(error,PermissionError) or readonly:
        return {"code":"DATABASE_READ_ONLY" if isinstance(error,SQLAlchemyError) else "WORKSPACE_READ_ONLY","message":"当前运行进程没有工作区或数据库写权限。","next_action":"运行doctor检查可写性与解释器身份；保持当前工作区，不提权、改ACL或绕过活动沙箱。"}
    if isinstance(error,SQLAlchemyError):
        if base in {5,6}:
            return {"code":"DATABASE_LOCKED","message":"数据库暂时被其他操作占用，本次写入未完成。","next_action":"保留输入，稍后用原幂等键重试；不要删除锁文件或数据库。"}
        if isinstance(error,IntegrityError):
            return {"code":"DATABASE_CONSTRAINT_ERROR","message":"数据库约束阻止了本次写入，事务已回滚。","next_action":"输入已保留，查看诊断编号；修复后以原幂等键重试，勿清空答案。"}
        return {"code":"DATABASE_ERROR","message":"数据库操作失败，当前请求未完成。","next_action":"运行doctor检查数据库；保留输入并使用原幂等键重试。"}
    return None
