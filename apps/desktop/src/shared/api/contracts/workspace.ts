

export type DoctorData = { healthy: boolean; workspace: { root: string; exists: boolean; writable: boolean }; database: { driver: string; status: string; managed_by_app: boolean; reachable: boolean }; next_action: string }
