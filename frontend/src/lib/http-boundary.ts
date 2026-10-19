export class RequestLimitError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function readBoundedBody(
  request: Request,
  maximum: number,
  deadlineMs = 10000,
): Promise<Buffer> {
  if (!request.body) return Buffer.alloc(0);
  const reader = request.body.getReader(),
    chunks: Uint8Array[] = [];
  let size = 0,
    timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    void reader.cancel().catch(() => {});
  }, deadlineMs);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (timedOut) throw new RequestLimitError(408, "Request body timeout");
      if (done) break;
      size += value.length;
      if (size > maximum) {
        await reader.cancel();
        throw new RequestLimitError(413, "Request exceeds size limit");
      }
      chunks.push(value);
    }
    return Buffer.concat(chunks);
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }
}
