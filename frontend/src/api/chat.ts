import type { ApiSuccessEnvelope } from '../types/api'
import type {
  ConversationCreateData,
  ConversationData,
  ConversationListData,
  CreateConversationRequest,
  GroundedAnswerData,
  GroundedCitationData,
  GroundedClaimData,
  SendConversationMessageRequest,
} from '../types/chat'
import {
  CHAT_ANSWER_MAX_LENGTH,
  CHAT_CLAIM_MAX_LENGTH,
  CHAT_EXCERPT_MAX_LENGTH,
  CHAT_LIMITATION_MAX_LENGTH,
  CHAT_QUESTION_MAX_LENGTH,
  CHAT_TITLE_MAX_LENGTH,
} from '../types/chat'
import { ApiError, isRecord, requestJson } from './client'

const CONVERSATIONS_PATH = '/api/conversations'
const ISO_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  const actualKeys = Object.keys(value)
  return (
    actualKeys.length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  )
}

function isBoundedString(
  value: unknown,
  maximum: number,
  allowEmpty = false,
): value is string {
  return (
    typeof value === 'string' &&
    value.length <= maximum &&
    (allowEmpty || value.trim().length > 0)
  )
}

function isIdentifier(value: unknown): value is string {
  return isBoundedString(value, 200)
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value)
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    ISO_TIMESTAMP.test(value) &&
    Number.isFinite(Date.parse(value))
  )
}

function isNullablePositiveInteger(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' && Number.isInteger(value) && value >= 1)
  )
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isConversation(value: unknown): value is ConversationData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['id', 'title', 'created_at', 'updated_at']) &&
    isUuid(value.id) &&
    isBoundedString(value.title, CHAT_TITLE_MAX_LENGTH) &&
    isTimestamp(value.created_at) &&
    isTimestamp(value.updated_at)
  )
}

function isCitation(value: unknown): value is GroundedCitationData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'citation_id',
      'document_id',
      'document_version_id',
      'chunk_id',
      'document_title',
      'version_number',
      'excerpt',
      'page_number',
      'sheet_name',
      'row_start',
      'row_end',
      'cell_start',
      'cell_end',
    ]) ||
    !isIdentifier(value.citation_id) ||
    !isUuid(value.document_id) ||
    !isUuid(value.document_version_id) ||
    !isUuid(value.chunk_id) ||
    !isBoundedString(value.document_title, 500) ||
    typeof value.version_number !== 'number' ||
    !Number.isInteger(value.version_number) ||
    value.version_number < 1 ||
    !isBoundedString(value.excerpt, CHAT_EXCERPT_MAX_LENGTH) ||
    !isNullablePositiveInteger(value.page_number) ||
    !isNullableString(value.sheet_name) ||
    !isNullablePositiveInteger(value.row_start) ||
    !isNullablePositiveInteger(value.row_end) ||
    !isNullableString(value.cell_start) ||
    !isNullableString(value.cell_end)
  ) {
    return false
  }

  const hasPage = value.page_number !== null
  const hasSheet = value.sheet_name !== null && value.sheet_name.length > 0
  const rowPairMatches =
    (value.row_start === null) === (value.row_end === null) &&
    (value.row_start === null || value.row_end! >= value.row_start)
  const cellPairMatches =
    (value.cell_start === null) === (value.cell_end === null) &&
    (value.cell_start === null ||
      (value.cell_start.trim().length > 0 && value.cell_end!.trim().length > 0))
  const spreadsheetCoordinatesRequireSheet =
    hasSheet ||
    (value.row_start === null &&
      value.row_end === null &&
      value.cell_start === null &&
      value.cell_end === null)

  return (
    (hasPage || hasSheet) &&
    !(hasPage && hasSheet) &&
    rowPairMatches &&
    cellPairMatches &&
    spreadsheetCoordinatesRequireSheet
  )
}

function isClaim(value: unknown): value is GroundedClaimData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['text', 'citation_ids']) &&
    isBoundedString(value.text, CHAT_CLAIM_MAX_LENGTH) &&
    Array.isArray(value.citation_ids) &&
    value.citation_ids.length > 0 &&
    value.citation_ids.every(isIdentifier) &&
    new Set(value.citation_ids).size === value.citation_ids.length
  )
}

function isExactEnvelope<T>(
  response: ApiSuccessEnvelope<unknown>,
  validateData: (value: unknown) => value is T,
): response is ApiSuccessEnvelope<T> {
  return (
    hasOnlyKeys(response as unknown as Record<string, unknown>, [
      'data',
      'request_id',
    ]) &&
    isIdentifier(response.request_id) &&
    validateData(response.data)
  )
}

