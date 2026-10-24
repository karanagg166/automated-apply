// This fixed route list prevents the server-side bearer from becoming a general proxy.
const routes: Array<[RegExp, string[]]> = [
  [/^application-answers\/(drafts|reuse-approvals)$/, ["GET"]],
  [/^application-answers\/drafts\/[a-f0-9-]{36}$/, ["PATCH"]],
  [
    /^application-answers\/drafts\/[a-f0-9-]{36}\/opportunity-evidence$/,
    ["GET"],
  ],
  [
    /^application-answers\/drafts\/[a-f0-9-]{36}\/(approve-reuse|revoke-reuse)$/,
    ["POST"],
  ],
  [/^browser-applications$/, ["POST"]],
  [/^browser-applications\/policy$/, ["GET"]],
  [/^browser-applications\/[a-f0-9-]{36}$/, ["GET"]],
  [/^browser-applications\/[a-f0-9-]{36}\/operation$/, ["GET"]],
  [
    /^browser-applications\/[a-f0-9-]{36}\/(open|actions|submission-preview|authorize-submission|submit|recover-submission|consent|opportunity-preview|opportunity-approve|company-source-preview|step-preview|advance-step|page-preview|resume-page)$/,
    ["POST"],
  ],
  [/^dashboard\/automation$/, ["GET", "PUT"]],
  [/^dashboard\/automation\/(history|matches)$/, ["GET"]],
  [/^dashboard\/automation\/(preview|run)$/, ["POST"]],
  [/^dashboard\/resume-sync$/, ["GET"]],
  [/^dashboard\/resume-sync\/source$/, ["PUT"]],
  [/^dashboard\/resume-sync\/sync$/, ["POST"]],
  [/^dashboard\/resume-sync\/versions\/[a-f0-9-]{36}\/review$/, ["GET"]],
  [/^dashboard\/resume-sync\/versions\/[a-f0-9-]{36}\/approve$/, ["POST"]],
  [/^profile$/, ["GET", "PUT", "PATCH"]],
  [/^candidate\/(resources|evidence)$/, ["GET", "POST"]],
  [/^candidate\/evidence\/[a-f0-9-]{36}$/, ["PATCH"]],
  [
    /^dashboard\/(runtime|connections|overview|onboarding\/manifest|notification-delivery-history|notification-preferences|notifications|presets|resumes)$/,
    ["GET", "POST", "PUT"],
  ],
  [/^dashboard\/notifications\/sync$/, ["POST"]],
  [/^dashboard\/notifications\/[a-f0-9-]{36}\/read$/, ["POST"]],
  [/^dashboard\/resumes\/[a-f0-9-]{36}$/, ["GET"]],
  [/^dashboard\/resumes\/[a-f0-9-]{36}\/confirm$/, ["POST"]],
  [/^dashboard\/jobs\/[a-f0-9-]{36}\/shortlist$/, ["POST"]],
  [
    /^startups\/(search|sources|shortlist|integrations\/status)$/,
    ["GET", "POST"],
  ],
  [/^startups\/discovery\/(preview|runs)$/, ["POST"]],
  [/^startups\/[a-f0-9-]{36}(\/(jobs|evidence|shortlist))?$/, ["GET", "POST"]],
  [/^jobs(\/search)?$/, ["GET"]],
  [/^jobs\/[a-f0-9-]{36}$/, ["GET"]],
  [
    /^jobs\/[a-f0-9-]{36}\/(application-preview|application-packets)$/,
    ["POST"],
  ],
  [
    /^companies\/[a-f0-9-]{36}\/(people|recommended-contacts|contacts|details)$/,
    ["GET"],
  ],
  [/^companies\/[a-f0-9-]{36}\/contacts\/(preview|enrich)$/, ["POST"]],
  [/^discovery\/people\/search$/, ["POST"]],
  [/^contacts\/[a-f0-9-]{36}$/, ["GET", "PATCH"]],
  [/^contact-enrichment\/providers$/, ["GET"]],
  [/^discovery\/(sources|runs\/[a-f0-9-]{36})$/, ["GET"]],
  [/^discovery\/(preview|runs)$/, ["POST"]],
  [/^application-packets$/, ["GET"]],
  [/^application-packets\/[a-f0-9-]{36}$/, ["GET", "PATCH"]],
  [/^application-packets\/[a-f0-9-]{36}\/(readiness|handoff|events)$/, ["GET"]],
  [
    /^application-packets\/[a-f0-9-]{36}\/(review|report-submission|questions)$/,
    ["POST"],
  ],
  [/^application-packets\/[a-f0-9-]{36}\/tracking$/, ["PATCH"]],
  [/^application-packets\/[a-f0-9-]{36}\/questions\/[a-f0-9-]{36}$/, ["PATCH"]],
  [
    /^application-packets\/[a-f0-9-]{36}\/questions\/[a-f0-9-]{36}\/generate$/,
    ["POST"],
  ],
  [/^outreach\/(drafts|history)$/, ["GET", "POST"]],
  [/^outreach\/drafts\/preview$/, ["POST"]],
  [/^outreach\/drafts\/[a-f0-9-]{36}$/, ["GET", "PATCH"]],
  [
    /^outreach\/drafts\/[a-f0-9-]{36}\/(approve|reject|send-preview|send)$/,
    ["POST"],
  ],
  [
    /^outreach\/(send-attempts\/[a-f0-9-]{36}|drafts\/[a-f0-9-]{36}\/eligibility)$/,
    ["GET"],
  ],
  [/^integrations(\/gmail\/status)?$/, ["GET"]],
  [/^integrations\/gmail\/(connect\/start|verify|disconnect)$/, ["POST"]],
  [/^operations\/status$/, ["GET"]],
];
export function permittedRoute(path: string, method: string) {
  return (
    !path.includes("..") &&
    !path.includes("%") &&
    routes.some(
      ([pattern, methods]) => pattern.test(path) && methods.includes(method),
    )
  );
}
