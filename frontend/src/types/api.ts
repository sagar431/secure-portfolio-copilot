export interface ApiSuccessEnvelope<T> {
  data: T
  request_id: string
}

export interface ApiErrorEnvelope {
  error: {
    code: string
    message: string
  }
  request_id: string
}
