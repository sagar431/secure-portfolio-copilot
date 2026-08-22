import {
  apiUrl,
  isErrorEnvelope,
  isSuccessEnvelope,
  requestJson,
} from './client'
import { ApiError } from './client'
import type {
  EvaluationRunDetail,
  EvaluationRunList,
} from '../types/evaluations'

export function listEvaluations(token: string, signal?: AbortSignal) {
  return requestJson<EvaluationRunList>('/api/admin/evaluations', {
    token,
    signal,
  })
}

export function getEvaluation(
  token: string,
  runId: string,
  signal?: AbortSignal,
) {
  return requestJson<EvaluationRunDetail>(
    `/api/admin/evaluations/${encodeURIComponent(runId)}`,
    { token, signal },
  )
}

export function runEvaluation(token: string, enableAdvisoryJudge: boolean) {
  return requestJson<EvaluationRunDetail>('/api/admin/evaluations/run', {
    method: 'POST',
    token,
    body: {
      suite_version: '1.0.0',
      enable_advisory_judge: enableAdvisoryJudge,
      max_judged_cases: enableAdvisoryJudge ? 2 : 0,
    },
  })
}

export async function downloadEvaluationReport(token: string, runId: string) {
  const response = await fetch(
    apiUrl(`/api/admin/evaluations/${encodeURIComponent(runId)}/report`),
    { headers: { Authorization: `Bearer ${token}` } },
  )
  if (!response.ok) {
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    if (isErrorEnvelope(payload)) {
      throw new ApiError(
        payload.error.message,
        response.status,
        payload.error.code,
        payload.request_id,
      )
    }
    throw new ApiError(
      'Evaluation report could not be downloaded.',
      response.status,
      'report_download_failed',
      null,
    )
  }
  const payload: unknown = await response.json()
  if (
    !isSuccessEnvelope<EvaluationRunDetail>({
      data: payload,
      request_id: 'download',
    })
  ) {
    throw new ApiError(
      'Evaluation report was invalid.',
      response.status,
      'invalid_response',
      null,
    )
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `evaluation-${runId}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}
