import { useRef, useState } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { errorMessage } from '../api/client'
import { useUploadProjectFiles } from '../api/projects'

// webkitRelativePath is set when a directory is picked; fall back to the bare name for single files.
function relPath(f: File): string {
  // webkitRelativePath is set when a folder is picked; fall back to bare name for single files
  return (f.webkitRelativePath && f.webkitRelativePath.length > 0) ? f.webkitRelativePath : f.name
}

export function UploadDropzone({ projectId }: { projectId: string }) {
  const folderInput = useRef<HTMLInputElement | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const upload = useUploadProjectFiles(projectId)

  async function send(fileList: FileList | null) {
    setError(null); setDone(null)
    if (!fileList || fileList.length === 0) return
    const files = Array.from(fileList)
    try {
      const res = await upload.mutateAsync({ files, paths: files.map(relPath) })
      setDone(res.uploaded)
    } catch (e) { setError(errorMessage(e)) }
  }

  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="card row gap2"
        style={{ padding: 14, alignItems: 'center', borderStyle: 'dashed', cursor: 'pointer' }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); void send(e.dataTransfer.files) }}>
        <Glyph name="upload" size={16} style={{ color: 'var(--accent)' }} />
        <span style={{ fontSize: 13, flexGrow: 1 }}>
          {upload.isPending ? 'Uploading…' : 'Drop files here, or:'}
        </span>
        <button className="btn btn-ghost sm" type="button" onClick={() => fileInput.current?.click()}>
          Files
        </button>
        <button className="btn btn-ghost sm" type="button" onClick={() => folderInput.current?.click()}>
          Folder
        </button>
        {/* Plain multi-file picker */}
        <input ref={fileInput} type="file" multiple style={{ display: 'none' }}
          onChange={(e) => void send(e.target.files)} />
        {/* Folder picker — webkitdirectory is non-standard but widely supported */}
        {/* @ts-expect-error webkitdirectory is non-standard */}
        <input ref={folderInput} type="file" multiple webkitdirectory="" style={{ display: 'none' }}
          onChange={(e) => void send(e.target.files)} />
      </div>
      {done != null && <div className="muted" style={{ fontSize: 12 }}>Uploaded {done} file(s).</div>}
      {error && <div style={{ fontSize: 12, color: 'var(--unreachable)' }}>{error}</div>}
    </div>
  )
}
