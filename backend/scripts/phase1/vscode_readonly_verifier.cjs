// Run only in the intended workspace as an Extension Development Host.
// No model request, credential read, configuration mutation or SQL operation.
const vscode = require('vscode');
const fs = require('node:fs');
const path = require('node:path');
exports.activate = async context => {
  const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!folder) return;
  const configured = path.join(folder, '.vscode/mcp.json');
  const report = path.join(folder, 'reports/phase1/current/vscode-mcp.private.json');
  const evidence = {client:'vs_code',evidence_type:'actual_vscode_extension_API_no_model',state:'pending_owner_trust_or_oauth',generation_requests:0,mutations:0,verified_at:new Date().toISOString()};
  const diagnostics=()=>{
    evidence.workspace_trusted=vscode.workspace.isTrusted;
    evidence.mcp_access=vscode.workspace.getConfiguration('chat').get('mcp.access','default');
    evidence.expected_workspace_config_present=fs.existsSync(configured);
  };
  const save=()=>{fs.mkdirSync(path.dirname(report),{recursive:true});fs.writeFileSync(report,JSON.stringify(evidence,null,2)+'\n',{mode:0o600});fs.chmodSync(report,0o600);};
  if (!fs.existsSync(configured)) return;
  const config = JSON.parse(fs.readFileSync(configured));
  const url = config.servers?.['supabase-automated-apply']?.url;
  if (url !== 'https://mcp.supabase.com/mcp?project_ref=luvdmwnlwaqgvfwlmlom&read_only=true&features=docs%2Cdatabase%2Cdebugging') return;
  diagnostics();save();
  // Narrow server IDs only. Do not start all workspace/global MCP providers.
  for (const id of ['mcp.config.ws0.supabase-automated-apply','workspace-dot-mcp.0.supabase-automated-apply']) {
    void vscode.commands.executeCommand('workbench.mcp.startServer',id,{waitForLiveTools:true,promptType:'all-untrusted'}).catch(()=>{});
  }
  let busy=false,elapsed=0;
  const timer=setInterval(async()=>{
    elapsed+=2;if(busy)return;
    const tools=vscode.lm.tools.filter(t=>/supabase/i.test(t.name)&&/automated.?apply/i.test(t.name));
    diagnostics();evidence.discovered_tools=tools.map(t=>t.name);evidence.observed_at=new Date().toISOString();save();
    const tool=tools.find(t=>/(?:_|\/)get_project_url$/.test(t.name));
    if(tool){
      busy=true;const cancel=new vscode.CancellationTokenSource();const timeout=setTimeout(()=>cancel.cancel(),30000);
      try{
        const result=await vscode.lm.invokeTool(tool.name,{input:{},toolInvocationToken:undefined},cancel.token);
        const text=result.content.map(item=>typeof item.value==='string'?item.value:'').join('\n');
        evidence.project_url_observed=text.includes('https://luvdmwnlwaqgvfwlmlom.supabase.co');
        evidence.read_only_tool='get_project_url';evidence.state=evidence.project_url_observed?'verified':'wrong_project_or_unavailable';
      }catch{evidence.state='owner_tool_authorization_required';}
      clearTimeout(timeout);cancel.dispose();clearInterval(timer);save();
    }
    if(elapsed>=600){clearInterval(timer);evidence.state='owner_trust_oauth_or_discovery_required';save();}
  },2000);
  context.subscriptions.push({dispose:()=>clearInterval(timer)});
};
