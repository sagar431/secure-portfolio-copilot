import type { ConversationData, GroundedAnswerData } from '../types/chat'

export const conversationData: ConversationData = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  title: 'Orion finance review',
  created_at: '2026-08-21T01:00:00Z',
  updated_at: '2026-08-21T02:00:00Z',
}

export const groundedAnswerData: GroundedAnswerData = {
  conversation_id: conversationData.id,
  user_message_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  assistant_message_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  status: 'grounded',
  answer: 'Operating margin improved. <script>window.unsafe = true</script>',
  claims: [
    {
      text: 'Operating margin improved to 18.4%.',
      citation_ids: ['C1'],
    },
  ],
  citations: [
    {
      citation_id: 'C1',
      document_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      document_version_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      chunk_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      document_title: 'orion-finance.xlsx',
      version_number: 2,
      excerpt:
        'Operating margin improved to 18.4%. <img src=x onerror=alert(1)>',
      page_number: null,
      sheet_name: 'Summary',
      row_start: 4,
      row_end: 8,
      cell_start: 'A4',
      cell_end: 'F8',
    },
  ],
  limitations: ['The answer covers the approved reporting period only.'],
}

export const insufficientAnswerData: GroundedAnswerData = {
  conversation_id: conversationData.id,
  user_message_id: '11111111-1111-4111-8111-111111111111',
  assistant_message_id: '22222222-2222-4222-8222-222222222222',
  status: 'insufficient_evidence',
  answer: 'The authorized documents do not contain enough evidence to answer.',
  claims: [],
  citations: [],
  limitations: ['No supported evidence matched the question.'],
}
