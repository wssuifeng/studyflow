

export type DocumentReadData = {
  protocol_version: string
  path: string
  status: 'PRESENT'
  markdown: string
  html: string
  file_size: number
  modified_at: string | null
  content_hash: string
}
