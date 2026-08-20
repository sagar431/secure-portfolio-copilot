import { useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import { getBackendHealth } from '../api/health'

type HealthState =
  | { status: 'loading' }
  | { status: 'online'; requestId: string }
  | { status: 'offline'; message: string; requestId: string | null }

export function BackendHealth() {
  const [state, setState] = useState<HealthState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()

    void getBackendHealth(controller.signal)
      .then((response) => {
        setState({ status: 'online', requestId: response.request_id })
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        if (error instanceof ApiError) {
          setState({
            status: 'offline',
            message: error.message,
            requestId: error.requestId,
          })
          return
        }
        setState({
          status: 'offline',
          message: 'Unexpected health-check failure.',
          requestId: null,
        })
      })

    return () => controller.abort()
  }, [])

  if (state.status === 'loading') {
    return <p role="status">Checking backend…</p>
  }

  if (state.status === 'offline') {
    return (
      <div className="health-card health-card--offline" role="alert">
        <strong>Backend unavailable</strong>
        <span>{state.message}</span>
        {state.requestId ? <small>Request ID: {state.requestId}</small> : null}
      </div>
    )
  }

  return (
    <div className="health-card health-card--online" role="status">
      <strong>Backend online</strong>
      <span>The API process is healthy.</span>
      <small>Request ID: {state.requestId}</small>
    </div>
  )
}
