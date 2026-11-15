const uuid = "[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
const routes: Record<string, RegExp> = {
  GET: new RegExp(
    `^(control|capabilities|runs|questions|discovery/schedule|runs/${uuid}(/(plan|events))?)$`,
  ),
  PUT: /^(control|discovery\/schedule)$/,
  POST: new RegExp(
    `^(runs|runs/${uuid}/control|runs/${uuid}/approvals/${uuid}|runs/${uuid}/questions/${uuid}/resolve|platforms/(himalayas|we_work_remotely)/(discover|ingest))$`,
  ),
};
export function permittedWorkflowRoute(path: string, method: string) {
  return routes[method]?.test(path) === true;
}
