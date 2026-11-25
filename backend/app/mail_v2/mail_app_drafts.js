// Silent Mail.app draft helper (JXA). Input: path to a 0600 JSON request file (argv[0]).
// Allowed operations: "probe" (no window) and "draft" (outgoing message saved with
// visible:false). The app is never brought to the foreground (a locked screen stalls
// that), and there is deliberately no delivery, removal or account-settings operation.
ObjC.import("Foundation");

function readRequest(path) {
  const text = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null);
  if (!text || text.isNil()) throw Error("request_unreadable");
  return JSON.parse(ObjC.unwrap(text));
}

function run(argv) {
  try {
    const request = readRequest(argv[0]);
    const mail = Application("com.apple.mail");
    if (request.action === "probe") {
      return JSON.stringify({ok: true, accounts: mail.accounts().length});
    }
    if (request.action !== "draft") throw Error("operation_denied");
    const properties = {subject: String(request.subject), content: String(request.body), visible: false};
    if (request.sender) properties.sender = String(request.sender);
    const draft = mail.OutgoingMessage(properties);
    mail.outgoingMessages.push(draft);
    draft.toRecipients.push(mail.ToRecipient({address: String(request.recipient)}));
    let attached = false;
    if (request.attachment) {
      try {
        draft.content.attachments.push(mail.Attachment({fileName: Path(String(request.attachment))}));
        attached = true;
      } catch (error) {
        attached = false;
      }
    }
    mail.save(draft);
    return JSON.stringify({saved: true, draft_id: String(draft.id()), attached: attached});
  } catch (error) {
    return JSON.stringify({error: "mail_app_operation_failed",
      apple_event_code: Number(error.errorNumber || error.number || 0)});
  }
}
