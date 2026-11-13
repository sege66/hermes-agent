// ki66 (local-only) helper for use-route-resume.ts.
//
// Upstream seeds `bootResumeRef` with `true`: the first resume a window
// dispatches is treated as the cold-start re-attachment and does not home
// focus/tabs. Locally only an initial routed/hash session is a cold-start
// re-attachment — a window that boots on new chat may navigate later, and its
// first resume must home focus/tabs like any other navigation. Rather than
// editing the upstream `useRef(true)` line, the seed is overridden once,
// during the first render, before any effect can read the ref.
import { type MutableRefObject, useState } from 'react'

export function useInitialRefValue<T>(ref: MutableRefObject<T>, initial: T): void {
  useState(() => {
    ref.current = initial
  })
}
