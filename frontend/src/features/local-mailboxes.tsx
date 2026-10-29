"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, readable, dateLabel } from "@/lib/api";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Input,
  Notice,
  Skeleton,
} from "@/components/ui";

type Account = {
  slot: "1" | "2";
  status: string;
  account_email?: string;
  generation?: number;
  enabled: boolean;
  drafts_enabled: boolean;
  body_review_enabled: boolean;
  token_health: string;
  last_verified_at?: string;
};
type Message = { id: string; from?: string; subject?: string };
const base = "integrations/gmail/local/accounts";

export function LocalMailboxes() {
  const query = useQuery({
    queryKey: ["local-mailboxes"],
    queryFn: () => api<{ accounts: Account[] }>(base),
  });
  if (query.isPending) return <Skeleton />;
  if (query.isError)
    return <ErrorState error={query.error} retry={() => query.refetch()} />;
  return (
    <section className="stack">
      <h2>Approved Gmail accounts</h2>
      <p>
        Choose each account through Google. Read selected inbox messages and
        create unsent drafts. Sending and background monitoring remain disabled.
      </p>
      <div className="grid-2">
        {query.data.accounts.map((account) => (
          <Mailbox key={account.slot} account={account} />
        ))}
      </div>
      <Notice>
        Apple Mail is an optional local adapter. It requires an approved account
        allowlist and separate read and draft permissions. It starts disabled.
      </Notice>
    </section>
  );
}

function Mailbox({ account }: { account: Account }) {
  const client = useQueryClient();
  const [consent, setConsent] = useState(false);
  const [search, setSearch] = useState("Naukri newer_than:30d");
  const [messages, setMessages] = useState<Message[]>([]);
  const [notice, setNotice] = useState("");
  const [drafts, setDrafts] = useState<string[]>([]);
  const path = `${base}/${account.slot}`;
  const action = useMutation({
    mutationFn: async ({
      name,
      body = {},
    }: {
      name: string;
      body?: unknown;
    }) => {
      const result = await post<Record<string, unknown>>(
        `${path}/${name}`,
        body,
      );
      if (name === "connect") {
        const url = new URL(String(result.authorization_url));
        if (url.origin !== "https://accounts.google.com")
          throw new Error("Unexpected Google sign-in destination");
        window.location.assign(url.toString());
      } else if (name === "search") setMessages(result.messages as Message[]);
      else if (name.includes("/read"))
        setNotice(
          "Selected message read and parsed. No body was stored or link opened. Sender authentication remains unverified.",
        );
      else if (name === "test-draft")
        setNotice(
          `Draft ${result.draft_id} exists in Gmail; its test message was absent from Sent at verification.`,
        );
      else setNotice(readable(String(result.status || "completed")));
      await client.invalidateQueries({ queryKey: ["local-mailboxes"] });
      return result;
    },
  });
  const list = useMutation({
    mutationFn: async () => {
      const result = await api<{ drafts: { id: string }[] }>(`${path}/drafts`);
      setDrafts(result.drafts.map((draft) => draft.id));
    },
  });
  const busy = action.isPending || list.isPending;
  return (
    <section className="card stack">
      <h3>Gmail account {account.slot}</h3>
      <Badge>{readable(account.status)}</Badge>
      {account.account_email && <p>{account.account_email}</p>}
      {!account.enabled && (
        <Notice>
          Local read/draft account setup is disabled until the reviewed
          integration is activated.
        </Notice>
      )}
      {account.status !== "connected" ? (
        <>
          <label>
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
            />{" "}
            I authorize this selected account for inbox reading and draft
            creation. Google’s compose permission also includes sending;
            Automated Apply has no send action for these accounts.
          </label>
          <Button
            disabled={!account.enabled || !consent}
            busy={busy}
            onClick={() =>
              action.mutate({
                name: "connect",
                body: {
                  account_consent: consent,
                  read_and_draft_consent: consent,
                },
              })
            }
          >
            Choose account with Google
          </Button>
        </>
      ) : (
        <>
          <p>
            Token health: {readable(account.token_health)} · Last verified{" "}
            {dateLabel(account.last_verified_at)}
          </p>
          <Button busy={busy} onClick={() => action.mutate({ name: "verify" })}>
            Verify connection
          </Button>
          <Field label="Search this account’s Inbox">
            <Input
              value={search}
              maxLength={500}
              onChange={(event) => setSearch(event.target.value)}
            />
          </Field>
          <Button
            busy={busy}
            onClick={() =>
              action.mutate({
                name: "search",
                body: { query: search, limit: 3 },
              })
            }
          >
            Search up to three messages
          </Button>
          {messages.map((message) => (
            <div key={message.id}>
              <p>
                {message.subject || "No subject"} ·{" "}
                {message.from || "Unknown sender"}
              </p>
              <Button
                disabled={!account.body_review_enabled}
                busy={busy}
                onClick={() =>
                  action.mutate({ name: `messages/${message.id}/read` })
                }
              >
                Read selected alert
              </Button>
            </div>
          ))}
          <Button
            disabled={!account.drafts_enabled}
            busy={busy}
            onClick={() =>
              action.mutate({
                name: "test-draft",
                body: { expected_generation: account.generation },
              })
            }
          >
            Create or verify one test draft to myself
          </Button>
          <Button busy={busy} onClick={() => list.mutate()}>
            List existing Gmail drafts
          </Button>
          {drafts.map((id) => (
            <p key={id}>Gmail draft {id}</p>
          ))}
          <Button
            busy={busy}
            onClick={() => action.mutate({ name: "disconnect" })}
          >
            Disconnect this account
          </Button>
        </>
      )}
      {notice && <Notice>{notice}</Notice>}
      {(action.error || list.error) && (
        <Notice>{(action.error || list.error)?.message}</Notice>
      )}
    </section>
  );
}
