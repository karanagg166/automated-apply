// Supported Mail scripting only. Inputs arrive as JSON argv, never source code.
// This helper deliberately implements no send, delete, forward or account settings operation.
function run(argv) {
  try {
    const request = JSON.parse(argv[0]);
    const mail = Application("com.apple.mail");
    const short = (value, max) => String(value || "").slice(0, max);
    const accounts = mail.accounts();
    if (request.action === "accounts") {
      return JSON.stringify({accounts: accounts.filter(a => !request.allowed_ids || request.allowed_ids.includes(a.id())).map(a => ({
        id: short(a.id(), 128), name: short(a.name(), 200),
        addresses: a.emailAddresses().map(v => short(v, 254)), enabled: a.enabled()
      }))});
    }
    const matches = accounts.filter(a => a.id() === request.account_id);
    if (matches.length !== 1 || !matches[0].enabled()) throw Error("account_offline");
    const account = matches[0];
    if (!account.emailAddresses().some(a => a.toLowerCase() === request.address.toLowerCase())) throw Error("account_identity_changed");
    if (request.action === "mailboxes") {
      return JSON.stringify({mailboxes: account.mailboxes().map(b => short(b.name(), 128))});
    }
    const boxes = account.mailboxes().filter(b => b.name() === request.mailbox);
    if (boxes.length !== 1) throw Error("mailbox_not_found");
    const box = boxes[0];
    const metadata = m => ({id: m.id(), sender: short(m.sender(), 1000),
      subject: short(m.subject(), 1000), message_id: short(m.messageId(), 1000),
      received_at: m.dateReceived().toISOString()});
    if (request.action === "search") {
      const since = new Date(request.since);
      const found = box.messages.whose({dateReceived: {_greaterThan: since}})();
      const output = [];
      let examined = 0;
      // Only bounded selected-folder metadata. No bodies or attachments here.
      for (let i = 0; i < Math.min(found.length, 100); i++) {
        examined++;
        const m = metadata(found[i]);
        if (request.metadata_discovery === true || request.senders.some(s => m.sender.toLowerCase().includes(s.toLowerCase()))) output.push(m);
        if (output.length >= request.limit) break;
      }
      return JSON.stringify({messages: output, examined, bounded: true});
    }
    if (request.action === "read") {
      const found = box.messages.whose({id: request.message_id})();
      if (found.length !== 1) throw Error("message_not_found");
      const m = found[0], data = metadata(m);
      if (new Date(data.received_at) < new Date(request.since) || !request.senders.some(s => data.sender.toLowerCase().includes(s.toLowerCase()))) throw Error("message_outside_scope");
      return JSON.stringify({...data, body: short(m.content(), 262144)});
    }
    if (request.action === "verify_draft" || request.action === "draft") {
      let found = box.messages.whose({subject: request.subject})();
      if (found.length === 0 && request.action === "draft") {
        const draft = mail.OutgoingMessage({subject: request.subject,
          content: request.body, sender: request.address, visible: false});
        mail.outgoingMessages.push(draft);
        draft.toRecipients.push(mail.ToRecipient({address: request.recipient}));
        mail.save(draft);
        // Saving is the only mailbox write. A later call independently checks this account's Drafts folder.
        return JSON.stringify({saved: true, outgoing_id: draft.id(), draft_verified: false, sent: false});
      }
      if (found.length !== 1) throw Error("draft_unconfirmed");
      const m = found[0];
      let sentEmpty = null;
      if (request.sent_mailbox) {
        const sent = account.mailboxes().filter(b => b.name() === request.sent_mailbox);
        if (sent.length !== 1) throw Error("sent_mailbox_unverified");
        sentEmpty = sent[0].messages.whose({subject: request.subject})().length === 0;
      }
      return JSON.stringify({draft_verified: true, id: m.id(), subject: short(m.subject(), 1000),
        sender: short(m.sender(), 1000), recipients: m.toRecipients().map(r => short(r.address(), 254)), sent_search_empty: sentEmpty, sent: false});
    }
    throw Error("operation_denied");
  } catch (error) {
    return JSON.stringify({error: "apple_mail_operation_failed", apple_event_code: Number(error.errorNumber || error.number || 0)});
  }
}
