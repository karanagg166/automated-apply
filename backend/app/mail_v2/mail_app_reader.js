// Read-only Mail.app inbox reader (JXA). Input: path to a 0600 JSON request file (argv[0]).
// Only operation: "read_recent" (newest inbox messages since a timestamp). It never brings
// Mail to the foreground, never changes read state, and has no compose, delivery, move or
// removal operation of any kind.
ObjC.import("Foundation");

function readRequest(path) {
  const text = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null);
  if (!text || text.isNil()) throw Error("request_unreadable");
  return JSON.parse(ObjC.unwrap(text));
}

function run(argv) {
  try {
    const request = readRequest(argv[0]);
    if (request.action !== "read_recent") throw Error("operation_denied");
    const mail = Application("com.apple.mail");
    const since = new Date(Number(request.since_ms) || 0);
    const limit = Math.max(1, Math.min(Number(request.limit) || 30, 100));
    const maxChars = Math.max(200, Math.min(Number(request.max_chars) || 4000, 20000));
    const inbox = mail.inbox.messages.whose({dateReceived: {_greaterThan: since}});
    const count = Math.min(inbox.length, limit);
    const out = [];
    for (let i = 0; i < count; i++) {
      const m = inbox[i];
      let body = "";
      try { body = String(m.content() || "").slice(0, maxChars); } catch (e) { body = ""; }
      out.push({
        message_id: String(m.messageId() || ""),
        sender: String(m.sender() || "").slice(0, 300),
        subject: String(m.subject() || "").slice(0, 300),
        received_ms: m.dateReceived() ? m.dateReceived().getTime() : null,
        body: body,
      });
    }
    return JSON.stringify({ok: true, messages: out});
  } catch (error) {
    return JSON.stringify({error: "mail_app_read_failed",
      apple_event_code: Number(error.errorNumber || error.number || 0)});
  }
}
