/**
 * Local (ki66) patch for the SSH dashboard-ownership probe, kept out of the
 * upstream-owned remote-lifecycle.ts.
 *
 * Upstream reads the remote argv from /proc and, where /proc is missing
 * (macOS), falls back to `ps` + shlex.split — which cannot tell an argument
 * containing spaces or quotes from several arguments. On darwin this patch
 * reads the exact argv with sysctl(KERN_PROCARGS2) instead and treats every
 * read failure as FOREIGN.
 *
 * The upstream script text stays untouched in remote-lifecycle.ts; this
 * rewrites the argv-read block of the finished script. If upstream reshapes
 * that block so the anchors no longer match, the script is returned unchanged
 * (plain upstream behaviour) and remote-lifecycle.ki66.test.ts fails.
 */

// From the upstream `try:` that opens /proc/<pid>/cmdline up to (not including) `ok=False`.
const UPSTREAM_ARGV_READ_RE = /try:\n raw=open\(f"\/proc\/\{pid\}\/cmdline","rb"\)\.read\(\)\n[\s\S]*?\n(?=ok=False\n)/

const UPSTREAM_IMPORTS = 'import os,shlex,subprocess,sys\n'

const KI66_ARGV_READ =
  'try:\n' +
  ' if sys.platform=="darwin":\n' +
  '  import ctypes\n' +
  '  libc=ctypes.CDLL(None,use_errno=True)\n' +
  '  libc.sysctl.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p,ctypes.c_size_t]\n' +
  '  mib=(ctypes.c_int*3)(1,49,pid)\n' +
  '  size=ctypes.c_size_t()\n' +
  '  if libc.sysctl(mib,3,None,ctypes.byref(size),None,0):raise OSError(ctypes.get_errno(),"sysctl size")\n' +
  '  if not 4<size.value<=1048576:raise ValueError("invalid argv size")\n' +
  '  buf=ctypes.create_string_buffer(size.value)\n' +
  '  if libc.sysctl(mib,3,buf,ctypes.byref(size),None,0):raise OSError(ctypes.get_errno(),"sysctl argv")\n' +
  '  raw=buf.raw[:size.value]\n' +
  '  argc=int.from_bytes(raw[:4],sys.byteorder)\n' +
  '  pos=raw.find(b"\\0",4)+1\n' +
  '  if pos==0:raise ValueError("missing executable")\n' +
  '  while pos<len(raw) and raw[pos]==0:pos+=1\n' +
  '  args=[]\n' +
  '  for _ in range(argc):\n' +
  '   end=raw.find(b"\\0",pos)\n' +
  '   if end<0:raise ValueError("truncated argv")\n' +
  '   args.append(raw[pos:end].decode("utf-8","surrogateescape"));pos=end+1\n' +
  ' else:\n' +
  '  raw=open(f"/proc/{pid}/cmdline","rb").read()\n' +
  '  args=[x.decode("utf-8","surrogateescape") for x in raw.split(b"\\0") if x]\n' +
  'except (OSError,ValueError):\n' +
  ' print("FOREIGN");sys.exit(0)\n'

/** Swap the upstream argv-read block of the ownership probe for the darwin-exact one. */
export function withDarwinArgvProbe(script: string): string {
  if (!UPSTREAM_ARGV_READ_RE.test(script)) {
    return script
  }

  const patched = script.replace(UPSTREAM_ARGV_READ_RE, () => KI66_ARGV_READ)

  // shlex/subprocess served only the replaced `ps` fallback.
  return patched.startsWith(UPSTREAM_IMPORTS) ? `import os,sys\n${patched.slice(UPSTREAM_IMPORTS.length)}` : patched
}