function isConversationListData(value: unknown): value is ConversationListData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['conversations']) &&
    Array.isArray(value.conversations) &&
    value.conversations.every(isConversation) &&
    new Set(value.conversations.map((conversation) => conversation.id)).size ===
      value.conversations.length
  )
}

function isConversationCreateData(
  value: unknown,
): value is ConversationCreateData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['conversation']) &&
    isConversation(value.conversation)
  )
}

function isGroundedAnswerData(value: unknown): value is GroundedAnswerData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'conversation_id',
      'user_message_id',
      'assistant_message_id',
      'status',
      'answer',
      'claims',
      'citations',
      'limitations',
    ]) ||
    !isUuid(value.conversation_id) ||
    !isUuid(value.user_message_id) ||
    !isUuid(value.assistant_message_id) ||
    (value.status !== 'grounded' && value.status !== 'insufficient_evidence') ||
    !isBoundedString(value.answer, CHAT_ANSWER_MAX_LENGTH) ||
    !Array.isArray(value.claims) ||
    !value.claims.every(isClaim) ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isCitation) ||
    !Array.isArray(value.limitations) ||
    !value.limitations.every((limitation) =>
      isBoundedString(limitation, CHAT_LIMITATION_MAX_LENGTH),
    )
  ) {
    return false
  }

  const citationIds = new Set(
    value.citations.map((citation) => citation.citation_id),
  )
  if (citationIds.size !== value.citations.length) {
    return false
  }

  if (value.status === 'insufficient_evidence') {
    return value.claims.length === 0 && value.citations.length === 0
  }
  if (value.claims.length === 0 || value.citations.length === 0) {
    return false
  }
  const referencedCitationIds = new Set(
    value.claims.flatMap((claim) => claim.citation_ids),
  )
  return (
    referencedCitationIds.size === citationIds.size &&
    [...referencedCitationIds].every((citationId) =>
      citationIds.has(citationId),
    )
  )
}

function invalidResponse(requestId: string | null) {
  return new ApiError(
    'Backend returned an invalid response.',
    200,
    'invalid_response',
    requestId,
  )
}

function validateTitle(title: string | null): CreateConversationRequest {
  if (title === null) {
    return { title: null }
  }
  const trimmedTitle = title.trim()
  if (!trimmedTitle || trimmedTitle.length > CHAT_TITLE_MAX_LENGTH) {
    throw new ApiError(
      `Conversation title must contain between 1 and ${CHAT_TITLE_MAX_LENGTH} characters.`,
      0,
      'invalid_conversation_title',
      null,
    )
  }
  return { title: trimmedTitle }
}

function validateMessage(content: string): SendConversationMessageRequest {
  const trimmedContent = content.trim()
  if (!trimmedContent || trimmedContent.length > CHAT_QUESTION_MAX_LENGTH) {
    throw new ApiError(
      `Question must contain between 1 and ${CHAT_QUESTION_MAX_LENGTH} characters.`,
      0,
      'invalid_chat_question',
      null,
    )
  }
  return { content: trimmedContent }
}

export async function listConversations(
  token: string,
  signal?: AbortSignal,
): Promise<ApiSuccessEnvelope<ConversationListData>> {
  const response = await requestJson<unknown>(CONVERSATIONS_PATH, {
    token,
    signal,
  })
  if (!isExactEnvelope(response, isConversationListData)) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}

export async function createConversation(
  token: string,
  title: string | null,
  signal?: AbortSignal,
): Promise<ApiSuccessEnvelope<ConversationCreateData>> {
  const response = await requestJson<unknown>(CONVERSATIONS_PATH, {
    method: 'POST',
    token,
    body: validateTitle(title),
    signal,
  })
  if (!isExactEnvelope(response, isConversationCreateData)) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}

export async function sendConversationMessage(
  token: string,
  conversationId: string,
  content: string,
  signal?: AbortSignal,
): Promise<ApiSuccessEnvelope<GroundedAnswerData>> {
  if (!isUuid(conversationId)) {
    throw new ApiError(
      'Select a valid conversation.',
      0,
      'invalid_conversation_id',
      null,
    )
  }
  const response = await requestJson<unknown>(
    `${CONVERSATIONS_PATH}/${encodeURIComponent(conversationId)}/messages`,
    {
      method: 'POST',
      token,
      body: validateMessage(content),
      signal,
    },
  )
  if (!isExactEnvelope(response, isGroundedAnswerData)) {
    throw invalidResponse(response.request_id ?? null)
  }
  if (response.data.conversation_id !== conversationId) {
    throw invalidResponse(response.request_id)
  }
  return response
}
